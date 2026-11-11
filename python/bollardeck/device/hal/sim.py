# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.hal.sim: the device on any Linux box, a VM or a dev machine.

Keys from a stream of key lines (stdin by default), no matrix of its own, null audio, mains power,
storage from the POPBOLLARD_* environment, button cues as one text line per change appended to
$BOLLAWAX_SIM_CUES, display frames as JSON lines appended to $BOLLAWAX_SIM_DISPLAY. Every other
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
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set

from ..cues import CueProblem, cue_line, normalise
from .base import HAL_API, Cue, KeyEvent, NullHandle, PowerState, parse_key_line  # noqa: F401 - HAL_API is this module's

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
