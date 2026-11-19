# SPDX-License-Identifier: Apache-2.0
"""bollardeck.popsnip.accept: the device check, held to
conformance/popsnip/accept.json, which the JavaScript twin (checkAccept, tests/js/popsnip-accept.test.js) passes
too, and the one Ed25519 equation both twins use (conformance/popsnip/ed25519.json)."""
import ast
import base64
import inspect
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import bollardeck.popsnip as P  # noqa: E402
from bollardeck.popsnip import accept as A_MODULE  # noqa: E402,F401

V = json.loads((ROOT / "conformance" / "popsnip" / "accept.json").read_text(encoding="ascii"))
SIG = json.loads((ROOT / "conformance" / "popsnip" / "ed25519.json").read_text(encoding="ascii"))
SOURCE = (ROOT / "python" / "bollardeck" / "popsnip" / "accept.py").read_text(encoding="utf-8")


def dec(t):
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


def run(c):
    lst = V["lists"].get(c["list"]) if c["list"] else None
    held = V["lists"].get(c["held_list"]) if c["held_list"] else None
    fls = V["files"][c["files"]]
    return P.accept(c["app"], V["releases"][c["release"]],
                    {k: t.encode("ascii") for k, t in fls.items()} if fls is not None else None,
                    V["logs"][c["log"]], V["heads"][c["head"]], V["certs"], V["roots"][c["roots"]],
                    (lst["index"], lst["pages"]) if lst else None, [dec(k) for k in V["pinned"][c["pinned"]]],
                    V["heads"][c["held_head"]] if c["held_head"] else None,
                    (held["index"], held["pages"]) if held else None)


class TheVectors(unittest.TestCase):
    def test_every_case(self):
        for c in V["cases"]:
            v = run(c)
            self.assertEqual((v.ok, v.code), (c["code"] is None, c["code"]), c["name"])
        self.assertGreaterEqual(len(V["cases"]), 25)
        self.assertGreaterEqual(sum(c["code"] is None for c in V["cases"]), 7)


class TheEquation(unittest.TestCase):
    def test_every_ed25519_case(self):
        from bollardeck.corpus import _ed25519 as E
        for c in SIG["cases"]:
            got = E.verify(bytes.fromhex(c["pub"]), bytes.fromhex(c["message"]), bytes.fromhex(c["signature"]))
            self.assertIs(got, c["valid"], c["name"])
        self.assertGreaterEqual(sum("mixed-order" in c["name"] for c in SIG["cases"]), 3)


class WhatItCannotReach(unittest.TestCase):
    """No environment, disk or network, no unsigned mode, and nothing a lapsed pass could change."""

    def test_no_environment_disk_or_network(self):
        tree = ast.parse(SOURCE)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                    for a in n.names} | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        for banned in ("environ", "getenv", "open", "urlopen", "socket", "Path"):
            self.assertNotIn(banned, names, banned)
        for banned in ("os", "urllib", "socket", "pathlib", "subprocess", "http"):
            self.assertNotIn(banned, imported, banned)

    def test_no_argument_a_lapse_could_change(self):
        params = list(inspect.signature(P.accept).parameters)
        self.assertEqual(params, ["app", "release", "files", "log", "head", "certs", "root_records", "revocations",
                                  "pinned", "held_head", "held_list"])
        self.assertFalse(any("pass" in p for p in params))
        self.assertNotIn("pass_active", SOURCE.split('"""', 2)[2].replace('"pass_active"', ""))

    def test_no_pinned_key_accepts_nothing(self):
        c = dict(V["cases"][0], pinned="other")
        self.assertEqual(run(c).code, "cert")
        v = P.accept("drumtoy", V["releases"]["r1"], {}, V["logs"]["main"], V["heads"]["main"], V["certs"], [], None, [])
        self.assertEqual(v.code, "cert")                         # an empty pinned list is no unsigned mode

    def test_nothing_raises(self):
        self.assertEqual(P.accept(*((None,) * 9)).code, "malformed")
        v = P.accept("x", {}, {}, [None], {}, [], [], (None, None), [])
        self.assertEqual((v.ok, v.code), (False, "head"))                 # a refusal with a code, not an exception


if __name__ == "__main__":
    unittest.main()
