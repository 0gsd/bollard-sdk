# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.gestures: button presses in, gestures out.

A pure state machine. It never reads a clock: every call carries a time in milliseconds on a clock
of your choosing, as long as it never runs backwards. The same engine, with the same rules, is
what a web page runs for its three on-screen buttons, and both are held to the vectors in
`conformance/gestures/timelines.json`.

    from bollardeck.device.gestures import GestureEngine

    engine = GestureEngine()                 # HOLD_MS 800, TAP_FOLLOW_MS 500, combos from the keymap
    engine.down(1, 0)                        # []
    engine.up(1, 120)                        # []   (button 1 has a triple tap: wait and see)
    engine.tick(621)                         # [Gesture("tap1", button=1, kind="tap", count=1, t_ms=620)]
    engine.down(3, 1000)                     # []
    engine.tick(1800)                        # [Gesture("hold3", ..., t_ms=1800)]  fires while still down
    engine.up(3, 2000)                       # []

Call `tick(now)` from a timer, or at least before you act on time passing; `next_deadline_ms()`
says when the next tick will have something to say. `down` and `up` advance the clock themselves.
`press(button, down_ms, up_ms)` feeds a complete press, and `key(event)` feeds a hal key event.

The clock is yours to keep. The engine raises ValueError when a time is earlier than the last one
it was given; it never clamps. A host that mixes two clocks (a bridge's release times and its own
for ticks, say) clamps before it calls: `t = max(t, last)`.

## The rules

Names: `tap<b>` one tap, `tap<b>x<n>` a chain of n taps, `hold<b>` a hold. `<b>` is 1, 2 or 3.

1. **Hold.** A press becomes `hold<b>` at the moment it has lasted `hold_ms`, while the button
   is still down. Its release then means nothing. A press released at exactly `hold_ms` is a hold.
2. **Tap.** A press released sooner is a tap.
3. **Combos.** `combos` says which chain lengths are gestures of their own, per button:
   `{1: [3], 3: [3]}` gives buttons 1 and 3 a triple tap. A button with no combos reports each
   tap as `tap<b>` at its release, with no delay.
4. **Chains.** On a button with combos, taps chain when the next press begins no later than
   `tap_follow_ms` after the last release. A chain that reaches the button's longest combo is
   reported at once as `tap<b>x<n>` (at the release of its last tap), and the chain is over.
5. **A chain ends early** when its follow window closes, when another button goes down, or when
   a hold fires (a hold is never part of a chain). It is then reported: as `tap<b>x<n>` when n is
   one of the button's combos, otherwise as n separate `tap<b>`, oldest first. So a lone tap on a
   button with combos is reported `tap_follow_ms` late.
6. **When.** Each gesture carries the time it became certain: the release for a completed combo
   or an undelayed tap; the end of the window (last release + `tap_follow_ms`) for a chain that
   timed out; the other button's press for a chain that was cut; `hold_ms` after the press for a
   hold, and that same moment for the taps it flushes ahead of itself. A window that closes at
   time D is reported by the first call with a time later than D; a press at exactly D still
   chains.
7. **Cancel.** `cancel(b, t)` drops a press that was not meant (the pointer left, the page lost
   focus). It is not a tap. If it had continued a chain, the chain's window starts again at t.
8. **Odd input.** `down` for a button that is already down and `up` or `cancel` for one that is
   not are ignored. A time earlier than the last one seen, or a button that is not 1, 2 or 3,
   raises ValueError.

9. **Key events.** `key(event)` takes what a hal's key source sends. A complete press
   (`"down": 0`, with the `hold_ms` it lasted) is a tap or a hold by that `hold_ms` alone, never
   by when the event is read: a release that is read late is still the tap it says it is. A press
   beginning (`"down": 1`) is a hint and never a gesture. It does one thing: while taps are
   pending on that button and the press began inside their follow window, their window is not
   closed until the press ends or has lasted `hold_ms`. A beginning whose release never comes is
   a lost press: it yields nothing, the next press on that button is a press of its own, and the
   hint is forgotten after `press_lost_ms`. A hold that arrives as a key event is reported when
   its release is read, stamped `hold_ms` after it began.
   A release is matched to a beginning before the beginning is believed. A release that states
   its own time (`t_ms`) and `hold_ms` describes a press that began at `t_ms - hold_ms`: it
   belongs to the announced press only when that is within `PRESS_MATCH_MS` of the
   announcement, so the two must be on one clock. If it began later, the announced press was
   lost: the hint is dropped and the release is a press of its own, at its own times. If it
   began earlier, it is an older press and the hint is kept for the one still under way. A
   release with no time of its own is read late at worst, so it belongs unless it began before
   the announcement. A release with no `hold_ms` is measured from its announcement only while
   that makes it a tap; otherwise the hint is dropped and it is a press of no length. Limit: a
   lost release followed, inside `press_lost_ms`, by a press that was not announced and states
   no time cannot be told from a late read, and is placed at the announcement.
