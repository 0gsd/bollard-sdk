# SPDX-License-Identifier: Apache-2.0
"""bollardeck.popsnip: the record forms, their canonical bytes, and conformance/popsnip/records.json.

The JavaScript twin runs the same vectors in tests/js/popsnip.test.js (through tests/test_js.py); this module also
feeds both twins the same random texts and asks for the same answers.
"""
import base64
import importlib.util
import json
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck.corpus import _ed25519  # noqa: E402
from bollardeck.popsnip import records as R  # noqa: E402

VECTORS = json.loads((ROOT / "conformance" / "popsnip" / "records.json").read_text(encoding="ascii"))
NODE = shutil.which("node")


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / ("%s.py" % name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def code_of(fn):
    try:
        fn()
    except R.RecordError as exc:
        return exc.code
    return None


def signed_entry(seq):
    return next(v["record"] for v in VECTORS["records"] if "canonical" in v
                and v["record"]["kind"] == "popsnip.rekey" and v["record"]["seq"] == seq)


class TheVectors(unittest.TestCase):
    def test_the_tool_makes_this_file(self):
        self.assertEqual(load_tool("popsnip_vectors").main(["--check"]), 0)

    def test_every_record(self):
        accepted = 0
        for v in VECTORS["records"]:
            self.assertEqual(code_of(lambda: R.check(v["record"], v.get("signed", True))), v["error"], v["name"])
            if "canonical" in v:
                self.assertEqual(R.canonical(v["record"]).decode("ascii"), v["canonical"], v["name"])
                self.assertEqual(R.record_id(v["record"]), v["id"], v["name"])
                self.assertEqual(R.signed_message(v["record"]), R.CONTEXT + v["canonical"].encode("ascii"))
                accepted += 1
        self.assertGreaterEqual(accepted, 15)
        self.assertEqual({v["record"]["kind"] for v in VECTORS["records"] if "canonical" in v}, set(R.KINDS))

    def test_every_text(self):
        for t in VECTORS["texts"]:
            for data in (t["text"], t["text"].encode("utf-8")):
                got = {}
                self.assertEqual(code_of(lambda: got.update(v=R.parse(data))), t["parse_error"], t["text"][:60])
                if t["parse_error"] is None:
                    canon = {}
                    err = code_of(lambda: canon.update(c=R.canonical(got["v"]).decode("ascii")))
                    self.assertEqual((err, canon.get("c")), (t["canonical_error"], t["canonical"]), t["text"][:60])
        self.assertEqual(code_of(lambda: R.parse(b'{"\xff":1}')), "bad_json")
        for depth in (100, 1000, 100000):                                    # never RecursionError
            self.assertEqual(code_of(lambda: R.parse('{"a":' + "[" * depth + "]" * depth + "}")), "bad_json")
        self.assertFalse(R.too_deep('{"a":' + "[" * 31 + "]" * 31 + "}"))
        self.assertTrue(R.too_deep('{"a":' + "[" * 32 + "]" * 32 + "}"))
        self.assertEqual(code_of(lambda: R.parse(42)), "bad_json")

    def test_the_rekey_requests(self):
        for r in VECTORS["rekey_requests"]:
            self.assertEqual(R.rekey_request(signed_entry(r["entry_seq"])), r["request"])
            self.assertEqual(R.canonical(r["request"]).decode("ascii"), r["canonical"])
            self.assertIs(R.check(r["request"]), r["request"])                # a kind of its own, checked
        self.assertEqual(code_of(lambda: R.rekey_request({})), "missing_field:app")


class TheSignatures(unittest.TestCase):
    def test_every_signed_vector_verifies_over_the_context_only(self):
        n = 0
        for v in VECTORS["records"]:
            if "canonical" not in v or v["signed_by"] is None:
                continue
            pub, sig = dec(VECTORS["keys"][v["signed_by"]]["pub"]), dec(v["record"]["signature"])
            self.assertTrue(_ed25519.verify(pub, R.signed_message(v["record"]), sig), v["name"])
            self.assertFalse(_ed25519.verify(pub, R.canonical(v["record"]), sig), v["name"])
            n += 1
        for r in VECTORS["rekey_requests"]:
            pub = dec(VECTORS["keys"][r["signed_by"]]["pub"])
            sig = dec(signed_entry(r["entry_seq"])["old_key_sig"])
            self.assertTrue(_ed25519.verify(pub, R.signed_message(r["request"]), sig))
        self.assertGreaterEqual(n, 15)

    def test_the_keys_are_the_printed_seeds(self):
        signer = load_tool("popsnip_vectors").sign_release
        for role, k in VECTORS["keys"].items():
            self.assertEqual(signer.b64u(signer.public_key(bytes.fromhex(k["seed_hex"]))), k["pub"], role)

    def test_the_tools_signer_meets_rfc_8032(self):
        # RFC 8032 section 7.1, TEST 1 and TEST 2 (the verifier is held to all of them in test_corpus_attest)
        signer = load_tool("popsnip_vectors").sign_release
        for sk, pk, msg, sig in (
                ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
                 "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
                 "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46b"
                 "d25bf5f0595bbe24655141438e7a100b"),
                ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
                 "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
                 "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c"
                 "387b2eaeb4302aeeb00d291612bb0c00")):
            self.assertEqual(signer.public_key(bytes.fromhex(sk)).hex(), pk)
            self.assertEqual(signer.sign(bytes.fromhex(sk), bytes.fromhex(msg)).hex(), sig)


