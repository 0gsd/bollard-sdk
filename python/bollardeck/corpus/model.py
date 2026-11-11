# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus.model: a corpus, read from its manifest.

A Corpus is made from a manifest that has passed the corpus-manifest schema; one that fails is
refused whole (ManifestRefused carries the problems). Its metadata, licence and notices can be
read freely. Its content (morpus files, the DNA, tracks, audio, art) is reached only through
accessors that take the Verdict Corpus.may() returned; the files themselves sit behind a
private store that accepts nothing but a Grant made from that Verdict.
"""

import copy
import json
import os
import re
import time
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Mapping, Optional, Tuple

from . import gate as _gate
from .gate import GateRequired, Identity, Standing, Verdict
from .licence import Licence

MANIFEST_NAME = "corpus.json"
MORPUS_DIRNAME = "morpus"
DNA_NAME = "corpus_dna.json"
STATUS_NAME = "STATUS.MD"
ART_DIRNAME = "art"
VERDICT_TTL_SEC = 900.0

# Which Verdicts open which accessor.
_STUDY = ("musicians_may_study",)
_MORPUS = ("musicians_may_study", "export_morpus")
_EXPORT = ("export_morpus",)
_AUDIO = ("stream_audio",)
_ART = ("store_art",)


class ManifestRefused(ValueError):
    """A manifest the SDK will not read. `reason` is a gate reason; `problems` says where."""

    def __init__(self, reason: str, problems: Tuple[str, ...], where: str = ""):
        self.reason = reason
        self.problems = tuple(problems)
        self.where = where
        head = "%s: " % where if where else ""
        super().__init__("%s%s: %s" % (head, reason, "; ".join(self.problems[:5]) or reason))


# Why content the gate allowed could not be had: NotAvailable.reason is one of these.
NOT_AVAILABLE_REASONS: Tuple[str, ...] = (
    "not_found",        # the hub (status 404 or 410) or the folder has no such file
    "unreachable",      # the hub did not answer, or would not just now (status: None, 401, 403, 429, 5xx)
    "not_licensed",     # the hub says the licence does not cover it
    "bad_name",         # the name or path asked for is not one a corpus can hold
    "bad_range",        # the byte range asked for cannot be read (status 416)
    "bad_answer",       # the hub answered with something that cannot be used
    "not_kept",         # the file may not be kept on this machine, so there is no path to give
    "no_store",         # this corpus is a manifest alone, or its store does not offer this
)


class NotAvailable(LookupError):
    """The gate allowed it, and this corpus (or where it is kept) has nothing of that kind.
    `reason` is one of NOT_AVAILABLE_REASONS; `status` is the HTTP status the hub answered with,
    or None when no hub answered (a local corpus, or a hub that is not answering)."""

    def __init__(self, message: str = "", reason: str = "not_found", status: Optional[int] = None):
        super().__init__(message)
        self.reason = reason
        self.status = status


# The headers of an upstream answer a relay may pass on. Nothing else leaves RangedAudio.
RELAY_HEADERS: Tuple[str, ...] = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag",
                                  "Last-Modified", "Cache-Control")
_RANGE_RE = re.compile(r"^bytes=(?:([0-9]{1,18})-([0-9]{1,18})?|-([0-9]{1,18}))\Z")


def read_range(byte_range: Any = None, range_header: Any = None) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """One byte range, from a pair or from a Range header's value. Returns None (the whole
    file), (start, end) with end inclusive, (start, None) to the end, or (None, n) for the last
    n bytes. A header is exactly "bytes=a-b", "bytes=a-" or "bytes=-n": one range, no spaces.
    Raises NotAvailable (reason "bad_range", status 416) for anything else."""
    def bad(what: Any) -> NotAvailable:
        return NotAvailable("%r is not a byte range this reads (one range: bytes=a-b, bytes=a- or bytes=-n)" % (what,),
                            "bad_range", 416)
    if range_header is not None and byte_range is not None:
        raise bad((byte_range, range_header))
    if range_header is not None:
        m = _RANGE_RE.match(range_header) if isinstance(range_header, str) else None
        if not m:
            raise bad(range_header)
        byte_range = (None, int(m.group(3))) if m.group(3) is not None else (
            int(m.group(1)), int(m.group(2)) if m.group(2) is not None else None)
    if byte_range is None:
        return None
    try:
        start, end = byte_range
    except (TypeError, ValueError):
        raise bad(byte_range) from None
    whole = lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0   # noqa: E731
    if start is None:
        if not whole(end) or end == 0:
            raise bad(byte_range)
        return None, end
    if not whole(start) or (end is not None and (not whole(end) or end < start)):
        raise bad(byte_range)
    return start, end


def range_value(byte_range: Tuple[Optional[int], Optional[int]]) -> str:
    """A range from read_range() as a Range header's value."""
    start, end = byte_range
    return "bytes=-%d" % end if start is None else "bytes=%d-%s" % (start, "" if end is None else end)


