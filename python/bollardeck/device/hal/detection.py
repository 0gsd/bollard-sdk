# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.hal.detection: which board family this is.

    family = $BOLLAWAX_HAL, when it names a known or registered family
           | the first registered family whose own rule accepts /proc/device-tree/model
           | with no model at all (a container: Docker hides /sys/firmware), the Arduino
             router's Unix socket at $ARDUINO_ROUTER_SOCKET (default
             /var/run/arduino-router.sock)                 -> unoq
           | from the model, by the built-in rules:
                 "Arduino UNO Q*" | "Arduino SA,Imola*"    -> unoq
                 "Raspberry Pi 5*" | "*Compute Module 5*"  -> pi5
           | sim

An unknown BOLLAWAX_HAL is never fatal: it is logged and the model decides. Detection names a
family; it does not need that family's code. A family that is detected and not registered runs on
the simulator (see the package docstring). Standard library only.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Tuple

logger = logging.getLogger("bollardeck.hal")

BUILTIN = ("unoq", "pi5", "sim")              # families the built-in rules can name
KNOWN = BUILTIN                               # the name this tuple has always had
ENV_VAR = "BOLLAWAX_HAL"
DEVICE_TREE_MODEL = Path("/proc/device-tree/model")
ROUTER_SOCKET_ENV = "ARDUINO_ROUTER_SOCKET"
ROUTER_SOCKET = Path("/var/run/arduino-router.sock")
UNOQ_MODELS = ("Arduino UNO Q", "Arduino SA,Imola")   # the second is what the board's device tree says

Rule = Tuple[str, Callable[[str], bool]]      # (family name, does this model string belong to it)


def model_string(path: Path = DEVICE_TREE_MODEL) -> str:
    """The device-tree model, NUL-stripped; "" when there is none (a Mac, a VM, a container without /proc)."""
    try:
        return Path(path).read_bytes().replace(b"\x00", b"").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def router_socket(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether the Arduino router's socket ($ARDUINO_ROUTER_SOCKET, else its default path) is a Unix socket
    here: the evidence of a Uno Q that a container can see. A tcp:// address or a plain file is not."""
    env = os.environ if env is None else env
    path = (env.get(ROUTER_SOCKET_ENV) or "").strip() or str(ROUTER_SOCKET)
    if "://" in path:
        return False
    try:
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def from_model(model: str) -> str:
    """The built-in rules alone."""
    m = (model or "").strip()
    if m.startswith(UNOQ_MODELS):
        return "unoq"
    if m.startswith("Raspberry Pi 5") or "Compute Module 5" in m:
        return "pi5"
    return "sim"


def detect(env: Optional[Mapping[str, str]] = None, model_path: Path = DEVICE_TREE_MODEL,
           names: Iterable[str] = BUILTIN, rules: Iterable[Rule] = ()) -> str:
    """The family name. `names` are the names $BOLLAWAX_HAL may force; `rules` are extra
    (name, matches) pairs tried, in order, before the built-in rules. `bollardeck.device.hal.detect()`
    is this function with the registry's names and rules filled in."""
    env = os.environ if env is None else env
    known = tuple(names)
    forced = (env.get(ENV_VAR) or "").strip().lower()
    if forced:
        if forced in known:
            return forced
        logger.warning("%s=%r is not one of %s; detecting the board instead", ENV_VAR, forced, "/".join(known))
    model = model_string(model_path)
    for name, matches in rules:
        try:
            if matches(model):
                return name
        except Exception as exc:  # noqa: BLE001 - a broken rule must not stop a device booting
            logger.warning("hal %s: its detection rule failed (%s: %s); skipped", name, type(exc).__name__, exc)
    if not model and router_socket(env):
        return "unoq"
    return from_model(model)
