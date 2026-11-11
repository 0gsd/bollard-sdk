# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.hal.sim: the device on any Linux box, a VM or a dev machine.

Keys from a stream of key lines (stdin by default), no matrix of its own, null audio, mains power,
storage from the POPBOLLARD_* environment, button cues as one text line per change appended to
$BOLLAWAX_SIM_CUES, display frames as JSON lines appended to $BOLLAWAX_SIM_DISPLAY; and (SDK 0.2.0) a
file player that decodes nothing, audio routes from $BOLLAWAX_SIM_ROUTES, and a Bluetooth radio
that holds its devices in memory. Every other
board family falls back to this one, one subsystem at a time, so this module imports nothing
outside the standard library and the SDK.

    import io
    from bollardeck.device.hal import sim

    keys = sim.StdinKeys(io.StringIO("1 120 1000\n3 900 4000\n"))
    list(keys.events())            # two key events: a short press of 1, a long press of 3
    lights = sim.FileCues("cues.txt")
    lights.set([{"button": 2, "state": "pulse", "role": "go"}])     # appends "1:off:- 2:pulse:go 3:off:-"
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from ..cues import CueProblem, cue_line, normalise
from .base import (AUDIO_ROUTES, HAL_API, BtDevice, Cue, KeyEvent, NullHandle, PowerState, Route,  # noqa: F401 - HAL_API is this module's
                   parse_key_line)

logger = logging.getLogger("bollardeck.hal")

NAME = "sim"
MAKER_CODE = "SIM"                                   # reserved: a sim is never a shipped device
AC_POWER = PowerState(ac_online=True, percent=98.0, voltage_mv=4150)
DEFAULT_DATA_DIR = Path("/popbollard/data")
# Where corpora are looked for when $POPBOLLARD_CORPUS_DIRS is not set. Empty in the SDK; a
# program that has a place of its own for them assigns it once at start-up.
DEFAULT_CORPUS_DIRS: List[Path] = []


class StdinKeys:
    """Key lines from a stream (stdin by default): "<button> <hold_ms> [release_ms]" for a complete
    press and "<button> down [t_ms]" for a press beginning. A line the grammar rejects is skipped.
    events() ends at end of input."""

    def __init__(self, stream: Any = None):
        self.stream = stream if stream is not None else sys.stdin

    def events(self) -> Iterator[KeyEvent]:
        for line in self.stream:
            if line == "":
                return
            ev = parse_key_line(line)
            if ev is not None:
                yield ev


Keys = StdinKeys


class NoMatrix:
    """The sim has no LEDs: frames go nowhere."""

    def show(self, frame: bytes, w: int, h: int) -> None:
        return None


Matrix = NoMatrix


def matrix_transport() -> Any:
    """The sim has no matrix transport of its own: None, which means off."""
    return None


def render_matrix(frames: Sequence[Any]) -> bytes:
    """What a file transport writes for these frames: '<t_ms> <hex>' lines."""
    return "".join(f"{int(t)} {f.hex()}\n" for t, f in frames).encode("ascii")


class NullAudio:
    def play_midi(self, path: Path, sf: str) -> NullHandle:
        return NullHandle()

    def tone(self, hz: float, ms: int) -> None:
        return None


AudioOut = NullAudio


class FileDisplay:
    """Frame documents as JSON lines appended to $BOLLAWAX_SIM_DISPLAY when set, else dropped."""

    def __init__(self, path: Optional[Path] = None):
        p = path if path is not None else os.environ.get("BOLLAWAX_SIM_DISPLAY")
        self.path = Path(p) if p else None

    def push(self, frame: Dict[str, Any]) -> None:
        if self.path is None:
            return
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(frame, sort_keys=True) + "\n")


Display = FileDisplay


def render_cue_lines(sets: Sequence[Sequence[Cue]]) -> bytes:
    """What FileCues writes for these cue lists, set one after another: a line per change,
    "1:on:a 2:off:- 3:pulse:go", nothing for a set identical to the one before."""
    out, last = [], None
    for cues in sets:
        line = cue_line(cues)
        if line != last:
            out.append(line + "\n")
            last = line
    return "".join(out).encode("ascii")


