# SPDX-License-Identifier: Apache-2.0
"""
Ed25519 signature verification (RFC 8032, section 5.1.7), standard library only.

Verify only: this module holds no private-key code. A public key or an R of small order is refused (the 8 torsion
points: the identity "signs" every message), as libsodium refuses them. It is not constant time and does not need to
be, since everything it handles is public. tests/test_corpus_attest.py runs it against the
RFC 8032 section 7.1 test vectors.
"""

import hashlib
from typing import Optional, Tuple

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)                     # a square root of -1

Point = Tuple[int, int, int, int]                  # extended coordinates (X, Y, Z, T), x = X/Z, y = Y/Z, xy = T/Z

# The DER SubjectPublicKeyInfo of an Ed25519 key is this prefix and the 32 key bytes (RFC 8410).
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _add(a: Point, b: Point) -> Point:
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return E * F % _P, G * H % _P, F * G % _P, E * H % _P


def _mul(k: int, pt: Point) -> Point:
    out: Point = (0, 1, 1, 0)
    while k > 0:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def _equal(a: Point, b: Point) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _decode(raw: bytes) -> Optional[Point]:
    """A point from its 32-byte encoding, or None when the bytes are not a point."""
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        if sign:
            return None
        x = 0
    else:
        x = pow(x2, (_P + 3) // 8, _P)
        if (x * x - x2) % _P != 0:
            x = x * _I % _P
        if (x * x - x2) % _P != 0:
            return None
        if x & 1 != sign:
            x = _P - x
    return x, y, 1, x * y % _P


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = _decode(_GY.to_bytes(32, "little"))           # the base point (its x is even)


def _small(pt: Point) -> bool:
    """True for the 8 points of small order (8 * pt is the identity)."""
    return _equal(_mul(8, pt), (0, 1, 1, 0))


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` (64 bytes) is `public_key`'s (32 bytes) signature of `message`."""
    if not isinstance(public_key, (bytes, bytearray)) or not isinstance(signature, (bytes, bytearray)):
        return False
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decode(bytes(public_key))
    r = _decode(bytes(signature[:32]))
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= _L:
        return False
    if _small(a) or _small(r):                     # no secret behind them: the identity key "signs" anything
        return False
    h = int.from_bytes(hashlib.sha512(bytes(signature[:32]) + bytes(public_key) + bytes(message)).digest(), "little") % _L
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))


def raw_public_key(der_or_raw: bytes) -> Optional[bytes]:
    """The 32 key bytes from a DER SubjectPublicKeyInfo, or from the 32 bytes themselves."""
    if len(der_or_raw) == 32:
        return bytes(der_or_raw)
    if len(der_or_raw) == 44 and der_or_raw[:12] == SPKI_PREFIX:
        return bytes(der_or_raw[12:])
    return None
