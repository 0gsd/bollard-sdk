# SPDX-License-Identifier: Apache-2.0
"""bollardeck.pxs: the .pxs block reader, writer and validator, and conformance/pxs/blocks.json."""
import base64
import importlib.util
import json
import pathlib
import sys
import unittest
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import pxs  # noqa: E402

VECTORS = ROOT / "conformance" / "pxs" / "blocks.json"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / ("%s.py" % name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Vectors(unittest.TestCase):
    def test_every_vector_gets_its_verdict(self):
        doc = json.loads(VECTORS.read_text())
        self.assertEqual(doc["version"], 1)
        self.assertGreaterEqual(len(doc["cases"]), 30)
        for case in doc["cases"]:
            data = zlib.decompress(base64.b64decode(case["file_z64"]))
            self.assertEqual(len(data), case["bytes"], case["name"])
            v = pxs.validate(data)
            want = case["expect"]
            self.assertEqual((v.valid, v.kind, v.rule), (want["valid"], want["kind"], want["rule"]),
                             "%s: %s" % (case["name"], v.reason))

    def test_the_vector_file_is_what_the_tool_makes(self):
        self.assertEqual(load_tool("pxs_vectors").main(["--check"]), 0)

    def test_every_rule_has_an_invalid_vector(self):
        rules = {c["expect"]["rule"] for c in json.loads(VECTORS.read_text())["cases"] if not c["expect"]["valid"]}
        self.assertEqual(rules, {"V1", "V3", "V4", "V5", "V6", "V7"})


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool("pxs_vectors")
        self.module = self.tool.tiny_it()

    def test_attach_then_read_back_inflated(self):
        head = {"schema": "pxs/1", "base": "it", "title": "round trip"}
        midi = b"MThd" + bytes(200)
        data = pxs.attach(self.module, [("HEAD", pxs.canonical_json(head)), ("MIDI", midi), ("pabc", b"x")])
        v = pxs.validate(data)
        self.assertTrue(v.valid, v.reason)
        self.assertEqual((v.kind, v.block_offset, v.head["title"]), ("pxs", len(self.module), "round trip"))
        self.assertEqual([c[0] for c in v.chunks], ["HEAD", "MIDI", "pabc"])
        self.assertEqual([c[1] for c in v.chunks], [0, 1, 1])               # deflated but HEAD
        got = {c.id: c.data for c in pxs.read_chunks(data)}
        self.assertEqual(got["MIDI"], midi)
        self.assertEqual(data[0x3C:0x40], b"PXS1")
        self.assertEqual(data[:0x3C], self.module[:0x3C])                    # the module is otherwise unchanged
        self.assertEqual(data[0x40:len(self.module)], self.module[0x40:])

    def test_the_same_inputs_give_the_same_bytes(self):
        chunks = [("HEAD", pxs.canonical_json({"schema": "pxs/1", "base": "it"})), ("CRED", b"{}")]
        self.assertEqual(pxs.attach(self.module, chunks), pxs.attach(self.module, chunks))

    def test_the_writer_refuses_what_the_validator_would(self):
        hd = pxs.canonical_json({"schema": "pxs/1", "base": "it"})
        with self.assertRaises(pxs.PxsError) as e:
            pxs.attach(self.module, [("CRED", b"{}"), ("HEAD", hd)])
        self.assertEqual(e.exception.rule, "V7")
        with self.assertRaises(pxs.PxsError) as e:
            pxs.attach(self.module, [("HEAD", hd), ("CRED", b"{}"), ("CRED", b"{}")])
        self.assertEqual(e.exception.rule, "V6")
        with self.assertRaises(pxs.PxsError) as e:
            pxs.attach(self.module + b"pad", [("HEAD", hd)])
        self.assertEqual(e.exception.rule, "V3")
        with self.assertRaises(pxs.PxsError) as e:
            pxs.attach(self.module, [("HEAD", hd), ("BIGG", bytes(300 * 1024))], deflate=False)
        self.assertEqual(e.exception.rule, "V5")

    def test_measure_it_finds_every_structure(self):
        lay = pxs.measure_it(self.module)
        self.assertEqual(lay.base_end, len(self.module))
        self.assertEqual(lay.unaccounted, 0)
        kinds = [what.split(" ")[0] for _s, _e, what in lay.regions]
        self.assertEqual(kinds, ["header", "message", "instrument", "sample", "pattern", "sample"])
        self.assertEqual(pxs.measure_it(self.tool.tiny_it(stereo=True)).stereo_samples, 1)

    def test_a_plain_module_with_too_much_trailing_junk_is_refused(self):
        v = pxs.validate(self.module + bytes(pxs.MAX_UNACCOUNTED + 1))
        self.assertEqual((v.valid, v.rule), (False, "V1"))
        self.assertTrue(pxs.validate(self.module + bytes(16)).valid)


if __name__ == "__main__":
    unittest.main()
