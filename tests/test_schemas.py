# SPDX-License-Identifier: Apache-2.0
"""The schemas, the validator, the conformance vectors, and the constants generated for Python and JS.

`jsonschema` is a cross-check here and never a runtime dependency: the tests that need it skip
when it is not installed, unless BOLLARD_SDK_REQUIRE_JSONSCHEMA is set (CI sets it), in which
case its absence is a failure.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import bollardeck  # noqa: E402
from bollardeck import constants, schema  # noqa: E402

SCHEMA_DIR = ROOT / "schema"
CONFORMANCE = ROOT / "conformance"
SUFFIX = ".schema.json"
ID_BASE = "https://popboll.com/sdk/schema/"

try:
    import jsonschema
    import referencing
except ImportError:
    jsonschema = referencing = None
    if os.environ.get("BOLLARD_SDK_REQUIRE_JSONSCHEMA"):
        raise


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def schema_files():
    return {p.name[: -len(SUFFIX)]: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SCHEMA_DIR.glob("*" + SUFFIX))}


def index():
    return json.loads((CONFORMANCE / "index.json").read_text(encoding="utf-8"))


def vectors():
    for v in index()["vectors"]:
        yield v, json.loads((CONFORMANCE / v["file"]).read_text(encoding="utf-8"))


class Schemas(unittest.TestCase):
    def test_every_schema_file_is_named_described_and_packaged(self):
        files = schema_files()
        self.assertEqual(sorted(files), schema.names(), "run tools/generate.py")
        for name, body in files.items():
            self.assertEqual(body["$schema"], schema.DIALECT, name)
            self.assertEqual(body["$id"], ID_BASE + name + SUFFIX, name)
            self.assertTrue(body.get("title", "").strip(), name)
            self.assertGreater(len(body.get("description", "")), 60, name)
            self.assertEqual(schema.load(name), body, "%s: run tools/generate.py" % name)

    def test_the_validator_implements_exactly_the_keywords_the_schemas_use(self):
        used = set()
        for name in schema.names():
            for _path, node in schema._subschemas(schema.load(name), ""):
                if isinstance(node, dict):
                    used |= set(node)
        self.assertEqual(used - schema.ANNOTATIONS, set(schema.KEYWORDS))

    def test_a_keyword_the_validator_does_not_implement_is_refused(self):
        base = {"$schema": schema.DIALECT, "$id": ID_BASE + "x" + SUFFIX}
        for extra in ({"format": "date-time"}, {"oneOf": [{}]}, {"else": {}}, {"uniqueItems": True},
                      {"properties": {"a": {"multipleOf": 2}}}, {"items": {"allOf": [{"contains": {}}]}},
                      {"type": "date"}, {"pattern": "("}, {"then": {}}):
            with self.assertRaises(schema.UnsupportedSchema, msg=str(extra)):
                schema.check_schema(dict(base, **extra))
        schema.check_schema(dict(base, type="object", properties={"a": True, "b": False}))
        with self.assertRaises(schema.UnsupportedSchema):
            schema.check_schema({"type": "object"})          # no $id, no $schema

    def test_every_schema_is_a_valid_2020_12_schema(self):
        if jsonschema is None:
            self.skipTest("jsonschema is not installed")
        for name, body in schema_files().items():
            jsonschema.Draft202012Validator.check_schema(body)

    def test_unknown_names_and_pointers_are_errors_not_passes(self):
        with self.assertRaises(KeyError):
            schema.validate("no-such-schema", {})
        with self.assertRaises(schema.UnsupportedSchema):
            schema.validate("cue#/$defs/nothing", {})


class Validator(unittest.TestCase):
    def test_a_name_can_point_inside_a_schema(self):
        self.assertEqual(schema.validate("cue#/$defs/cue", {"button": 1, "state": "on", "role": None}), [])
        self.assertTrue(schema.is_valid("device-identity#/$defs/device_serial", "PB0042-ACME-1A2B3C"))
        self.assertFalse(schema.is_valid("device-identity#/$defs/device_serial", "VPB0042-WEB-pb-example"))

    def test_problems_carry_json_pointers(self):
        found = schema.validate("makers", {"schema": "popboll.makers/1", "makers": [{"a/b": 1, "c~d": 2}]})
        pointers = {p.pointer for p in found}
        self.assertIn("/makers/0/a~1b", pointers)       # RFC 6901: "/" in a key is written ~1
        self.assertIn("/makers/0/c~0d", pointers)       # and "~" is written ~0
        self.assertIn("/makers/0", pointers)
        self.assertTrue(all(str(p).startswith("#" + p.pointer + ": ") for p in found))
        self.assertEqual({p.pointer for p in schema.validate("licence", 7)}, {""})

    def test_numbers_and_booleans_are_told_apart_as_json_schema_says(self):
        one = {"button": 1.0, "state": "on", "role": None}
        self.assertTrue(schema.is_valid("cue#/$defs/cue", one))                        # 1.0 is the integer 1
        self.assertFalse(schema.is_valid("cue#/$defs/cue", dict(one, button=True)))    # true is not 1
        self.assertFalse(schema.is_valid("cue#/$defs/cue", dict(one, button=1.5)))
        self.assertFalse(schema.is_valid("licence", {"scope": "full", "store_art": 1}))

    def test_a_pattern_ends_at_the_end_not_before_a_final_newline(self):
        manifest = json.loads((CONFORMANCE / "corpus-manifest/valid/minimal.json").read_text(encoding="utf-8"))
        self.assertTrue(schema.is_valid("corpus-manifest", manifest))
        manifest["id"] += "\n"
        self.assertFalse(schema.is_valid("corpus-manifest", manifest))

    def test_validating_does_not_change_the_document_or_the_schema(self):
        for v, doc in vectors():
            before, kept = copy.deepcopy(doc), copy.deepcopy(schema.load(v["schema"]))
            schema.validate(v["schema"], doc)
            self.assertEqual(doc, before, v["file"])
            self.assertEqual(schema.load(v["schema"]), kept, v["file"])


class Conformance(unittest.TestCase):
    def test_the_index_lists_every_vector_file_and_nothing_else(self):
        idx = index()
        self.assertEqual(idx["version"], 1)
        self.assertEqual(idx["schemas"], {n: "schema/%s%s" % (n, SUFFIX) for n in schema.names()})
        listed = [v["file"] for v in idx["vectors"]]
        self.assertEqual(len(listed), len(set(listed)))
        on_disk = sorted(str(p.relative_to(CONFORMANCE).as_posix()) for p in CONFORMANCE.glob("*/*/*.json"))
        self.assertEqual(sorted(listed), on_disk)
        for v in idx["vectors"]:
            self.assertEqual(set(v), {"schema", "file", "valid", "reason"} | (set() if v["valid"] else {"at"}), v["file"])
            self.assertEqual(v["file"].split("/")[:2], [v["schema"], "valid" if v["valid"] else "invalid"], v["file"])
            self.assertTrue(v["reason"].strip() and "\n" not in v["reason"], v["file"])

    def test_every_schema_has_vectors_both_ways(self):
        counts = {name: [0, 0] for name in schema.names()}
        for v in index()["vectors"]:
            counts[v["schema"]][0 if v["valid"] else 1] += 1
        for name, (good, bad) in counts.items():
            self.assertGreaterEqual(good, 2, name)
            self.assertGreaterEqual(bad, 5, name)

    def test_the_validator_gives_every_vector_its_verdict(self):
        for v, doc in vectors():
            found = schema.validate(v["schema"], doc)
            if v["valid"]:
                self.assertEqual([str(p) for p in found], [], v["file"])
            else:
                self.assertTrue(found, "%s: accepted, but %s" % (v["file"], v["reason"]))
                self.assertIn(v["at"], {p.pointer for p in found},
                              "%s: no problem reported at %r: %s" % (v["file"], v["at"], [str(p) for p in found]))

    def test_jsonschema_agrees_on_every_vector(self):
        if jsonschema is None:
            self.skipTest("jsonschema is not installed")
        bodies = schema_files()
        registry = referencing.Registry().with_resources(
            [(body["$id"], referencing.Resource.from_contents(body)) for body in bodies.values()])
        for v, doc in vectors():
            theirs = jsonschema.Draft202012Validator(bodies[v["schema"]], registry=registry).is_valid(doc)
            self.assertEqual(theirs, v["valid"], "%s: jsonschema disagrees with the index" % v["file"])
            self.assertEqual(schema.is_valid(v["schema"], doc), theirs, v["file"])


class Constants(unittest.TestCase):
    def source(self):
        return json.loads((ROOT / "constants" / "constants.json").read_text(encoding="utf-8"))["constants"]

    def test_generated_files_are_fresh(self):
        self.assertEqual(load_tool("generate").stale(), [], "run tools/generate.py")

    def test_the_check_notices_a_stale_file(self):
        generate = load_tool("generate")
        real = generate.CONSTANTS
        changed = json.loads(real.read_text(encoding="utf-8"))
        changed["constants"]["HOLD_MS"]["value"] += 1
        try:
            with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stderr(io.StringIO()) as said:
                generate.CONSTANTS = pathlib.Path(folder) / "constants.json"
                generate.CONSTANTS.write_text(json.dumps(changed), encoding="utf-8")
                self.assertEqual(sorted(generate.stale()),
                                 ["js/bollardeck.constants.js", "js/bollardeck.js", "python/bollardeck/constants.py"])
                self.assertEqual(generate.main(["--check"]), 1)
                self.assertIn("is stale", said.getvalue())
        finally:
            generate.CONSTANTS = real
        self.assertEqual(generate.main(["--check"]), 0)

    def test_python_carries_the_source_values(self):
        source = self.source()
        self.assertEqual(sorted(constants.__all__), sorted(source))
        for name, entry in source.items():
            self.assertEqual(json.loads(json.dumps(getattr(constants, name))), entry["value"], name)
        self.assertEqual((constants.HOLD_MS, constants.TAP_FOLLOW_MS), (800, 500))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_js_carries_the_same_values_every_way_it_loads(self):
        script = (
            "const a = require('./js/bollardeck.js'), c = require('./js/bollardeck.constants.js');"
            "import('./js/bollardeck.mjs').then(m => {"
            " let frozen = Object.isFrozen(a.constants) && Object.isFrozen(a.constants.BUTTONS[0]);"
            " try { a.constants.HOLD_MS = 1; } catch (e) {}"
            " console.log(JSON.stringify([a.constants, c, m.constants, globalThis.bollardeckConstants, frozen]));"
            "});"
        )
        out = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True)
        in_main, alone, module, as_global, frozen = json.loads(out.stdout)
        want = {name: entry["value"] for name, entry in self.source().items()}
        self.assertEqual([in_main, alone, module, as_global], [want] * 4)
        self.assertTrue(frozen)

    def test_the_cue_schema_and_the_constants_say_the_same(self):
        cue = schema.load("cue")["$defs"]["cue"]["properties"]
        self.assertEqual(cue["state"]["enum"], list(constants.CUE_STATES))
        self.assertEqual(cue["role"]["enum"], list(constants.CUE_ROLES) + [None])
        self.assertEqual(cue["button"]["enum"], [b["button"] for b in constants.BUTTONS])

    def test_buttons_are_numbers_and_the_wire_names_are_kept_as_data(self):
        self.assertEqual([b["button"] for b in constants.BUTTONS], [1, 2, 3])
        self.assertEqual([b["wire"] for b in constants.BUTTONS], ["inner", "middle", "outer"])
        for b in constants.BUTTONS:
            self.assertEqual(set(b), {"button", "label", "wire", "id", "job"})
            self.assertTrue(b["id"].startswith("BTN_%d_" % b["button"]))

    def test_the_package_still_imports_with_the_standard_library_only(self):
        code = ("import sys, bollardeck.schema as s, bollardeck.constants;"
                "s.validate('licence', {'scope': 'full'});"
                "print(sorted(m for m in sys.modules if m.split('.')[0] in ('jsonschema', 'yaml', 'referencing')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
                             env=dict(os.environ, PYTHONPATH=str(ROOT / "python")))
        self.assertEqual(out.stdout.strip(), "[]")
        self.assertEqual(bollardeck.SPEAKS["licence"], schema.load("licence")["properties"]["schema"]["anyOf"][1]["const"])
        self.assertEqual(bollardeck.SPEAKS["routine_api"], schema.load("routine-manifest")["properties"]["api"]["const"])


if __name__ == "__main__":
    unittest.main()
