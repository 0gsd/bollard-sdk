# SPDX-License-Identifier: Apache-2.0
"""The SDK's version and what it speaks. The single source: js/, c/ and the tag are checked against it."""

__version__ = "0.2.0"

# Wire and format versions this SDK speaks. Keys are the names the specifications use.
SPEAKS = {
    "bollardeck": "bollardeck/1",
    "routine_api": 1,
    "licence": "popboll.licence/1",
    "mrph5": "mrph5/1",
    "wbol": "wbol/1",
}

# The oldest Bollawax release this SDK is tested against.
MIN_BOLLAWAX = "0.2.4"
