#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
tools/popsnip_vectors.py: write conformance/popsnip/records.json, the vectors for Pop Snip records, which
bollardeck.popsnip.records (Python) and js/bollardeck.popsnip.js must both give byte for byte.

    python3 tools/popsnip_vectors.py           write the file
    python3 tools/popsnip_vectors.py --check   write nothing; exit 1 when the file differs from what this makes

What is the code's and what is the rule's. The expected refusal codes, the hand-written canonical texts and every
name are written here, as the rules; a valid record's canonical text and id are what the Python twin makes, so the
JavaScript twin is held to Python byte for byte. Signatures are real Ed25519 (RFC 8032) by TEST keys whose seeds are
printed in the file. The signer below is for those test keys only: plain big-integer arithmetic, not constant time,
never for a real key.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
from bollardeck.corpus import _ed25519 as E  # noqa: E402
from bollardeck.popsnip import records as R  # noqa: E402

OUT = ROOT / "conformance" / "popsnip" / "records.json"


class sign_release:                                          # noqa: N801 - a namespace, read like a module below
    """RFC 8032 section 5.1.6 signing over the verifier's own curve arithmetic, for the printed test keys only."""

    @staticmethod
    def b64u(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _encode(pt) -> bytes:
        x, y, z, _t = pt
        zi = pow(z, E._P - 2, E._P)
        x, y = x * zi % E._P, y * zi % E._P
        return (y | ((x & 1) << 255)).to_bytes(32, "little")

    @staticmethod
    def _expand(secret: bytes):
        h = hashlib.sha512(secret).digest()
        a = int.from_bytes(h[:32], "little")
        a &= (1 << 254) - 8
        a |= 1 << 254
        return a, h[32:]

    @classmethod
    def public_key(cls, secret: bytes) -> bytes:
        a, _prefix = cls._expand(secret)
        return cls._encode(E._mul(a, E._G))

    @classmethod
    def sign(cls, secret: bytes, message: bytes) -> bytes:
        a, prefix = cls._expand(secret)
        pub = cls._encode(E._mul(a, E._G))
        r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % E._L
        big_r = cls._encode(E._mul(r, E._G))
        k = int.from_bytes(hashlib.sha512(big_r + pub + message).digest(), "little") % E._L
        return big_r + ((r + k * a) % E._L).to_bytes(32, "little")


T0 = "2026-11-16T12:00:00Z"
T1 = "2026-11-16T12:05:00Z"
T2 = "2026-11-17T09:00:00Z"
T3 = "2026-11-18T09:00:00Z"
T3_7 = "2026-11-25T09:00:00Z"
T4 = "2026-11-19T10:00:00Z"
NOTICE = "https://popboll.com/dev/notices/"


def seed(role: str) -> bytes:
    return hashlib.sha256(("popsnip-test-key/" + role).encode("ascii")).digest()


ROLES = ("release", "launch", "dev", "dev2", "dev3", "dev4")
KEYS = {r: {"seed_hex": seed(r).hex(), "pub": sign_release.b64u(sign_release.public_key(seed(r)))} for r in ROLES}


def pub(role: str) -> str:
    return KEYS[role]["pub"]


def signed(record: Dict[str, Any], role: str) -> Dict[str, Any]:
    """As every signer must: check the record before it is signed, and again after."""
    out = {k: v for k, v in record.items() if k != "signature"}
    R.check(out, signed=False)
    out["signature"] = sign_release.b64u(sign_release.sign(seed(role), R.signed_message(out)))
    return R.check(out)


def small_order() -> List[str]:
    """The 8 points of small order, canonically encoded, found from the curve: L * Q lands in the torsion group for
    any point Q, and the group it generates is walked until all 8 are seen. The JS twin's SMALL_ORDER must equal this."""
    P = E._P

    def enc(pt):
        x, y, z, _t = pt
        zi = pow(z, P - 2, P)
        x, y = x * zi % P, y * zi % P
        return (y | ((x & 1) << 255)).to_bytes(32, "little")
    found, y = set(), 2
    while len(found) < 8:
        for sign in (0, 1):
            q = E._decode((y | (sign << 255)).to_bytes(32, "little"))
            if q is None:
                continue
            t, cur = E._mul(E._L, q), (0, 1, 1, 0)
            for _ in range(8):
                cur = E._add(cur, t)
                found.add(enc(cur).hex())
        y += 1
    return sorted(found)


def off_curve() -> str:
    """A canonical-looking y with no point on the curve (no x)."""
    y = 2
    while E._decode(y.to_bytes(32, "little")) is not None:
        y += 1
    return sign_release.b64u(y.to_bytes(32, "little"))


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def build() -> Dict[str, Any]:
    files1 = {"index.html": file_hash("<!doctype html><title>drumtoy</title><script src=app.js></script>"),
              "app.js": file_hash("console.log('drumtoy 1')"), "sounds/kick.ogg": file_hash("kick")}
    rel1 = signed({"v": 1, "kind": "popsnip.release", "app": "drumtoy", "version": 1, "prev": None, "files": files1,
                   "permissions": ["audio-in", "midi"], "dev_key": pub("dev")}, "dev")
    files2 = dict(files1, **{"app.js": file_hash("console.log('drumtoy 2')")})
    rel2 = signed({"v": 1, "kind": "popsnip.release", "app": "drumtoy", "version": 2, "prev": R.record_id(rel1),
                   "files": files2, "permissions": ["audio-in", "midi"], "csp": "img-src 'self'",
                   "dev_key": pub("dev")}, "dev")
    cert = signed({"v": 1, "kind": "popsnip.launch-key", "kid": "launch-test1", "pub": pub("launch"),
                   "not_before": "2026-11-16T00:00:00Z", "not_after": "2027-12-21T00:00:00Z"}, "release")

    log: List[Dict[str, Any]] = []

    def append(entry: Dict[str, Any]) -> Dict[str, Any]:
        entry = dict(entry, v=1, seq=len(log) + 1, prev=R.record_id(log[-1]) if log else R.GENESIS, kid="launch-test1")
        entry = signed(entry, "launch")
        log.append(entry)
        return entry

    append({"kind": "popsnip.launch", "app": "drumtoy", "account": "acct_TEST0001", "dev_key": pub("dev"),
            "release0": R.record_id(rel1), "launched_at": T0, "pass_active": True, "pass_kind": "standard"})
    append({"kind": "popsnip.publish", "app": "drumtoy", "version": 1, "manifest": R.record_id(rel1),
            "dev_key": pub("dev"), "published_at": T0})
    append({"kind": "popsnip.publish", "app": "drumtoy", "version": 2, "manifest": R.record_id(rel2),
            "dev_key": pub("dev"), "published_at": T1})
    rk = {"kind": "popsnip.rekey", "app": "drumtoy", "from_key": pub("dev"), "to_key": pub("dev2"),
          "from_account": "acct_TEST0001", "to_account": "acct_TEST0001", "path": "old_key", "requested_at": T2,
          "effective_at": T2, "challenge": sign_release.b64u(hashlib.sha256(b"challenge-1").digest())}
    rk["old_key_sig"] = sign_release.b64u(sign_release.sign(seed("dev"), R.signed_message(R.rekey_request(dict(rk, v=1)))))
    append(rk)
    append({"kind": "popsnip.rekey", "app": "drumtoy", "from_key": pub("dev2"), "to_key": pub("dev3"),
            "from_account": "acct_TEST0001", "to_account": "acct_TEST0001", "path": "account_only",
            "requested_at": T3, "effective_at": T3_7,
            "challenge": sign_release.b64u(hashlib.sha256(b"challenge-2").digest())})
    append({"kind": "popsnip.rekey-cancel", "app": "drumtoy", "cancels": 5, "cancels_id": R.record_id(log[4]),
            "requested_at": T4})
    head = signed({"v": 1, "kind": "popsnip.head", "seq": 6, "head_hash": R.record_id(log[5]), "at": T4,
                   "kid": "launch-test1"}, "launch")
    transfer = {"v": 1, "kind": "popsnip.rekey", "app": "drumtoy", "from_key": pub("dev2"), "to_key": pub("dev4"),
                "from_account": "acct_TEST0001", "to_account": "acct_TEST0002", "path": "old_key", "requested_at": T3,
                "effective_at": T3_7, "challenge": sign_release.b64u(hashlib.sha256(b"challenge-3").digest()),
                "seq": 7, "prev": R.record_id(log[5]), "kid": "launch-test1"}
    transfer["old_key_sig"] = sign_release.b64u(sign_release.sign(seed("dev2"), R.signed_message(R.rekey_request(transfer))))
    transfer = signed(transfer, "launch")
    revs = signed({"v": 1, "kind": "popsnip.revocations", "seq": 1, "prev": R.GENESIS, "at": T4, "kid": "launch-test1",
                   "entries": [
                       {"n": 1, "target": {"release": R.record_id(rel2)}, "action": "revoke", "ground": "malware",
                        "at": T2, "by": "owner", "notice": NOTICE + "2026-0001"},
                       {"n": 2, "target": {"release": R.record_id(rel2)}, "action": "reinstate", "ground": "malware",
                        "at": T3, "by": "owner", "notice": NOTICE + "2026-0001"},
                       {"n": 3, "target": {"dev_key": pub("dev2")}, "action": "revoke", "ground": "key_compromise",
                        "at": T4, "by": "delegate", "notice": NOTICE + "2026-0002", "after_seq": 3},
                       {"n": 4, "target": {"app": "drumtoy"}, "action": "revoke",
                        "ground": "withdrawn_by_developer", "at": T4, "by": "developer", "notice": NOTICE + "2026-0003"},
                   ]}, "launch")
    revoked = signed({"v": 1, "kind": "popsnip.launch-key-revoked", "kid": "launch-test1", "after_seq": 5, "at": T4},
                     "release")
    reaffirm = signed({"v": 1, "kind": "popsnip.reaffirm", "kid": "launch-test1",
                       "reaffirmed": [{"seq": 6, "id": R.record_id(log[5])}], "at": T4}, "release")
    proof = signed({"v": 1, "kind": "popsnip.key-proof", "account": "acct_TEST0001", "dev_key": pub("dev"),
                    "challenge": sign_release.b64u(hashlib.sha256(b"challenge-0").digest())}, "dev")

    valid = [("launch-key certificate", cert, "release"), ("release v1", rel1, "dev"), ("release v2", rel2, "dev")]
    valid += [("log %d %s" % (e["seq"], e["kind"]), e, "launch") for e in log]
    valid += [("head", head, "launch"), ("transfer", transfer, "launch"), ("revocations", revs, "launch"),
              ("launch key revoked", revoked, "release"), ("reaffirm", reaffirm, "release"), ("key proof", proof, "dev")]

    # the rekey requests are records too: no signature of their own (theirs is the rotation's old_key_sig)
    valid += [("rekey request for seq 4", R.rekey_request(log[3]), None),
              ("rekey request for the transfer", R.rekey_request(transfer), None)]

    records = []
    for name, rec, role in valid:
        R.check(rec)
        records.append({"name": name, "record": rec, "error": None, "canonical": R.canonical(rec).decode("ascii"),
                        "id": R.record_id(rec), "signed_by": role})

    launch, rk_old, rk_acct, cancel = log[0], log[3], log[4], log[5]

    def bad(name: str, base: Dict[str, Any], error: str, signed_: bool = True, **changes: Any) -> None:
        rec = copy.deepcopy(base)
        for k, v in changes.items():
            k = k.rstrip("_")
            if v is DROP:
                rec.pop(k, None)
            else:
                rec[k] = v
        vec = {"name": name, "record": rec, "error": error}
        if not signed_:
            vec["signed"] = False                 # check(record, signed=False): a record about to be signed
        records.append(vec)

    DROP = object()
    bad("an app name with a capital", launch, "bad_field:app", app="Drumtoy")
    bad("an app name with two hyphens", launch, "bad_field:app", app="drum--toy")
    bad("an app name too short", launch, "bad_field:app", app="dt")
    bad("pass_active false", launch, "bad_field:pass_active", pass_active=False)
    bad("pass_active 1, not true", launch, "bad_field:pass_active", pass_active=1)
    bad("an unknown pass kind", launch, "bad_field:pass_kind", pass_kind="lifetime")
    bad("release0 missing", launch, "missing_field:release0", release0=DROP)
    bad("the signature missing", launch, "missing_field:signature", signature=DROP)
    bad("a field no launch has", launch, "unknown_field:note", note="hi")
    bad("an unknown field wins over a bad one", launch, "unknown_field:zzz", app="BAD", zzz=1)
    bad("bad fields are tried in sorted order", launch, "bad_field:account", app="BAD", account="acct_x")
    bad("v 2", launch, "bad_version", v=2)
    bad("v true", launch, "bad_version", v=True)
    bad("v missing", launch, "bad_version", v=DROP)
    bad("an unknown kind", launch, "unknown_kind", kind="popsnip.lunch")
    bad("no kind", launch, "unknown_kind", kind=DROP)
    bad("seq 1 with a prev that isn't genesis", launch, "rule:genesis", prev=R.record_id(rel1))
    bad("seq 2 with the genesis prev", launch, "rule:genesis", seq=2)
    bad("seq 0", launch, "bad_field:seq", seq=0)
    bad("seq past 2**53 - 1", launch, "bad_number", seq=2 ** 53)
    bad("prev in capitals", launch, "bad_field:prev", prev=R.record_id(rel1).upper())
    bad("prev null in a chain", launch, "bad_field:prev", prev=None)
    bad("30 February", launch, "bad_field:launched_at", launched_at="2026-02-30T00:00:00Z")
    bad("hour 24", launch, "bad_field:launched_at", launched_at="2026-11-16T24:00:00Z")
    bad("a space for T", launch, "bad_field:launched_at", launched_at="2026-11-16 12:00:00Z")
    bad("fractional seconds", launch, "bad_field:launched_at", launched_at="2026-11-16T12:00:00.5Z")
    bad("an offset", launch, "bad_field:launched_at", launched_at="2026-11-16T12:00:00+00:00")
    bad("before 1970", launch, "bad_field:launched_at", launched_at="1969-12-31T23:59:59Z")
    bad("29 February in a leap year is a day", launch, "rule:genesis", launched_at="2028-02-29T00:00:00Z", seq=3)
    bad("an account too short", launch, "bad_field:account", account="acct_short")
    bad("a key with padding", launch, "bad_field:dev_key", dev_key=pub("dev") + "=")
    bad("a key in standard base64's alphabet", launch, "bad_field:dev_key", dev_key="+" + pub("dev")[1:])
    last = pub("dev")[-1]
    other = next(c for c in "BCDEFGHIJKLMNOPQRSTUVWXYZ" if (sign_release_b64_index(c) & 3) and c != last)
    bad("a key whose unused low bits are set", launch, "bad_field:dev_key", dev_key=pub("dev")[:-1] + other)
    bad("a key one character short", launch, "bad_field:dev_key", dev_key=pub("dev")[:-1])
    bad("a signature one character short", launch, "bad_field:signature", signature=launch["signature"][:-1])
    bad("a kid in capitals", launch, "bad_field:kid", kid="Launch-test1")
    bad("a non-ASCII letter", launch, "not_ascii", app="drümtoy")
    bad("DEL in a string", launch, "not_ascii", account="acct_TEST\x7f0001")
    bad("a tab in a string", launch, "not_ascii", account="acct_TEST\t0001")
    bad("a non-ASCII key", launch, "not_ascii", **{"é": 1})
    bad("non-ASCII beats an unknown kind", launch, "not_ascii", kind="popsnip.läunch")

    bad("version 1 with a prev", rel1, "rule:first_release", prev=R.record_id(rel2))
    bad("version 2 with no prev", rel2, "rule:first_release", prev=None)
    bad("version 0", rel1, "bad_field:version", version=0)
    bad("a parent folder in a path", rel1, "bad_field:files", files={"../x.js": files1["app.js"]})
    bad("an absolute path", rel1, "bad_field:files", files={"/app.js": files1["app.js"]})
    bad("a dot file", rel1, "bad_field:files", files={".htaccess": files1["app.js"]})
    bad("a space in a path", rel1, "bad_field:files", files={"a b.js": files1["app.js"]})
    bad("an empty segment", rel1, "bad_field:files", files={"a//b.js": files1["app.js"]})
    bad("a backslash", rel1, "bad_field:files", files={"a\\b.js": files1["app.js"]})
    bad("two names that differ only in case", rel1, "bad_field:files",
        files={"App.js": files1["app.js"], "app.js": files1["app.js"]})
    bad("a name that is also a folder", rel1, "bad_field:files",
        files={"sounds": files1["app.js"], "sounds/kick.ogg": files1["app.js"]})
    bad("a name that is also a folder, in another case", rel1, "bad_field:files",
        files={"Sounds": files1["app.js"], "sounds/kick.ogg": files1["app.js"]})
    bad("no files", rel1, "bad_field:files", files={})
    bad("a file hash in capitals", rel1, "bad_field:files", files={"app.js": files1["app.js"].upper()})
    bad("permissions out of order", rel1, "bad_field:permissions", permissions=["midi", "audio-in"])
    bad("a permission twice", rel1, "bad_field:permissions", permissions=["midi", "midi"])
    bad("a permission in capitals", rel1, "bad_field:permissions", permissions=["Midi"])
    bad("an empty csp", rel2, "bad_field:csp", csp="")
    bad("a launch's field on a release", rel1, "unknown_field:pass_kind", pass_kind="standard")

    bad("old_key without old_key_sig", rk_old, "rule:old_key_sig", old_key_sig=DROP)
    bad("account_only with old_key_sig", rk_acct, "rule:old_key_sig", old_key_sig=rk_old["old_key_sig"])
    bad("account_only taking effect at once", rk_acct, "rule:delay", effective_at=T3)
    bad("account_only a second short of 7 days", rk_acct, "rule:delay", effective_at="2026-11-25T08:59:59Z")
    bad("old_key on one account with a delay", rk_old, "rule:delay", effective_at="2026-11-24T09:00:00Z")
    bad("a transfer taking effect at once", transfer, "rule:delay", effective_at=T3)
    bad("rotating to the same key", rk_old, "rule:same_key", to_key=pub("dev"))
    bad("an unknown path", rk_old, "bad_field:path", path="email")
    bad("a cancel naming itself", cancel, "rule:cancels", cancels=6)
    bad("a cancel naming a later entry", cancel, "rule:cancels", cancels=9)
    bad("a certificate that ends before it starts", cert, "rule:window", not_after="2026-11-15T00:00:00Z")
    bad("a certificate that ends as it starts", cert, "rule:window", not_after="2026-11-16T00:00:00Z")

    e = copy.deepcopy(revs["entries"])
    bad("revocation entries out of number", revs, "bad_field:entries", entries=[e[1]])
    bad("a developer revoking for malware", revs, "bad_field:entries", entries=[dict(e[0], by="developer")])
    bad("the owner withdrawing for a developer", revs, "bad_field:entries", entries=[dict(e[3], n=1, by="owner")])
    bad("a notice off popboll.com", revs, "bad_field:entries", entries=[dict(e[0], notice="http://popboll.com/dev/notices/x")])
    bad("a target naming two things", revs, "bad_field:entries",
        entries=[dict(e[0], target={"app": "drumtoy", "release": R.record_id(rel2)})])
    bad("an unknown ground", revs, "bad_field:entries", entries=[dict(e[0], ground="lapsed")])
    bad("an entry with a stray field", revs, "bad_field:entries", entries=[dict(e[0], note="x")])
    bad("a negative after_seq", revs, "bad_field:entries", entries=[dict(e[2], n=1, after_seq=-1)])
    bad("an empty list is a list", revs, None, entries=[])
    bad("reaffirmed out of order", reaffirm, "bad_field:reaffirmed",
        reaffirmed=[{"seq": 6, "id": R.record_id(log[5])}, {"seq": 5, "id": R.record_id(log[4])}])
    bad("nothing reaffirmed", reaffirm, "bad_field:reaffirmed", reaffirmed=[])
    bad("unsigned: a launch about to be signed", launch, None, False, signature=DROP)
    bad("unsigned: a release about to be signed", rel1, None, False, signature=DROP)
    bad("unsigned: a signature already there", launch, "unknown_field:signature", False)
    bad("unsigned: the kid is still required", launch, "missing_field:kid", False, signature=DROP, kid=DROP)
    bad("unsigned: the shape still counts", launch, "bad_field:app", False, signature=DROP, app="Bad")
    bad("signed: no signature", launch, "missing_field:signature", True, signature=DROP)
    nul = {"name": "signed: null is signed (only false is unsigned)", "record": {k: v for k, v in launch.items()
                                                                            if k != "signature"},
           "signed": None, "error": "missing_field:signature"}
    records.append(nul)
    req = R.rekey_request(log[3])
    bad("a rekey request for an account_only rotation", req, "rule:request_path", path="account_only")
    bad("a rekey request to the same key", req, "rule:same_key", to_key=req["from_key"])
    bad("a rekey request with a signature", req, "unknown_field:signature", signature=log[3]["signature"])
    # public keys that cannot sign: small order, non-canonical, off the curve
    for i, h in enumerate(small_order()):
        so = sign_release.b64u(bytes.fromhex(h))
        bad("a small-order developer key (%d of 8)" % (i + 1), launch, "bad_field:dev_key", dev_key=so)
    so0 = sign_release.b64u(bytes.fromhex(small_order()[2]))           # the identity
    bad("a key proof for the identity point", proof, "bad_field:dev_key", dev_key=so0)
    bad("a certificate for the identity point", cert, "bad_field:pub", pub=so0)
    bad("a rotation to the identity point", rk_old, "bad_field:to_key", to_key=so0)
    bad("a revocation naming the identity point", revs, "bad_field:entries",
        entries=[dict(revs["entries"][2], n=1, target={"dev_key": so0})])
    P_ = E._P
    for name, y in (("y = p", P_), ("y = p + 1", P_ + 1), ("y = p + 18", P_ + 18)):
        bad("a non-canonical key (%s)" % name, launch, "bad_field:dev_key",
            dev_key=sign_release.b64u(y.to_bytes(32, "little")))
    bad("x = 0 with the sign bit set", launch, "bad_field:dev_key",
        dev_key=sign_release.b64u(bytes.fromhex("01" + "00" * 30 + "80")))
    bad("a key off the curve", launch, "bad_field:dev_key", dev_key=off_curve())
    bad("a challenge of zero bytes is only bytes", proof, None, challenge=sign_release.b64u(bytes(32)))
    records.append({"name": "a list is not a record", "record": [launch], "error": "not_object"})
    records.append({"name": "a string is not a record", "record": "popsnip.launch", "error": "not_object"})

    texts = [
        # text, parse error, canonical text or canonical error (written by hand: these are the rules)
        ('{"b":1,"a":{"d":[3,{"c":"x"}],"c":null}}', None, '{"a":{"c":null,"d":[3,{"c":"x"}]},"b":1}', None),
        (' {\n\t"a" : true ,\r\n "b":false}\n', None, '{"a":true,"b":false}', None),
        ('{"a":"q\\"b\\\\c/d"}', None, '{"a":"q\\"b\\\\c/d"}', None),
        ('{"a":"\\/\\u0041"}', None, '{"a":"/A"}', None),
        ('{"__proto__":1,"constructor":2}', None, '{"__proto__":1,"constructor":2}', None),
        ('{"a":-0}', None, '{"a":0}', None),
        ('{"a":9007199254740991,"b":-9007199254740991}', None, '{"a":9007199254740991,"b":-9007199254740991}', None),
        ('{"a":9007199254740992}', None, None, "bad_number"),
        ('{"a":90071992547409930000}', None, None, "bad_number"),
        ('{"a":"\\u007f"}', None, None, "not_ascii"),
        ('{"a":"\\u00e9"}', None, None, "not_ascii"),
        ('{"a":"\\ud83d\\ude00"}', None, None, "not_ascii"),
        ('{"a":"\\n"}', None, None, "not_ascii"),
        ('{"a":"é"}', None, None, "not_ascii"),
        ('{"signature":"é","a":1}', None, '{"a":1}', None),
        ('{"a":1,"a":2}', "duplicate_key", None, None),
        ('{"a":{"b":1,"b":2},"a":3}', "duplicate_key", None, None),
        ('{"a":1,"a":1.5}', "bad_number", None, None),
        ('{"a":1.0}', "bad_number", None, None),
        ('{"a":1e3}', "bad_number", None, None),
        ('{"a":1E+2}', "bad_number", None, None),
        ('{"a":NaN}', "bad_json", None, None),
        ('{"a":Infinity}', "bad_json", None, None),
        ('{"a":-Infinity}', "bad_json", None, None),
        ('{"a":01}', "bad_json", None, None),
        ('{"a":.5}', "bad_json", None, None),
        ('{"a":+1}', "bad_json", None, None),
        ('{"a":1.}', "bad_json", None, None),
        ('{"a":-}', "bad_json", None, None),
        ('{"a":1,}', "bad_json", None, None),
        ('{"a" 1}', "bad_json", None, None),
        ("{'a':1}", "bad_json", None, None),
        ('{"a":tru}', "bad_json", None, None),
        ('{"a":"\x01"}', "bad_json", None, None),
        ('{"a":"\\x41"}', "bad_json", None, None),
        ('{"a":"\\u12"}', "bad_json", None, None),
        ('{"a":"open}', "bad_json", None, None),
        ('﻿{}', "bad_json", None, None),
        ('{} {}', "bad_json", None, None),
        ('{} ', "bad_json", None, None),
        ('', "bad_json", None, None),
        ('{', "bad_json", None, None),
        ('[1]', "not_object", None, None),
        ('"x"', "not_object", None, None),
        ('1', "not_object", None, None),
        ('null', "not_object", None, None),
        ('{"a":' * 31 + '{}' + '}' * 31, None, '{"a":' * 31 + '{}' + '}' * 31, None),
        ('{"a":' * 32 + '{}' + '}' * 32, "bad_json", None, None),
        ('{"a":[' + '[' * 30 + ']' * 30 + ']}', None, '{"a":[' + '[' * 30 + ']' * 30 + ']}', None),
        ('{"a":[' + '[' * 31 + ']' * 31 + ']}', "bad_json", None, None),
        # depth is counted first, over the text: deep nesting is bad_json whatever it holds
        ('{"a":' + '[' * 500 + ']' * 500 + '}', "bad_json", None, None),
        ('{"a":' + '[' * 40 + '{"b":1,"b":2}' + ']' * 40 + '}', "bad_json", None, None),
        ('{"a":' + '[' * 40 + '1.5' + ']' * 40 + '}', "bad_json", None, None),
        ('{"a":' + '[' * 600 + '"x' + '}', "bad_json", None, None),
        ('{"b":1,"b":2,"a":' + '[' * 40 + ']' * 40 + '}', "bad_json", None, None),
        # brackets inside a string never count, an escaped quote does not end it
        ('{"a":"' + '[' * 40 + '"}', None, '{"a":"' + '[' * 40 + '"}', None),
        ('{"a":"\\"' + '{' * 40 + '"}', None, '{"a":"\\"' + '{' * 40 + '"}', None),
        ('{"a":"\\\\","b":' + '[' * 32 + ']' * 32 + '}', "bad_json", None, None),
        (']]]]]]{}', "bad_json", None, None),
        # integer literals past 2**53 - 1 are read, then refused as bad_number, however long
        ('{"a":' + '1' * 5000 + '}', None, None, "bad_number"),
        ('{"a":-' + '9' * 400 + '}', None, None, "bad_number"),
        ('{"a":12345678901234567}', None, None, "bad_number"),
        ('{"a":-9007199254740992}', None, None, "bad_number"),
        ('{"a":0' + '0' * 20 + '}', "bad_json", None, None),
    ]
    text_vectors = []
    for text, perr, canon, cerr in texts:
        got_err, got = None, None
        try:
            value = R.parse(text)
        except R.RecordError as exc:
            got_err = exc.code
        assert got_err == perr, (text, got_err, perr)
        if perr is None:
            try:
                got = R.canonical(value).decode("ascii")
                assert cerr is None and got == canon, (text, got, canon)
            except R.RecordError as exc:
                assert exc.code == cerr, (text, exc.code, cerr)
        text_vectors.append({"text": text, "parse_error": perr, "canonical": canon, "canonical_error": cerr})

    for v in records:
        if "canonical" in v:
            continue
        try:
            R.check(v["record"], v.get("signed", True))
            got = None
        except R.RecordError as exc:
            got = exc.code
        assert got == v["error"], (v["name"], got, v["error"])

    return {
        "about": ("Vectors for Pop Snip records, written by tools/popsnip_vectors.py. Both twins give these answers: "
                  "check(record, signed) refuses with `error` or accepts (`signed` is true unless a vector says false); "
                  "canonical() of an accepted record is `canonical` and "
                  "record_id() is `id`; parse() of a text refuses with `parse_error` or gives a value whose canonical() "
                  "is `canonical` or refuses with `canonical_error`. Signatures are Ed25519 over CONTEXT + canonical by "
                  "the TEST keys below (seeds printed: never use them for anything real)."),
        "context": R.CONTEXT.decode("ascii"),
        "small_order": small_order(),
        "genesis": R.GENESIS,
        "keys": KEYS,
        "records": records,
        "texts": text_vectors,
        "rekey_requests": [
            {"entry_seq": 4, "request": R.rekey_request(rk_old),
             "canonical": R.canonical(R.rekey_request(rk_old)).decode("ascii"), "signed_by": "dev"},
            {"entry_seq": 7, "request": R.rekey_request(transfer),
             "canonical": R.canonical(R.rekey_request(transfer)).decode("ascii"), "signed_by": "dev2"},
        ],
    }


def sign_release_b64_index(c: str) -> int:
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".index(c)


def main(argv: List[str]) -> int:
    text = json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=True) + "\n"
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="ascii") != text:
            print("%s differs from what %s makes" % (OUT.relative_to(ROOT), Path(__file__).name), file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="ascii")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