class FileCues:
    """Button cues as text lines appended to $BOLLAWAX_SIM_CUES when set, else dropped: one line per
    change (render_cue_lines), so a tick loop may call set() as often as it likes. A bad cue is
    left out and logged once (`repairs` keeps every one seen, for a test to read)."""

    def __init__(self, path: Optional[Path] = None):
        p = path if path is not None else os.environ.get("BOLLAWAX_SIM_CUES")
        self.path = Path(p) if p else None
        self.last: Optional[str] = None
        self.repairs: List[CueProblem] = []
        self._said: Set[str] = set()

    def _report(self, problem: CueProblem) -> None:
        self.repairs.append(problem)
        if problem.message not in self._said:
            self._said.add(problem.message)
            logger.warning("cues: %s", problem)

    def set(self, cues: Sequence[Cue]) -> None:
        line = cue_line(normalise(cues, on_problem=self._report))
        if line == self.last:
            return
        self.last = line
        if self.path is None:
            return
        with self.path.open("a", encoding="ascii") as fh:
            fh.write(line + "\n")

    def clear(self) -> None:
        self.set([])


Cues = FileCues


class ACPower:
    """Mains power, always: a VM has no battery to park for."""

    def __init__(self, sysfs_dir: Any = None):
        self.sysfs_dir = sysfs_dir       # ignored: the sim never reads /sys

    def read(self) -> PowerState:
        return AC_POWER


Power = ACPower


class EnvStorage:
    """POPBOLLARD_DATA_DIR and POPBOLLARD_CORPUS_DIRS (os.pathsep-separated)."""

    def __init__(self, env: Optional[Dict[str, str]] = None):
        self.env = dict(os.environ if env is None else env)

    def data_dir(self) -> Path:
        return Path(self.env.get("POPBOLLARD_DATA_DIR") or DEFAULT_DATA_DIR)

    def corpus_dirs(self) -> List[Path]:
        raw = self.env.get("POPBOLLARD_CORPUS_DIRS") or ""
        dirs = [Path(p) for p in raw.split(os.pathsep) if p.strip()]
        return dirs or [Path(p) for p in DEFAULT_CORPUS_DIRS]


Storage = EnvStorage


# ---------------------------------------------------------------- SDK 0.2.0: files, routes, Bluetooth

FILE_SUFFIXES = (".mp3", ".flac", ".ogg", ".oga", ".opus", ".wav", ".webm", ".m4a", ".mp4", ".aac", ".mid", ".midi")


class NullFiles:
    """The sim decodes nothing: play_file records what it was asked (`played`, for a test) and
    plays silence; can_play goes by the file's name."""

    def __init__(self) -> None:
        self.played: List[Tuple[Path, int]] = []

    def play_file(self, path: Path, offset_ms: int = 0) -> NullHandle:
        if isinstance(offset_ms, bool) or int(offset_ms) < 0:
            raise ValueError("offset_ms is a time from the start of the file, not %r" % (offset_ms,))
        self.played.append((Path(path), int(offset_ms)))
        return NullHandle()

    def can_play(self, path: Path) -> bool:
        return Path(path).suffix.lower() in FILE_SUFFIXES


FilePlayer = NullFiles

ROUTES_ENV = "BOLLAWAX_SIM_ROUTES"
DEFAULT_SIM_ROUTES = ("dock",)          # a dev machine's own speakers stand for a dock