class SmallOrder(unittest.TestCase):
    """Keys that cannot sign (small order, non-canonical, off the curve): refused by check() and by the verifier."""

    def test_the_list_is_the_curve_s_torsion(self):
        self.assertEqual(VECTORS["small_order"], load_tool("popsnip_vectors").small_order())
        self.assertEqual(len(VECTORS["small_order"]), 8)
        for h in VECTORS["small_order"]:
            pt = _ed25519._decode(bytes.fromhex(h))
            self.assertTrue(pt is not None and _ed25519._small(pt), h)

    def test_the_identity_signs_nothing(self):
        ident = bytes.fromhex("01" + "00" * 31)
        for msg in (b"", b"anything", R.CONTEXT + b'{"a":1}'):
            self.assertFalse(_ed25519.verify(ident, msg, ident + bytes(32)))
        for h in VECTORS["small_order"]:
            self.assertFalse(_ed25519.verify(bytes.fromhex(h), b"x", bytes.fromhex(h) + bytes(32)), h)

    def test_real_keys_still_verify(self):
        signer = load_tool("popsnip_vectors").sign_release
        for role, k in VECTORS["keys"].items():
            seed = bytes.fromhex(k["seed_hex"])
            self.assertTrue(_ed25519.verify(signer.public_key(seed), b"m", signer.sign(seed, b"m")), role)


class TheForm(unittest.TestCase):
    def test_every_kind_has_a_signer_and_log_kinds_a_time(self):
        self.assertEqual(set(R.SIGNER), set(R.KINDS))
        self.assertTrue(set(R.SIGNER.values()) <= {"release", "launch", "dev"})
        self.assertEqual(set(R.TIME_FIELD), set(R.LOG_KINDS))
        for kind in R.LOG_KINDS:
            self.assertIn(R.TIME_FIELD[kind], R.KINDS[kind][1])
            self.assertIn("seq", R.KINDS[kind][1])

    def test_canonical_never_changes_the_record(self):
        rec = dict(next(v["record"] for v in VECTORS["records"] if "canonical" in v))
        before = json.dumps(rec, sort_keys=True)
        R.canonical(rec)
        R.check(rec)
        self.assertEqual(json.dumps(rec, sort_keys=True), before)

    def test_in_memory_values_outside_the_form(self):
        for value, code in ((1.0, "bad_number"), (float("nan"), "bad_number"), (2 ** 53, "bad_number"),
                            (-(2 ** 53), "bad_number"), (b"x", "bad_number"), ((1, 2), "bad_number"),
                            ("café", "not_ascii"), ("a\x7fb", "not_ascii"), ("a\nb", "not_ascii")):
            self.assertEqual(code_of(lambda: R.canonical({"a": value})), code, repr(value))
        self.assertEqual(code_of(lambda: R.canonical({1: "a"})), "not_ascii")
        self.assertEqual(code_of(lambda: R.canonical({1: "a", "b": 2})), "not_ascii")     # mixed keys: no TypeError
        self.assertEqual(code_of(lambda: R.canonical({"a": {1, 2}})), "bad_number")
        deep = {}
        for _ in range(R.MAX_DEPTH + 5000):                                  # in memory, deeper than any stack
            deep = {"a": deep}
        self.assertEqual(code_of(lambda: R.canonical(deep)), "bad_json")
        self.assertEqual(code_of(lambda: R.check(deep)), "bad_json")
        self.assertEqual(R.canonical({"a": True, "b": None, "c": [2 ** 53 - 1, -(2 ** 53 - 1)]}),
                         b'{"a":true,"b":null,"c":[9007199254740991,-9007199254740991]}')

    def test_the_package_exports(self):
        import bollardeck.popsnip as P
        for name in P.__all__:
            self.assertTrue(hasattr(P, name), name)
        self.assertIs(P.check, R.check)


