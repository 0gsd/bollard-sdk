# SPDX-License-Identifier: Apache-2.0
"""The device layer: hal and its registry, cues, gestures, the keymap resolver, identity, the dock placeholder.

The behaviour vectors under conformance/gestures/ and conformance/cues/ are the contract the
browser binding is held to as well; this file is the Python run of them.
"""
import io
import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import constants, schema  # noqa: E402
from bollardeck.device import cues, dock, hal, identity, keymap  # noqa: E402
from bollardeck.device.gestures import (DEFAULT_COMBOS, Gesture, GestureEngine, combos_from_keymap,  # noqa: E402
                                        gesture_name, parse_gesture)
from bollardeck.device.hal import base, sim  # noqa: E402

CONFORMANCE = ROOT / "conformance"


def vectors(rel):
    return json.loads((CONFORMANCE / rel).read_text(encoding="utf-8"))


def schema_vectors(name):
    index = json.loads((CONFORMANCE / "index.json").read_text(encoding="utf-8"))
    for v in index["vectors"]:
        if v["schema"] == name:
            yield v, json.loads((CONFORMANCE / v["file"]).read_text(encoding="utf-8"))


class Quiet(unittest.TestCase):
    """Fallbacks log warnings on purpose; keep the test output clean and let a test read them."""

    def setUp(self):
        self.logged = []
        handler = logging.Handler()
        handler.emit = lambda record: self.logged.append(record.getMessage())
        for name in ("bollardeck.hal", "bollardeck.identity"):
            logger = logging.getLogger(name)
            logger.addHandler(handler)
            logger.propagate = False
            self.addCleanup(logger.removeHandler, handler)
        self.addCleanup(hal.reset)


# ── constants ────────────────────────────────────────────────────────────────────────────

class Constants(unittest.TestCase):
    def test_one_button_vocabulary_numbers_with_labels_as_data(self):
        self.assertEqual(constants.BUTTON_NUMBERS, (1, 2, 3))
        self.assertEqual(tuple(b["button"] for b in constants.BUTTONS), constants.BUTTON_NUMBERS)
        self.assertEqual([b["label"] for b in constants.BUTTONS], ["inner", "middle", "outer"])
        self.assertEqual(base.BUTTONS, (1, 2, 3))                  # one tuple, of integers (finding 16)
        self.assertFalse(hasattr(base, "CUE_BUTTONS"))

    def test_gesture_names_are_every_tap_chain_and_hold(self):
        want = ["tap%d" % b for b in (1, 2, 3)]
        for n in range(2, constants.TAP_CHAIN_MAX + 1):
            want += ["tap%dx%d" % (b, n) for b in (1, 2, 3)]
        want += ["hold%d" % b for b in (1, 2, 3)]
        self.assertEqual(list(constants.GESTURES), want)
        for name in constants.GESTURES:
            kind, button, count = parse_gesture(name)
            self.assertEqual(gesture_name(kind, button, count), name)
        for bad in ("tap4", "tap1x4", "tap1x1", "hold1x2", "hold_outer", "", None, 3):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_gesture(bad)

    def test_the_keymap_constant_fits_its_schema_and_the_schema_names_every_gesture(self):
        self.assertEqual(schema.validate("keymap", json.loads(json.dumps(constants.KEYMAP))), [])
        self.assertEqual(keymap.problems(json.loads(json.dumps(constants.KEYMAP))), [])
        body = schema.load("keymap")
        for section in ("prompt", "idle", "always"):
            self.assertEqual(list(body["properties"][section]["properties"]), list(constants.GESTURES), section)
        kinds = {k for by_kind in constants.KEYMAP["prompt"].values() for k in by_kind}
        self.assertEqual(kinds, set(constants.PROMPT_KINDS))
        self.assertEqual(json.loads(keymap.dumps()), json.loads(json.dumps(constants.KEYMAP)))

    def test_the_default_combos_are_the_chains_the_keymap_names(self):
        self.assertEqual(DEFAULT_COMBOS, {1: (3,), 3: (3,)})
        self.assertEqual(combos_from_keymap({"idle": {"tap2x2": "x", "tap2x3": "y", "tap1": "z"}}), {2: (2, 3)})


# ── cues ─────────────────────────────────────────────────────────────────────────────────

def as_dicts(found):
    return [{"index": p.index, "kind": p.kind, "dropped": p.dropped} for p in found]


