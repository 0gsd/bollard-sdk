# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.cart: what a cart says about itself (SDK 0.2.0).

The cart self-descriptor, version 1 (the `cart-descriptor` schema): a cart's serial, role, power,
audio route and ports, sent in its bollardeck hello to a dock or a primary cart, shown by its SOS
console, and handed to a player running on it. Plain values; this module only checks them.

    from bollardeck.device import cart
    cart.problems({"v": 1, "serial": "PB0042-UNOQ-a1b2", "role": "pocket"})   # []
    cart.ROLES                        # ("primary", "guest", "tv", "pocket", "off")
"""

from typing import Any, List

from .. import schema as _schema
from ..constants import AUDIO_ROUTES, CART_ROLES, POWER_SOURCES

__all__ = ["VERSION", "ROLES", "ROUTES", "POWER_SOURCES", "problems"]

VERSION = 1
ROLES = tuple(CART_ROLES)
ROUTES = tuple(AUDIO_ROUTES)


def problems(desc: Any) -> List[str]:
    """Every reason a document is not a cart self-descriptor ([] = fine), as text."""
    return ["%s: %s" % (p.pointer or "(document)", p.message) for p in _schema.validate("cart-descriptor", desc)]
