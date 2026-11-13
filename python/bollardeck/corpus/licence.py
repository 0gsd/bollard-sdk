# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus.licence: read a licence block (popboll.licence/1).

This module says what a block grants on paper: its scope, its eight capabilities and the two
moments it can close (revoked_at, expires_at). Whether a capability is allowed right now, for a
given caller, is the gate's answer (bollardeck.corpus.gate), never this module's.

Rules, fixed here:

  * A block is read only after it passes the "licence" schema. A block that fails is closed.
  * No block (None) grants nothing. Status "missing".
  * A scope this code does not know, or a version newer than VERSION, grants nothing.
  * A capability left out takes its scope's default; a hard limit of the scope wins over the
    block; a capability whose prerequisite is off is off.
  * Times are UTC. "2031-02-03T04:05:06Z", the same with a fraction or without the Z, or a date
    alone (midnight UTC). A UTC offset is refused. A time that is not a real moment (30 February)
    closes the block.
"""

import calendar
import re
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from .. import schema as _schema

SCHEMA = "popboll.licence/1"
VERSION = 1

FULL = "full"
MORPUS_ONLY = "morpus_only"
PUBLIC_DOMAIN_MIDI = "public_domain_midi"

CAPABILITIES: Tuple[str, ...] = (
    "transcode", "store_audio", "stream_audio", "store_art", "store_morpus",
    "musicians_may_study", "export_morpus", "device_copies",
    "stream_render",        # the MIDI may be played rendered through Pop Boll's own sounds (not a recording)
)

# (A, B): A is on only while B is on.
IMPLIES: Tuple[Tuple[str, str], ...] = (
    ("stream_audio", "store_audio"),
    ("musicians_may_study", "store_morpus"),
    ("export_morpus", "store_morpus"),
)

_ON = {k: True for k in CAPABILITIES}
# scope -> (defaults, hard limits nothing in the block can override)
SCOPES: Dict[str, Tuple[Mapping[str, bool], Mapping[str, bool]]] = {
    FULL: (dict(_ON, stream_render=False), {}),
    MORPUS_ONLY: (
        dict(_ON, store_audio=False, stream_audio=False, store_art=False, export_morpus=False, stream_render=False),
        {"store_audio": False, "stream_audio": False},
    ),
    PUBLIC_DOMAIN_MIDI: (
        dict(_ON, transcode=False, store_audio=False, stream_audio=False, store_art=False),
        {"store_audio": False, "stream_audio": False},
    ),
}

# Statuses of a block on paper. "active" here still has to pass the gate's clock.
OK = "ok"
MISSING = "missing"
INVALID = "invalid"
UNKNOWN_SCOPE = "unknown_scope"
NEWER_VERSION = "newer_version"

_TIME = re.compile(
    r"^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"(?:T([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])(\.[0-9]+)?Z?)?\Z")


class BadTime(ValueError):
    """A time that is not UTC in the licence format, or not a real moment."""


def parse_time(text: Any) -> Optional[float]:
    """Seconds since the epoch for a licence time; None for null or "". Raises BadTime."""
    if text is None or text == "":
        return None
    if not isinstance(text, str):
        raise BadTime("a time is a string, not %r" % (text,))
    m = _TIME.match(text)
    if not m:
        raise BadTime("%r is not a UTC time (YYYY-MM-DDTHH:MM:SS[.fff][Z] or YYYY-MM-DD; no offsets)" % text)
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if day > calendar.monthrange(year, month)[1]:
        raise BadTime("%r is not a real date" % text)
    hour, minute, second = (int(m.group(i)) if m.group(i) else 0 for i in (4, 5, 6))
    whole = calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))
    return whole + (float(m.group(7)) if m.group(7) else 0.0)


def format_time(ts: float) -> str:
    """A moment as the licence format writes it, to the second: 2031-02-03T04:05:06Z."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def to_epoch(when: Any, clock=time.time) -> float:
    """`when` as seconds since the epoch: None is now, a number is itself, a string is parsed."""
    if when is None:
        return float(clock())
    if isinstance(when, bool):
        raise BadTime("a clock is a number or a UTC time string")
    if isinstance(when, (int, float)):
        return float(when)
    ts = parse_time(when)
    if ts is None:
        raise BadTime("a clock is a number or a UTC time string")
    return ts


