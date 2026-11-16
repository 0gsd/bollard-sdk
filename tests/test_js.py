# SPDX-License-Identifier: Apache-2.0
"""The browser binding: its JavaScript tests, its generated schemas, and its agreement with Python.

The JavaScript tests live in tests/js/ and run with plain `node --test` (no packages). This module
runs them from the Python suite when node is installed, and also checks, without node, that the
behaviour vectors are well formed. The expected values are re-derived from this repository's own
Python in tests/test_device.py (the cues) and tests/test_matrix.py (the matrix), always.
"""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import schema  # noqa: E402

JS = ROOT / "js"
CONFORMANCE = ROOT / "conformance"
NODE = shutil.which("node")
PARTS = ("schemas", "schema", "cues", "matrix", "gestures", "keymap", "corpus", "help", "popsnip", "dom")
MATRIX_CALLS = {"film", "playback", "idle", "corpus", "glyph", "dj", "text", "premiere", "tone",
                "dj_beat", "dj_crossfader", "dj_camelot", "text_pass_ms", "str_seed", "ascii"}


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def node(script):
    return subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, check=True).stdout


class JavaScriptTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_node_test_files_pass(self):
        files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests" / "js").glob("*.test.js"))
        self.assertGreaterEqual(len(files), 4)
        out = subprocess.run([NODE, "--test"] + files, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout[-6000:] + out.stderr[-2000:])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_javascript_and_python_report_every_vector_the_same_way(self):
        # Not only the same verdict: the same places, refused by the same keywords.
        script = (
            "const fs = require('fs'), b = require('./js/bollardeck.js');"
            "const idx = JSON.parse(fs.readFileSync('conformance/index.json', 'utf8'));"
            "console.log(JSON.stringify(idx.vectors.map((v) => b.schema.validate(v.schema,"
            " JSON.parse(fs.readFileSync('conformance/' + v.file, 'utf8'))).map((p) => [p.pointer, p.keyword]))));"
        )
        theirs = json.loads(node(script))
        index = json.loads((CONFORMANCE / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(theirs), len(index["vectors"]))
        for v, found in zip(index["vectors"], theirs):
            doc = json.loads((CONFORMANCE / v["file"]).read_text(encoding="utf-8"))
            ours = sorted([p.pointer, p.keyword] for p in schema.validate(v["schema"], doc))
            self.assertEqual(sorted(found), ours, v["file"])
            self.assertEqual(not found, v["valid"], v["file"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_both_validators_implement_the_same_keywords(self):
        got = json.loads(node("const s = require('./js/bollardeck.js').schema;"
                              "console.log(JSON.stringify([s.KEYWORDS, s.ANNOTATIONS, s.TYPES, s.DIALECT, s.names()]))"))
        self.assertEqual(sorted(got[0]), sorted(schema.KEYWORDS))
        self.assertEqual(sorted(got[1]), sorted(schema.ANNOTATIONS))
        self.assertEqual(got[2], list(schema.TYPES))
        self.assertEqual(got[3], schema.DIALECT)
        self.assertEqual(got[4], schema.names())


class TwinGate(unittest.TestCase):
    @unittest.skipUnless(NODE, "node is not installed")
    def test_javascript_and_python_give_every_gate_vector_the_same_verdict_in_full(self):
        # Not only allowed and reason: capability, corpus, scope, the three times and pending.
        from bollardeck.corpus import Identity, Standing, judge
        script = (
            "const fs = require('fs'), b = require('./js/bollardeck.js'), out = [];"
            "for (const f of fs.readdirSync('conformance/corpus-gate').sort()) {"
            " const d = JSON.parse(fs.readFileSync('conformance/corpus-gate/' + f, 'utf8'));"
            " for (const c of d.cases) { const v = b.corpus.judge(d.manifests[c.manifest], c.capability, c.identity, c.clock, c.standing);"
            "  out.push(Object.assign(v.asDict(), {valid_until: v.validUntil})); } }"
            "console.log(JSON.stringify(out));"
        )
        theirs = json.loads(node(script))
        ours = []
        for path in sorted((CONFORMANCE / "corpus-gate").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for c in doc["cases"]:
                v = judge(doc["manifests"][c["manifest"]], c["capability"], Identity.from_dict(c.get("identity")),
                          c["clock"], Standing.from_dict(c.get("standing")))
                ours.append((c["name"], dict(v.as_dict(), valid_until=v.valid_until)))
        self.assertEqual(len(theirs), len(ours))
        self.assertGreaterEqual(len(ours), 100)
        for (name, mine), other in zip(ours, theirs):
            mine.pop("detail")          # the wording quotes values each language's way
            other.pop("detail")
            self.assertEqual(other, mine, name)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_two_gates_know_the_same_names(self):
        from bollardeck.corpus import gate, licence
        got = json.loads(node("const c = require('./js/bollardeck.js').corpus;"
                              "console.log(JSON.stringify([c.REASONS, c.ALL_CAPABILITIES, c.SCOPES, c.VERDICT_TTL_SEC]))"))
        self.assertEqual(got[0], list(gate.REASONS))
        self.assertEqual(got[1], list(gate.ALL_CAPABILITIES))
        self.assertEqual(sorted(got[2]), sorted(licence.SCOPES))
        from bollardeck.corpus import model
        self.assertEqual(got[3], model.VERDICT_TTL_SEC)


class GeneratedSchemas(unittest.TestCase):
    # tools/generate.py writes js/bollardeck.schemas.js; its freshness is checked with the other
    # generated files in tests/test_schemas.py.
    def test_it_carries_every_schema_and_says_it_is_generated(self):
        text = (JS / "bollardeck.schemas.js").read_text(encoding="utf-8")
        self.assertIn("GENERATED by tools/generate.py", text)
        for name in schema.names():
            line = "    %s: %s," % (json.dumps(name), json.dumps(schema.load(name), ensure_ascii=True, separators=(",", ":")))
            self.assertIn(line, text, name)


class Packaging(unittest.TestCase):
    def test_every_part_is_a_file_and_is_named_by_both_entry_points(self):
        main = (JS / "bollardeck.js").read_text(encoding="utf-8")
        module = (JS / "bollardeck.mjs").read_text(encoding="utf-8")
        self.assertIn("var PARTS = %s;" % json.dumps(list(PARTS)), main)
        for part in PARTS:
            self.assertTrue((JS / ("bollardeck.%s.js" % part)).is_file(), part)
            self.assertIn('import "./bollardeck.%s.js";' % part, module)

    def test_the_pure_parts_do_not_touch_a_page(self):
        # Only bollardeck.dom.js may use elements, a canvas or animation frames; bollardeck.js uses
        # the document only to load its parts.
        for part in ("schemas", "schema", "cues", "matrix", "gestures", "keymap"):
            code = re.sub(r"/\*.*?\*/|//[^\n]*", "", (JS / ("bollardeck.%s.js" % part)).read_text(encoding="utf-8"), flags=re.S)
            for word in ("document.", "window.", "requestAnimationFrame", "getContext", "localStorage", "fetch("):
                self.assertNotIn(word, code, "bollardeck.%s.js uses %s" % (part, word))

    def test_the_browser_example_needs_no_server_and_no_network(self):
        html = (ROOT / "examples" / "browser" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="../../js/bollardeck.js"></script>', html)
        self.assertNotRegex(re.sub(r"<!--.*?-->", "", html, flags=re.S), r"https?://")
        self.assertNotIn("import ", html)


class BehaviourVectors(unittest.TestCase):
    """The vectors under conformance/matrix/ and conformance/cue-render/ are plain JSON any
    implementation can run. These checks need neither node nor the device's engine."""

    def files(self, folder):
        found = sorted((CONFORMANCE / folder).glob("*.json"))
        self.assertTrue(found, folder)
        return found

    def test_vector_files_are_written_the_way_the_pinning_tool_writes_them(self):
        tool = load_tool("pin_vectors")
        for path in self.files("matrix") + self.files("cue-render"):
            text = path.read_text(encoding="utf-8")
            self.assertEqual(tool.dumps(json.loads(text)), text, path.name)

    def test_matrix_vectors_are_well_formed(self):
        count = 0
        for path in self.files("matrix"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["version"], 1, path.name)
            self.assertEqual(doc["pinned_to"], {"python": "bollardeck.matrix"}, path.name)
            names = [v["name"] for v in doc["vectors"]]
            self.assertEqual(len(names), len(set(names)), path.name)
            for v in doc["vectors"]:
                count += 1
                self.assertIn(v["call"], MATRIX_CALLS, v["name"])
                self.assertEqual(set(v) - {"frame", "value"}, {"name", "call", "args"}, v["name"])
                self.assertEqual(len(set(v) & {"frame", "value"}), 1, v["name"])
                if "frame" in v:
                    self.assertRegex(v["frame"], r"^[0-9a-f]{226}$", v["name"])
                for arg in v["args"].values():
                    if isinstance(arg, dict) and set(arg) == {"$fixture"}:
                        self.assertIn(arg["$fixture"], doc.get("fixtures", {}), v["name"])
        self.assertGreaterEqual(count, 1100)

    def test_cue_render_vectors_hold_valid_cue_lists_and_three_buttons_each(self):
        count = 0
        for path in self.files("cue-render"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["version"], 1)
            self.assertEqual(set(doc["constants"]), {"PULSE_PERIOD_MS", "CHASE_PERIOD_MS", "PULSE_FLOOR", "CHASE_TAIL", "CHASE_STEPS"})
            self.assertEqual(doc["pinned_to"], {"python": "bollardeck.device.cues"})
            for v in doc["vectors"]:
                count += 1
                self.assertEqual(schema.validate("cue", v["cues"]), [], v["name"])
                self.assertEqual([b["button"] for b in v["buttons"]], [1, 2, 3], v["name"])
                driven = {c["button"] for c in v["cues"]}
                for b in v["buttons"]:
                    self.assertEqual(set(b), {"button", "driven", "state", "role", "level", "arc", "head", "pixel"}, v["name"])
                    self.assertEqual(b["driven"], b["button"] in driven, v["name"])
                    self.assertTrue(0 <= b["level"] <= 1 and 0 <= b["pixel"] <= 255 and len(b["arc"]) == 3, v["name"])
        self.assertGreaterEqual(count, 100)


if __name__ == "__main__":
    unittest.main()
