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
"""

__all__ = ["AVAILABLE", "WAITS_ON"]

AVAILABLE = False
WAITS_ON = ("Bollard v2 (the normative dock descriptor)", "the bollardeck specification rewritten for the cart")