class SimRoutes:
    """Audio routes from $BOLLAWAX_SIM_ROUTES (comma-separated kinds, e.g. "jack,bt"; unset: "dock").
    The newest route listed is current at start. plug(kind) and unplug(kind) change what is
    available, for a test or a demo; unplugging the current route leaves "none" current. The hal
    only reports and switches: which route should win is the player's rule (spec v0.3 §6.3)."""

    def __init__(self, kinds: Optional[Sequence[str]] = None, env: Optional[Dict[str, str]] = None):
        environ = os.environ if env is None else env
        if kinds is None:
            raw = environ.get(ROUTES_ENV)
            kinds = [k.strip() for k in raw.split(",")] if raw is not None else list(DEFAULT_SIM_ROUTES)
        self._available: List[str] = []
        for k in kinds:
            if k and k != "none" and k in AUDIO_ROUTES and k not in self._available:
                self._available.append(k)
            elif k and k not in AUDIO_ROUTES:
                logger.warning("sim routes: %r is not a route (one of %s); left out", k, ", ".join(AUDIO_ROUTES))
        self._current = self._available[-1] if self._available else "none"
        self._volume: Dict[str, int] = {k: 50 for k in AUDIO_ROUTES if k != "none"}

    def available(self) -> List[Route]:
        return [Route(k, label=k) for k in self._available]

    def current(self) -> str:
        return self._current

    def select(self, kind: str) -> str:
        if kind == "none":
            self._current = "none"
        elif kind in self._available:
            self._current = kind
        else:
            raise ValueError("route %r is not available (available: %s)" % (kind, ", ".join(self._available) or "none"))
        return self._current

    def _kind(self, kind: Optional[str]) -> Optional[str]:
        k = self._current if kind is None else kind
        if k != "none" and k not in self._volume:
            raise ValueError("%r is not a route (one of %s)" % (k, ", ".join(AUDIO_ROUTES)))
        return None if k == "none" else k

    def volume(self, kind: Optional[str] = None) -> int:
        k = self._kind(kind)
        return 0 if k is None else self._volume[k]

    def set_volume(self, level: int, kind: Optional[str] = None) -> int:
        k = self._kind(kind)
        if k is None:
            return 0
        self._volume[k] = max(0, min(100, int(level)))
        return self._volume[k]

    def plug(self, kind: str) -> None:
        if kind not in AUDIO_ROUTES or kind == "none":
            raise ValueError("%r is not a route that can be plugged" % (kind,))
        if kind not in self._available:
            self._available.append(kind)

    def unplug(self, kind: str) -> None:
        if kind in self._available:
            self._available.remove(kind)
        if self._current == kind:
            self._current = "none"


AudioRoutes = SimRoutes


class SimBluetooth:
    """A radio in memory. No device exists until appear() says a headset is in pairing mode near
    by; a device that appears while a pair() window is open is paired and connected, otherwise it
    is only seen. tick(t_ms) closes a window whose time has passed. Time enters as t_ms."""

    def __init__(self) -> None:
        self._devices: Dict[str, BtDevice] = {}
        self._until: Optional[int] = None

    def devices(self) -> List[BtDevice]:
        return [self._devices[a] for a in sorted(self._devices)]

    def pair(self, seconds: int = 60, t_ms: int = 0) -> None:
        if isinstance(seconds, bool) or int(seconds) <= 0:
            raise ValueError("a pairing window is some seconds long, not %r" % (seconds,))
        self._until = int(t_ms) + int(seconds) * 1000

    def pairing_until(self) -> Optional[int]:
        return self._until

    def tick(self, t_ms: int) -> None:
        if self._until is not None and int(t_ms) > self._until:
            self._until = None

    def appear(self, address: str, name: str = "", t_ms: int = 0, kind: str = "audio") -> BtDevice:
        self.tick(t_ms)
        known = self._devices.get(address)
        paired = bool(known and known.paired) or self._until is not None
        dev = BtDevice(address, name or (known.name if known else ""), paired=paired, connected=paired, kind=kind)
        self._devices[address] = dev
        if self._until is not None:
            self._until = None              # one window pairs one headset
        return dev

    def connect(self, address: str) -> bool:
        dev = self._devices.get(address)
        if dev is None or not dev.paired:
            return False
        self._devices[address] = BtDevice(dev.address, dev.name, True, True, dev.kind)
        return True

    def disconnect(self, address: str) -> None:
        dev = self._devices.get(address)
        if dev is not None:
            self._devices[address] = BtDevice(dev.address, dev.name, dev.paired, False, dev.kind)

    def forget(self, address: str) -> None:
        self._devices.pop(address, None)


Bluetooth = SimBluetooth