def resolve_flags(scope: str, block: Mapping[str, Any]) -> Dict[str, bool]:
    """The eight capabilities a block of a known scope grants on paper."""
    defaults, fixed = SCOPES[scope]
    flags = dict(defaults)
    for k in CAPABILITIES:
        if isinstance(block.get(k), bool):
            flags[k] = block[k]
    flags.update(fixed)
    for a, b in IMPLIES:
        if flags[a] and not flags[b]:
            flags[a] = False
    return flags


class Licence:
    """One licence block, read. Immutable. `status` is OK, MISSING, INVALID, UNKNOWN_SCOPE or
    NEWER_VERSION; anything but OK grants nothing."""

    __slots__ = ("status", "scope", "version", "flags", "revoked_at", "expires_at", "problems", "_block")

    def __init__(self, status: str, scope: str = "", version: int = VERSION,
                 flags: Optional[Mapping[str, bool]] = None, revoked_at: Optional[float] = None,
                 expires_at: Optional[float] = None, problems: Tuple[str, ...] = (),
                 block: Optional[Mapping[str, Any]] = None):
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "flags", dict(flags) if flags and status == OK else {k: False for k in CAPABILITIES})
        object.__setattr__(self, "revoked_at", revoked_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "problems", tuple(problems))
        object.__setattr__(self, "_block", dict(block) if isinstance(block, Mapping) else {})

    def __setattr__(self, name, value):
        raise AttributeError("a Licence does not change")

    @classmethod
    def from_block(cls, block: Any) -> "Licence":
        """Read a block. Never raises: a block that cannot be read is a closed Licence."""
        if block is None:
            return cls(MISSING, problems=("the corpus has no licence block",))
        problems = _schema.validate("licence", block)
        if problems:
            said = tuple(str(p) for p in problems)
            if isinstance(block, Mapping):
                scope, version = block.get("scope"), block.get("version", VERSION)
                if not isinstance(scope, str) or scope not in SCOPES:
                    return cls(UNKNOWN_SCOPE, scope if isinstance(scope, str) else "", problems=said, block=block)
                if isinstance(version, (int, float)) and not isinstance(version, bool) and version > VERSION:
                    return cls(NEWER_VERSION, scope, int(version), problems=said, block=block)
                return cls(INVALID, scope, problems=said, block=block)
            return cls(INVALID, problems=said)
        scope = block["scope"]
        try:
            revoked, expires = parse_time(block.get("revoked_at")), parse_time(block.get("expires_at"))
        except BadTime as exc:
            return cls(INVALID, scope, problems=(str(exc),), block=block)
        return cls(OK, scope, int(block.get("version", VERSION)), resolve_flags(scope, block),
                   revoked, expires, block=block)

    def grants(self, capability: str) -> bool:
        """What the block says on paper. Not an answer to "may I": ask the gate."""
        return bool(self.flags.get(capability, False))

    def why_off(self, capability: str) -> str:
        """Why a capability of an OK block is off, in words a UI can show."""
        if self.status != OK or capability not in CAPABILITIES or self.flags.get(capability):
            return ""
        defaults, fixed = SCOPES[self.scope]
        if capability in fixed:
            return "scope %s never allows %s" % (self.scope, capability)
        explicit = self._block.get(capability)
        if explicit is False:
            return "the licence switches %s off" % capability
        if not defaults[capability] and explicit is None:
            return "scope %s does not include %s" % (self.scope, capability)
        for a, b in IMPLIES:
            if a == capability and not self.flags.get(b):
                return "%s needs %s, which is off" % (a, b)
        return "%s is off" % capability

    def block(self) -> Dict[str, Any]:
        """A copy of the block as written (empty when there was none)."""
        return dict(self._block)

    def summary(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": self.status, "scope": self.scope, "version": self.version}
        out.update({k: bool(self.flags[k]) for k in CAPABILITIES})
        for k in ("revoked_at", "expires_at"):
            v = getattr(self, k)
            out[k] = format_time(v) if v is not None else None
        return out
