# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.dock: reserved for the `Dock` protocol. Nothing is implemented here yet.

A dock is what a cart sits in: a Pop Boll, a Glass Snipler, or something a third party builds.
This module will hold the Python shape of a dock (what a dock tells a cart about itself, and what
a cart may ask of it), next to the hal protocols in `bollardeck.device.hal.base`.

It is empty on purpose. The protocol is defined by two specification texts that are not written:

1. **Bollard v2**, with the normative dock descriptor: its field types, the `class` and `layer`
   enums, and `slots`. `spec/bollard.md` in this repository is version 1, the interface under the
   Boll's foot; its §25 lists what is decided for v2.
2. **The bollardeck rewrite for the cart**: who says `hello` to whom, CDC or CDC-NCM, the guest
   hello with a secure-element challenge, and the EJECT and encoder events. `spec/bollardeck.md`
   §20 records what is decided about the cart and its docks, and lists what is not written.

A `Dock` written before those exist would be a guess that third parties then build against.
When both are published, this module gains: the descriptor as a typed value with a validator (and
a `dock-descriptor` schema under `schema/`), the `Dock` protocol, and a simulated dock beside
`hal.sim`. The C header `c/bollardeck.h` gets the same descriptor as structs.

Until then:

- `AVAILABLE` is False and `WAITS_ON` names the two documents, so a program can check.
- For buttons, lights, power and storage, use `bollardeck.device.hal`; that is what a Boll is
  today, and it will sit behind the `Dock` protocol later, not be replaced by it.

## The descriptor values (SDK 0.2.0, a draft)

What a Bolltridge needs from a dock is here already, as plain values checked by the
`dock-descriptor` schema (version 1, a draft Bollard v2 will make normative), so a cart can act on
a descriptor and on its absence with one shape:

    from bollardeck.device import dock
    dock.problems({"v": 1, "class": "speaker", "charge_w": 8})   # [] : fine
    dock.NO_DOCK                      # {"v": 1, "class": "none"}: nothing on the Bollport (pocket)
    dock.PLAIN                        # {"v": 1, "class": "plain"}: a hub or screen with no descriptor (TV)
    dock.charge_budget_w(desc)        # P4: what the cart may draw to charge; 5 W when a dock says nothing
    dock.role_for(desc)               # "primary", "tv" or "pocket"; "guest" when the cart is a USB device

"none" and "plain" are never sent by a dock: the cart makes them for itself.
"""

from typing import Any, List, Mapping, Optional

from .. import schema as _schema

__all__ = ["AVAILABLE", "WAITS_ON", "VERSION", "DOCK_CLASSES", "CART_MADE_CLASSES", "NO_DOCK", "PLAIN",
           "DEFAULT_CHARGE_W", "problems", "charge_budget_w", "role_for", "is_dock"]

AVAILABLE = False
WAITS_ON = ("Bollard v2 (the normative dock descriptor)", "the bollardeck specification rewritten for the cart")

VERSION = 1
DOCK_CLASSES = ("speaker", "screen")        # what a dock sends
CART_MADE_CLASSES = ("none", "plain")       # what the cart makes for itself: no dock, a dock that said nothing
NO_DOCK = {"v": VERSION, "class": "none"}
PLAIN = {"v": VERSION, "class": "plain"}
DEFAULT_CHARGE_W = 5.0                      # rule P4: a dock that states no budget allows 5 W


def problems(desc: Any) -> List[str]:
    """Every reason a document is not a dock descriptor ([] = fine), as text."""
    return ["%s: %s" % (p.pointer or "(document)", p.message) for p in _schema.validate("dock-descriptor", desc)]


def is_dock(desc: Optional[Mapping[str, Any]]) -> bool:
    """Is this a dock that described itself (not none, not plain, not missing)?"""
    return bool(desc) and desc.get("class") in DOCK_CLASSES


def charge_budget_w(desc: Optional[Mapping[str, Any]]) -> float:
    """What the cart may draw to charge its own battery here (spec v0.3 rule P4): the dock's
    charge_w, or DEFAULT_CHARGE_W when a dock or a plain hub states none; 0 with nothing on the
    Bollport (the cart then charges only from its side port)."""
    if not desc or desc.get("class") == "none":
        return 0.0
    w = desc.get("charge_w")
    if isinstance(w, bool) or not isinstance(w, (int, float)) or w < 0:
        return DEFAULT_CHARGE_W
    return float(w)


def role_for(desc: Optional[Mapping[str, Any]], usb_device: bool = False) -> str:
    """The cart role for what is on the Bollport (spec v0.3 §5.3): "guest" when the cart was given
    the USB device role behind a primary (it learns that from USB, not from a descriptor, C3a);
    else "primary" in a dock that described itself, "tv" with a plain hub or screen, "pocket" with
    nothing (no descriptor at all reads as nothing)."""
    if usb_device:
        return "guest"
    if is_dock(desc):
        return "primary"
    if desc and desc.get("class") == "plain":
        return "tv"
    return "pocket"
