# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.hal.base: the protocols every board family implements, hal interface version 1.

A hal is a set of small Python protocols with one implementation per board family. The SDK
carries one family, `sim` (any Linux box, a VM, a dev machine); a real board's family is
registered from outside (`bollardeck.device.hal.register`). Programs talk to these shapes and never
to a device file; hardware libraries, if any, live only inside a board's own module. Standard
library only. Time enters as t_ms, never from the wall clock inside the hal.

A board module (or any object with these attributes) exports:

    NAME            its family name, the one it is registered under ("sim", "unoq", ...)
    MAKER_CODE      the maker code in this board's device serials, PB####-<MAKER>-<hardware id>
    HAL_API         optional: the hal interface version it was written for (absent means 1)
    Keys(stream)    button events                       -> the Keys protocol
    Matrix()        an LED matrix                       -> the Matrix protocol
    AudioOut()      sound                               -> the AudioOut protocol
    Display()       a screen that takes frame documents -> the Display protocol
    Power(sysfs)    battery and mains                   -> the Power protocol
    Storage()       where data and corpora live         -> the Storage protocol
    Cues()          button cues                         -> the Cues protocol
    FilePlayer()    audio files from an offset          -> the FilePlayer protocol      (optional, SDK 0.2.0)
    AudioRoutes()   where sound goes: dock, jack, ...   -> the AudioRoutes protocol     (optional, SDK 0.2.0)
    Bluetooth()     headsets and speakers               -> the Bluetooth protocol       (optional, SDK 0.2.0)
    matrix_transport()   the board's own matrix transport when nobody said which, or None for off
    render_matrix(frames)  the bytes this board's matrix renderer emits for [(t_ms, frame), ...]

Anything a module leaves out is taken from the simulator, one subsystem at a time.

`HAL_API` is the version of this interface: the protocol method names and signatures, the key
event and cue shapes, and the attribute list above. It goes up when a change would break a board
module written for the version before. The three subsystems marked SDK 0.2.0 were added without a new
version: a board module written before them simply lacks them and gets the simulator's, and
`PowerState` gained two fields with defaults, so `PowerState(ac_online, percent, voltage_mv)`
means what it always did.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Protocol, Sequence

from ...constants import (AUDIO_ROUTES, BUTTON_NUMBERS, CHASE_PERIOD_MS, CUE_ROLES, CUE_STATES, POWER_SOURCES,
                          PULSE_PERIOD_MS)
from ..cues import Cue, cue_line, normalise as normalise_cue_list

__all__ = ["HAL_API", "KeyEvent", "PowerState", "Handle", "Keys", "Matrix", "AudioOut", "Display", "Power",
           "Storage", "Cue", "Cues", "FilePlayer", "AudioRoutes", "Route", "Bluetooth", "BtDevice", "AUDIO_ROUTES",
           "POWER_SOURCES", "MAKER_CODES", "DEFAULT_MAKER_CODE", "maker_code_for", "BUTTONS",
           "parse_key_line", "key_line", "KEY_DOWN_WORD", "normalise_cue_list", "cue_line", "NullHandle", "frames_hex",
           "CUE_STATES", "CUE_ROLES", "PULSE_PERIOD_MS", "CHASE_PERIOD_MS"]

HAL_API = 1

# {"t": "key", "i": <button 1..3>, "down": 0, "hold_ms": int, "t_ms": int or None}
# One complete press: how long it was held, and when it was released if the bridge said. A key
# source that can see a press begin may also send {"t": "key", "i": <button>, "down": 1, "t_ms":
# int or None} at that moment, ahead of the "down": 0 event for the same press; the key line
# grammar has a line for each. A press beginning is a hint only: consumers that want complete
# presses skip events with "down": 1.
KeyEvent = Dict[str, Any]


