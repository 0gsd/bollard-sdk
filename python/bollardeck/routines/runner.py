# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.routines.runner: loading routines and calling their hooks.

The usage guide is the package docstring (`bollardeck.routines`). This module holds the pieces:
the read-only views a hook receives, the runtime guard, `load_routines`, and `RoutineSet`, whose
six methods (`plan`, `part_candidate`, `verdict`, `overdub`, `export`, `drama`) each call one hook
on every routine that asked for it and keep only the changes that hook is allowed to make.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import random
import re
import sys
import threading
import time
import types
import zipfile
from dataclasses import asdict, dataclass, is_dataclass, replace as dc_replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Container, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..device.identity import song_id_prefix
from .errors import RoutineError, RoutineSetupError
from .manifest import (API_VERSION, ENTRY_NAME, HARD_LIMITS, HOOKS, MANIFEST_NAME, NAME_RE, ManifestError,
                       parse_manifest)

__all__ = ["API_VERSION", "HOOKS", "HARD_LIMITS", "MANIFEST_NAME", "ENTRY_NAME", "NAME_RE", "DIRECTIVE_RE",
           "BANNED_IMPORTS", "ENV_PATHS", "ENV_OFF", "ENV_DATA_DIR", "RoutineError", "RoutineSetupError",
           "ManifestError", "Factory", "Routine", "RoutineSet", "RoutineContext", "CorpusView", "VerdictView",
           "freeze", "thaw", "check_source", "is_package", "discover", "default_routine_dirs", "load_routine",
           "load_routines", "is_hosted_service", "parse_manifest", "main"]

ENV_PATHS = "POPBOLLARD_ROUTINES"
ENV_OFF = "POPBOLLARD_NO_ROUTINES"
ENV_DATA_DIR = "POPBOLLARD_DATA_DIR"

DIRECTIVE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,47}$")

# Modules no routine may import: the network, other processes, foreign code. Checked statically
# before loading; the runtime guard below refuses the same capabilities whatever the import
# path. A host adds the names of its own modules that a routine must not reach (the ones that
# write corpora or own the song state) with `banned_imports=` on load_routines().
BANNED_IMPORTS = frozenset({
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib",
    "smtplib", "telnetlib", "xmlrpc", "asyncio", "subprocess", "multiprocessing", "ctypes",
    "cffi",
})


@dataclass(frozen=True)
class Factory:
    """What the program that calls the hooks means by a chord, a note and a bar. The routine API
    checks what a routine hands back against these; it carries no music theory of its own.

    chords         the chord names a plan's progression may use (anything `in` works on)
    note_type      the class of a note event. A dataclass with the fields channel_1based, pitch,
                   velocity, start_tick, duration_ticks and origin_tag
    ticks_per_bar  how long a bar is, in the ticks note events are timed in"""
    chords: Container[str]
    note_type: type
    ticks_per_bar: int


# ── read-only views ─────────────────────────────────────────────────────────────────────