10. **How long.** Each gesture carries `hold_ms`, how long its press lasted: for a tap, down to
   release; for a chain, its last tap; for a hold that fires while the button is still down, the
   engine's `hold_ms` (the press is not over); for a hold fed as a complete press, the whole
   press.

Debouncing is not here: drop contact bounce before it reaches the engine.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ..constants import (BUTTON_NUMBERS, GESTURES, HOLD_MS, KEYMAP, PRESS_LOST_MS, PRESS_MATCH_MS, TAP_CHAIN_MAX,
                         TAP_FOLLOW_MS)

__all__ = ["Gesture", "GestureEngine", "gesture_name", "parse_gesture", "combos_from_keymap", "DEFAULT_COMBOS",
           "GESTURES", "HOLD_MS", "TAP_FOLLOW_MS", "TAP_CHAIN_MAX", "PRESS_LOST_MS", "PRESS_MATCH_MS"]

_NAME_RE = re.compile(r"^(tap|hold)([1-9])(?:x([1-9][0-9]*))?\Z")


class Gesture(NamedTuple):
    """One gesture. `name` is what a keymap is keyed by; `kind` is "tap" or "hold"; `count` is the
    number of taps (1 for a hold); `t_ms` is when it became certain; `hold_ms` is how long its
    press lasted (rule 10; None only on a Gesture made by hand without one)."""
    name: str
    button: int
    kind: str
    count: int
    t_ms: int
    hold_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"gesture": self.name, "t_ms": self.t_ms}


def gesture_name(kind: str, button: int, count: int = 1) -> str:
    """"tap1", "tap3x3", "hold2"."""
    if kind == "hold":
        return "hold%d" % button
    return "tap%d" % button if count == 1 else "tap%dx%d" % (button, count)


def parse_gesture(name: str) -> Tuple[str, int, int]:
    """(kind, button, count) for one of the names in `GESTURES`; ValueError for anything else."""
    m = _NAME_RE.match(name) if isinstance(name, str) else None
    if not m or name not in GESTURES:
        raise ValueError("%r is not a gesture name (one of %s)" % (name, ", ".join(GESTURES)))
    return m.group(1), int(m.group(2)), int(m.group(3) or 1)


def combos_from_keymap(keymap: Mapping[str, Any], contexts: Iterable[str] = ()) -> Dict[int, Tuple[int, ...]]:
    """The chain lengths a keymap gives a meaning to, per button: the combos an engine needs so
    that every gesture the keymap names can happen. {1: (3,), 3: (3,)} for the platform's keymap.
    `contexts` adds the maps of those device contexts ("pocket"): an engine for a cart in a pocket
    is made with `combos_from_keymap(KEYMAP, ("pocket",))`, which gives every button a double tap;
    with no contexts the answer is what it was before contexts existed."""
    found: Dict[int, set] = {}
    for section in ("prompt", "idle", "always") + tuple(contexts):
        for name in (keymap.get(section) or {}):
            m = _NAME_RE.match(name)
            if m and m.group(1) == "tap" and m.group(3):
                found.setdefault(int(m.group(2)), set()).add(int(m.group(3)))
    return {b: tuple(sorted(ns)) for b, ns in sorted(found.items())}


DEFAULT_COMBOS: Dict[int, Tuple[int, ...]] = combos_from_keymap(KEYMAP)


def _check_combos(combos: Mapping[Any, Iterable[int]]) -> Dict[int, Tuple[int, ...]]:
    out: Dict[int, Tuple[int, ...]] = {}
    for key, counts in combos.items():
        button = int(key) if isinstance(key, str) and key.isdigit() else key
        if isinstance(button, bool) or button not in BUTTON_NUMBERS:
            raise ValueError("combos: %r is not a button (1, 2 or 3)" % (key,))
        ns = tuple(sorted(set(counts)))
        for n in ns:
            if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= TAP_CHAIN_MAX:
                raise ValueError("combos: a chain is 2 to %d taps, not %r" % (TAP_CHAIN_MAX, n))
        if ns:
            out[button] = ns
    return out


