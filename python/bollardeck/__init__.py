# SPDX-License-Identifier: Apache-2.0
"""
bollardeck: the Bollawax Bollard SDK.

Subpackages (each one's docstring is its usage guide; a placeholder says so):

    bollardeck.corpus    read corpora and respect their licence and settings
    bollardeck.device    the hardware abstraction, button cues, gestures, the keymap, device identity
    bollardeck.routines  the routine API
    bollardeck.deck      a minimal deck service and its client (a draft, as bollardeck Part A is)
    bollardeck.pxs       read, write and validate .pxs, the Pop Snip format (an IT module plus a PXS block)
    bollardeck.snipler   Glass Snipler event and frame types (a placeholder)

And four modules:

    bollardeck.matrix     the LED matrix frame engine, the twin of js/bollardeck.matrix.js
    bollardeck.help       check help packs and director scripts (the browser part is js/bollardeck.help.js)
    bollardeck.schema     validate a document against one of the platform's formats (schema/)
    bollardeck.constants  values Python and JS must agree on (generated from constants/)

Standard library only.
"""

from ._version import MIN_BOLLAWAX, SPEAKS, __version__

__all__ = ["__version__", "SPEAKS", "MIN_BOLLAWAX"]