def freeze(obj: Any) -> Any:
    """Deep read-only copy: dicts become MappingProxyType, lists/tuples tuples, sets frozensets."""
    if is_dataclass(obj) and not isinstance(obj, type):
        obj = asdict(obj)
    if isinstance(obj, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(freeze(v) for v in obj)
    if isinstance(obj, (set, frozenset)):
        return frozenset(freeze(v) for v in obj)
    return obj


def thaw(obj: Any) -> Any:
    """The inverse of freeze(), for JSON output."""
    if isinstance(obj, Mapping):
        return {k: thaw(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [thaw(v) for v in obj]
    if isinstance(obj, frozenset):
        return sorted(thaw(v) for v in obj)
    return obj


class _Lazy:
    """A read-only attribute computed on first access (freezing the corpus DNA is not free)."""

    def __init__(self, fn: Callable[[], Any]):
        self._fn, self._done, self._value = fn, False, None

    def get(self) -> Any:
        if not self._done:
            self._value, self._done = self._fn(), True
        return self._value


class CorpusView:
    """What a routine sees of the active corpora: ids, labels, summaries and merged DNA, frozen.
    There is deliberately no way from here to a Corpus, a CorpusSet or a path to write to."""

    __slots__ = ("_ids", "_labels", "_summaries", "_dna")

    def __init__(self, ids: Sequence[str], labels: Sequence[str],
                 summaries: Callable[[], Any], dna: Callable[[], Any]):
        object.__setattr__(self, "_ids", tuple(ids))
        object.__setattr__(self, "_labels", tuple(labels))
        object.__setattr__(self, "_summaries", _Lazy(lambda: freeze(summaries())))
        object.__setattr__(self, "_dna", _Lazy(lambda: freeze(dna())))

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("CorpusView is read-only")

    ids = property(lambda self: self._ids)
    labels = property(lambda self: self._labels)
    summaries = property(lambda self: self._summaries.get())
    dna = property(lambda self: self._dna.get())


@dataclass(frozen=True)
class VerdictView:
    """A judge's verdict as a routine sees it. Frozen: a routine can read a score, never forge one."""
    judge_id: str
    judge_number: int
    domain: str
    score: float
    threshold: float
    lock_vote: bool
    metrics: Mapping[str, float]
    directives: Tuple[str, ...]


class RoutineContext:
    """The `ctx` every hook receives. Everything on it is read-only except `rng`, `log` and
    the routine's own `folder`."""

    def __init__(self, *, routine: "Routine", hook: str, song_id: str, rng: random.Random,
                 corpus: CorpusView, roster: _Lazy, taste_dna: _Lazy, device: Mapping[str, Any],
                 part: Optional[Mapping[str, Any]], take: Optional[int], log: Callable[[str], None]):
        self.routine_name = routine.name
        self.routine_version = routine.version
        self.hook = hook
        self.song_id = song_id
        self.rng = rng
        self.corpus = corpus
        self._roster = roster
        self._taste = taste_dna
        self.device = device
        self.part = part
        self.take = take
        self.folder = routine.folder
        self._log = log
        self.api = API_VERSION

    @property
    def roster(self) -> Mapping[str, Any]:
        """{"musicians": {channel: {...}}, "judges": {judge_id: {...}}}, frozen."""
        return self._roster.get()

    @property
    def taste_dna(self) -> Mapping[str, Any]:
        return self._taste.get()

    def log(self, message: Any) -> None:
        """One line into this song's `routines_applied[*].log` (capped)."""
        self._log(str(message))


# ── the runtime guard ───────────────────────────────────────────────────────────────────

_GUARD = threading.local()
_GUARD_INSTALLED = False
_BLOCKED_PREFIXES = ("socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                     "os.fork", "os.forkpty", "pty.", "ctypes.", "urllib.", "http.", "ftplib.",
                     "smtplib.", "webbrowser.", "winreg.", "msvcrt.")
_PATH_EVENTS = {"os.remove": (0,), "os.unlink": (0,), "os.rmdir": (0,), "os.mkdir": (0,),
                "os.rename": (0, 1), "os.replace": (0, 1), "os.link": (0, 1), "os.symlink": (0, 1),
                "os.chmod": (0,), "os.chown": (0,), "os.truncate": (0,), "os.utime": (0,),
                "shutil.rmtree": (0,), "shutil.copyfile": (1,), "shutil.copytree": (1,),
                "shutil.move": (0, 1), "shutil.make_archive": (0,), "shutil.unpack_archive": (1,)}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
# A routine may never read a device's soul keystore or open a database outside its own folder
# (the state database holds the band's cards: rarity must not be forgeable by a routine).
_SECRET_BASENAMES = ("soul_keystore.json",)


def _is_secret(path: Any) -> bool:
    if isinstance(path, int):
        return False
    try:
        return os.path.basename(os.fsdecode(path)) in _SECRET_BASENAMES
    except (TypeError, ValueError):
        return False


def _inside(path: Any, folder: Optional[Path]) -> bool:
    if folder is None or isinstance(path, int):
        return isinstance(path, int)   # an already-open fd was opened under the same rules
    try:
        p = Path(os.fsdecode(path))
        p = p if p.is_absolute() else Path.cwd() / p
        return os.path.commonpath([os.path.realpath(p), os.path.realpath(folder)]) == os.path.realpath(folder)
    except (TypeError, ValueError):
        return False


def _audit(event: str, args: Tuple[Any, ...]) -> None:
    if not getattr(_GUARD, "active", False):
        return
    folder = getattr(_GUARD, "folder", None)
    if event.startswith(_BLOCKED_PREFIXES):
        raise PermissionError(f"routine guard: '{event}' is not allowed inside a routine")
    if event == "open":
        path, mode, flags = (tuple(args) + (None, None, None))[:3]
        if _is_secret(path):
            raise PermissionError("routine guard: a routine may not read the device's soul")
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                  (isinstance(flags, int) and bool(flags & _WRITE_FLAGS))
        if writing and not _inside(path, folder):
            raise PermissionError(f"routine guard: writing {path!r} is outside the routine's folder")
    elif event == "sqlite3.connect":
        db = args[0] if args else None
        if db not in (":memory:", "", b":memory:", b"") and not _inside(db, folder):
            raise PermissionError(f"routine guard: opening database {db!r} is outside the routine's folder")
    elif event in _PATH_EVENTS:
        for i in _PATH_EVENTS[event]:
            if i < len(args) and not _inside(args[i], folder):
                raise PermissionError(f"routine guard: '{event}' on {args[i]!r} is outside the routine's folder")


def _install_guard() -> None:
    global _GUARD_INSTALLED
    if not _GUARD_INSTALLED:
        sys.addaudithook(_audit)   # permanent for the process; a no-op outside routine calls
        _GUARD_INSTALLED = True


class _Guarded:
    def __init__(self, folder: Optional[Path]):
        self.folder = folder

    def __enter__(self) -> None:
        _install_guard()
        self.prev = (getattr(_GUARD, "active", False), getattr(_GUARD, "folder", None))
        _GUARD.active, _GUARD.folder = True, self.folder

    def __exit__(self, *exc: Any) -> None:
        _GUARD.active, _GUARD.folder = self.prev


# ── packages and loading ────────────────────────────────────────────────────────────────

@dataclass
class Routine:
    name: str
    version: str
    author: str
    hooks: Tuple[str, ...]
    limits: Dict[str, float]
    order: int
    source: str                       # where it was found (folder or zip path)
    folder: Optional[Path]            # the one place it may write
    module: types.ModuleType
    description: str = ""
    position: int = 0                 # discovery position (tie-break for `order`)

    def limit(self, key: str) -> float:
        hard = HARD_LIMITS[key]
        asked = self.limits.get(key)
        try:
            return min(hard, float(asked)) if asked is not None else hard
        except (TypeError, ValueError):
            return hard


def _banned(extra: Iterable[str]) -> frozenset:
    if isinstance(extra, str):
        raise RoutineSetupError("banned_imports is a list of module names, not one string")
    names = frozenset(extra)
    for name in names:
        if not isinstance(name, str) or not name or "." in name:
            raise RoutineSetupError("banned_imports: %r is not a top-level module name" % (name,))
    return BANNED_IMPORTS | names


def check_source(src: str, where: str, banned_imports: Iterable[str] = ()) -> None:
    """Static refusal of imports that reach the network, processes or ctypes (`BANNED_IMPORTS`),
    and of the host's own modules named in `banned_imports` (top-level names: banning "engine"
    bans "engine.state" too)."""
    banned = _banned(banned_imports)
    tree = ast.parse(src, filename=where)
    for node in ast.walk(tree):
        mods: List[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module] if node.level == 0 else []
        for m in mods:
            if m.split(".")[0] in banned:
                raise RoutineError(f"{where}: import of '{m}' is not allowed in a routine")


def _read_package(path: Path) -> Tuple[str, str, Optional[Path]]:
    """(manifest text, source text, writable folder) of a routine folder or zip."""
    if path.is_dir():
        return ((path / MANIFEST_NAME).read_text(encoding="utf-8"),
                (path / ENTRY_NAME).read_text(encoding="utf-8"), path)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        man = next((n for n in names if n.split("/")[-1] == MANIFEST_NAME and n.count("/") <= 1), None)
        if man is None:
            raise RoutineError(f"{path}: no {MANIFEST_NAME} at the top of the zip")
        prefix = man[: -len(MANIFEST_NAME)]
        if prefix + ENTRY_NAME not in names:
            raise RoutineError(f"{path}: no {ENTRY_NAME} next to {MANIFEST_NAME}")
        folder = path.with_suffix(".data")   # a zip's writable folder sits beside it
        return (zf.read(man).decode("utf-8"), zf.read(prefix + ENTRY_NAME).decode("utf-8"), folder)


def is_package(path: Path) -> bool:
    if path.is_dir():
        return (path / MANIFEST_NAME).is_file()
    if path.is_file() and path.suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                return any(n.split("/")[-1] == MANIFEST_NAME and n.count("/") <= 1 for n in zf.namelist())
        except zipfile.BadZipFile:
            return False
    return False


def default_routine_dirs(data_dir: Optional[Path] = None) -> List[Path]:
    """`<data dir>/routines` (the data dir given, else $POPBOLLARD_DATA_DIR; left out when neither
    is set), then every path in $POPBOLLARD_ROUTINES."""
    base = data_dir if data_dir is not None else (os.environ.get(ENV_DATA_DIR) or None)
    out = [Path(base) / "routines"] if base else []
    for raw in os.environ.get(ENV_PATHS, "").split(os.pathsep):
        if raw.strip():
            out.append(Path(raw.strip()).expanduser())
    return out


def discover(paths: Iterable[Path]) -> List[Path]:
    """Routine packages under `paths`, in load order."""
    found: List[Path] = []
    for p in paths:
        p = Path(p)
        if is_package(p):
            found.append(p)
        elif p.is_dir():
            found.extend(c for c in sorted(p.iterdir(), key=lambda c: c.name)
                         if not c.name.startswith((".", "_")) and is_package(c))
    return found


def load_routine(path: Path, position: int = 0, banned_imports: Iterable[str] = ()) -> Routine:
    man_text, src, folder = _read_package(Path(path))
    man = parse_manifest(man_text, str(path))
    man.pop("api")
    check_source(src, f"{path}/{ENTRY_NAME}", banned_imports)
    module = types.ModuleType(f"bollardeck_routine_{re.sub(r'[^a-z0-9_]', '_', man['name'])}")
    module.__file__ = f"{path}/{ENTRY_NAME}"
    with _Guarded(folder):
        exec(compile(src, module.__file__, "exec"), module.__dict__)
    missing = [h for h in man["hooks"] if not callable(getattr(module, h, None))]
    if missing:
        raise RoutineError(f"{path}: manifest lists {missing} but {ENTRY_NAME} does not define them")
    return Routine(module=module, source=str(path), folder=folder, position=position, **man)


def is_hosted_service() -> bool:
    """True on the hosted web app (Cloud Run), which never runs user routines."""
    return bool(os.environ.get("K_SERVICE") or os.environ.get("POPBOLLARD_CLOUD_RUN"))


def load_routines(paths: Optional[Iterable[Path]] = None, data_dir: Optional[Path] = None,
                  factory: Optional[Factory] = None, banned_imports: Iterable[str] = ()) -> "RoutineSet":
    """Every routine from `paths` (default: default_routine_dirs()), ordered and de-duplicated.
    A package that fails to load is kept as a load failure (it shows in the song meta).
    `factory` says what a chord, a note and a bar are in the program that will call the hooks.
    `banned_imports` names the host's own top-level modules no routine may import, on top of
    `BANNED_IMPORTS`."""
    banned_imports = tuple(_banned(banned_imports) - BANNED_IMPORTS)       # a bad list is the host's bug: raise now
    if os.environ.get(ENV_OFF, "").strip() in ("1", "true", "yes") or is_hosted_service():
        return RoutineSet([], factory=factory)
    routines: List[Routine] = []
    failures: List[Dict[str, Any]] = []
    seen: set = set()
    for pos, pkg in enumerate(discover(paths if paths is not None else default_routine_dirs(data_dir))):
        try:
            r = load_routine(pkg, pos, banned_imports)
        except Exception as exc:  # noqa: BLE001 - any load error just skips the package
            failures.append({"name": pkg.stem, "version": "", "hook": "load", "where": str(pkg),
                             "error": f"{type(exc).__name__}: {exc}"[:400]})
            continue
        if r.name in seen:
            failures.append({"name": r.name, "version": r.version, "hook": "load", "where": str(pkg),
                             "error": "duplicate name: an earlier routine with this name was loaded"})
            continue
        seen.add(r.name)
        routines.append(r)
    routines.sort(key=lambda r: (r.order, r.position))
    return RoutineSet(routines, failures, factory=factory)


# ── the set the factory calls ───────────────────────────────────────────────────────────

class RoutineSet:
    """The routines one song runs with. Falsy when nothing is installed, so every factory call
    site is `if routines: ...` and an empty set costs nothing."""

    def __init__(self, routines: Sequence[Routine], load_failures: Sequence[Dict[str, Any]] = (),
                 factory: Optional[Factory] = None):
        self.factory = factory
        self.routines: List[Routine] = list(routines)
        self.load_failures: List[Dict[str, Any]] = list(load_failures)
        self.state: Dict[str, Any] = {}
        self._song: Dict[str, Any] = {}

    def __bool__(self) -> bool:
        return bool(self.routines or self.load_failures)

    def _need_factory(self) -> Factory:
        if self.factory is None:
            raise RoutineSetupError("this RoutineSet has no factory: pass factory=Factory(chords, note_type, "
                                    "ticks_per_bar) to load_routines() or RoutineSet(), or set .factory")
        return self.factory

    @property
    def names(self) -> List[str]:
        return [r.name for r in self.routines]

    # -- per-song set-up ----------------------------------------------------------------

    def begin_song(self, *, song_id: str, rng_seed: Any, state: Optional[Dict[str, Any]] = None,
                   idx_data: Optional[Dict[str, Any]] = None, taste_dna: Optional[Dict[str, Any]] = None,
                   corpus_set: Any = None, corpus_ids: Sequence[str] = (), corpus_labels: Sequence[str] = (),
                   device_serial: str = "") -> None:
        """Start (or, with the checkpointed `state`, resume) a song. `state` is a dict the
        factory keeps in its checkpoint; this set records into it in place."""
        self.state = state if state is not None else {}
        st = self.state
        st.setdefault("applied", {})
        st.setdefault("failed", [])
        for r in self.routines:
            st["applied"].setdefault(r.name, {"name": r.name, "version": r.version, "author": r.author,
                                              "source": r.source, "hooks_called": {}, "log": []})
        idx = idx_data or {}
        if corpus_set is not None:
            ids, labels = list(corpus_set.ids), list(corpus_set.labels())
            summaries, dna = corpus_set.summaries, corpus_set.merged_dna
        else:
            ids, labels = list(corpus_ids), list(corpus_labels)
            summaries, dna = (lambda: []), (lambda: {})
        serial = device_serial or str(idx.get("device_serial") or "")
        self._song = {
            "song_id": song_id, "seed": rng_seed,
            "corpus": CorpusView(ids, labels, summaries, dna),
            "roster": _Lazy(lambda: freeze({"musicians": idx.get("musician_roster", {}),
                                            "judges": idx.get("judge_roster", {})})),
            "taste": _Lazy(lambda: freeze(taste_dna or {})),
            "device": freeze({"serial": serial, "song_id_prefix": song_id_prefix(serial or None)}),
        }

    def _disabled(self, r: Routine) -> bool:
        return any(f["name"] == r.name for f in self.state.get("failed", []))

    def _active(self, hook: str) -> List[Routine]:
        return [r for r in self.routines if hook in r.hooks and not self._disabled(r)]

    def _call(self, r: Routine, hook: str, args: Tuple[Any, ...], part: Any = None,
              take: Optional[int] = None) -> Tuple[bool, Any]:
        """(ok, result). On any failure the routine is disabled for the song and recorded."""
        rec = self.state["applied"][r.name]
        cap = int(r.limit("max_log_lines"))

        def _log(msg: str) -> None:
            if len(rec["log"]) < cap:
                rec["log"].append(msg[:200])

        part_view = None
        if part is not None:
            part_view = freeze({k: getattr(part, k) for k in ("part_index", "label", "category", "bars",
                                                                "progression", "energy", "movement_index")})
        ctx = RoutineContext(
            routine=r, hook=hook, song_id=self._song.get("song_id", ""),
            rng=random.Random(f"{self._song.get('seed')}|{r.name}|{hook}|"
                              f"{getattr(part, 'part_index', '')}|{take if take is not None else ''}"),
            corpus=self._song["corpus"], roster=self._song["roster"], taste_dna=self._song["taste"],
            device=self._song["device"], part=part_view, take=take, log=_log)
        where = hook if part is None else f"{hook} part {part.part_index}" + (f" take {take}" if take else "")
        t0 = time.perf_counter()
        try:
            with _Guarded(r.folder):
                result = getattr(r.module, hook)(*args, ctx)
            ms = (time.perf_counter() - t0) * 1000.0
            if ms > r.limit("max_ms_per_call"):
                raise RoutineError(f"took {ms:.0f} ms (limit {r.limit('max_ms_per_call'):.0f} ms)")
        except Exception as exc:  # noqa: BLE001 - a routine must never break the song
            self._fail(r, where, exc)
            return False, None
        rec["hooks_called"][hook] = rec["hooks_called"].get(hook, 0) + 1
        return True, result

    def _fail(self, r: Routine, where: str, exc: BaseException) -> None:
        self.state["failed"].append({"name": r.name, "version": r.version, "hook": where.split(" ")[0],
                                     "where": where, "error": f"{type(exc).__name__}: {exc}"[:400]})

    # -- hooks --------------------------------------------------------------------------

    _PLAN_PART_EDITABLE = ("progression", "energy", "bars", "label")
    _PLAN_PART_FIXED = ("category", "assigned_team_ids", "study_break_channel", "movement_index", "leitmotif_role")

    def plan(self, plan: Any) -> Any:
        """on_plan(plan, ctx) after the planning summit. A routine may re-order the parts of a
        single (not a suite), and change each part's progression (1-8 chords from the factory's
        chord library), energy (0-1), bars (a multiple of 4, 4-32) and label. Anything else it
        changes is a violation. part_index is renumbered in the new order; total_bars is
        recomputed."""
        if not self._active("on_plan"):
            return plan
        chords = self._need_factory().chords
        for r in self._active("on_plan"):
            work = copy.deepcopy(plan)
            ok, res = self._call(r, "on_plan", (work,))
            if not ok:
                continue
            new = res if res is not None else work
            try:
                plan = self._accept_plan(plan, new, chords)
            except Exception as exc:  # noqa: BLE001
                self._fail(r, "on_plan", exc)
        return plan

    def _accept_plan(self, old: Any, new: Any, chords: Container[str]) -> Any:
        if type(new) is not type(old):
            raise RoutineError("on_plan must return the plan (or None)")
        a, b = asdict(old), asdict(new)
        for k in a:
            if k not in ("parts", "total_bars") and a[k] != b.get(k):
                raise RoutineError(f"on_plan may not change plan.{k}")
        old_by_idx = {p.part_index: p for p in old.parts}
        new_idx = [p.part_index for p in new.parts]
        if sorted(new_idx) != sorted(old_by_idx):
            raise RoutineError("on_plan may re-order parts but not add or remove them")
        if (old.form == "suite" or old.movements) and new_idx != [p.part_index for p in old.parts]:
            raise RoutineError("on_plan may not re-order the parts of a suite")
        staged = []
        for pos, np in enumerate(new.parts, start=1):
            op = old_by_idx[np.part_index]
            for k in self._PLAN_PART_FIXED:
                if getattr(np, k) != getattr(op, k):
                    raise RoutineError(f"on_plan may not change part.{k} (part {op.part_index})")
            prog = list(np.progression)
            if not 1 <= len(prog) <= 8 or any(c not in chords for c in prog):
                raise RoutineError(f"part {op.part_index}: progression {prog} must be 1-8 chords from the chord library")
            energy = float(np.energy)
            if not 0.0 <= energy <= 1.0:
                raise RoutineError(f"part {op.part_index}: energy {energy} outside 0-1")
            bars = int(np.bars)
            if bars % 4 or not 4 <= bars <= 32:
                raise RoutineError(f"part {op.part_index}: bars {bars} must be a multiple of 4 in 4-32")
            staged.append((op, pos, prog, energy, bars, str(np.label)[:40]))
        # Everything validated: apply to the ORIGINAL plan objects, so whatever the factory
        # aliases into the plan (e.g. the live good-enough benchmarks) stays aliased.
        for op, pos, prog, energy, bars, label in staged:
            if (op.part_index, op.progression, op.energy, op.bars, op.label) != (pos, prog, energy, bars, label):
                op.part_index, op.progression, op.energy, op.bars, op.label = pos, prog, energy, bars, label
        old.parts[:] = [st[0] for st in staged]
        old.total_bars = sum(p.bars for p in old.parts)
        return old

    def part_candidate(self, part: Any, notes: List[Any], take: int) -> List[Any]:
        """on_part_candidate(part, notes, ctx) after synthesis + autotune, before the judges.
        The routine may transform the take's NoteEvents (returned list, or the copy edited in
        place). Every note must be a valid NoteEvent inside the part."""
        if not self._active("on_part_candidate"):
            return notes
        NoteEvent, TICKS_PER_BAR = self._need_factory().note_type, self._need_factory().ticks_per_bar
        for r in self._active("on_part_candidate"):
            work = [copy.copy(n) for n in notes]
            ok, res = self._call(r, "on_part_candidate", (copy.deepcopy(part), work), part, take)
            if not ok:
                continue
            new = res if res is not None else work
            try:
                cap = int(len(notes) * r.limit("max_notes_factor")) + 512
                if not isinstance(new, list) or len(new) > cap:
                    raise RoutineError(f"on_part_candidate must return a list of at most {cap} NoteEvents")
                end = part.bars * TICKS_PER_BAR
                for n in new:
                    if not isinstance(n, NoteEvent):
                        raise RoutineError("on_part_candidate returned something that is not a NoteEvent")
                    if not (1 <= n.channel_1based <= 16 and 0 <= n.pitch <= 127 and 1 <= n.velocity <= 127
                            and 0 <= n.start_tick < end and n.duration_ticks > 0):
                        raise RoutineError(f"invalid note {n}")
                notes = new
            except Exception as exc:  # noqa: BLE001
                self._fail(r, f"on_part_candidate part {part.part_index} take {take}", exc)
        return notes

    def verdict(self, part: Any, verdicts: Sequence[Any], take: int) -> Tuple[List[str], List[str]]:
        """on_verdict(part, verdicts, ctx) after the 7 judges. Verdicts are frozen VerdictViews.
        The routine returns None or {"directives": [...], "veto": bool, "reason": str}.
        Returns (extra directives, names of routines that vetoed the lock). Scores are never
        touched; a veto only sends the band round again and expires at the take ceiling."""
        views = tuple(VerdictView(v.judge_id, v.judge_number, v.domain, float(v.score), float(v.threshold),
                                  bool(v.lock_vote), freeze(dict(v.metrics)), tuple(v.directives))
                      for v in verdicts)
        directives: List[str] = []
        vetoes: List[str] = []
        for r in self._active("on_verdict"):
            ok, res = self._call(r, "on_verdict", (copy.deepcopy(part), views), part, take)
            if not ok or res is None:
                continue
            try:
                if not isinstance(res, Mapping):
                    raise RoutineError("on_verdict must return None or a mapping")
                ds = list(res.get("directives") or [])
                if len(ds) > r.limit("max_directives_per_verdict") or any(
                        not isinstance(d, str) or not DIRECTIVE_RE.match(d) for d in ds):
                    raise RoutineError(f"directives {ds} must be <= "
                                       f"{int(r.limit('max_directives_per_verdict'))} codes matching {DIRECTIVE_RE.pattern}")
                unknown = set(res) - {"directives", "veto", "reason"}
                if unknown:
                    raise RoutineError(f"on_verdict may only return directives/veto/reason, got {sorted(unknown)}")
                directives.extend(d for d in ds if d not in directives)
                if bool(res.get("veto")):
                    vetoes.append(r.name)
            except Exception as exc:  # noqa: BLE001
                self._fail(r, f"on_verdict part {part.part_index} take {take}", exc)
        return directives, vetoes

    def overdub(self, plan: Any, bus: Any) -> List[Dict[str, Any]]:
        """on_overdub(plan, bus, ctx) after the band's overdub votes. `plan` is a copy and `bus`
        a frozen view ({"locked_parts": {part_index: (NoteEvent, ...)}}). The routine returns
        {part_index: [NoteEvent, ...]} of notes to ADD (overdubs are additive); they are tagged
        origin "routine:<name>". Returns what was added, for the overdub report."""
        if not self._active("on_overdub"):
            return []
        NoteEvent, TICKS_PER_BAR = self._need_factory().note_type, self._need_factory().ticks_per_bar
        added: List[Dict[str, Any]] = []
        bars_by_idx = {p.part_index: p.bars for p in plan.parts}
        for r in self._active("on_overdub"):
            view = MappingProxyType({"locked_parts": MappingProxyType(
                {k: tuple(copy.copy(n) for n in v) for k, v in bus.locked_parts.items()})})
            ok, res = self._call(r, "on_overdub", (copy.deepcopy(plan), view))
            if not ok or not res:
                continue
            try:
                if not isinstance(res, Mapping):
                    raise RoutineError("on_overdub must return None or {part_index: [NoteEvent, ...]}")
                staged: Dict[int, List[Any]] = {}
                for k, evs in res.items():
                    k = int(k)
                    if k not in bus.locked_parts:
                        raise RoutineError(f"part {k} is not a locked part")
                    evs = list(evs)
                    if len(evs) > r.limit("max_overdub_notes_per_part"):
                        raise RoutineError(f"too many overdub notes for part {k}")
                    end = bars_by_idx.get(k, 0) * TICKS_PER_BAR
                    for n in evs:
                        if not isinstance(n, NoteEvent) or not (1 <= n.channel_1based <= 16 and 0 <= n.pitch <= 127
                                                                 and 1 <= n.velocity <= 127 and 0 <= n.start_tick < end
                                                                 and n.duration_ticks > 0):
                            raise RoutineError(f"invalid overdub note {n!r}")
                    staged[k] = [dc_replace(n, origin_tag=f"routine:{r.name}") for n in evs]
                for k, evs in staged.items():
                    bus.locked_parts[k].extend(evs)
                    added.append({"routine": r.name, "part_index": k, "notes_added": len(evs)})
            except Exception as exc:  # noqa: BLE001
                self._fail(r, "on_overdub", exc)
        return added

    def export(self, meta: Mapping[str, Any]) -> Dict[str, Any]:
        """on_export(meta, ctx) just before the song's .json is written. `meta` is frozen; the
        routine returns a JSON-serialisable mapping that is stored under
        meta["routine_meta"][<name>]. Returns the keys to merge into the meta (always the
        routines_applied / routines_failed record)."""
        frozen = None
        extra: Dict[str, Any] = {}
        for r in self._active("on_export"):
            frozen = frozen if frozen is not None else freeze(meta)
            ok, res = self._call(r, "on_export", (frozen,))
            if not ok or res is None:
                continue
            try:
                if not isinstance(res, Mapping):
                    raise RoutineError("on_export must return None or a mapping")
                blob = json.dumps(thaw(res), sort_keys=True)
                if len(blob.encode()) > r.limit("max_export_bytes"):
                    raise RoutineError(f"on_export metadata is over {int(r.limit('max_export_bytes'))} bytes")
                extra[r.name] = json.loads(blob)
            except Exception as exc:  # noqa: BLE001
                self._fail(r, "on_export", exc)
        out = self.report()
        if extra:
            out["routine_meta"] = extra
        return out

    def drama(self, film: Dict[str, Any]) -> Dict[str, Any]:
        """on_drama(shots, ctx) on a directed film: a dict with a "shots" list. The
        routine may re-order the shots and add new ones (a dict with a str "kind", an int
        "duration_ms" in 180-20000 and an optional "data" dict); every original shot must
        still be there. Timings are recomputed."""
        shots = list(film.get("shots") or [])
        for r in self._active("on_drama"):
            work = copy.deepcopy(shots)
            ok, res = self._call(r, "on_drama", (work,))
            if not ok:
                continue
            new = res if res is not None else work
            try:
                if not isinstance(new, list):
                    raise RoutineError("on_drama must return a list of shots (or None)")
                key = lambda s: json.dumps({k: v for k, v in s.items() if k != "t_ms"}, sort_keys=True, default=str)
                remaining = [key(s) for s in shots]
                added = []
                for s in new:
                    if not isinstance(s, dict):
                        raise RoutineError("a shot must be a dict")
                    k = key(s)
                    if k in remaining:
                        remaining.remove(k)
                        continue
                    if not isinstance(s.get("kind"), str) or not isinstance(s.get("duration_ms"), int) \
                            or not 180 <= s["duration_ms"] <= 20000 or not isinstance(s.get("data", {}), dict):
                        raise RoutineError(f"added shot {s!r} needs a str kind and an int duration_ms in 180-20000")
                    added.append(s)
                if remaining:
                    raise RoutineError(f"on_drama removed or changed {len(remaining)} original shot(s)")
                if len(added) > r.limit("max_added_shots"):
                    raise RoutineError(f"on_drama added {len(added)} shots (limit {int(r.limit('max_added_shots'))})")
                for s in added:
                    s.setdefault("data", {})
                    s["by_routine"] = r.name
                shots = new
            except Exception as exc:  # noqa: BLE001
                self._fail(r, "on_drama", exc)
        out = dict(film)
        t = 0
        kinds: Dict[str, int] = {}
        retimed = []
        for s in shots:
            s2 = dict(s)
            s2["t_ms"] = t
            t += int(s2["duration_ms"])
            kinds[s2["kind"]] = kinds.get(s2["kind"], 0) + 1
            retimed.append(s2)
        out.update(shots=retimed, total_ms=t, kinds=kinds)
        if self:
            out.update(self.report())
        return out

    # -- reporting ----------------------------------------------------------------------

    def report(self) -> Dict[str, Any]:
        failed_names = {f["name"] for f in self.state.get("failed", [])}
        applied = [copy.deepcopy(self.state["applied"][r.name]) for r in self.routines
                   if r.name in self.state.get("applied", {}) and r.name not in failed_names]
        return {"routines_applied": applied,
                "routines_failed": copy.deepcopy(self.load_failures) + copy.deepcopy(self.state.get("failed", []))}


def main(argv: Optional[List[str]] = None) -> int:
    """`python3 -m bollardeck.routines [paths...]`: list the routines that would load, in order."""
    args = list(sys.argv[1:] if argv is None else argv)
    rset = load_routines([Path(a) for a in args] if args else None)
    for r in rset.routines:
        print(f"{r.order:>4}  {r.name} {r.version} by {r.author}  hooks={','.join(r.hooks)}  ({r.source})")
    for f in rset.load_failures:
        print(f"skip  {f['name']}: {f['error']}  ({f['where']})")
    if not rset:
        print("no routines installed")
    return 0
