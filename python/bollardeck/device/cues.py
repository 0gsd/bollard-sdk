# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.cues: what should be lit for each of the three buttons.

The buttons have no lights of their own. A cue says what a button stands for right now, and each
board shows it where it can: the simulator writes a text line, the Boll uses its light ring and
matrix, a web page draws it. A cue list replaces the one before it; a button with no cue is not
driven.

    from bollardeck.device import cues

    lit = cues.normalise([cues.cue(1, "on", "a"), cues.cue(3, "pulse", "go")])
    # [{"button": 1, "state": "on", "role": "a"}, {"button": 3, "state": "pulse", "role": "go"}]
    cues.cue_line(lit)            # "1:on:a 2:off:- 3:pulse:go"
    cues.to_wire(lit)             # [{"btn": "inner", "state": "on", "role": "a"}, ...]

A button is its number, 1 to 3. States and roles are `CUE_STATES` and `CUE_ROLES` in
`bollardeck.constants`; a role may also be None. `pulse` breathes every `PULSE_PERIOD_MS`, `chase`
turns every `CHASE_PERIOD_MS`.

**A valid cue list** fits the `cue` schema and has at most one cue per button, in any order.
`problems(cues)` returns what is wrong with a list ([] when it is valid), each as a
`bollardeck.schema.Problem`; a second cue for a button is reported at its `button` with the
keyword `one-per-button`, because a schema cannot state that rule. The browser binding's
`bollardeck.cues.problems` gives the same answer for the same list.

**The normaliser.** `normalise(cues)` returns the cue list every renderer wants: one dict per
button with exactly `button`, `state` and `role`, at most one per button, in button order. Its
output is always a valid cue list. What it does with a list that is not valid is a decision
recorded here:

- By default it never raises. A cue it cannot use is dropped and a role it cannot use becomes
  None, because cues are set from tick loops that drive lights, and a light loop must not stop
  for one bad cue. Two cues for one button is not valid; the repair is to keep the last. Two
  things are tidied without comment: a cue with no `role` member has none, and members the cue
  model does not have are left out.
- Nothing else is repaired silently. `repairs(cues)` returns every drop and repair as a
  `CueProblem`, and `normalise(cues, on_problem=fn)` calls `fn` with each one. The hal's own cue
  renderers log them once.
- `normalise(cues, strict=True)` raises `CueError` instead. Use it where a cue list enters your
  program: a test, a routine, a message from another process.

**What a button shows.** `at(cues, t_ms)` answers for all three buttons at a moment, the same way
on every surface:

    cues.at([cues.cue(3, "pulse", "go")], 125)[2]
    # {"button": 3, "driven": True, "state": "pulse", "role": "go",
    #  "level": 0.675, "arc": [0.675, 0.675, 0.675], "head": None, "pixel": 172}

`driven` is False for a button the list does not mention (leave it alone). `level` is how bright
one lamp for the button is, 0 to 1; `arc` is the same for a surface that draws a button as
`CHASE_STEPS` lamps in a row; `head` is the lamp that leads a chase; `pixel` is `level` as 0 to
255. `off` is dark and `on` is full. `pulse` breathes once per `PULSE_PERIOD_MS` between 1 and
`PULSE_FLOOR`, full at t = 0. `chase` steps a full lamp through the arc once per
`CHASE_PERIOD_MS` with the others at `CHASE_TAIL`; a single lamp shows the middle of the arc.
`calm=True` (reduced motion) draws pulse and chase exactly as on. Time is counted in whole
milliseconds. `at` wants a valid list and raises `CueError` otherwise; `compile(cues)` checks
once and returns something to ask every frame. The vectors are `conformance/cue-render/`.

**The wire.** `bollardeck/1` names the buttons `inner`, `middle`, `outer` under the key `btn`,
and keeps those words for as long as it is `bollardeck/1` (`spec/bollardeck.md` §6.2; a wire that
carries button numbers is proposed for a later protocol version, §22). `to_wire` and `from_wire`
translate at that boundary and nowhere else; the two forms are not interchangeable, and
`normalise` refuses a wire-form cue.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .. import schema as _schema
from ..constants import (BUTTON_NUMBERS, BUTTONS, CHASE_PERIOD_MS, CHASE_STEPS, CHASE_TAIL, CUE_ROLES, CUE_STATES,
                         PULSE_FLOOR, PULSE_PERIOD_MS)