def _random_value(rng, depth):
    pick = rng.random()
    if depth > 3 or pick < 0.45:
        kind = rng.randrange(6)
        if kind == 0:
            return rng.choice([0, 1, -1, 2 ** 53 - 1, -(2 ** 53 - 1), rng.randrange(-10 ** 6, 10 ** 6)])
        if kind == 1:
            return rng.choice([True, False, None])
        alphabet = "ab\"\\/ {}[]:,\x7e\x20" + "".join(chr(c) for c in range(0x21, 0x7f, 7))
        if rng.random() < 0.1:                                       # now and then, outside the form
            alphabet += rng.choice(["\x7f", "é", "\n", "\x01", "\ud83d"])
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 8)))
    if pick < 0.7:
        return [_random_value(rng, depth + 1) for _ in range(rng.randrange(0, 4))]
    keys = ["".join(rng.choice("abcAB_-\"\\ ~") for _ in range(rng.randrange(0, 4))) for _ in range(rng.randrange(0, 5))]
    return {k: _random_value(rng, depth + 1) for k in keys}


def _spelled(value, rng):
    """JSON text for value with random whitespace and escapes, so the parsers see more than one spelling."""
    def ws():
        return "".join(rng.choice(" \t\n\r") for _ in range(rng.randrange(0, 2)))
    if isinstance(value, dict):
        return "{" + ws() + ",".join(ws() + _spelled(k, rng) + ws() + ":" + ws() + _spelled(v, rng) + ws()
                                     for k, v in value.items()) + ws() + "}"
    if isinstance(value, list):
        return "[" + ws() + ",".join(ws() + _spelled(v, rng) + ws() for v in value) + ws() + "]"
    if isinstance(value, str):
        out = '"'
        for ch in value:
            r = rng.random()
            if ch in '"\\':
                out += "\\" + ch
            elif r < 0.2:
                out += ("\\u%04x" if rng.random() < 0.5 else "\\u%04X") % ord(ch)
            elif ch == "/" and r < 0.5:
                out += "\\/"
            else:
                out += ch
        return out + '"'
    return json.dumps(value)


class TheTwinsAgree(unittest.TestCase):
    @unittest.skipUnless(NODE, "node is not installed")
    def test_random_texts(self):
        rng = random.Random(20261116)
        texts = [_spelled({"k": _random_value(rng, 0)}, rng) for _ in range(400)]
        texts += ['{"a":' + str(n) + "}" for n in (2 ** 53 - 1, 2 ** 53, -(2 ** 53), 10 ** 30, 0, 1234567890123456)]
        texts += ['{"a":%s}' % s for s in ("1.5", "1e2", "-0", "00", "0.0", "-9007199254740991", "-9007199254740992")]
        # hostile input: the codes agree too
        texts += ['{"a":' + "1" * n + "}" for n in (16, 17, 4300, 4301, 5000)]
        for d in (31, 32, 33, 40, 513, 600):
            for inner in ("1", "1.5", '{"b":1,"b":2}', '"x"', "NaN", ""):
                texts.append('{"a":' + "[" * d + inner + "]" * d + "}")
        texts += ['{"a":"' + "\\" * n + '"' + "[" * 40 + "}" for n in range(4)]
        want = []
        for t in texts:
            try:
                want.append(R.canonical(R.parse(t)).decode("ascii"))
            except R.RecordError as exc:
                want.append("!" + exc.code)
        script = ("const P=require('./js/bollardeck.popsnip.js');const T=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));"
                  "console.log(JSON.stringify(T.map(t=>{try{return P.canonicalText(P.parse(t))}"
                  "catch(e){if(!(e instanceof P.RecordError))throw e;return '!'+e.code}})))")
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "texts.json"
            path.write_text(json.dumps(texts), encoding="ascii")
            out = subprocess.run([NODE, "-e", script, str(path)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        for t, a, b in zip(texts, want, json.loads(out.stdout)):
            self.assertEqual(b, a, t)
        self.assertGreater(sum(1 for w in want if not w.startswith("!")), 300)


if __name__ == "__main__":
    unittest.main()
