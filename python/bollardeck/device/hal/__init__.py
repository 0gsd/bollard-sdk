# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.hal: the hardware abstraction layer, interface version 1 (`HAL_API`).

    from bollardeck.device import hal

    board = hal.current()            # detected once: $BOLLAWAX_HAL > the device-tree model > sim
    board.name                       # "sim" on a dev machine
    board.maker_code                 # the maker code in this board's serials ("SIM")
    for ev in board.keys(stream).events(): ...     # a complete press, or ("down": 1) a press beginning
    board.cues().set([{"button": 1, "state": "on", "role": "a"}])
    board.power().read()             # PowerState(ac_online, percent, voltage_mv)
    board.storage().data_dir()
    hal.describe()                   # "sim", or "unoq (power->sim)" after a fallback

The protocols are in `hal.base`, the detection rules in `hal.detection`, the simulator in `hal.sim`.

## Board families and the registry

The SDK carries one family, the simulator. A real board's family lives with the code that drives
that board and registers itself:

    from bollardeck.device import hal

    hal.register("unoq", "mydevice.hal_unoq", maker_code="UNOQ")

`register(name, module, ...)`:

- `name`: the family name, lower case (`^[a-z][a-z0-9_]{1,15}$`). "sim" is taken.
- `module`: the board module itself, the dotted name of one to import, or a function with no
  arguments that returns one. A name or a function is not touched until the board is first used,
  so registering never imports hardware code. What a board module exports is listed in
  `hal.base`; anything it leaves out is the simulator's.
- `maker_code`: the maker code in this family's serials, used when the module cannot be loaded.
  Defaults to the built-in table (`unoq` -> UNOQ, `pi5` -> PI5).
- `matches`: a function taking the device-tree model string and saying whether it is this
  family. Leave it out for `unoq` and `pi5`, which the built-in rules already recognise.
- `replace=True` to register a name a second time.

Registering forgets the detected board, so register before the first `hal.current()` or call
`hal.reset()` after. `hal.registered()` lists the families; `hal.unregister(name)` removes one.

## Wrong hal is never fatal