class RangedAudio:
    """One recording, open, with what a relay needs to answer its own caller: `status` (200,
    206 or 416), `headers` (those of RELAY_HEADERS the source sent), and read()/close(). Use it
    as a context manager. From Corpus.open_audio_ranged()."""

    def __init__(self, status: int, headers: Mapping[str, str], body: Any, length: Optional[int] = None):
        self.status = int(status)
        self.headers: Dict[str, str] = dict(headers)
        self._body = body
        self._left = length                     # bytes still to give, when the body is a longer file

    def read(self, n: int = -1) -> bytes:
        if self._body is None:
            return b""
        if self._left is None:
            return self._body.read() if n is None or n < 0 else self._body.read(n)
        want = self._left if n is None or n < 0 else min(n, self._left)
        data = self._body.read(want) if want > 0 else b""
        self._left -= len(data)
        return data

    def close(self) -> None:
        if self._body is not None:
            self._body.close()
            self._body = None

    def __enter__(self) -> "RangedAudio":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _refuse(self: Any, *args: Any, **kw: Any) -> None:
    raise TypeError("this is a read-only view of a manifest; take a copy with copy.deepcopy() or Corpus.manifest()")


class FrozenDict(dict):
    """A dict that refuses to change. It is still a dict, so schema validators and json read
    it. `frozen()` makes one; copy.copy, copy.deepcopy and pickle give back a plain dict."""
    __slots__ = ()
    __init__ = __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _refuse

    def __copy__(self) -> Dict[str, Any]:
        return dict(self)

    def __deepcopy__(self, memo: Dict[int, Any]) -> Dict[str, Any]:
        return {k: copy.deepcopy(v, memo) for k, v in self.items()}

    def __reduce__(self) -> Tuple[Any, ...]:
        return dict, (dict(self),)


class FrozenList(list):
    """A list that refuses to change; copies of it are plain lists."""
    __slots__ = ()
    __init__ = __setitem__ = __delitem__ = __iadd__ = __imul__ = _refuse
    append = clear = extend = insert = pop = remove = reverse = sort = _refuse

    def __copy__(self) -> List[Any]:
        return list(self)

    def __deepcopy__(self, memo: Dict[int, Any]) -> List[Any]:
        return [copy.deepcopy(v, memo) for v in self]

    def __reduce__(self) -> Tuple[Any, ...]:
        return list, (list(self),)


def frozen(value: Any) -> Any:
    """A read-only copy of a JSON value: dicts and lists, all the way down, refuse to change."""
    if isinstance(value, Mapping):
        out = FrozenDict.__new__(FrozenDict)
        dict.update(out, ((k, frozen(v)) for k, v in value.items()))
        return out
    if isinstance(value, (list, tuple)):
        items = FrozenList.__new__(FrozenList)
        list.extend(items, (frozen(v) for v in value))
        return items
    return value


def safe_name(name: Any) -> bool:
    """A bare file name: no folders, not hidden, no control characters."""
    return (isinstance(name, str) and 0 < len(name) <= 255 and "/" not in name and "\\" not in name
            and not name.startswith(".") and not any(ord(c) < 32 or ord(c) == 127 for c in name))


def safe_rel_path(raw: Any) -> str:
    """A track's path relative to the corpus root ("2004/song.mp3"), or "" when it is not safe."""
    rel = raw.strip() if isinstance(raw, str) else ""
    if not rel or len(rel) > 1024 or rel.startswith("/") or "\\" in rel:
        return ""
    return rel if all(safe_name(seg) for seg in rel.split("/")) else ""