@dataclass(frozen=True)
class PowerState:
    """What a board's power looks like now. `ac_online` is True when outside power is present (mains,
    a dock, a USB charger or computer); `percent` and `voltage_mv` describe the battery. Added in
    SDK 0.2.0, with defaults so the three-field form means what it always did: `source` (one of
    `POWER_SOURCES`: where the power comes from now, "unknown" when the board cannot tell) and
    `charging` (True while the battery charges, False when it does not, None when there is no
    battery or the board cannot tell)."""
    ac_online: bool
    percent: float
    voltage_mv: int
    source: str = "unknown"
    charging: Optional[bool] = None


class Handle(Protocol):
    """A sound that is playing: wait for it or stop it."""
    def wait(self, timeout: Optional[float] = None) -> None: ...
    def stop(self) -> None: ...


class Keys(Protocol):
    def events(self) -> Iterator[KeyEvent]: ...


class Matrix(Protocol):
    def show(self, frame: bytes, w: int, h: int) -> None: ...


class AudioOut(Protocol):
    def play_midi(self, path: Path, sf: str) -> Handle: ...
    def tone(self, hz: float, ms: int) -> None: ...


class Display(Protocol):
    def push(self, frame: Dict[str, Any]) -> None: ...     # a frame document (JSON)


class Power(Protocol):
    def read(self) -> PowerState: ...


class FilePlayer(Protocol):
    """Audio files (SDK 0.2.0). play_file starts `path` `offset_ms` into it on the current route and
    returns at once with a Handle; a pause is stop() and a later play_file at the paused offset.
    can_play says whether this board can decode the file at all (by its content or its name)."""
    def play_file(self, path: Path, offset_ms: int = 0) -> Handle: ...
    def can_play(self, path: Path) -> bool: ...


@dataclass(frozen=True)
class Route:
    """One place sound can go (SDK 0.2.0): `kind` is one of `AUDIO_ROUTES`; `label` is for people
    ("Bose QC35", "Pop Boll"); `device` is the board's own name for it (an ALSA or PipeWire sink,
    a Bluetooth address), opaque to programs."""
    kind: str
    label: str = ""
    device: str = ""


class AudioRoutes(Protocol):
    """Where the board's sound goes (SDK 0.2.0).
    available() lists the routes that could play now; current() is the kind playing now ("none"
    when none); select(kind) makes that route current and returns the kind now current (ValueError
    for a kind that is not available); volume and set_volume are 0..100 for a route (the current
    one when kind is None)."""
    def available(self) -> List[Route]: ...
    def current(self) -> str: ...
    def select(self, kind: str) -> str: ...
    def volume(self, kind: Optional[str] = None) -> int: ...
    def set_volume(self, level: int, kind: Optional[str] = None) -> int: ...


@dataclass(frozen=True)
class BtDevice:
    """A Bluetooth device the board knows (SDK 0.2.0). `kind` is "audio" for headphones and speakers
    (an A2DP sink), "other" for anything else."""
    address: str
    name: str = ""
    paired: bool = False
    connected: bool = False
    kind: str = "audio"


class Bluetooth(Protocol):
    """Headsets and speakers (SDK 0.2.0). The board is the audio source; pair() opens a window of
    `seconds` in which it looks for a headset in pairing mode and pairs with it; pairing_until is
    when that window closes (t_ms, None when closed). Time enters as t_ms, never from the clock."""
    def devices(self) -> List[BtDevice]: ...
    def pair(self, seconds: int = 60, t_ms: int = 0) -> None: ...
    def pairing_until(self) -> Optional[int]: ...
    def connect(self, address: str) -> bool: ...
    def disconnect(self, address: str) -> None: ...
    def forget(self, address: str) -> None: ...


class Storage(Protocol):
    def data_dir(self) -> Path: ...
    def corpus_dirs(self) -> List[Path]: ...


class Cues(Protocol):
    """What should be lit for each button. set() replaces the whole cue list (a button with no cue
    is not driven: the board's own lights keep it); clear() is set([]), no cue at all. set() never
    raises for a bad cue: it shows what `bollardeck.device.cues.normalise` keeps."""
    def set(self, cues: Sequence[Cue]) -> None: ...
    def clear(self) -> None: ...


