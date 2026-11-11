# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.matrix: the Python frame engine makes, byte for byte, the frame of every vector under
conformance/matrix/, the same vectors tests/js/matrix.test.js holds the JavaScript engine to.

The rest covers what a vector cannot say: the MatrixFrame class, the text preview with its LED
line, a temperament or tone that is not a mapping, and that the tables the two engines carry are
the same tables (asked of node, when node is installed).
"""
import ast
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import matrix as M  # noqa: E402

VECTORS = ROOT / "conformance" / "matrix"
NODE = shutil.which("node")
CALLS = ["ascii", "corpus", "dj", "dj_beat", "dj_camelot", "dj_crossfader", "film", "glyph", "idle",
         "playback", "premiere", "str_seed", "text", "text_pass_ms", "tone"]


def run(call, a):
    """One vector's call, with the vector files' argument names and defaults."""
    g = a.get
    calm = bool(g("calm", False))
    if call == "film":
        return M.to_hex(M.film(g("song"), g("t_ms"), calm))
    if call == "playback":
        return M.to_hex(M.playback(g("song"), g("pos_s"), calm))
    if call == "idle":
        return M.to_hex(M.idle(g("t_ms"), calm, g("temperament")))
    if call == "corpus":
        return M.to_hex(M.corpus(g("t_ms"), g("level", 0), g("bands"), calm))
    if call == "glyph":
        return M.to_hex(M.glyph(g("name"), g("t_ms"), calm))
    if call == "dj":
        return M.to_hex(M.dj(g("seg"), g("pos_s"), g("t_ms", 0), calm))
    if call == "text":
        return M.to_hex(M.text(g("text"), g("t_ms"), bool(g("loop", True)), g("priority", "pairing"), g("ttl_ms"), calm))
    if call == "premiere":
        return M.to_hex(M.premiere(g("number"), g("t_ms"), bool(g("opened", False)), calm, g("tier", "")))
    if call == "tone":
        return M.to_hex(M.tone(M.from_hex(g("frame")), g("tone")))
    if call == "dj_beat":
        return M.dj_beat(g("seg"), g("pos_s"))
    if call == "dj_crossfader":
        return M.dj_crossfader(g("seg"), g("pos_s"))
    if call == "dj_camelot":
        return list(M.dj_camelot(g("value")))
    if call == "text_pass_ms":
        return M.text_pass_ms(g("text"))
    if call == "str_seed":
        return M.str_seed(g("text"))
    if call == "ascii":
        return M.to_ascii(M.from_hex(g("frame")))
    raise AssertionError("no matrix call named %r" % call)


def resolve(args, fixtures):
    return {k: fixtures[v["$fixture"]] if isinstance(v, dict) and set(v) == {"$fixture"} else v for k, v in args.items()}


def documents():
    found = sorted(VECTORS.glob("*.json"))
    return [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in found]


class Vectors(unittest.TestCase):
    def test_there_are_vectors_for_every_part_of_the_engine(self):
        calls, count = set(), 0
        for name, doc in documents():
            self.assertEqual(doc["version"], 1, name)
            self.assertEqual(doc["pinned_to"], {"python": "bollardeck.matrix"}, name)
            for v in doc["vectors"]:
                calls.add(v["call"])
                count += 1
        self.assertEqual(sorted(calls), CALLS)
        self.assertGreaterEqual(count, 1100)

    def test_the_engine_makes_every_vector(self):
        for name, doc in documents():
            fixtures = doc.get("fixtures", {})
            before = json.dumps(fixtures)
            for v in doc["vectors"]:
                with self.subTest(file=name, vector=v["name"]):
                    args_before = json.dumps(v["args"])
                    got = run(v["call"], resolve(v["args"], fixtures))
                    want = v["frame"] if "frame" in v else v["value"]
                    self.assertEqual(got, want)
                    self.assertIs(type(got), type(want))        # 20 and 20.0 are different values here
                    self.assertEqual(json.dumps(v["args"]), args_before, "the engine changed its input")
            self.assertEqual(json.dumps(fixtures), before, name + ": the engine changed its input")

    def test_the_long_names_and_the_short_names_are_the_same_functions(self):
        for short in ("film", "playback", "idle", "corpus", "glyph", "dj", "text", "premiere", "tone"):
            self.assertIs(getattr(M, short), getattr(M, short + "_frame"), short)
        for name in M.__all__:
            self.assertTrue(hasattr(M, name), name)


class Frames(unittest.TestCase):
    def test_a_frame_is_104_pixels_and_three_rgb_leds(self):
        self.assertEqual((M.W, M.H, M.N, M.FRAME_BYTES), (13, 8, 104, 113))
        frame = M.glyph_frame("boot", 120)
        self.assertEqual(len(frame.pixels), M.N)
        self.assertEqual([len(led) for led in frame.rgb], [3, 3, 3])
        self.assertEqual(len(frame.to_bytes()), M.FRAME_BYTES)
        self.assertEqual(frame.to_bytes()[:M.N], frame.pixels)
        self.assertEqual(frame.to_bytes()[M.N:], bytes(c for led in frame.rgb for c in led))

    def test_every_frame_function_returns_113_bytes(self):
        song = {"song_id": "s", "drama": {"shots": [{"kind": "JAM", "duration_ms": 1000}]}, "notes": [[0, 1, 1, 60, 100]]}
        frames = [M.film_frame(song, 300), M.playback_frame(song, 0.2), M.idle_frame(500),
                  M.idle_frame(500, False, {"shape": "tide", "rgb": [1, 2, 3]}), M.corpus_frame(500, 90),
                  M.dj_frame({"id": "d"}, 1.5, 1500), M.text_frame("HELLO", 900), M.premiere_frame(3, 700),
                  M.premiere_frame(3, 700, True, False, "rare"), M.tone_frame(M.idle_frame(0), {"mix": 128, "tint": [255, 0, 0]})]
        frames += [M.glyph_frame(name, 250) for name in M.GLYPHS]
        for frame in frames:
            self.assertIsInstance(frame, M.MatrixFrame)
            self.assertEqual(len(frame.to_bytes()), 113)
            self.assertEqual(len(frame.hex()), 226)

    def test_a_frame_round_trips_through_bytes_and_hex(self):
        frame = M.film_frame({"song_id": "r", "drama": {"shots": [{"kind": "VOTE", "duration_ms": 2000}]}}, 1500)
        self.assertEqual(M.MatrixFrame.from_bytes(frame.to_bytes()), frame)
        self.assertEqual(M.from_hex(M.to_hex(frame)), frame)
        self.assertEqual(M.to_hex(frame), frame.hex())
        self.assertEqual(M.to_hex(frame), frame.to_bytes().hex())
        again = M.MatrixFrame(list(frame.pixels), [list(led) for led in frame.rgb])
        self.assertEqual(again, frame)
        self.assertEqual(hash(again), hash(frame))
        self.assertNotEqual(frame, M.idle_frame(0))
        self.assertNotEqual(frame, frame.to_bytes())

    def test_a_frame_of_the_wrong_size_is_refused(self):
        with self.assertRaises(ValueError):
            M.MatrixFrame([0] * 103)
        with self.assertRaises(ValueError):
            M.MatrixFrame([0] * 104, [(0, 0, 0)] * 2)
        with self.assertRaises(ValueError):
            M.MatrixFrame.from_bytes(bytes(112))
        with self.assertRaises(ValueError):
            M.from_hex("00")
        with self.assertRaises(ValueError):
            M.from_hex("zz" * M.FRAME_BYTES)

    def test_lit_total_and_at(self):
        pixels = [0] * M.N
        pixels[0] = 255
        pixels[M.W * 2 + 5] = 40                      # x = 5, y = 2
        pixels[M.N - 1] = 1
        frame = M.MatrixFrame(pixels, [(300, -1, 7), (1, 2, 3), (4, 5, 6)])
        self.assertEqual(frame.lit(), 3)
        self.assertEqual(frame.total(), 296)
        self.assertEqual((frame.at(0, 0), frame.at(5, 2), frame.at(12, 7), frame.at(1, 0)), (255, 40, 1, 0))
        self.assertEqual(frame.rgb, ((44, 255, 7), (1, 2, 3), (4, 5, 6)))      # each value is kept to one byte
        self.assertEqual(M.MatrixFrame([0] * M.N).rgb, ((0, 0, 0),) * 3)
        self.assertIn("lit=3", repr(frame))

    def test_the_text_preview(self):
        pixels = [0] * M.N
        for x, v in enumerate((0, 1, 51, 52, 103, 154, 205, 255)):
            pixels[x] = v
        frame = M.MatrixFrame(pixels, [(255, 0, 16), (0, 128, 0), (1, 2, 3)])
        rows = M.to_ascii(frame).split("\n")
        self.assertEqual(len(rows), M.H)
        self.assertEqual({len(row) for row in rows}, {M.W})
        self.assertEqual(rows[0], ".::-+*##.....")       # 1 to 51, to 102, to 153, to 204, to 255
        self.assertEqual(rows[1:], ["." * M.W] * 7)
        self.assertEqual(frame.ascii(), M.to_ascii(frame))
        with_leds = M.to_ascii(frame, rgb=True).split("\n")
        self.assertEqual(with_leds[:M.H], rows)
        self.assertEqual(with_leds[M.H:], ["#ff0010 #008000 #010203"])


class LooseInput(unittest.TestCase):
    def test_a_temperament_that_is_not_a_mapping_is_no_temperament(self):
        for t_ms in (0, 700, 1900):
            for calm in (False, True):
                plain = M.idle_frame(t_ms, calm)
                for odd in ("x", 7, 1.5, True, ["breath"], ("tide",), object(), None, {}, [], "", 0):
                    self.assertEqual(M.idle_frame(t_ms, calm, odd), plain, repr(odd))

    def test_a_tone_that_is_not_a_mapping_leaves_the_frame_alone(self):
        frame = M.glyph_frame("boot", 120)
        for odd in ("x", 7, 1.5, True, [1, 2, 3], ("lut",), object(), None, {}, [], "", 0):
            self.assertEqual(M.tone_frame(frame, odd), frame, repr(odd))
        self.assertNotEqual(M.tone_frame(frame, {"mix": 256, "tint": [255, 0, 0]}), frame)

    def test_a_name_that_every_javascript_object_has_is_an_unknown_name(self):
        for name in ("constructor", "toString", "__proto__", "hasOwnProperty", "valueOf"):
            song = {"song_id": "p", "drama": {"shots": [{"kind": name, "duration_ms": 1000}]}}
            unknown = {"song_id": "p", "drama": {"shots": [{"kind": "NOT_A_KIND", "duration_ms": 1000}]}}
            self.assertEqual(M.film(song, 300), M.film(unknown, 300), name)
            self.assertEqual(M.text("OK", 0, True, name), M.text("OK", 0, True, "nothing"), name)
            self.assertEqual(M.premiere(2, 900, True, False, name), M.premiere(2, 900, True, False, "legendary"), name)
            self.assertEqual(M.glyph(name, 0), M.idle(0), name)

    def test_the_engine_is_pure(self):
        song = {"song_id": "purity", "bpm": 111, "drama": {"shots": [{"kind": "JAM", "duration_ms": 3000},
                {"kind": "MUTATION", "duration_ms": 3000, "actors": {"old": "a", "new": "b"}}]},
                "notes": [[0, 1, 1, 60, 100], [0.5, 0.2, 10, 36, 120]]}
        first = [M.film(song, 4100), M.playback(song, 0.6), M.idle(900)]
        M.film({"song_id": "other", "drama": {"shots": [{"kind": "LOCK", "duration_ms": 500}]}}, 100)
        M.playback({"notes": [[0, 1, 2, 60, 100]]}, 0.1)
        self.assertEqual([M.film(song, 4100), M.playback(song, 0.6), M.idle(900)], first)


class Module(unittest.TestCase):
    def test_it_imports_only_what_a_frame_engine_needs(self):
        tree = ast.parse((ROOT / "python" / "bollardeck" / "matrix.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "no relative imports")
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported, {"__future__", "bisect", "math", "typing"})

    def test_the_device_plumbing_is_not_here(self):
        for name in ("control_path", "scroll_text", "clear", "active_overlay", "overlay_frame", "handle_control",
                     "_send_control", "_register", "_OV_LOCK", "_LOCAL_DAEMON", "_demo"):
            self.assertFalse(hasattr(M, name), name)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_two_engines_carry_the_same_tables(self):
        names = ["W", "H", "N", "FRAME_BYTES", "TICK_MS", "GLYPHS", "COLS", "PALETTE", "PREMIERE_PERIOD_MS", "PREMIERE_OPEN_MS"]
        script = ("const m = require('./js/bollardeck.js').matrix; const out = {};"
                  "for (const k of %s) out[k] = m[k]; process.stdout.write(JSON.stringify(out));" % json.dumps(names))
        theirs = json.loads(subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
        self.assertEqual(sorted(theirs), sorted(names))
        for name in ("W", "H", "N", "FRAME_BYTES", "TICK_MS", "PREMIERE_PERIOD_MS", "PREMIERE_OPEN_MS"):
            self.assertEqual(theirs[name], getattr(M, name), name)
            self.assertIs(type(theirs[name]), int, name)
        self.assertEqual(theirs["GLYPHS"], list(M.GLYPHS))
        self.assertEqual(theirs["COLS"], [list(group) for group in M.COLS])
        self.assertEqual(theirs["PALETTE"], {str(ch): list(rgb) for ch, rgb in M.PALETTE.items()})
        self.assertEqual(sorted(M.PALETTE), list(range(1, 17)))
        self.assertEqual(sorted(ch for group in M.COLS for ch in group), list(range(1, 17)))


if __name__ == "__main__":
    unittest.main()