class GestureEngine:
    """See the module docstring for the rules. One engine per set of three buttons."""

    def __init__(self, *, hold_ms: int = HOLD_MS, tap_follow_ms: int = TAP_FOLLOW_MS,
                 combos: Optional[Mapping[Any, Iterable[int]]] = None, press_lost_ms: int = PRESS_LOST_MS):
        if hold_ms <= 0 or tap_follow_ms < 0 or press_lost_ms < 0:
            raise ValueError("hold_ms must be above 0, and tap_follow_ms and press_lost_ms 0 or more")
        self.hold_ms = int(hold_ms)
        self.tap_follow_ms = int(tap_follow_ms)
        self.press_lost_ms = int(press_lost_ms)
        self.combos = _check_combos(DEFAULT_COMBOS if combos is None else combos)
        self._now: Optional[int] = None
        self._down: Dict[int, List[Any]] = {}       # button -> [down_ms, hold already fired]
        self._began: Dict[int, Any] = {}            # button -> when a key source said a press began (a hint)
        self._chain_holds: List[Any] = []           # how long each pending tap lasted, oldest first
        self._chain_dropped = False                 # set_combos took the pending chain's combos away
        self._chain_button: Optional[int] = None
        self._chain_count = 0
        self._chain_release = 0                     # when the chain's last tap was released
        self._chain_open = False                    # the chain's button is down again, in time

    # -- reading the state ------------------------------------------------------------------

    @property
    def pending(self) -> int:
        """Taps waiting to learn whether they are part of a chain."""
        return self._chain_count

    def is_down(self, button: int) -> bool:
        """Is this button down, as `down` and `up` have told it? A press a key source only
        announced is not: see `waiting`."""
        return button in self._down

    def waiting(self, button: Optional[int] = None) -> bool:
        """Has a key source announced a press (on this button, or on any) whose release has not
        been read yet and is not yet given up on?"""
        return bool(self._began) if button is None else button in self._began

    def next_deadline_ms(self) -> Optional[int]:
        """The earliest time at which `tick` would report something if nothing else happens; None
        when nothing is waiting on the clock."""
        if self._chain_dropped and self._chain_count:
            return self._now or 0
        times = [d + self.hold_ms for d, held in self._down.values() if not held]
        if self._chain_count and not self._chain_open:
            began = self._began.get(self._chain_button)
            closes = self._chain_release + self.tap_follow_ms
            # An announced press that began inside the window holds it until it could no longer
            # be a tap, or until it is given up on, whichever is sooner.
            until = None if began is None or began > closes else min(began + self.hold_ms, began + self.press_lost_ms + 1)
            times.append(closes + 1 if until is None else max(closes + 1, until))
        return min(times) if times else None

    def set_combos(self, combos: Optional[Mapping[Any, Iterable[int]]] = None) -> "GestureEngine":
        """Change which chain lengths are gestures, on a running engine (None: the keymap's).
        Nothing in flight is lost: a button that is down stays down and pending taps stay
        pending, judged by the new combos from here on. Taps pending on a button that no longer
        has a combo, or that are already as many as its longest, are reported by the next call
        (stamped with the end of their window, or with that call's time while the window is
        still open)."""
        self.combos = _check_combos(DEFAULT_COMBOS if combos is None else combos)
        self._chain_dropped = self._chain_over()
        return self

    # -- feeding it -------------------------------------------------------------------------

    def tick(self, t_ms: int) -> List[Gesture]:
        """Say what time it is. Returns what became certain since the last call."""
        return self._advance(self._time(t_ms))

    def down(self, button: int, t_ms: int) -> List[Gesture]:
        b, t = self._button(button), self._time(t_ms)
        out = self._advance(t)
        if b in self._down:
            return out
        if self._chain_count:
            if self._chain_button != b:
                out += self._flush(t)                 # another button ends a chain
            else:
                self._chain_open = True               # pressed in time: wait for this one
        self._down[b] = [t, False]
        return out

    def up(self, button: int, t_ms: int) -> List[Gesture]:
        b = self._button(button)
        if b in self._down:
            self._began.pop(b, None)                  # an edge is the truth: a hint for this button is over
        return self._up(b, t_ms)

    def _up(self, b: int, t_ms: int) -> List[Gesture]:
        t = self._time(t_ms)
        out = self._advance(t)                        # a press that reached hold_ms fires here
        if b not in self._down:
            return out
        down_ms, held = self._down.pop(b)
        if held:
            return out
        return out + self._tap(b, t, t - down_ms)

    def cancel(self, button: int, t_ms: int) -> List[Gesture]:
        b, t = self._button(button), self._time(t_ms)
        out = self._advance(t)
        self._began.pop(b, None)                      # a cancelled press takes its announcement with it
        if b not in self._down:
            return out
        self._down.pop(b)
        if self._chain_count and self._chain_button == b and self._chain_open:
            self._chain_open = False
            self._chain_release = t                   # the window starts again
        return out

    def press(self, button: int, down_ms: int, up_ms: int) -> List[Gesture]:
        """One complete press: `down` then `up`."""
        return self.down(button, down_ms) + self.up(button, up_ms)

    def key(self, event: Mapping[str, Any], now_ms: Optional[int] = None) -> List[Gesture]:
        """One hal key event (rule 9). `{"t": "key", "i": button, "down": 0, "hold_ms": ..., "t_ms":
        release or None}` is a complete press, `hold_ms` long, that ended at its `t_ms` (at
        `now_ms` when the bridge gave no time). It is a tap or a hold by its `hold_ms` alone.

        `{"t": "key", "i": button, "down": 1, "t_ms": ...}` says a press began. It is a hint: it
        returns [] and never becomes a gesture. It keeps pending taps on that button from being
        reported as singles by a `tick` that runs while the next press of their chain is still
        held, and the press it announces is then placed at `began .. began + hold_ms` whatever
        time its release carries or is read at. Without the hint the engine cannot take back
        what a tick reported: a host that ticks with the wall clock and gets only complete
        presses sees a chain whose next press was still down at the tick as single taps.

        Only a button that `down()` itself was called for is ended by a `"down": 0` event as an
        edge, at the event's time."""
        b = self._button(event.get("i"))
        release = event.get("t_ms")
        if release is None:
            release = now_ms
        if release is None:
            raise ValueError("this key event has no time: pass now_ms")
        self._forget_lost(release if now_ms is None else max(release, now_ms))
        if event.get("down"):
            self._began[b] = release                                     # a hint, and nothing more
            return []
        if b in self._down:
            self._began.pop(b, None)
            return self.up(b, max(release, self._now or release))        # the end of a press down() began
        began = self._began.get(b)
        stated = event.get("hold_ms")
        if began is not None:
            # Is this the release of the press that was announced? (rule 9)
            if stated is None:
                age = release - began
                belongs, stale = 0 <= age < self.hold_ms, True           # never a hold from the hint's age
                stated = age if belongs else None
            else:
                starts = release - max(0, int(stated or 0))              # when the press it describes began
                own_time = event.get("t_ms") is not None
                belongs = (abs(starts - began) <= PRESS_MATCH_MS if own_time else starts >= began - PRESS_MATCH_MS)
                stale = starts > began                                   # the announced press was lost
            if belongs or stale:
                del self._began[b]
            if not belongs:
                began = None
        held = max(0, int(stated or 0))
        if began is not None:
            release = began + held                                       # placed by its beginning
        start = release - held
        if self._now is None or start >= self._now:
            out = self.down(b, start) + self._up(b, release)      # not up(): a hint kept above stays
            return [g._replace(hold_ms=held) if g.kind == "hold" and g.button == b else g for g in out]
        # The press began before the last time this engine was told about (a tick ran while the
        # button was down, or the event arrived late). Judge it by its own two times.
        out: List[Gesture] = self._dropped(self._now)
        if self._chain_count and self._chain_button != b:
            out += self._flush(start)
        if held >= self.hold_ms:
            out += self._flush(start + self.hold_ms)
            out.append(Gesture(gesture_name("hold", b), b, "hold", 1, start + self.hold_ms, held))
        else:
            out += self._tap(b, release, held)
        self._now = max(self._now, release)
        return out

    def feed(self, event: Mapping[str, Any]) -> List[Gesture]:
        """One event as the conformance vectors write it: `{"t_ms", "edge": "down"|"up"|"cancel",
        "button"}`, `{"t_ms", "edge": "tick"}`, `{"t_ms", "edge": "key", "key": {a hal key event}}`,
        which is `key(event["key"], now_ms=event["t_ms"])`: a key event read at t_ms, or
        `{"edge": "combos", "combos": {...}}`, which is `set_combos`."""
        edge = event.get("edge")
        if edge == "key":
            return self.key(event["key"], now_ms=event["t_ms"])
        if edge == "combos":
            self.set_combos(event["combos"])
            return []
        if edge == "tick":
            return self.tick(event["t_ms"])
        if edge in ("down", "up", "cancel"):
            return getattr(self, edge)(event["button"], event["t_ms"])
        raise ValueError("edge must be down, up, cancel, tick, key or combos, not %r" % (edge,))

    def run(self, events: Sequence[Mapping[str, Any]]) -> List[Gesture]:
        """Every gesture a list of events produces, in order."""
        out: List[Gesture] = []
        for event in events:
            out += self.feed(event)
        return out

    # -- the machine ------------------------------------------------------------------------

    @staticmethod
    def _button(button: Any) -> int:
        if isinstance(button, bool) or button not in BUTTON_NUMBERS:
            raise ValueError("button must be 1, 2 or 3, not %r" % (button,))
        return int(button)

    def _time(self, t_ms: Any) -> int:
        if isinstance(t_ms, bool) or not isinstance(t_ms, (int, float)) or t_ms != t_ms:
            raise ValueError("t_ms must be a number, not %r" % (t_ms,))
        if self._now is not None and t_ms < self._now:
            raise ValueError("time ran backwards: %r after %r" % (t_ms, self._now))
        self._now = t_ms
        return t_ms

    def _chain_over(self) -> bool:
        """After set_combos: can the pending chain no longer grow?"""
        counts = self.combos.get(self._chain_button) if self._chain_count else None
        return self._chain_count > 0 and (not counts or self._chain_count >= counts[-1])

    def _dropped(self, t: Any) -> List[Gesture]:
        """Report a chain that set_combos ended, as of time t."""
        if not self._chain_dropped:
            return []
        self._chain_dropped = False
        if not self._chain_over():
            return []
        return self._flush(t if self._chain_open else min(t, self._chain_release + self.tap_follow_ms))

    def _forget_lost(self, t: Any) -> None:
        """Drop the hint of a press whose release has not come press_lost_ms after it began."""
        for b in [b for b, began in self._began.items() if t - began > self.press_lost_ms]:
            del self._began[b]

    def _held_back(self, t: Any) -> bool:
        """Is the pending chain waiting on an announced press that began in its window and may
        still be a tap at time t?"""
        began = self._began.get(self._chain_button)
        return (began is not None and began <= self._chain_release + self.tap_follow_ms
                and t < began + self.hold_ms)

    def _tap(self, b: int, t: int, held: Any) -> List[Gesture]:
        """A tap on button b, `held` long, was released at time t."""
        counts = self.combos.get(b)
        if not counts:
            return self._flush(t) + [Gesture(gesture_name("tap", b), b, "tap", 1, t, held)]
        out = self._flush(t) if self._chain_count and self._chain_button != b else []
        self._chain_button, self._chain_open = b, False
        self._chain_count += 1
        self._chain_holds.append(held)
        # A tap that is reported late (a key event from the past) never moves the window back.
        self._chain_release = t if self._chain_count == 1 else max(self._chain_release, t)
        if self._chain_count >= counts[-1]:
            n = self._chain_count
            self._chain_button, self._chain_count, self._chain_holds = None, 0, []
            out.append(Gesture(gesture_name("tap", b, n), b, "tap", n, self._chain_release, held))
        return out

    def _flush(self, t: int) -> List[Gesture]:
        """End the pending chain and report it as of time t."""
        b, n, holds = self._chain_button, self._chain_count, self._chain_holds
        self._chain_button, self._chain_count, self._chain_open, self._chain_holds = None, 0, False, []
        if not n or b is None:
            return []
        if n in self.combos.get(b, ()):
            return [Gesture(gesture_name("tap", b, n), b, "tap", n, t, holds[-1])]
        return [Gesture(gesture_name("tap", b), b, "tap", 1, t, held) for held in holds]

    def _advance(self, t: int) -> List[Gesture]:
        """Everything the clock alone decides up to time t, oldest first."""
        self._forget_lost(t)
        out: List[Gesture] = self._dropped(t)
        while True:
            hold_at, hold_button = None, None
            for b in sorted(self._down):
                d, held = self._down[b]
                if not held and d + self.hold_ms <= t and (hold_at is None or d + self.hold_ms < hold_at):
                    hold_at, hold_button = d + self.hold_ms, b
            close_at = None
            if (self._chain_count and not self._chain_open and self._chain_release + self.tap_follow_ms < t
                    and not self._held_back(t)):
                close_at = self._chain_release + self.tap_follow_ms
            if close_at is not None and (hold_at is None or close_at <= hold_at):
                out += self._flush(close_at)
            elif hold_at is not None:
                out += self._flush(hold_at)           # a hold is never part of a chain
                self._down[hold_button][1] = True
                out.append(Gesture(gesture_name("hold", hold_button), hold_button, "hold", 1, hold_at, self.hold_ms))
            else:
                return out