# The maker code each first-party board family reports. A board module says the same as its
# MAKER_CODE; Board.maker_code falls back to this table when a family's module is not installed
# and the simulator stands in.
MAKER_CODES: Dict[str, str] = {"unoq": "UNOQ", "pi5": "PI5", "sim": "SIM"}
DEFAULT_MAKER_CODE = "UNOQ"        # every serial from before maker codes were registered carries it


def maker_code_for(name: str) -> str:
    """The maker code for a board family name; DEFAULT_MAKER_CODE for a name this table lacks."""
    return MAKER_CODES.get(str(name or "").strip().lower(), DEFAULT_MAKER_CODE)


# The buttons, as numbers. One tuple for cues, key events and the key-line grammar alike.
BUTTONS = tuple(BUTTON_NUMBERS)
_BUTTON_WORDS = {str(b): b for b in BUTTONS}


KEY_DOWN_WORD = "down"


def parse_key_line(line: str) -> Optional[KeyEvent]:
    """One line of the button format a GPIO bridge writes, as a key event; None for a line that is
    not one. The button is written exactly "1", "2" or "3".

        "<button> <hold_ms> [release_ms]"   a complete press, written at its release
            -> {"t": "key", "i": button, "down": 0, "hold_ms": ..., "t_ms": release_ms or None}
        "<button> down [t_ms]"              a press beginning, written the moment it goes down
            -> {"t": "key", "i": button, "down": 1, "t_ms": t_ms or None}

    The second line is optional: a bridge that can write it lets a gesture engine keep a chain of
    taps whole across a poll (`bollardeck.device.gestures`, rule 9). The complete-press line still
    follows at the release, and it alone says whether the press was a tap or a hold."""
    parts = str(line).strip().split()
    if len(parts) < 2 or parts[0] not in _BUTTON_WORDS:
        return None
    try:
        if parts[1] == KEY_DOWN_WORD:
            if len(parts) > 3:
                return None
            return {"t": "key", "i": _BUTTON_WORDS[parts[0]], "down": 1, "t_ms": int(parts[2]) if len(parts) > 2 else None}
        ev: KeyEvent = {"t": "key", "i": _BUTTON_WORDS[parts[0]], "down": 0, "hold_ms": int(parts[1]), "t_ms": None}
        if len(parts) > 2:
            ev["t_ms"] = int(parts[2])
        return ev
    except ValueError:
        return None


def key_line(button: int, hold_ms: Optional[int] = None, release_ms: Optional[int] = None, *, down: bool = False,
             t_ms: Optional[int] = None) -> str:
    """The line `parse_key_line` reads back: key_line(1, 120, 5000) -> "1 120 5000", and for a
    press beginning key_line(1, down=True, t_ms=4880) -> "1 down 4880" (or "1 down" with no time)."""
    if isinstance(button, bool) or button not in BUTTONS:
        raise ValueError("button must be 1, 2 or 3, not %r" % (button,))
    if down:
        if hold_ms is not None or release_ms is not None:
            raise ValueError("a press beginning has no hold_ms and no release_ms: pass t_ms")
        return "%d %s%s" % (button, KEY_DOWN_WORD, "" if t_ms is None else " %d" % int(t_ms))
    if hold_ms is None or t_ms is not None:
        raise ValueError("a complete press needs hold_ms, and its time is release_ms")
    tail = "" if release_ms is None else " %d" % int(release_ms)
    return "%d %d%s" % (button, int(hold_ms), tail)


class NullHandle:
    def wait(self, timeout: Optional[float] = None) -> None:
        return None

    def stop(self) -> None:
        return None


def frames_hex(frames: Sequence[Any]) -> List[str]:
    """[(t_ms, frame), ...] -> the frames' hex, for fixtures and messages. A frame is anything with
    a hex() method (bytes, or a matrix frame object)."""
    return [f.hex() for _t, f in frames]