class Cues(unittest.TestCase):
    def test_normalise_vectors(self):
        for v in vectors("cues/normalise.json")["normalise"]:
            with self.subTest(v["name"]):
                seen = []
                out = cues.normalise(v["input"], on_problem=seen.append)
                self.assertEqual(out, v["output"])
                self.assertEqual(as_dicts(seen), v["repairs"])
                self.assertEqual(as_dicts(cues.repairs(v["input"])), v["repairs"])
                self.assertEqual(cues.problems(out), [], "normalise's output is always a valid cue list")
                self.assertEqual(cues.cue_line(v["input"]), v["line"])
                self.assertEqual(cues.to_wire(v["input"]), v["wire"])
                self.assertEqual(cues.normalise(out), out, "normalising twice changes nothing")
                self.assertEqual(cues.from_wire(v["wire"], strict=True), out, "the wire form carries the same list")
                if v["repairs"]:
                    with self.assertRaises(cues.CueError) as caught:
                        cues.normalise(v["input"], strict=True)
                    self.assertEqual(as_dicts(caught.exception.problems), v["repairs"])
                else:
                    self.assertEqual(cues.normalise(v["input"], strict=True), v["output"])

    def test_one_rule_for_what_a_valid_list_is(self):
        # The same file is run by tests/js/cues.test.js: a valid list fits the schema and names no
        # button twice; at() and compile() refuse anything else; normalise repairs it.
        seen_twice = 0
        for v in vectors("cues/normalise.json")["normalise"]:
            with self.subTest(v["name"]):
                found = cues.problems(v["input"])
                self.assertEqual(found == [], v["valid"])
                self.assertEqual(cues.is_valid(v["input"]), v["valid"])
                if "one_per_button" in v:
                    seen_twice += 1
                    self.assertEqual(schema.validate("cue", v["input"]), [], "the schema alone cannot see it")
                    self.assertEqual([(p.pointer, p.keyword) for p in found], [(at, "one-per-button") for at in v["one_per_button"]])
                    self.assertEqual({r["kind"] for r in v["repairs"]}, {"duplicate"})
                if v["valid"]:
                    self.assertEqual(v["repairs"], [])
                    self.assertEqual([c for c in cues.compile(v["input"]).cues], v["output"])
                    self.assertEqual(len(cues.at(v["input"], 0)), 3)
                else:
                    with self.assertRaises(cues.CueError) as caught:
                        cues.at(v["input"], 0)
                    self.assertEqual(caught.exception.problems, found)
                    self.assertEqual(len(cues.at(cues.normalise(v["input"]), 0)), 3)
        self.assertGreaterEqual(seen_twice, 3)
        self.assertIn("one-per-button", schema.load("cue")["description"])

    def test_from_wire_vectors(self):
        for v in vectors("cues/normalise.json")["from_wire"]:
            with self.subTest(v["name"]):
                seen = []
                self.assertEqual(cues.from_wire(v["wire"], on_problem=seen.append), v["output"])
                self.assertEqual(as_dicts(seen), v["repairs"])

    def test_normalise_never_raises_and_always_fits_the_schema(self):
        junk = [None, 7, "x", {}, [[]], [{"button": float("nan"), "state": "on"}], [{"button": 2.0, "state": "on"}],
                [{"button": 1e99, "state": "on"}], [{"button": [1], "state": "on"}], ({"button": 3, "state": "chase"},),
                [{"button": 1, "state": ["on"]}], [{"button": 1, "state": "on", "role": {"a": 1}}]]
        for value in junk:
            out = cues.normalise(value)
            self.assertEqual(schema.validate("cue", out), [], repr(value))
        self.assertEqual(cues.normalise([{"button": 2.0, "state": "on"}]), [{"button": 2, "state": "on", "role": None}])
        self.assertIs(type(cues.normalise([{"button": 2.0, "state": "on"}])[0]["button"]), int)

    def test_every_schema_vector_agrees_with_the_normaliser(self):
        # A list the cue schema accepts comes through strict normalising unchanged but for its
        # order. A list it refuses is either reported by repairs(), or is one of the two quiet
        # tidyings: a missing role, a member the cue model does not have.
        for v, doc in schema_vectors("cue"):
            with self.subTest(v["file"]):
                found = cues.repairs(doc)
                self.assertEqual(cues.is_valid(doc), v["valid"], "no schema vector names a button twice")
                if v["valid"]:
                    self.assertEqual(found, [])
                    self.assertEqual(cues.normalise(doc, strict=True), sorted(doc, key=lambda c: c["button"]))
                elif not found:
                    out = cues.normalise(doc, strict=True)
                    self.assertNotEqual(out, doc)
                    self.assertTrue(cues.is_valid(out))
                    self.assertTrue(all(set(c) != {"button", "state", "role"} for c in doc), "a quiet repair")

    def test_render_vectors(self):
        # conformance/cue-render/ is what every surface shows; the browser binding runs the same file.
        doc = vectors("cue-render/vectors.json")
        self.assertEqual(doc["constants"], {name: getattr(constants, name) for name in
                                            ("PULSE_PERIOD_MS", "CHASE_PERIOD_MS", "PULSE_FLOOR", "CHASE_TAIL", "CHASE_STEPS")})
        self.assertGreaterEqual(len(doc["vectors"]), 100)
        for v in doc["vectors"]:
            got = cues.at(v["cues"], v["t_ms"], calm=bool(v.get("calm", False)))
            self.assertEqual(json.dumps(got), json.dumps(v["buttons"]), v["name"])

    def test_the_cue_vectors_are_pinned_to_this_renderer(self):
        tool = ROOT / "tools" / "pin_vectors.py"
        out = subprocess.run([sys.executable, "-B", str(tool), "--check"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_rendering_rules(self):
        self.assertEqual(cues.pulse_level(0), 1)
        self.assertAlmostEqual(cues.pulse_level(constants.PULSE_PERIOD_MS / 2), constants.PULSE_FLOOR, places=12)
        self.assertEqual(cues.pulse_level(100.9), cues.pulse_level(100), "time is counted in whole milliseconds")
        self.assertEqual(cues.pulse_level(-0.5), cues.pulse_level(0), "towards zero")
        self.assertAlmostEqual(cues.pulse_level(-100), cues.pulse_level(constants.PULSE_PERIOD_MS - 100), places=12)
        self.assertAlmostEqual(cues.pulse_level(1000, 2000), constants.PULSE_FLOOR, places=12)
        self.assertEqual([cues.chase_head(t) for t in (0, 333, 334, 666, 667, 999, 1000, -1)], [0, 0, 1, 1, 2, 2, 0, 2])
        self.assertEqual(cues.chase_head(1500, 3000), 1)
        self.assertEqual([cues.to_pixel(x) for x in (0, 1, 0.5, 2.5 / 255, 3.5 / 255)], [0, 255, 128, 2, 4])
        calm = cues.at([cues.cue(1, "pulse", "a"), cues.cue(2, "chase", "warn"), cues.cue(3, "off")], 130, calm=True)
        self.assertEqual([(e["state"], e["level"], e["arc"], e["head"], e["pixel"]) for e in calm],
                         [("pulse", 1, [1, 1, 1], None, 255), ("chase", 1, [1, 1, 1], None, 255), ("off", 0, [0, 0, 0], None, 0)])
        show = cues.compile([cues.cue(3, "chase"), cues.cue(1)])
        self.assertEqual([c["button"] for c in show.cues], [1, 3])
        self.assertEqual([(e["driven"], e["head"]) for e in show.at(400)], [(True, None), (False, None), (True, 1)])
        self.assertEqual(show.at(400)[2]["arc"], [constants.CHASE_TAIL, 1, constants.CHASE_TAIL])
        for bad in ("soon", None, float("nan"), float("inf"), True):
            with self.assertRaises(TypeError, msg=repr(bad)):
                cues.at([], bad)
        with self.assertRaises(ValueError):
            cues.pulse_level(0, 0)

    def test_cue_builder_and_lines(self):
        self.assertEqual(cues.cue(2), {"button": 2, "state": "on", "role": None})
        self.assertEqual(cues.cue(3, "pulse", "go"), {"button": 3, "state": "pulse", "role": "go"})
        for args in ((4,), ("1",), (1, "blink"), (1, "on", "purple"), (1, "off", "a"), (True,)):
            with self.assertRaises(cues.CueError, msg=repr(args)):
                cues.cue(*args)
        line = "1:on:a 2:off:- 3:pulse:go"
        self.assertEqual(cues.cue_line(cues.parse_cue_line(line)), line)
        self.assertEqual(len(cues.parse_cue_line(line)), 3)
        for bad in ("1:on", "4:on:a", "1:blink:-", "one:on:-"):
            with self.assertRaises(cues.CueError, msg=bad):
                cues.parse_cue_line(bad)
        self.assertEqual([cues.wire_for_button(b) for b in (1, 2, 3)], ["inner", "middle", "outer"])
        self.assertEqual([cues.button_for_wire(w) for w in ("inner", "middle", "outer")], [1, 2, 3])
        for bad in (0, 4, "1", True):
            with self.assertRaises(ValueError):
                cues.wire_for_button(bad)
        with self.assertRaises(ValueError):
            cues.button_for_wire("centre")

    def test_line_sequence_vector(self):
        seq = vectors("cues/normalise.json")["lines"]
        self.assertEqual(sim.render_cue_lines(seq["sets"]).decode("ascii").splitlines(), seq["lines"])
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "cues.txt"
            lights = sim.FileCues(path)
            for cue_list in seq["sets"]:
                lights.set(cue_list)
            self.assertEqual(path.read_text().splitlines(), seq["lines"])


# ── gestures and the keymap ──────────────────────────────────────────────────────────────

class Gestures(unittest.TestCase):
    def test_timeline_vectors(self):
        for v in vectors("gestures/timelines.json")["vectors"]:
            with self.subTest(v["name"]):
                engine = GestureEngine(**v["config"])
                for i, event in enumerate(v["events"]):
                    if event.get("raises"):
                        with self.assertRaises(ValueError):
                            engine.feed(event)
                        self.assertEqual(i, len(v["events"]) - 1, "a vector ends where it raises")
                        break
                    want = event.get("emits", [])
                    got = engine.feed(event)
                    self.assertEqual([g.to_dict() for g in got], [{"gesture": w["gesture"], "t_ms": w["t_ms"]} for w in want],
                                     "event %d: %s" % (i, event))
                    for g, w in zip(got, want):
                        self.assertIsInstance(g.hold_ms, int, "event %d: every gesture says how long" % i)
                        if "hold_ms" in w:
                            self.assertEqual(g.hold_ms, w["hold_ms"], "event %d: %s" % (i, event))

    def test_every_vector_event_is_well_formed(self):
        for v in vectors("gestures/timelines.json")["vectors"]:
            self.assertEqual(set(v), {"name", "about", "config", "events"}, v["name"])
            self.assertEqual(set(v["config"]), {"hold_ms", "tap_follow_ms", "combos"}, v["name"])
            for event in v["events"]:
                self.assertIn(event["edge"], ("down", "up", "cancel", "tick", "key", "combos"), v["name"])
                self.assertEqual("button" in event, event["edge"] in ("down", "up", "cancel"), v["name"])
                self.assertEqual("key" in event, event["edge"] == "key", v["name"])
                self.assertEqual("combos" in event, event["edge"] == "combos", v["name"])
                self.assertLessEqual(set(event), {"t_ms", "edge", "button", "key", "combos", "emits", "raises"}, v["name"])
                for g in event.get("emits", []):
                    self.assertIn(g["gesture"], constants.GESTURES, v["name"])
                    self.assertLessEqual(set(g), {"gesture", "t_ms", "hold_ms"}, v["name"])
        names = [v["name"] for v in vectors("gestures/timelines.json")["vectors"]]
        for needed in ("key-late-release-stays-a-tap", "key-lost-release", "key-real-hold",
                       "key-poll-during-a-held-press-keeps-the-triple-tap", "combos-set-while-a-press-is-in-flight"):
            self.assertIn(needed, names)

    def test_the_engine_reports_the_same_whatever_the_tick_rate(self):
        # Extra ticks never change which gestures come out, or their times: only which call reports them.
        for v in vectors("gestures/timelines.json")["vectors"]:
            # A key event is judged in the past, so what a tick has already said cannot be taken
            # back: those timelines do depend on when the ticks fall (rule 9), and are left out.
            if any(e.get("raises") or e["edge"] in ("key", "combos") for e in v["events"]):
                continue
            with self.subTest(v["name"]):
                plain = GestureEngine(**v["config"])
                want = [g.to_dict() for e in v["events"] for g in plain.feed(e)]
                last = v["events"][-1]["t_ms"]
                want += [g.to_dict() for g in plain.tick(last + 5000)]
                busy, got, now = GestureEngine(**v["config"]), [], 0
                for event in v["events"]:
                    while now + 7 < event["t_ms"]:
                        now += 7
                        got += [g.to_dict() for g in busy.tick(now)]
                    got += [g.to_dict() for g in busy.feed(event)]
                    now = event["t_ms"]
                got += [g.to_dict() for g in busy.tick(last + 5000)]
                self.assertEqual(got, want)
                self.assertEqual(busy.pending, 0)
                self.assertIsNone(busy.next_deadline_ms())

    def test_next_deadline_says_when_a_tick_will_speak(self):
        engine = GestureEngine()
        self.assertIsNone(engine.next_deadline_ms())
        engine.down(1, 100)
        self.assertEqual(engine.next_deadline_ms(), 900)              # the hold
        engine.up(1, 200)
        self.assertEqual((engine.pending, engine.next_deadline_ms()), (1, 701))   # the window, one past its end
        self.assertEqual(engine.tick(700), [])
        self.assertEqual(engine.tick(701), [Gesture("tap1", 1, "tap", 1, 700, 100)])
        self.assertIsNone(engine.next_deadline_ms())

    def test_key_events_from_the_hal(self):
        engine = GestureEngine()
        events = list(sim.StdinKeys(io.StringIO("3 90 2000\n3 80 2300\nnonsense\n3 85 2600\n2 1100 5000\n")).events())
        names = [g.name for ev in events for g in engine.key(ev)]
        self.assertEqual(names, ["tap3x3", "hold2"])
        with self.assertRaises(ValueError):
            GestureEngine().key({"t": "key", "i": 1, "down": 0, "hold_ms": 50, "t_ms": None})
        self.assertEqual([g.name for g in GestureEngine().key({"i": 2, "hold_ms": 50, "t_ms": None}, now_ms=400)], ["tap2"])

    def test_a_late_key_event_is_judged_by_its_own_times(self):
        engine = GestureEngine()
        engine.tick(1000)                                             # the clock ran on while a button was down
        self.assertEqual(engine.key({"i": 1, "hold_ms": 900, "t_ms": 1500}), [Gesture("hold1", 1, "hold", 1, 1400, 900)])
        self.assertEqual([g.name for g in engine.key({"i": 2, "hold_ms": 50, "t_ms": 1450})], ["tap2"])

    def test_a_key_source_that_reports_the_press_beginning_keeps_chains_whole(self):
        # With only complete presses, a tick during the second press would end the chain.
        engine, out = GestureEngine(), []
        out += engine.key({"i": 1, "down": 1, "t_ms": 0}) + engine.key({"i": 1, "down": 0, "hold_ms": 100, "t_ms": 100})
        out += engine.key({"i": 1, "down": 1, "t_ms": 550}) + engine.tick(620)
        out += engine.key({"i": 1, "down": 0, "hold_ms": 100, "t_ms": 650})
        out += engine.key({"i": 1, "down": 1, "t_ms": 700}) + engine.key({"i": 1, "down": 0, "hold_ms": 50, "t_ms": 750})
        self.assertEqual([g.name for g in out], ["tap1x3"])
        late = GestureEngine()
        late.key({"i": 1, "hold_ms": 100, "t_ms": 100})
        self.assertEqual([g.name for g in late.tick(620)], ["tap1"])   # the documented limit of complete presses

    def test_a_press_beginning_is_only_a_hint(self):
        # Fed the wall clock, a press beginning used to turn a late or lost release into a hold.
        engine = GestureEngine()
        self.assertEqual(engine.key({"i": 2, "down": 1, "t_ms": None}, now_ms=1000), [])
        self.assertEqual((engine.is_down(2), engine.waiting(2), engine.waiting(), engine.waiting(1)), (False, True, True, False))
        self.assertEqual(engine.tick(1900) + engine.tick(3000), [])                      # no hold from the clock alone
        self.assertEqual(engine.key({"i": 2, "down": 0, "hold_ms": 120, "t_ms": None}, now_ms=3100),
                         [Gesture("tap2", 2, "tap", 1, 1120, 120)])
        self.assertFalse(engine.waiting())
        lost = GestureEngine()
        lost.key({"i": 1, "down": 1, "t_ms": 0})
        self.assertEqual(lost.tick(constants.PRESS_LOST_MS), [])
        self.assertTrue(lost.waiting(1))
        self.assertEqual(lost.tick(constants.PRESS_LOST_MS + 1), [])
        self.assertFalse(lost.waiting(1))                                                # given up on
        self.assertIsNone(lost.next_deadline_ms())
        # A press that down() began is still ended by its key event, as an edge.
        mixed = GestureEngine()
        mixed.down(2, 0)
        self.assertEqual(mixed.key({"i": 2, "down": 0, "hold_ms": 5, "t_ms": 60}), [Gesture("tap2", 2, "tap", 1, 60, 60)])

    def test_the_deadline_knows_about_a_held_back_chain(self):
        engine = GestureEngine()
        engine.key({"i": 1, "down": 0, "hold_ms": 100, "t_ms": 100})
        self.assertEqual(engine.next_deadline_ms(), 601)
        engine.key({"i": 1, "down": 1, "t_ms": 300})
        self.assertEqual(engine.next_deadline_ms(), 1100)                                # began + hold_ms
        self.assertEqual(engine.tick(1099), [])
        self.assertEqual(engine.tick(1100), [Gesture("tap1", 1, "tap", 1, 600, 100)])

    def test_a_hint_given_up_on_before_hold_ms_frees_the_deadline(self):
        engine = GestureEngine(press_lost_ms=200)
        engine.key({"i": 1, "down": 0, "hold_ms": 100, "t_ms": 100})
        engine.key({"i": 1, "down": 1, "t_ms": 300})
        self.assertEqual(engine.next_deadline_ms(), 601)                 # the window's own end: the hint is gone at 501
        self.assertEqual(engine.tick(600), [])
        self.assertEqual(engine.tick(601), [Gesture("tap1", 1, "tap", 1, 600, 100)])
        short = GestureEngine(press_lost_ms=200, tap_follow_ms=50)
        short.key({"i": 1, "down": 0, "hold_ms": 100, "t_ms": 100})
        short.key({"i": 1, "down": 1, "t_ms": 140})
        self.assertEqual(short.next_deadline_ms(), 341)                  # given up on at began + press_lost_ms + 1
        self.assertEqual((short.tick(340), [g.name for g in short.tick(341)]), ([], ["tap1"]))

    def test_an_edge_or_a_cancel_ends_a_hint(self):
        engine = GestureEngine()
        engine.key({"i": 2, "down": 1, "t_ms": 0})
        engine.down(2, 10)
        self.assertTrue(engine.waiting(2))
        engine.up(2, 60)
        self.assertFalse(engine.waiting(2))
        engine.key({"i": 3, "down": 1, "t_ms": 100})
        engine.cancel(3, 120)
        self.assertFalse(engine.waiting())
        engine.key({"i": 3, "down": 1, "t_ms": 200})
        engine.up(3, 220)                                                # not down as an edge: nothing to end
        self.assertTrue(engine.waiting(3))

    def test_combos_can_change_while_the_engine_runs(self):
        engine = GestureEngine(combos={})
        engine.down(1, 0)
        self.assertIs(engine.set_combos({1: [3]}), engine)
        self.assertEqual((engine.is_down(1), engine.up(1, 50), engine.pending), (True, [], 1))
        engine.set_combos(None)
        self.assertEqual(engine.combos, {1: (3,), 3: (3,)})
        with self.assertRaises(ValueError):
            engine.set_combos({4: [3]})
        self.assertEqual(engine.pending, 1)                                              # a refused change changes nothing
        engine.set_combos({})
        self.assertEqual(engine.next_deadline_ms(), 50)
        self.assertEqual(engine.tick(60), [Gesture("tap1", 1, "tap", 1, 60, 50)])

    def test_bad_configuration_is_refused(self):
        for combos in ({4: [3]}, {1: [1]}, {1: [4]}, {1: [True]}, {"x": [2]}):
            with self.assertRaises(ValueError, msg=repr(combos)):
                GestureEngine(combos=combos)
        with self.assertRaises(ValueError):
            GestureEngine(hold_ms=0)
        self.assertEqual(GestureEngine(combos={"2": [3, 2]}).combos, {2: (2, 3)})
        self.assertEqual((GestureEngine().hold_ms, GestureEngine().tap_follow_ms),
                         (constants.HOLD_MS, constants.TAP_FOLLOW_MS))


class Keymap(unittest.TestCase):
    def test_is_gesture_never_raises(self):
        for name in constants.GESTURES:
            self.assertTrue(keymap.is_gesture(name), name)
        for name in ("screen", "tap4", "tap1x4", "", None, 1, ["tap1"], b"tap1"):
            self.assertFalse(keymap.is_gesture(name), repr(name))

    def test_resolve_vectors(self):
        doc = vectors("gestures/resolve.json")
        for group in doc["groups"]:
            for case in group["cases"]:
                with self.subTest(group=group["name"], gesture=case["gesture"], prompt=case["prompt"],
                                  context=case.get("context")):
                    got = keymap.resolve(case["gesture"], case["prompt"], group["keymap"], context=case.get("context"))
                    self.assertEqual(got.to_dict(), case["expect"])
                    self.assertEqual(got.handled, case["expect"]["source"] is not None)
                    self.assertEqual(got.action, got.value if got.kind == "do" else None)
                    self.assertEqual(got.choice, got.value if got.kind == "choice" else None)
            self.assertEqual(schema.validate("keymap", group["keymap"]), [], group["name"])
        for bad in doc["errors"]:
            with self.assertRaises(ValueError, msg=bad["gesture"]):
                keymap.resolve(bad["gesture"])
        for bad in doc["bad_keymaps"]:
            with self.assertRaises(ValueError, msg=bad["about"]):
                keymap.resolve(bad["gesture"], bad["prompt"], bad["keymap"])
            self.assertTrue(keymap.problems(bad["keymap"]), bad["about"])
        for bad in doc["bad_contexts"]:
            with self.assertRaises(ValueError, msg=bad["about"]):
                keymap.resolve(bad["gesture"], context=bad["context"])

    def test_the_pocket_context_adds_and_changes_nothing_else(self):
        # SDK 0.2.0: a context is optional; with none, every answer is what it was before.
        self.assertEqual(keymap.CONTEXTS, ("pocket",))
        for g in constants.GESTURES:
            for p in (None,) + tuple(constants.PROMPT_KINDS):
                without = dict(constants.KEYMAP)
                without.pop("pocket")
                self.assertEqual(keymap.resolve(g, p).to_dict(), keymap.resolve(g, p, without).to_dict(), (g, p))
        self.assertEqual(keymap.resolve("tap2", context="pocket").action, "whats_on")
        self.assertEqual(keymap.resolve("tap2").source, None)
        self.assertEqual(keymap.resolve("hold3", context="pocket").source, "always")
        self.assertEqual(keymap.resolve("tap1", "abc", context="pocket").choice, "A")
        self.assertEqual(keymap.resolve("tap1x3", context="pocket").to_dict(),
                         {"source": "idle", "kind": "do", "value": "leave_us_alone"})
        verbs = set(constants.KEYMAP["pocket"].values())
        self.assertLessEqual(verbs, set(constants.POCKET_VERBS))
        self.assertEqual(keymap.problems(constants.KEYMAP), [])

    def test_combos_are_unchanged_without_a_context(self):
        from bollardeck.device import gestures
        self.assertEqual(gestures.DEFAULT_COMBOS, {1: (3,), 3: (3,)})
        self.assertEqual(gestures.combos_from_keymap(constants.KEYMAP, ("pocket",)), {1: (2, 3), 2: (2,), 3: (2, 3)})

    def test_a_pocket_entry_under_always_is_a_problem(self):
        doc = {"v": 2, "prompt": {}, "idle": {}, "always": {"hold3": "power"}, "pocket": {"hold3": "stop"}}
        self.assertEqual(len(keymap.problems(doc)), 1)
        self.assertIn("/pocket/hold3", keymap.problems(doc)[0])

    def test_the_platform_group_is_the_constant_and_covers_everything(self):
        group = vectors("gestures/resolve.json")["groups"][0]
        self.assertEqual(group["keymap"], json.loads(json.dumps(constants.KEYMAP)))
        seen = {(c["gesture"], c["prompt"]) for c in group["cases"]}
        want = {(g, p) for g in constants.GESTURES for p in (None,) + tuple(constants.PROMPT_KINDS)}
        self.assertLessEqual(want, seen)
        for case in group["cases"]:
            self.assertEqual(keymap.resolve(case["gesture"], case["prompt"]).to_dict(), case["expect"])

    def test_raw_and_problems(self):
        self.assertTrue(keymap.wants_raw("game"))
        self.assertFalse(keymap.wants_raw("abc"))
        made_up = vectors("gestures/resolve.json")["groups"][1]["keymap"]
        self.assertEqual(schema.validate("keymap", made_up), [])
        shadowed = keymap.problems(made_up)
        self.assertEqual(len(shadowed), 2)                         # hold3 in prompt and in idle, under always
        self.assertTrue(all("never applies" in p for p in shadowed))
        self.assertTrue(keymap.problems({"v": 2}))
        self.assertEqual((keymap.VERSION, constants.KEYMAP["v"]), (2, 2))

    def test_a_meaning_says_what_it_is(self):
        # Version 2: no reader needs a list of which words are verbs.
        kinds = set()
        for by_kind in constants.KEYMAP["prompt"].values():
            for meaning in by_kind.values():
                if meaning is not None:
                    self.assertEqual(len(meaning), 1)
                    kinds |= set(meaning)
        self.assertEqual(kinds, {"choice", "do"})
        self.assertEqual(tuple(keymap.resolve("tap2", "spectrum")), ("prompt", "choice", 0))
        self.assertIsNone(keymap.resolve("tap2", "spectrum").action)
        self.assertEqual(tuple(keymap.resolve("hold2", "game")), ("prompt", "do", "forfeit"))
        self.assertEqual(tuple(keymap.resolve("hold1", "game")), ("prompt", None, None))
        self.assertEqual(keymap.resolve("hold3").action, "power")


# ── the hal ──────────────────────────────────────────────────────────────────────────────

def fake_board(name="fakeboard", maker="FAKE", **extra):
    """A board module made in memory: its own cues and power, everything else left to the sim."""
    module = types.ModuleType("hal_" + name)
    module.NAME, module.MAKER_CODE = name, maker
    module.lit = []

    class Cues:
        def set(self, cue_list):
            module.lit.append(base.cue_line(cue_list))

        def clear(self):
            self.set([])

    class Power:
        def __init__(self, sysfs_dir=None):
            raise OSError("no fuel gauge on this bench")

    module.Cues, module.Power = Cues, Power
    for key, value in extra.items():
        setattr(module, key, value)
    return module


class Hal(Quiet):
    def tearDown(self):
        for name in hal.registered():
            if name != "sim":
                hal.unregister(name)
        sys.modules.pop("bollardeck_test_fake_hal", None)

    def test_interface_version(self):
        self.assertEqual(hal.HAL_API, 1)
        self.assertEqual((sim.NAME, sim.MAKER_CODE, sim.HAL_API), ("sim", "SIM", 1))

    def test_the_sim_is_the_default_board(self):
        with tempfile.TemporaryDirectory() as folder:
            nothing = pathlib.Path(folder) / "model"
            self.assertEqual(hal.detect(env={}, model_path=nothing), "sim")
            board = hal.board("sim")
            self.assertEqual((board.name, board.maker_code, board.describe()), ("sim", "SIM", "sim"))
            self.assertEqual(board.power().read(), base.PowerState(True, 98.0, 4150))
            self.assertIsNone(board.matrix_transport())
            board.matrix().show(b"\x00", 13, 8)
            board.audio().tone(440.0, 10)
            board.audio().play_midi(nothing, "sf").wait()
            storage = sim.EnvStorage({"POPBOLLARD_DATA_DIR": "/d", "POPBOLLARD_CORPUS_DIRS": os.pathsep.join(["/a", "/b"])})
            self.assertEqual((storage.data_dir(), storage.corpus_dirs()),
                             (pathlib.Path("/d"), [pathlib.Path("/a"), pathlib.Path("/b")]))
            self.assertEqual((sim.EnvStorage({}).data_dir(), sim.EnvStorage({}).corpus_dirs()),
                             (pathlib.Path("/popbollard/data"), []))
            frames = pathlib.Path(folder) / "frames.jsonl"
            sim.FileDisplay(frames).push({"v": 1, "b": 2})
            self.assertEqual(json.loads(frames.read_text()), {"b": 2, "v": 1})
            self.assertEqual(sim.render_matrix([(0, b"\x01\x02"), (40, b"\xff")]), b"0 0102\n40 ff\n")
            self.assertEqual(base.frames_hex([(0, b"\x01\x02")]), ["0102"])

    def test_a_uno_q_by_its_board_model_or_its_router_socket(self):
        """A Uno Q's device tree says "Arduino SA,Imola"; inside a container there is no device-tree model at all,
        and the Arduino router's Unix socket is the board's evidence there. A model naming another board still
        decides, and $BOLLAWAX_HAL still wins."""
        import socket
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory(prefix="r", dir="/tmp") as short:
            model = pathlib.Path(folder) / "model"
            model.write_bytes(b"Arduino SA,Imola\x00")
            self.assertEqual(hal.detect(env={}, model_path=model), "unoq")
            nothing = pathlib.Path(folder) / "none"
            path = pathlib.Path(short) / "router.sock"
            router = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            router.bind(str(path))
            try:
                with_socket = {"ARDUINO_ROUTER_SOCKET": str(path)}
                self.assertEqual(hal.detect(env=with_socket, model_path=nothing), "unoq")
                model.write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")
                self.assertEqual(hal.detect(env=with_socket, model_path=model), "pi5")
                self.assertEqual(hal.detect(env=dict(with_socket, BOLLAWAX_HAL="sim"), model_path=nothing), "sim")
            finally:
                router.close()
            path.unlink()                                              # no socket there any more
            plain = pathlib.Path(short) / "plain"
            plain.write_text("")
            for not_a_socket in (str(path), str(plain), "tcp://127.0.0.1:9"):
                self.assertEqual(hal.detect(env={"ARDUINO_ROUTER_SOCKET": not_a_socket}, model_path=nothing), "sim",
                                 not_a_socket)

    def test_detection_order(self):
        with tempfile.TemporaryDirectory() as folder:
            model = pathlib.Path(folder) / "model"
            model.write_bytes(b"Arduino UNO Q\x00")
            self.assertEqual(hal.detect(env={}, model_path=model), "unoq")
            self.assertEqual(hal.detect(env={"BOLLAWAX_HAL": "sim"}, model_path=model), "sim")
            self.assertEqual(hal.detect(env={"BOLLAWAX_HAL": "PI5"}, model_path=model), "pi5")
            self.assertEqual(hal.detect(env={"BOLLAWAX_HAL": "toaster"}, model_path=model), "unoq")
            self.assertTrue(any("toaster" in line for line in self.logged))
            model.write_bytes(b"Raspberry Pi Compute Module 5 Rev 1.0\x00")
            self.assertEqual(hal.detect(env={}, model_path=model), "pi5")
            model.write_bytes(b"Some Other Board")
            self.assertEqual(hal.detect(env={}, model_path=model), "sim")

    def test_a_known_board_that_is_not_registered_runs_on_the_sim_and_says_so(self):
        board = hal.board("unoq")
        self.assertIs(board.module, sim)
        self.assertEqual(board.maker_code, "UNOQ")                 # the family's code, not the sim's
        self.assertEqual(board.describe(), "unoq (module->sim)")
        self.assertTrue(any("unoq is not registered" in line for line in self.logged))
        with self.assertRaises(ValueError):
            hal.board("toaster")

    def test_registering_a_fake_board_from_outside(self):
        fake = fake_board()
        family = hal.register("fakeboard", fake, matches=lambda model: model.startswith("Fake Board"))
        self.assertEqual((family.name, family.maker_code), ("fakeboard", "FAKE"))
        self.assertEqual(hal.registered(), ("sim", "fakeboard"))
        self.assertEqual(hal.known(), ("unoq", "pi5", "sim", "fakeboard"))
        with tempfile.TemporaryDirectory() as folder:
            model = pathlib.Path(folder) / "model"
            model.write_bytes(b"Fake Board rev 2\x00")
            self.assertEqual(hal.detect(env={}, model_path=model), "fakeboard")
            self.assertEqual(hal.detect(env={"BOLLAWAX_HAL": "fakeboard"}, model_path=pathlib.Path(folder) / "none"),
                             "fakeboard")
        board = hal.board("fakeboard")
        self.assertIs(board.module, fake)
        self.assertEqual(board.maker_code, "FAKE")
        board.cues().set([{"button": 1, "state": "on", "role": "a"}])
        self.assertEqual(fake.lit, ["1:on:a 2:off:- 3:off:-"])     # the board's own cues
        self.assertEqual(board.power().read().ac_online, True)       # its Power raised: the sim's
        self.assertIsInstance(board.keys(io.StringIO("")), sim.StdinKeys)   # it has no Keys: the sim's
        self.assertEqual(board.describe(), "fakeboard (keys->sim, power->sim)")
        self.assertEqual(sum("power unavailable" in line for line in self.logged), 1)
        board.power()
        self.assertEqual(sum("power unavailable" in line for line in self.logged), 1, "logged once")

    def test_current_follows_the_registry(self):
        os.environ["BOLLAWAX_HAL"] = "fakeboard"
        self.addCleanup(os.environ.pop, "BOLLAWAX_HAL", None)
        hal.reset()
        first = hal.current()                                       # not registered yet: the model decides
        self.assertNotEqual(first.name, "fakeboard")
        hal.register("fakeboard", fake_board())                     # registering forgets the detected board
        self.assertEqual(hal.current().name, "fakeboard")
        self.assertIs(hal.current(), hal.current())
        self.assertEqual((hal.maker_code(), hal.describe()), ("FAKE", "fakeboard"))
        hal.unregister("fakeboard")
        self.assertNotEqual(hal.current().name, "fakeboard")

    def test_a_board_is_registered_lazily_by_name_or_by_loader(self):
        calls = []

        def loader():
            calls.append(1)
            return fake_board("lazyboard", "LAZY")

        hal.register("lazyboard", loader, maker_code="LAZY")
        self.assertEqual(calls, [], "registering must not load the board's code")
        self.assertEqual(hal.board("lazyboard").module.NAME, "lazyboard")
        self.assertEqual(calls, [1])

        sys.modules["bollardeck_test_fake_hal"] = fake_board("namedboard", "NAMED")
        hal.register("namedboard", "bollardeck_test_fake_hal", maker_code="NAMED")
        self.assertEqual(hal.board("namedboard").maker_code, "NAMED")

        hal.register("unoq", "a_module_that_is_not_installed")       # its maker code comes from the table
        board = hal.board("unoq")
        self.assertIs(board.module, sim)
        self.assertEqual((board.maker_code, board.describe()), ("UNOQ", "unoq (module->sim)"))
        self.assertTrue(any("unoq could not be loaded" in line for line in self.logged))

    def test_a_board_written_for_a_newer_interface_is_not_used(self):
        hal.register("newboard", fake_board("newboard", "NEWB", HAL_API=hal.HAL_API + 1))
        board = hal.board("newboard")
        self.assertIs(board.module, sim)
        self.assertEqual(board.maker_code, "NEWB")
        self.assertTrue(any("hal interface 2" in line for line in self.logged))
        hal.register("oldboard", fake_board("oldboard", "OLDB", HAL_API=1))
        self.assertEqual(hal.board("oldboard").module.NAME, "oldboard")

    def test_registration_rules(self):
        for bad in ("sim", "Fake", "x", "has space", "", None, 7, "a" * 17):
            with self.assertRaises(ValueError, msg=repr(bad)):
                hal.register(bad, fake_board())
        with self.assertRaises(ValueError):
            hal.register("nocode", lambda: fake_board())               # a loader needs a maker code given
        with self.assertRaises(ValueError):
            hal.register("badcode", fake_board(), maker_code="x")
        with self.assertRaises(ValueError):
            hal.register("noboard", None, maker_code="NONE")
        with self.assertRaises(ValueError):
            hal.unregister("sim")
        hal.register("twice", fake_board("twice", "TWICE"))
        with self.assertRaises(ValueError):
            hal.register("twice", fake_board("twice", "TWICE"))
        hal.register("twice", fake_board("twice", "AGAIN"), replace=True)
        self.assertEqual(hal.board("twice").maker_code, "AGAIN")
        hal.unregister("never_registered")                          # unknown names are ignored

    def test_a_broken_detection_rule_is_skipped(self):
        hal.register("brokenrule", fake_board("brokenrule", "BROKE"), matches=lambda model: 1 / 0)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(hal.detect(env={}, model_path=pathlib.Path(folder) / "none"), "sim")
        self.assertTrue(any("detection rule failed" in line for line in self.logged))

    def test_key_lines(self):
        self.assertEqual(base.parse_key_line("1 120 5000\n"),
                         {"t": "key", "i": 1, "down": 0, "hold_ms": 120, "t_ms": 5000})
        self.assertEqual(base.parse_key_line("3 900")["t_ms"], None)
        self.assertIs(type(base.parse_key_line("2 5")["i"]), int)
        for bad in ("", "1", "4 100", "01 100", "+1 100", "1 abc", "one 100", "1 100 x"):
            self.assertIsNone(base.parse_key_line(bad), bad)
        self.assertEqual(base.parse_key_line(base.key_line(2, 80, 900))["hold_ms"], 80)
        self.assertEqual(base.key_line(3, 10), "3 10")
        self.assertEqual(base.parse_key_line("2 down 4880\n"), {"t": "key", "i": 2, "down": 1, "t_ms": 4880})
        self.assertEqual(base.parse_key_line(" 3 down "), {"t": "key", "i": 3, "down": 1, "t_ms": None})
        self.assertEqual(base.key_line(2, down=True, t_ms=4880), "2 down 4880")
        self.assertEqual(base.key_line(2, down=True), "2 down")
        for bad in ("2 DOWN", "2 down x", "2 down 1 2", "4 down", "down 2", "2 up 10"):
            self.assertIsNone(base.parse_key_line(bad), bad)
        for bad in (dict(hold_ms=5, down=True), dict(release_ms=5, down=True), dict(), dict(hold_ms=5, t_ms=9)):
            with self.assertRaises(ValueError, msg=repr(bad)):
                base.key_line(1, **bad)
        events = list(sim.StdinKeys(io.StringIO("1 down 1000\n1 120 1120\n1 down\n")).events())
        self.assertEqual([(e["down"], e["t_ms"]) for e in events], [(1, 1000), (0, 1120), (1, None)])
        engine = GestureEngine(combos={})
        self.assertEqual([[g.name for g in engine.key(e)] for e in events[:2]], [[], ["tap1"]])
        with self.assertRaises(ValueError):
            base.key_line("1", 10)

    def test_a_bad_cue_is_left_out_and_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "cues.txt"
            lights = sim.FileCues(path)
            for _ in range(3):                                      # a tick loop sets the same list again and again
                lights.set([{"button": "1", "state": "on"}, {"button": 2, "state": "on", "role": "b"}])
            self.assertEqual(path.read_text(), "1:off:- 2:on:b 3:off:-\n")
            self.assertEqual(len(lights.repairs), 3)
            self.assertEqual(sum("button must be 1, 2 or 3" in line for line in self.logged), 1, "logged once")
            lights.clear()
            self.assertEqual(path.read_text().splitlines()[-1], "1:off:- 2:off:- 3:off:-")
        self.assertIsNone(sim.FileCues().set([{"button": 1, "state": "on"}]))   # no path: dropped quietly


# ── identity ─────────────────────────────────────────────────────────────────────────────

class Identity(Quiet):
    def test_parse_and_format(self):
        self.assertEqual(identity.parse("PB0007-UNOQ-0123456789"), identity.Serial(False, 7, "UNOQ", "0123456789"))
        self.assertEqual(identity.parse(" VPB0007-web-pb-k3x9qa "), identity.Serial(True, 7, "WEB", "pb-k3x9qa"))
        self.assertEqual(identity.parse_serial("PB0002-USB-PEER-774411"), (2, "PEER-774411"))
        for bad in ("", None, "PB007-UNOQ-1", "XB0007-UNOQ-1", "PB0007-UNOQ-", "PB0007--1", "PB0007-UNOQ-1\n2"):
            self.assertIsNone(identity.parse(bad), repr(bad))
        self.assertEqual(identity.maker_code("PB0007-acme-1"), "ACME")
        self.assertIsNone(identity.maker_code("nonsense"))
        self.assertEqual((identity.number_from_serial("VPB0042-WEB-x"), identity.song_id_prefix("VPB0042-WEB-x")), (42, "pb0042"))
        self.assertEqual(identity.song_id_prefix(None), "pb0000")
        self.assertEqual((identity.label_for(7), identity.label_for(0)), ("PBOLL #0007", "PBOLL #????"))
        self.assertEqual(identity.format_serial(7, "0123456789", "unoq"), "PB0007-UNOQ-0123456789")
        self.assertEqual(identity.format_serial(123456, "ab-c", "WEB", virtual=True), "VPB123456-WEB-ab-c")
        for number, hw, maker in ((-1, "A1", "UNOQ"), (1000000, "A1", "UNOQ"), (True, "A1", "UNOQ"), (1, "", "UNOQ"),
                                  (1, " A1", "UNOQ"), (1, "A1", "x"), (1, "A1", ""), (1, "A1", "TOOLONGX"), (1.5, "A1", "UNOQ")):
            with self.assertRaises(ValueError, msg=repr((number, hw, maker))):
                identity.format_serial(number, hw, maker)
        for number, hw, maker in ((0, "0", "PI5"), (9999, "0123456789", "UNOQ"), (10000, "Ab9", "ACME")):
            serial = identity.format_serial(number, hw, maker)
            self.assertEqual(identity.parse(serial), identity.Serial(False, number, maker, hw))

    def test_the_module_and_the_schema_use_the_same_patterns(self):
        defs = schema.load("device-identity")["$defs"]
        samples = ["PB0007-UNOQ-0123456789", "VPB0007-WEB-pb-k3x9qa", "PB0002-USB-PEER-774411", "PB0001-acme-1",
                   "PB0007-PI5-AB12", "PB007-UNOQ-1", "PB0007-UNOQ-", "pb0007-UNOQ-1", "PB1234567-UNOQ-1",
                   "PB0007-AB-1", "PB0007-ABCDEFG-1", "PB0007-1AB-1", "PB0007-UNOQ-" + "A" * 33, "PB0007-UNOQ-1\n"]
        for text in samples:
            with self.subTest(text):
                self.assertEqual(bool(identity.SERIAL_RE.match(text)), schema.is_valid("device-identity#/$defs/serial", text))
                self.assertEqual(bool(identity.DEVICE_SERIAL_RE.match(text)),
                                 schema.is_valid("device-identity#/$defs/device_serial", text))
        for code in ("UNOQ", "PI5", "AB", "ABCDEFG", "1AB", "unoq", "A-B", "ABC\n"):
            self.assertEqual(identity.is_maker_code(code), schema.is_valid("device-identity#/$defs/maker_code", code), code)
        self.assertIn("serial", defs)

    def test_validate_serial(self):
        self.assertEqual(identity.validate_serial("PB0007-UNOQ-0123456789"), [])
        self.assertTrue(identity.is_device_serial("PB0042-PI5-AB12CD"))
        cases = {"VPB0007-WEB-pb-k3x9qa": "virtual", "PB0007-ACME-1234ABCD": "reserved", "PB0007-SIM-1234": "reserved",
                 "PB0007-ZZZZ-1234": "not in the registry", "PB0007-unoq-1234": "maker code must be",
                 "PB0007-UNOQ-12-34": "maker code must be", "banana": "is not PB####", "": "is not PB####"}
        for serial, why in cases.items():
            found = identity.validate_serial(serial)
            self.assertEqual(len(found), 1, serial)
            self.assertIn(why, found[0], serial)
            self.assertFalse(identity.is_device_serial(serial))
        rows = [{"code": "ZZZZ", "name": "Made-up maker", "kind": "third-party", "registered": "2026-01-01",
                 "contact": None, "notes": ""}]
        self.assertEqual(identity.validate_serial("PB0007-ZZZZ-1234", rows), [])
        self.assertEqual(len(identity.validate_serial("PB0007-UNOQ-1234", rows)), 1)

    def test_the_packaged_registry(self):
        document = identity.registry()
        self.assertEqual(document, json.loads((ROOT / "constants" / "makers.json").read_text(encoding="utf-8")))
        self.assertEqual(document["schema"], identity.MAKERS_SCHEMA)
        self.assertEqual(identity.validate_registry(document), [])
        document["makers"].clear()
        self.assertTrue(identity.registry()["makers"], "registry() hands out copies")
        rows = identity.load_makers()
        self.assertEqual({r["kind"] for r in rows}, set(identity.MAKER_KINDS) - {"third-party"})
        self.assertEqual(identity.maker_entry("unoq")["kind"], "first-party")
        self.assertIsNone(identity.maker_entry("ZZZZ"))
        self.assertTrue(identity.is_registered_maker("PI5"))
        for code in ("SIM", "WEB", "ACME", "ZZZZ", "", None):
            self.assertFalse(identity.is_registered_maker(code), code)
        for family, code in base.MAKER_CODES.items():
            self.assertIsNotNone(identity.maker_entry(code), family)

    def test_registry_vectors_get_the_schemas_verdict(self):
        for v, doc in schema_vectors("makers"):
            with self.subTest(v["file"]):
                self.assertEqual(identity.validate_registry(doc) == [], v["valid"])
        twice = identity.registry()
        twice["makers"].append(dict(twice["makers"][0]))
        self.assertEqual(schema.validate("makers", twice), [], "a schema cannot see a repeated code")
        found = identity.validate_registry(twice)
        self.assertEqual(len(found), 1)
        self.assertIn("listed twice", found[0])

    def test_another_copy_of_the_registry_and_the_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "makers.json"
            good = {"schema": "popboll.makers/1", "makers": [
                {"code": "ZZZZ", "name": "Made-up maker", "kind": "third-party", "registered": "2026-01-01",
                 "contact": None, "notes": ""}]}
            path.write_text(json.dumps(good))
            self.assertEqual([r["code"] for r in identity.load_makers(path)], ["ZZZZ"])
            self.assertTrue(identity.is_registered_maker("zzzz", path))
            self.assertEqual(identity.validate_serial("PB0007-ZZZZ-1234", path), [])
            good["makers"][0]["kind"] = "nonsense"
            path.write_text(json.dumps(good))
            self.assertEqual(identity.load_makers(path), identity.load_makers())
            path.write_text("{not json")
            self.assertEqual(identity.load_makers(path), identity.load_makers())
            self.assertEqual(identity.load_makers(pathlib.Path(folder) / "missing.json"), identity.load_makers())
            self.assertEqual(len(self.logged), 3)

    def test_reading_a_devices_own_identity_file(self):
        with tempfile.TemporaryDirectory() as folder:
            data = pathlib.Path(folder)
            self.assertIsNone(identity.read_identity(data))             # no file: None, not an error
            self.assertEqual(identity.known_serial(data, env={}), "")
            self.assertIsNone(identity.identity_path(None, env={}))
            self.assertIsNone(identity.read_identity(None, env={}))
            doc = {"schema_version": 1, "serial": "PB0007-UNOQ-0123456789", "number": 7, "maker": "UNOQ",
                   "hardware_id": "0123456789", "source": "hardware:/proc/device-tree/serial-number",
                   "created_at": "2026-11-06T12:00:00Z"}
            (data / "device_identity.json").write_text(json.dumps(doc))
            me = identity.read_identity(data)
            self.assertEqual((me.serial, me.number, me.label, me.hardware_id, me.source, me.maker),
                             ("PB0007-UNOQ-0123456789", 7, "PBOLL #0007", "0123456789", "file", "UNOQ"))
            self.assertEqual(me.to_dict()["maker"], "UNOQ")
            self.assertEqual(identity.read_identity(data / "device_identity.json"), me)
            self.assertEqual(identity.read_identity(None, env={"POPBOLLARD_DATA_DIR": folder}), me)
            self.assertEqual(identity.known_serial(data, env={}), doc["serial"])
            self.assertEqual(identity.known_serial(data, env={"POPBOLLARD_DEVICE_SERIAL": " VPB0001-WEB-x "}), "VPB0001-WEB-x")
            (data / "device_identity.json").write_text(json.dumps({"serial": "VPB0042-WEB-pb-example"}))
            alone = identity.read_identity(data)
            self.assertEqual((alone.number, alone.hardware_id, alone.label), (42, "pb-example", "PBOLL #0042"))

    def test_identity_vectors_and_unreadable_files_are_errors_not_absences(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "device_identity.json"
            for v, doc in schema_vectors("device-identity"):
                with self.subTest(v["file"]):
                    path.write_text(json.dumps(doc))
                    if v["valid"]:
                        self.assertEqual(identity.read_identity(path).serial, doc["serial"])
                        self.assertEqual(identity.identity_problems(doc), [])
                    else:
                        with self.assertRaises(identity.IdentityError):
                            identity.read_identity(path)
                        with self.assertRaises(identity.IdentityError):
                            identity.known_serial(path, env={})
            path.write_text("{not json")
            with self.assertRaises(identity.IdentityError):
                identity.read_identity(path)
            path.write_text("[]")
            with self.assertRaises(identity.IdentityError):
                identity.load_identity_file(path)

    def test_nothing_here_assigns_or_writes(self):
        # Reading is in scope; making up, probing, provisioning and writing are not.
        for name in ("resolve_device_identity", "provision", "probe_hardware", "write_identity_file",
                     "normalize_hardware_id", "board_maker_code"):
            self.assertFalse(hasattr(identity, name), name)
        text = (ROOT / "python" / "bollardeck" / "device" / "identity.py").read_text()
        for word in ("import secrets", "import subprocess", "write_text", "os.replace", "open("):
            self.assertNotIn(word, text)


# ── the dock placeholder, the docs, the example ──────────────────────────────────────────

class Rest(unittest.TestCase):
    def test_the_dock_protocol_still_waits_and_says_on_what(self):
        # SDK 0.2.0: the descriptor values arrived (tests/test_cart.py); the Dock protocol
        # itself still waits for Bollard v2 and the bollardeck rewrite.
        self.assertFalse(dock.AVAILABLE)
        self.assertEqual(len(dock.WAITS_ON), 2)
        self.assertEqual(dock.__all__[:2], ["AVAILABLE", "WAITS_ON"])
        self.assertIn("Bollard v2", dock.__doc__)
        self.assertFalse(hasattr(dock, "Dock"))

    def test_every_module_has_a_usage_guide(self):
        import bollardeck.device as device
        import bollardeck.device.gestures as gestures
        for module in (device, cues, gestures, keymap, identity, hal, base, sim, dock):
            self.assertGreater(len(module.__doc__ or ""), 400, module.__name__)

    def test_the_device_layer_imports_with_the_standard_library_only(self):
        code = ("import sys, bollardeck.device.hal, bollardeck.device.cues, bollardeck.device.gestures,"
                " bollardeck.device.keymap, bollardeck.device.identity, bollardeck.device.dock, bollardeck.routines;"
                "print(sorted(m for m in sys.modules if m.split('.')[0] in ('jsonschema', 'yaml', 'referencing')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
                             env=dict(os.environ, PYTHONPATH=str(ROOT / "python")))
        self.assertEqual(out.stdout.strip(), "[]")

    def test_the_example_runs_on_the_simulator(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BOLLAWAX_", "POPBOLLARD_"))}
        out = subprocess.run([sys.executable, str(ROOT / "examples" / "device_on_sim.py")], cwd=ROOT,
                             capture_output=True, text=True, env=dict(env, BOLLAWAX_HAL="sim"))
        self.assertEqual(out.returncode, 0, out.stderr)
        for line in ("board: sim (maker code SIM, hal interface 1)", "part 3 Bridge    I-bVII-IV-I",
                     "tap1    prompt: choose 'A'", "tap3x3  prompt: choose 'C'", "hold2   prompt: do pass",
                     "tap1    idle: do skip_to_frontier", "hold3   always: do power", "1:on:a 2:on:b 3:on:c"):
            self.assertIn(line, out.stdout)
        self.assertNotIn("switched off", out.stdout)


if __name__ == "__main__":
    unittest.main()