def pairs_in(names) -> List[Tuple[str, str]]:
    """The (notes, MIDI) pairs among morpus file names, in name order."""
    have = set(names)
    return [(n, n[:-3] + ".mid") for n in sorted(have)
            if n.endswith(".md") and n.upper() != STATUS_NAME and n[:-3] + ".mid" in have]


# ── stores: where a corpus's files are. Private. Every content method takes a Grant first. ──

class _NoStore:
    """A corpus known only by its manifest."""

    source = "manifest"
    root: Optional[Path] = None

    def __init__(self, corpus_id: str):
        self.corpus_id = corpus_id

    def standing(self) -> Standing:
        return Standing("local")

    def freshen(self, now: float, force: bool = False, witness: bool = True) -> Optional[Dict[str, Any]]:
        return None

    def _nothing(self, grant, what: str):
        _gate.check_grant(grant, self.corpus_id)
        raise NotAvailable("%s: this corpus was read from a manifest alone; it has no %s" % (self.corpus_id, what),
                           "no_store")

    def morpus_index(self, grant) -> List[str]:
        return self._nothing(grant, "morpus")

    def read_morpus(self, grant, name: str) -> bytes:
        return self._nothing(grant, "morpus")

    def morpus_path(self, grant, name: str) -> Path:
        return self._nothing(grant, "morpus")

    def export_bundle(self, grant, slug: str) -> bytes:
        return self._nothing(grant, "morpus")

    def tracks(self, grant) -> List[Dict[str, Any]]:
        return self._nothing(grant, "track listing")

    def open_audio(self, grant, file: str, byte_range: Optional[Tuple[int, Optional[int]]]) -> BinaryIO:
        return self._nothing(grant, "audio")

    def open_audio_ranged(self, grant, file: Any, byte_range) -> RangedAudio:
        return self._nothing(grant, "audio")

    def read_art(self, grant, name: str) -> bytes:
        return self._nothing(grant, "art")


class _LocalStore(_NoStore):
    """A corpus root on disk: corpus.json, morpus/, art/, and source audio."""

    source = "local"

    def __init__(self, corpus_id: str, root: Path):
        super().__init__(corpus_id)
        self.root = Path(root)

    def _inside(self, path: Path) -> Path:
        real, base = Path(os.path.realpath(path)), Path(os.path.realpath(self.root))
        if base != real and base not in real.parents:
            raise NotAvailable("%s: %s is outside the corpus root" % (self.corpus_id, path.name), "bad_name")
        if not real.is_file():
            raise NotAvailable("%s: no file %s" % (self.corpus_id, path.name), "not_found")
        return real

    def morpus_index(self, grant) -> List[str]:
        _gate.check_grant(grant, self.corpus_id)
        folder = self.root / MORPUS_DIRNAME
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.iterdir() if p.is_file() and safe_name(p.name))

    def morpus_path(self, grant, name: str) -> Path:
        _gate.check_grant(grant, self.corpus_id)
        if not safe_name(name):
            raise NotAvailable("%s: %r is not a morpus file name" % (self.corpus_id, name), "bad_name")
        return self._inside(self.root / MORPUS_DIRNAME / name)

    def read_morpus(self, grant, name: str) -> bytes:
        _gate.check_grant(grant, self.corpus_id)
        return self.morpus_path(grant, name).read_bytes()

    def export_bundle(self, grant, slug: str) -> bytes:
        _gate.check_grant(grant, self.corpus_id)
        return self.read_morpus(grant, slug if slug.endswith(".mrph5") else slug + ".mrph5")

    def tracks(self, grant) -> List[Dict[str, Any]]:
        _gate.check_grant(grant, self.corpus_id)
        raise NotAvailable("%s: the SDK does not list a local corpus's recordings; open one by its path" % self.corpus_id,
                           "no_store")

    def _recording(self, file: Any) -> Path:
        rel = safe_rel_path(file)
        if not rel or rel.split("/")[0] in (MORPUS_DIRNAME, ART_DIRNAME) or rel == MANIFEST_NAME:
            raise NotAvailable("%s: %r is not a recording's path" % (self.corpus_id, file), "bad_name")
        return self._inside(self.root / rel)

    def open_audio(self, grant, file: str, byte_range: Optional[Tuple[int, Optional[int]]]) -> BinaryIO:
        _gate.check_grant(grant, self.corpus_id)
        path = self._recording(file)
        fh = open(path, "rb")
        if byte_range and byte_range[0] is None:                     # the last n bytes
            fh.seek(max(0, path.stat().st_size - byte_range[1]))
        elif byte_range and byte_range[0]:
            fh.seek(byte_range[0])
        return fh

    def open_audio_ranged(self, grant, file: Any, byte_range) -> RangedAudio:
        _gate.check_grant(grant, self.corpus_id)
        path = self._recording(file)
        size = path.stat().st_size
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(size)}
        if byte_range is None:
            return RangedAudio(200, headers, open(path, "rb"))
        start, end = byte_range
        if start is None:
            start, end = max(0, size - end), size - 1
        else:
            end = size - 1 if end is None else min(end, size - 1)
        if size == 0 or start >= size:
            return RangedAudio(416, {"Accept-Ranges": "bytes", "Content-Range": "bytes */%d" % size, "Content-Length": "0"}, None)
        fh = open(path, "rb")
        fh.seek(start)
        headers.update({"Content-Length": str(end - start + 1), "Content-Range": "bytes %d-%d/%d" % (start, end, size)})
        return RangedAudio(206, headers, fh, end - start + 1)

    def read_art(self, grant, name: str) -> bytes:
        _gate.check_grant(grant, self.corpus_id)
        base = name.split("/")[-1] if isinstance(name, str) else ""
        if not safe_name(base):
            raise NotAvailable("%s: %r is not an art file name" % (self.corpus_id, name), "bad_name")
        return self._inside(self.root / ART_DIRNAME / base).read_bytes()