__all__ = ["Cue", "CueError", "CueProblem", "cue", "problems", "is_valid", "normalise", "repairs", "cue_line",
           "parse_cue_line", "to_wire", "from_wire", "button_for_wire", "wire_for_button",
           "at", "compile", "Compiled", "pulse_level", "chase_head", "to_pixel",
           "BUTTON_NUMBERS", "CUE_STATES", "CUE_ROLES", "PULSE_PERIOD_MS", "CHASE_PERIOD_MS", "PULSE_FLOOR",
           "CHASE_TAIL", "CHASE_STEPS", "ONE_PER_BUTTON"]

ONE_PER_BUTTON = "one-per-button"  # the keyword `problems` reports a second cue for a button under

Cue = Dict[str, Any]               # {"button": 1|2|3, "state": "off"|"on"|"pulse"|"chase", "role": "a"|...|None}

_WIRE_BY_BUTTON: Dict[int, str] = {row["button"]: row["wire"] for row in BUTTONS}
_BUTTON_BY_WIRE: Dict[str, int] = {row["wire"]: row["button"] for row in BUTTONS}


class CueProblem(NamedTuple):
    """One thing `normalise` dropped or repaired. `index` is the cue's place in the input (None for
    the list itself); `kind` is "list", "cue", "button", "state", "role" or "duplicate"; `dropped`
    says whether the cue was left out (True) or kept with a repair (False)."""
    index: Optional[int]
    kind: str
    message: str
    dropped: bool

    def __str__(self) -> str:
        where = "cue list" if self.index is None else "cue %d" % self.index
        return "%s: %s" % (where, self.message)


class CueError(ValueError):
    """A cue list that was refused. `problems` holds every reason: `CueProblem`s from strict
    normalising, or `bollardeck.schema.Problem`s from `at` and `compile`."""

    def __init__(self, found: Sequence[Any]):
        self.problems = list(found)
        super().__init__("; ".join(str(p) for p in self.problems))


def cue(button: int, state: str = "on", role: Optional[str] = None) -> Cue:
    """One well-formed cue, or `CueError`. `cue(2)` is button 2 lit with no role."""
    return _normalise([{"button": button, "state": state, "role": role}], strict=True)[0]