A family that is detected and not registered, a module that fails to import, a module written for
a newer `HAL_API`, a subsystem that raises: each one falls back to the simulator's, is logged
once on the `bollardeck.hal` logger, and shows in `board.describe()`. A device with the wrong
image still boots and says what it is missing.
"""
from __future__ import annotations

import importlib
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

from . import base, detection, sim
from .base import (HAL_API, AudioOut, Cues, Display, Keys, KeyEvent, Matrix, Power, PowerState, Storage,
                   key_line, normalise_cue_list, parse_key_line)
from .detection import BUILTIN, DEVICE_TREE_MODEL, ENV_VAR

__all__ = ["HAL_API", "Board", "Family", "board", "current", "describe", "detect", "maker_code", "reset",
           "register", "unregister", "registered", "known", "KNOWN", "families", "base", "detection", "sim",
           "AudioOut", "Cues", "Display", "Keys", "KeyEvent", "Matrix", "Power", "PowerState", "Storage",
           "normalise_cue_list", "parse_key_line", "key_line"]

logger = logging.getLogger("bollardeck.hal")
_LOCK = threading.RLock()
_CURRENT: Optional["Board"] = None
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,15}$")
_MAKER_RE = re.compile(r"^[A-Z][A-Z0-9]{2,5}$")

ModuleSource = Union[str, Callable[[], Any], Any]
KNOWN = BUILTIN                 # the family names the built-in rules can return; see known() for all of them


@dataclass(frozen=True)
class Family:
    """One registered board family."""
    name: str
    source: Any                                   # a module, a dotted module name, or a loader function
    maker_code: str
    matches: Optional[Callable[[str], bool]] = None

    def load(self) -> Any:
        """The board module. Raises whatever importing or building it raises."""
        if isinstance(self.source, str):
            return importlib.import_module(self.source)
        if callable(self.source) and not hasattr(self.source, "NAME"):
            return self.source()
        return self.source


_FAMILIES: Dict[str, Family] = {"sim": Family("sim", sim, sim.MAKER_CODE)}


def register(name: str, module: ModuleSource, *, maker_code: Optional[str] = None,
             matches: Optional[Callable[[str], bool]] = None, replace: bool = False) -> Family:
    """Add a board family (see the package docstring). Returns the Family."""
    global _CURRENT
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError("hal family name %r must match %s" % (name, _NAME_RE.pattern))
    if name == "sim":
        raise ValueError("the simulator is built in; register a board family under its own name")
    if module is None:
        raise ValueError("hal family %r needs a module, a module name or a loader" % name)
    if matches is not None and not callable(matches):
        raise ValueError("hal family %r: matches must be a function of the model string" % name)
    code = str(maker_code or "").strip().upper() or base.MAKER_CODES.get(name, "")
    if not code and not isinstance(module, str) and not callable(module):
        code = str(getattr(module, "MAKER_CODE", "") or "").strip().upper()
    if not _MAKER_RE.match(code):
        raise ValueError("hal family %r needs a maker code (3 to 6 upper-case letters or digits, "
                         "starting with a letter), not %r" % (name, code))
    family = Family(name, module, code, matches)
    with _LOCK:
        if name in _FAMILIES and not replace:
            raise ValueError("hal family %r is already registered (replace=True to replace it)" % name)
        _FAMILIES[name] = family
        _CURRENT = None
    return family


def unregister(name: str) -> None:
    """Remove a registered family. Unknown names are ignored; the simulator stays."""
    global _CURRENT
    if name == "sim":
        raise ValueError("the simulator cannot be unregistered")
    with _LOCK:
        _FAMILIES.pop(name, None)
        _CURRENT = None


def registered() -> Tuple[str, ...]:
    """The registered family names, "sim" first, the rest in the order they were registered."""
    with _LOCK:
        return tuple(_FAMILIES)


def known() -> Tuple[str, ...]:
    """Every family name detection can return or $BOLLAWAX_HAL can force: the built-in names and
    the registered ones."""
    with _LOCK:
        return BUILTIN + tuple(n for n in _FAMILIES if n not in BUILTIN)


def detect(env: Optional[Mapping[str, str]] = None, model_path: Any = DEVICE_TREE_MODEL) -> str:
    """Which family this machine is (see `hal.detection` for the order)."""
    with _LOCK:
        rules = [(f.name, f.matches) for f in _FAMILIES.values() if f.matches is not None]
    return detection.detect(env=env, model_path=model_path, names=known(), rules=rules)


def load_module(name: str) -> Any:
    """The board module for a family; the simulator when the family is not registered, cannot be
    loaded, or was written for a newer hal interface."""
    with _LOCK:
        family = _FAMILIES.get(name)
    if family is None:
        if name not in BUILTIN:
            raise ValueError("unknown hal %r; one of %s" % (name, "/".join(known())))
        logger.warning("hal %s is not registered in this program; using sim", name)
        return sim
    try:
        module = family.load()
    except Exception as exc:  # noqa: BLE001 - a board whose code is missing or broken runs on the sim
        logger.warning("hal %s could not be loaded (%s: %s); using sim", name, type(exc).__name__, exc)
        return sim
    wants = getattr(module, "HAL_API", HAL_API)
    if isinstance(wants, bool) or not isinstance(wants, int) or wants > HAL_API or wants < 1:
        logger.warning("hal %s was written for hal interface %r and this SDK speaks %d; using sim",
                       name, wants, HAL_API)
        return sim
    return module


class Board:
    """One board: the module for `name`, each subsystem falling back to the simulator's on failure."""

    def __init__(self, name: str, module: Any = None):
        self.name = name
        self.module = module if module is not None else load_module(name)
        self.fallbacks: Dict[str, str] = {}
        if self.module is sim and name != "sim":
            self.fallbacks["module"] = "not available"

    @property
    def maker_code(self) -> str:
        """The maker code in this board's device serials: the module's MAKER_CODE, or the family's
        registered code when the simulator stands in for its module."""
        if getattr(self.module, "NAME", None) == self.name:
            code = str(getattr(self.module, "MAKER_CODE", "") or "").strip().upper()
            if code:
                return code
        with _LOCK:
            family = _FAMILIES.get(self.name)
        return family.maker_code if family is not None else base.maker_code_for(self.name)

    def _use(self, subsystem: str, make: Callable[[], Any], fallback: Callable[[], Any]) -> Any:
        try:
            return make()
        except Exception as exc:  # noqa: BLE001 - a board that cannot do X does X the sim way
            if subsystem not in self.fallbacks:
                logger.warning("hal %s: %s unavailable (%s: %s); using the sim's", self.name, subsystem,
                               type(exc).__name__, exc)
            self.fallbacks[subsystem] = f"{type(exc).__name__}: {exc}"
            return fallback()

    def keys(self, stream: Any = None) -> Keys:
        return self._use("keys", lambda: self.module.Keys(stream), lambda: sim.StdinKeys(stream))

    def matrix(self) -> Matrix:
        return self._use("matrix", lambda: self.module.Matrix(), sim.NoMatrix)

    def matrix_transport(self) -> Any:
        return self._use("matrix", lambda: self.module.matrix_transport(), sim.matrix_transport)

    def audio(self) -> AudioOut:
        return self._use("audio", lambda: self.module.AudioOut(), sim.NullAudio)

    def display(self) -> Display:
        return self._use("display", lambda: self.module.Display(), sim.FileDisplay)

    def power(self, sysfs_dir: Any = None) -> Power:
        return self._use("power", lambda: self.module.Power(sysfs_dir), lambda: sim.ACPower(sysfs_dir))

    def storage(self) -> Storage:
        return self._use("storage", lambda: self.module.Storage(), sim.EnvStorage)

    def cues(self) -> Cues:
        return self._use("cues", lambda: self.module.Cues(), sim.FileCues)

    def describe(self) -> str:
        if not self.fallbacks:
            return self.name
        return f"{self.name} ({', '.join(f'{k}->sim' for k in sorted(self.fallbacks))})"


def board(name: Optional[str] = None) -> Board:
    """A Board for `name` (detected when None). Not cached: see current()."""
    return Board(name or detect())


def current() -> Board:
    """The process's board, detected once."""
    global _CURRENT
    with _LOCK:
        if _CURRENT is None:
            _CURRENT = Board(detect())
        return _CURRENT


def reset() -> None:
    """Forget the detected board (tests; after changing $BOLLAWAX_HAL)."""
    global _CURRENT
    with _LOCK:
        _CURRENT = None


def maker_code() -> str:
    """The process's board's maker code ("UNOQ", "PI5", "SIM", or a registered family's)."""
    return current().maker_code


def describe() -> str:
    """For a boot line: the board and any subsystem that fell back to the simulator."""
    try:
        return current().describe()
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({type(exc).__name__})"


def families() -> List[Family]:
    """The registered families, as registered."""
    with _LOCK:
        return list(_FAMILIES.values())