# ── the corpus ───────────────────────────────────────────────────────────────────────────

class Corpus:
    """One corpus. Make it with Corpus.from_manifest(), Corpus.load() or a HubClient."""

    def __init__(self, manifest: Mapping[str, Any], store=None, clock=time.time,
                 verdict_ttl: float = VERDICT_TTL_SEC, where: str = ""):
        reading = _gate.read_manifest(manifest)
        if reading.refusal:
            raise ManifestRefused(reading.refusal, reading.problems, where or reading.corpus_id)
        self._manifest: Dict[str, Any] = copy.deepcopy(dict(manifest))     # a view is copied to plain dicts too
        self._view: Optional[FrozenDict] = None
        self._reading = reading
        self._store = store if store is not None else _NoStore(reading.corpus_id)
        self._clock = clock
        self._verdict_ttl = float(verdict_ttl)

    # ---- making one ------------------------------------------------------------------
    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any], **kw) -> "Corpus":
        """A corpus from a manifest dict alone. Raises ManifestRefused."""
        return cls(manifest, **kw)

    @classmethod
    def load(cls, root, **kw) -> "Corpus":
        """A corpus from a folder holding corpus.json (or from its morpus/ folder).
        Raises ManifestRefused, also when there is no readable corpus.json."""
        root = Path(root)
        if root.name == MORPUS_DIRNAME and (root.parent / MANIFEST_NAME).exists():
            root = root.parent
        path = root / MANIFEST_NAME
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ManifestRefused("manifest_invalid", ("no readable corpus.json (%s)" % exc.__class__.__name__,), str(root)) from None
        except ValueError as exc:
            raise ManifestRefused("manifest_invalid", ("corpus.json is not JSON (%s)" % exc,), str(root)) from None
        cid = manifest.get("id") if isinstance(manifest, dict) else ""
        return cls(manifest, store=_LocalStore(cid if isinstance(cid, str) else "", root), where=str(root), **kw)

    # ---- metadata: free to read ------------------------------------------------------
    @property
    def id(self) -> str:
        return self._manifest["id"]

    @property
    def number(self) -> int:
        return int(self._manifest["number"])

    @property
    def slug(self) -> str:
        return self._manifest["slug"]

    @property
    def name(self) -> str:
        return self._manifest["name"]

    @property
    def artist(self) -> str:
        return self._manifest["artist"]

    @property
    def display_label(self) -> str:
        return self._manifest["display_label"]

    @property
    def description(self) -> str:
        return self._manifest.get("description", "")

    @property
    def edition_label(self) -> str:
        """The edition stamped on what this corpus inspires, e.g. "PB 9001 — PLACEHOLDERS Edition"."""
        return self._manifest.get("edition") or "PB %04d — %s Edition" % (self.number, self.slug)

    @property
    def licence(self) -> Licence:
        """The licence on paper. Whether something is allowed now is may()'s answer."""
        return self._reading.licence

    @property
    def visibility(self) -> str:
        """"public" or "private". A manifest that does not say is public."""
        return self._reading.visibility

    @property
    def form_cap(self) -> Optional[Dict[str, Any]]:
        cap = self._manifest.get("form_cap")
        return copy.deepcopy(cap) if cap else None

    @property
    def attestation(self) -> Optional[Dict[str, Any]]:
        block = self._manifest.get("attestation")
        return copy.deepcopy(block) if block else None

    @property
    def source(self) -> str:
        """"local", "hub" or "manifest": where this corpus's files are."""
        return self._store.source

    @property
    def root(self) -> Optional[Path]:
        """The folder a local or cached corpus lives in, or None."""
        return self._store.root

    @property
    def standing(self) -> Standing:
        return self._store.standing()

    def manifest(self) -> Dict[str, Any]:
        """A copy of the manifest, unknown members included. Yours to change."""
        return copy.deepcopy(self._manifest)

    def manifest_view(self) -> Dict[str, Any]:
        """The manifest, read-only and without a copy per call: the same object each time until
        the manifest changes (a refresh that brings a new one). Its dicts and lists are real
        dicts and lists that raise TypeError on any change, so the gate, a schema validator and
        json.dumps read it as they read a copy. copy.deepcopy(view), copy.copy(view) and pickle
        give back plain dicts and lists you may change, and Corpus.from_manifest(view) works."""
        if self._view is None:
            self._view = frozen(self._manifest)
        return self._view

    def summary(self) -> Dict[str, Any]:
        return {"id": self.id, "display_label": self.display_label, "name": self.name, "artist": self.artist,
                "edition": self.edition_label, "source": self.source, "visibility": self.visibility,
                "licence": self.licence.summary()}

    def __repr__(self) -> str:
        return "Corpus(%s, %s)" % (self.id, self.source)

    def notices(self) -> Dict[str, Any]:
        """The attribution a client must show with anything made from or played out of this
        corpus: the edition label, the corpus's own notice and each MIDI source's attribution.
        `lines` is the same, ready to print."""
        attributions, seen = [], set()
        for row in self._manifest.get("midi_sources") or []:
            text = (row.get("attribution") or "").strip()
            if not text:
                continue
            attributions.append({"file": row.get("file", ""), "title": row.get("title", ""), "attribution": text,
                                 "source_url": row.get("source_url", ""), "source_licence": row.get("source_licence", "")})
            seen.add(text)
        note = (self._manifest.get("license_note") or "").strip()
        lines = [self.edition_label] + ([note] if note else [])
        for row in attributions:
            if row["attribution"] in seen:
                seen.discard(row["attribution"])
                lines.append(row["attribution"])
        return {"corpus_id": self.id, "artist": self.artist, "edition": self.edition_label,
                "license_note": note, "attributions": attributions, "lines": lines}

    # ---- the gate --------------------------------------------------------------------
    def refresh(self, now: Any = None, force: bool = True) -> None:
        """Revalidate against the hub this corpus came from (nothing to do for a local one).
        A manifest the hub now serves that the SDK cannot read closes the corpus. `now` is the
        time to record the check at; leave it out for the corpus's own clock. A time you supply
        is never taken as something the cache witnessed (see gate.Standing.witnessed_at)."""
        fresh = self._store.freshen(_gate.to_epoch(now, self._clock), force, witness=now is None)
        if fresh is not None:
            reading = _gate.read_manifest(fresh)
            if not reading.refusal and reading.corpus_id == self.id:
                self._manifest = copy.deepcopy(dict(fresh))
                self._view = None
            elif not reading.refusal:
                reading = _gate.Reading(self.id, "manifest_invalid",
                                        ["#/id: the hub answered with %s" % reading.corpus_id], reading.licence)
            self._reading = reading

    def may(self, capability: str, identity: Optional[Identity] = None, now: Any = None) -> Verdict:
        """May `identity` do `capability` with this corpus now? Never raises. For a corpus from
        a hub this revalidates the licence first when it is due, by the corpus's own clock.
        `now` is the time to judge at, and nothing else: asking about another time ("what if it
        were next year?") writes nothing and moves no revalidation."""
        try:
            self.refresh(None, force=False)
        except Exception:      # a store that cannot revalidate is an unreachable hub, not a crash
            pass
        return _gate.decide(self._reading, capability, identity, now if now is not None else self._clock(),
                            self._store.standing())

    def _admit(self, verdict: Verdict, capabilities: Tuple[str, ...]):
        return _gate.admit(verdict, self.id, _gate.stamp_of(self._reading, self._store.standing()),
                           capabilities, float(self._clock()), self._verdict_ttl)

    # ---- content: every accessor takes the Verdict from may() --------------------------
    def morpus_index(self, verdict: Verdict) -> List[str]:
        """The names of the morpus files. Needs "study" or "export_morpus"."""
        return self._store.morpus_index(self._admit(verdict, _MORPUS))

    def study_pairs(self, verdict: Verdict) -> List[Tuple[str, str]]:
        """The (notes, MIDI) file name pairs the musicians study. Needs "study"."""
        return pairs_in(self._store.morpus_index(self._admit(verdict, _STUDY)))

    def read_morpus(self, name: str, verdict: Verdict) -> bytes:
        """One morpus file. Needs "study" or "export_morpus"."""
        return self._store.read_morpus(self._admit(verdict, _MORPUS), name)

    def morpus_path(self, name: str, verdict: Verdict) -> Path:
        """One morpus file as a path on disk (fetched into the cache first when the corpus is
        on a hub). Needs "study" or "export_morpus"; a hub corpus also needs to be storable here."""
        return self._store.morpus_path(self._admit(verdict, _MORPUS), name)

    def dna(self, verdict: Verdict) -> Dict[str, Any]:
        """The corpus DNA, parsed. Needs "study"."""
        data = json.loads(self._store.read_morpus(self._admit(verdict, _STUDY), DNA_NAME).decode("utf-8"))
        if not isinstance(data, dict):
            raise NotAvailable("%s: the DNA file is not an object" % self.id)
        return data

    def export_bundle(self, slug: str, verdict: Verdict) -> bytes:
        """One MRPH5 bundle, for handing to a person. Needs "export_morpus"."""
        return self._store.export_bundle(self._admit(verdict, _EXPORT), slug)

    def tracks(self, verdict: Verdict) -> List[Dict[str, Any]]:
        """The recordings a player can stream. Needs "stream_audio"."""
        return self._store.tracks(self._admit(verdict, _AUDIO))

    def open_audio(self, file: str, verdict: Verdict,
                   byte_range: Optional[Tuple[Optional[int], Optional[int]]] = None) -> BinaryIO:
        """One recording, open for reading. Needs "stream_audio". `byte_range` is (start, end)
        with end inclusive, (start, None) to the end, or (None, n) for the last n bytes."""
        return self._store.open_audio(self._admit(verdict, _AUDIO), file, read_range(byte_range))

    def open_audio_ranged(self, file: Any, verdict: Verdict, byte_range: Any = None,
                          range_header: Optional[str] = None) -> RangedAudio:
        """One recording for a relay: a RangedAudio with the source's status (200, 206 or 416)
        and the headers a relay passes on (RELAY_HEADERS). Needs "stream_audio". Give the range
        as `byte_range` (as open_audio takes it) or as `range_header`, the value of the Range
        header your own caller sent ("bytes=0-65535", "bytes=1000-", "bytes=-500"); neither is
        the whole recording. A range that cannot be read raises NotAvailable with reason
        "bad_range" and status 416; a range past the end comes back as a 416 answer."""
        return self._store.open_audio_ranged(self._admit(verdict, _AUDIO), file, read_range(byte_range, range_header))

    def read_art(self, name: str, verdict: Verdict) -> bytes:
        """One cover image. Needs "store_art"."""
        return self._store.read_art(self._admit(verdict, _ART), name)


__all__ = ["Corpus", "ManifestRefused", "NotAvailable", "NOT_AVAILABLE_REASONS", "GateRequired", "RangedAudio",
           "RELAY_HEADERS", "read_range", "range_value", "frozen", "safe_name", "safe_rel_path"]