def _button_number(value: Any) -> Optional[int]:
    """1, 2 or 3 for a JSON integer that names a button (1.0 is the integer 1), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return int(value) if value == int(value) and int(value) in BUTTON_NUMBERS else None


def _scan(cues: Any) -> "tuple[List[Cue], List[CueProblem]]":
    found: List[CueProblem] = []
    by: Dict[int, Cue] = {}
    if not isinstance(cues, (list, tuple)):
        found.append(CueProblem(None, "list", "not a list (%s)" % type(cues).__name__, True))
        return [], found
    for i, c in enumerate(cues):
        if not isinstance(c, dict):
            found.append(CueProblem(i, "cue", "not an object", True))
            continue
        b = _button_number(c.get("button"))
        if b is None:
            hint = " (\"btn\" is the wire form: use from_wire)" if "btn" in c and "button" not in c else ""
            found.append(CueProblem(i, "button", "button must be 1, 2 or 3, not %r%s" % (c.get("button"), hint), True))
            continue
        state = c.get("state")
        if not isinstance(state, str) or state not in CUE_STATES:
            found.append(CueProblem(i, "state", "state must be one of %s, not %r" % ("/".join(CUE_STATES), state), True))
            continue
        role = c.get("role")
        if role is not None and (not isinstance(role, str) or role not in CUE_ROLES):
            found.append(CueProblem(i, "role", "role %r is not one of %s; read as none" % (role, "/".join(CUE_ROLES)), False))
            role = None
        elif role is not None and state == "off":
            found.append(CueProblem(i, "role", "an off cue carries no role; %r read as none" % role, False))
            role = None
        if b in by:
            found.append(CueProblem(i, "duplicate", "button %d has two cues; this one replaces the earlier" % b, False))
        by[b] = {"button": b, "state": state, "role": role}
    return [by[b] for b in sorted(by)], found


def _normalise(cues: Any, strict: bool = False, on_problem: Optional[Callable[[CueProblem], None]] = None) -> List[Cue]:
    out, found = _scan(cues)
    if strict and found:
        raise CueError(found)
    if on_problem is not None:
        for p in found:
            on_problem(p)
    return out


def normalise(cues: Any, *, strict: bool = False,
              on_problem: Optional[Callable[[CueProblem], None]] = None) -> List[Cue]:
    """The cue list every renderer wants (see the module docstring). The result always fits the
    `cue` schema. Not strict: never raises, drops what it cannot use, tells `on_problem` about each
    drop or repair. Strict: raises `CueError` on the first list with any problem."""
    return _normalise(cues, strict, on_problem)


def repairs(cues: Any) -> List[CueProblem]:
    """Everything `normalise` would drop or repair in `cues`, but for its two quiet tidyings (a
    missing role, an unknown member). [] when there is nothing to report."""
    return _scan(cues)[1]


def problems(cues: Any) -> List[_schema.Problem]:
    """What is wrong with `cues` as a cue list ([] when it is valid): the `cue` schema's problems,
    and a second cue for a button the list already has one for (keyword "one-per-button")."""
    found = _schema.validate("cue", cues)
    if found:
        return found
    seen = set()
    for i, c in enumerate(cues):
        b = int(c["button"])
        if b in seen:
            found.append(_schema.Problem("/%d/button" % i, "is a second cue for button %d" % b, ONE_PER_BUTTON))
        seen.add(b)
    return found


def is_valid(cues: Any) -> bool:
    """Is this a valid cue list: fits the `cue` schema, no button twice?"""
    return not problems(cues)


def cue_line(cues: Any) -> str:
    """One text line for a cue list, every button named: "1:on:a 2:off:- 3:pulse:go". A button with
    no cue reads off."""
    by = {c["button"]: c for c in _normalise(cues)}
    parts = []
    for b in BUTTON_NUMBERS:
        c = by.get(b) or {"state": "off", "role": None}
        parts.append("%d:%s:%s" % (b, c["state"], c["role"] or "-"))
    return " ".join(parts)


def parse_cue_line(line: str) -> List[Cue]:
    """The cue list a `cue_line` stands for, every button named. Raises `CueError` for a line that
    is not one."""
    out = []
    for i, part in enumerate(str(line).split()):
        bits = part.split(":")
        if len(bits) != 3 or bits[0] not in {str(b) for b in BUTTON_NUMBERS}:
            raise CueError([CueProblem(i, "cue", "%r is not <button>:<state>:<role or ->" % part, True)])
        out.append({"button": int(bits[0]), "state": bits[1], "role": None if bits[2] == "-" else bits[2]})
    return _normalise(out, strict=True)


def wire_for_button(button: int) -> str:
    """The name the bollardeck page uses for a button under "btn": 1 -> "inner"."""
    b = _button_number(button)
    if b is None:
        raise ValueError("button must be 1, 2 or 3, not %r" % (button,))
    return _WIRE_BY_BUTTON[b]


def button_for_wire(name: str) -> int:
    """The button a wire name stands for: "inner" -> 1."""
    try:
        return _BUTTON_BY_WIRE[name]
    except (KeyError, TypeError):
        raise ValueError("btn must be one of %s, not %r" % ("/".join(_BUTTON_BY_WIRE), name)) from None


def to_wire(cues: Any) -> List[Dict[str, Any]]:
    """A cue list as the content of a bollardeck `cues` message: `{"btn", "state", "role"}` with
    `btn` inner, middle or outer. The input is normalised first (not strict)."""
    return [{"btn": _WIRE_BY_BUTTON[c["button"]], "state": c["state"], "role": c["role"]} for c in _normalise(cues)]


def from_wire(items: Any, *, strict: bool = False,
              on_problem: Optional[Callable[[CueProblem], None]] = None) -> List[Cue]:
    """The cue list a bollardeck `cues` message carries, in the SDK's own form. An item whose `btn`
    is not a wire name is dropped (or refused, when strict), like any other bad cue."""
    if not isinstance(items, (list, tuple)):
        return _normalise(items, strict, on_problem)
    out: List[Any] = []
    for item in items:
        if isinstance(item, dict) and "button" not in item:
            b = _BUTTON_BY_WIRE.get(item.get("btn")) if isinstance(item.get("btn"), str) else None
            # an unknown btn becomes a button no cue can have, so it is refused with its own text
            out.append({"button": b if b is not None else "btn %r" % (item.get("btn"),),
                        "state": item.get("state"), "role": item.get("role")})
        else:
            # a device-form cue is not a wire cue: hand normalise something it will refuse
            out.append({"button": None, "state": None} if isinstance(item, dict) else item)
    return _normalise(out, strict, on_problem)


# ── what a button shows at a moment ──────────────────────────────────────────────────────

def _clock(t_ms: Any) -> int:
    if isinstance(t_ms, bool) or not isinstance(t_ms, (int, float)) or t_ms != t_ms or t_ms in (math.inf, -math.inf):
        raise TypeError("a time is a finite number of milliseconds, not %r" % (t_ms,))
    return int(t_ms)                   # whole milliseconds, towards zero, as the device counts


def _period(value: Any, default: int, name: str) -> float:
    p = default if value is None else value
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not p > 0:
        raise ValueError("%s must be a number above 0, not %r" % (name, p))
    return p


def pulse_level(t_ms: float, period_ms: Optional[float] = None) -> float:
    """The breathe of a pulse cue: 1 at t = 0 (and every period), PULSE_FLOOR half a period later."""
    p = _period(period_ms, PULSE_PERIOD_MS, "the pulse period")
    phase = (_clock(t_ms) % p) / p
    return PULSE_FLOOR + (1 - PULSE_FLOOR) * (0.5 + 0.5 * math.cos(math.tau * phase))


def chase_head(t_ms: float, period_ms: Optional[float] = None) -> int:
    """Which lamp of a button's arc leads a chase: 0, 1, 2 in turn, one turn per period."""
    p = _period(period_ms, CHASE_PERIOD_MS, "the chase period")
    return int((_clock(t_ms) % p) * CHASE_STEPS // p)


def to_pixel(level: float) -> int:
    """A level 0..1 as 0..255, a half rounding to the even neighbour."""
    return int(round(255 * level))


def _entry(button: int, c: Optional[Cue], t: int, calm: bool, pulse_ms: Any, chase_ms: Any) -> Dict[str, Any]:
    dark = [0] * CHASE_STEPS
    e: Dict[str, Any] = {"button": button, "driven": c is not None, "state": c["state"] if c else "off",
                         "role": c["role"] if c else None, "level": 0, "arc": dark, "head": None, "pixel": 0}
    if c is None or c["state"] == "off":
        return e
    if c["state"] == "chase" and not calm:
        e["head"] = chase_head(t, chase_ms)
        e["arc"] = [1 if i == e["head"] else CHASE_TAIL for i in range(CHASE_STEPS)]
        e["level"] = e["arc"][CHASE_STEPS // 2]
    else:
        k = pulse_level(t, pulse_ms) if c["state"] == "pulse" and not calm else 1
        e["level"], e["arc"] = k, [k] * CHASE_STEPS
    e["pixel"] = to_pixel(e["level"])
    return e


class Compiled:
    """A cue list that has been checked once. `cues` is the list in button order; `at(t_ms)` says
    what the three buttons show then."""

    def __init__(self, cues: Sequence[Cue]):
        self.cues: Tuple[Cue, ...] = tuple(dict(c) for c in cues)
        self._by = {c["button"]: c for c in self.cues}

    def at(self, t_ms: float, *, calm: bool = False, pulse_period_ms: Optional[float] = None,
           chase_period_ms: Optional[float] = None) -> List[Dict[str, Any]]:
        t = _clock(t_ms)
        return [_entry(b, self._by.get(b), t, bool(calm), pulse_period_ms, chase_period_ms) for b in BUTTON_NUMBERS]


def compile(cues: Any) -> Compiled:  # noqa: A001 - the browser binding's name for the same thing
    """Check a cue list once and get something to ask at each frame. Raises `CueError` (with the
    `problems`) when the list is not a valid cue list. The list is copied."""
    found = problems(cues)
    if found:
        raise CueError(found)
    return Compiled([{"button": int(c["button"]), "state": c["state"], "role": c["role"]}
                     for c in sorted(cues, key=lambda c: c["button"])])


def at(cues: Any, t_ms: float, *, calm: bool = False, pulse_period_ms: Optional[float] = None,
       chase_period_ms: Optional[float] = None) -> List[Dict[str, Any]]:
    """What the three buttons show at `t_ms` for this cue list: three entries, for buttons 1, 2,
    3 (see the module docstring). Raises `CueError` for a list that is not valid; in a loop that
    must not stop, pass `normalise(cues)`, or `compile` once."""
    return compile(cues).at(t_ms, calm=calm, pulse_period_ms=pulse_period_ms, chase_period_ms=chase_period_ms)
