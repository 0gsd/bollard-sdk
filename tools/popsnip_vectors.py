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
OUT_ACCEPT = ROOT / "conformance" / "popsnip" / "accept.json"


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
    rev_entries = [
        {"n": 1, "target": {"release": R.record_id(rel2)}, "action": "revoke", "ground": "malware",
         "at": T2, "by": "owner", "notice": NOTICE + "2026-0001"},
        {"n": 2, "target": {"release": R.record_id(rel2)}, "action": "reinstate", "ground": "malware",
         "at": T3, "by": "owner", "notice": NOTICE + "2026-0001"},
        {"n": 3, "target": {"dev_key": pub("dev2")}, "action": "revoke", "ground": "key_compromise",
         "at": T4, "by": "delegate", "notice": NOTICE + "2026-0002", "after_seq": 3},
        {"n": 4, "target": {"app": "drumtoy"}, "action": "revoke",
         "ground": "withdrawn_by_developer", "at": T4, "by": "developer", "notice": NOTICE + "2026-0003"},
    ]
    page0 = R.paginate(rev_entries)[0]                     # format B: the entries live in pages the index names
    revs = signed({"v": 1, "kind": "popsnip.revocations", "seq": 1, "prev": R.GENESIS, "at": T4, "kid": "launch-test1",
                   "count": 4, "page_size": R.PAGE_SIZE, "pages": [R.record_id(page0)]}, "launch")
    revoked = signed({"v": 1, "kind": "popsnip.launch-key-revoked", "kid": "launch-test1", "after_seq": 5, "at": T4},
                     "release")
    reaffirm = signed({"v": 1, "kind": "popsnip.reaffirm", "kid": "launch-test1",
                       "reaffirmed": [{"seq": 6, "id": R.record_id(log[5])}], "at": T4}, "release")
    proof = signed({"v": 1, "kind": "popsnip.key-proof", "account": "acct_TEST0001", "dev_key": pub("dev"),
                    "challenge": sign_release.b64u(hashlib.sha256(b"challenge-0").digest())}, "dev")

    valid = [("launch-key certificate", cert, "release"), ("release v1", rel1, "dev"), ("release v2", rel2, "dev")]
    valid += [("log %d %s" % (e["seq"], e["kind"]), e, "launch") for e in log]
    valid += [("head", head, "launch"), ("transfer", transfer, "launch"), ("revocations", revs, "launch"),
              ("revocation page 0", page0, None),
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

    e = copy.deepcopy(rev_entries)
    bad("revocation entries with a gap", page0, "bad_field:entries", entries=[e[0], e[2]])
    bad("page 0 starting at entry 2", page0, "rule:page_numbers", entries=[e[1]])
    bad("page 1 starting at entry 1", page0, "rule:page_numbers", page=1)
    bad("a developer revoking for malware", page0, "bad_field:entries", entries=[dict(e[0], by="developer")])
    bad("the owner withdrawing for a developer", page0, "bad_field:entries", entries=[dict(e[3], n=1, by="owner")])
    bad("a notice off popboll.com", page0, "bad_field:entries", entries=[dict(e[0], notice="http://popboll.com/dev/notices/x")])
    bad("a target naming two things", page0, "bad_field:entries",
        entries=[dict(e[0], target={"app": "drumtoy", "release": R.record_id(rel2)})])
    bad("an unknown ground", page0, "bad_field:entries", entries=[dict(e[0], ground="lapsed")])
    bad("an entry with a stray field", page0, "bad_field:entries", entries=[dict(e[0], note="x")])
    bad("a negative after_seq", page0, "bad_field:entries", entries=[dict(e[2], n=1, after_seq=-1)])
    bad("an empty page", page0, "bad_field:entries", entries=[])
    bad("a page of 257 entries", page0, "bad_field:entries",
        entries=[dict(e[0], n=i) for i in range(1, R.PAGE_SIZE + 2)])
    bad("a page past the last there can be", page0, "bad_field:page", page=R.MAX_PAGES)
    bad("a page with a signature", page0, "unknown_field:signature", signature=revs["signature"])
    bad("an empty list is a list", revs, None, count=0, pages=[])
    bad("a list of another page size", revs, "bad_field:page_size", page_size=128)
    bad("a list naming too few pages", revs, "rule:pages", count=R.PAGE_SIZE + 1)
    bad("a list naming a page it does not need", revs, "rule:pages", count=0)
    bad("a page id in capitals", revs, "bad_field:pages", pages=[R.record_id(page0).upper()])
    bad("a list longer than the form allows", revs, "bad_field:count", count=R.MAX_REVOCATIONS + 1)
    bad("a list still carrying entries", revs, "unknown_field:entries", entries=rev_entries)
    resigned = signed(dict(revs, seq=2, prev=R.record_id(revs), resigned_after="launch-old"), "launch")
    records.append({"name": "a list re-signed after its key was revoked", "record": resigned, "error": None,
                    "canonical": R.canonical(resigned).decode("ascii"), "id": R.record_id(resigned),
                    "signed_by": "launch"})
    bad("a key re-signing its own list", resigned, "rule:resigned_after", resigned_after="launch-test1")
    bad("resigned_after not a kid", resigned, "bad_field:resigned_after", resigned_after="Launch Old")
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
    bad("a revocation naming the identity point", page0, "bad_field:entries",
        entries=[dict(page0["entries"][2], n=1, target={"dev_key": so0})])
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
        "page_size": R.PAGE_SIZE,
        "lists": lists(),
        "states": states(),
        "rekey_requests": [
            {"entry_seq": 4, "request": R.rekey_request(rk_old),
             "canonical": R.canonical(R.rekey_request(rk_old)).decode("ascii"), "signed_by": "dev"},
            {"entry_seq": 7, "request": R.rekey_request(transfer),
             "canonical": R.canonical(R.rekey_request(transfer)).decode("ascii"), "signed_by": "dev2"},
        ],
    }


def sign_release_b64_index(c: str) -> int:
    return "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".index(c)


def states() -> Dict[str, Any]:
    """An app's account and key at a log position (the key walk): a change
    counts for an entry only if the change's seq is lower than the entry's and its effective_at is not after the
    entry's time; changes take effect in the order of effective_at, then seq; a change whose from_key (or from_account)
    is not current when it takes effect changes nothing; a cancel counts only when logged before effective_at. `seq`
    null asks about the log's end. The answers are written by hand, not computed, so they check any walk."""
    log: List[Dict[str, Any]] = []
    k1, k2, k3, acct = pub("dev"), pub("dev2"), pub("dev3"), "acct_TEST0001"
    A, B, C, C7, D = ("2026-11-17T09:00:00Z", "2026-11-18T09:00:00Z", "2026-11-19T09:00:00Z", "2026-11-26T09:00:00Z",
                      "2026-11-20T09:00:00Z")

    def append(entry: Dict[str, Any]) -> Dict[str, Any]:
        entry = dict(entry, v=1, seq=len(log) + 1, prev=R.record_id(log[-1]) if log else R.GENESIS, kid="launch-test1")
        if entry.get("path") == "old_key":
            entry["old_key_sig"] = sign_release.b64u(sign_release.sign(
                seed({k1: "dev", k2: "dev2", k3: "dev3"}[entry["from_key"]]), R.signed_message(R.rekey_request(entry))))
        log.append(signed(entry, "launch"))
        return log[-1]

    def nonce(text: str) -> str:
        return sign_release.b64u(hashlib.sha256(text.encode("ascii")).digest())

    def rekey(app: str, frm: str, to: str, path: str, at: str, eff: str, c: str) -> Dict[str, Any]:
        return {"kind": "popsnip.rekey", "app": app, "from_key": frm, "to_key": to, "from_account": acct,
                "to_account": acct, "path": path, "requested_at": at, "effective_at": eff, "challenge": nonce(c)}
    append({"kind": "popsnip.launch", "app": "drumtoy", "account": acct, "dev_key": k1, "release0": "a" * 64,
            "launched_at": A, "pass_active": True, "pass_kind": "standard"})
    append({"kind": "popsnip.publish", "app": "drumtoy", "version": 1, "manifest": "a" * 64, "dev_key": k1,
            "published_at": A})
    append({"kind": "popsnip.publish", "app": "drumtoy", "version": 2, "manifest": "b" * 64, "dev_key": k1,
            "published_at": B})                                            # seq 3: K1's, in the same second as ...
    append(rekey("drumtoy", k1, k2, "old_key", B, B, "state-1"))           # seq 4: ... the rotation to K2
    append({"kind": "popsnip.launch", "app": "beattoy", "account": acct, "dev_key": k1, "release0": "c" * 64,
            "launched_at": B, "pass_active": True, "pass_kind": "standard"})
    append(rekey("beattoy", k1, k2, "account_only", C, C7, "state-2"))     # seq 6: K1 -> K2, in seven days
    append(rekey("beattoy", k1, k3, "old_key", D, D, "state-3"))           # seq 7: K1 -> K3, at once (a signed log the
                                                                           # service never writes, but a device reads)
    q = [("a release logged in the same second as a rotation is the old key's", "drumtoy", B, 3, k1),
         ("the entry after the rotation is the new key's", "drumtoy", B, 5, k2),
         ("at the log's end", "drumtoy", B, None, k2),
         ("before anything changed", "drumtoy", A, 2, k1),
         ("the change at once took effect first", "beattoy", D, 8, k3),
         ("the week-old change finds K3 current and changes nothing", "beattoy", C7, None, k3),
         ("while the week runs, K1 still", "beattoy", C, 7, k1),
         ("a bound below the later change leaves it out (not yet in effect)", "beattoy", "2026-11-25T09:00:00Z", 7, k1),
         ("a bound below the later change leaves it out (now in effect)", "beattoy", "2026-11-27T00:00:00Z", 7, k2)]
    return {"entries": log,
            "queries": [{"name": n, "app": app, "at": at, "seq": seq, "account": acct, "key": key}
                        for n, app, at, seq, key in q]}


def lists() -> Dict[str, Any]:
    """Whole revocation lists for check_list (both twins). Each page and index is written once, under a name; a case
    names its index and its pages (a name list, or something that is not a list) and gives the answer."""
    def entry(n: int) -> Dict[str, Any]:
        return {"n": n, "target": {"release": hashlib.sha256(b"release %d" % n).hexdigest()}, "action": "revoke",
                "ground": "malware", "at": T4, "by": "owner", "notice": NOTICE + "r%d" % n}

    def index(count: int, pages: List[Dict[str, Any]], seq: int = 2) -> Dict[str, Any]:
        return signed({"v": 1, "kind": "popsnip.revocations", "seq": seq,
                       "prev": R.GENESIS if seq == 1 else hashlib.sha256(b"list %d" % (seq - 1)).hexdigest(),
                       "at": T4, "kid": "launch-test1", "count": count, "page_size": R.PAGE_SIZE,
                       "pages": [R.record_id(p) for p in pages]}, "launch")
    entries = [entry(n) for n in range(1, R.PAGE_SIZE + 2)]                 # 257: one full page and one entry more
    p0, p1 = R.paginate(entries)
    short0 = {"v": 1, "kind": "popsnip.revocation-page", "page": 0, "entries": entries[:1]}   # a page, but not full
    late1 = {"v": 1, "kind": "popsnip.revocation-page", "page": 1, "entries": [entry(R.PAGE_SIZE + 1), entry(R.PAGE_SIZE + 2)]}
    tampered = copy.deepcopy(p1)
    tampered["entries"][0]["ground"] = "fraud"
    more = entries + [entry(R.PAGE_SIZE + 2)]
    p1b = R.paginate(more)[1]                                            # page 1, one entry longer
    rewritten0 = copy.deepcopy(p0)
    rewritten0["entries"][0]["ground"] = "fraud"                          # entry 1 rewritten, re-signed
    pages = {"p0": p0, "p1": p1, "short0": short0, "late1": late1, "tampered1": tampered, "p1b": p1b,
             "rewritten0": rewritten0}
    indexes = {"good": index(len(entries), [p0, p1]), "empty": index(0, [], seq=1),
               "short_first": index(R.PAGE_SIZE + 1, [short0, late1]), "overcount": index(R.PAGE_SIZE + 2, [p0, p1]),
               "longer": index(len(more), [p0, p1b], seq=3), "same_later": index(len(entries), [p0, p1], seq=3),
               "rewritten": index(len(entries), [rewritten0, p1], seq=3),
               "shorter": index(R.PAGE_SIZE, [p0], seq=3)}
    cases = [
        {"name": "two pages, the last short", "index": "good", "pages": ["p0", "p1"], "error": None, "count": 257},
        {"name": "an empty list", "index": "empty", "pages": [], "error": None, "count": 0},
        {"name": "the pages swapped", "index": "good", "pages": ["p1", "p0"], "error": "rule:list"},
        {"name": "a page missing", "index": "good", "pages": ["p0"], "error": "rule:list"},
        {"name": "a page changed after signing", "index": "good", "pages": ["p0", "tampered1"], "error": "rule:list"},
        {"name": "a short page that is not the last", "index": "short_first", "pages": ["short0", "late1"],
         "error": "rule:list"},
        {"name": "a count the pages do not hold", "index": "overcount", "pages": ["p0", "p1"], "error": "rule:list"},
        {"name": "pages that are not a list", "index": "good", "pages": "p0", "error": "rule:list"},
    ]
    # check_extends: (old index, its pages) then (new index, its pages); the held list is "good" (seq 2, 257 entries)
    extensions = [
        {"name": "one entry more, the full page the same", "old": ["good", ["p0", "p1"]],
         "new": ["longer", ["p0", "p1b"]], "error": None},
        {"name": "the same entries, a later seq", "old": ["good", ["p0", "p1"]],
         "new": ["same_later", ["p0", "p1"]], "error": None},
        {"name": "from nothing", "old": ["empty", []], "new": ["good", ["p0", "p1"]], "error": None},
        {"name": "an entry rewritten", "old": ["good", ["p0", "p1"]], "new": ["rewritten", ["rewritten0", "p1"]],
         "error": "rule:extends"},
        {"name": "fewer entries", "old": ["good", ["p0", "p1"]], "new": ["shorter", ["p0"]], "error": "rule:extends"},
        {"name": "the same seq again", "old": ["good", ["p0", "p1"]], "new": ["good", ["p0", "p1"]],
         "error": "rule:extends"},
        {"name": "an older list", "old": ["longer", ["p0", "p1b"]], "new": ["good", ["p0", "p1"]],
         "error": "rule:extends"},
    ]
    return {"pages": pages, "indexes": indexes, "cases": cases, "extensions": extensions}


def acceptance() -> Dict[str, Any]:
    """The device check's vectors (accept()): one signed history, a few signed variants of it, the releases and
    their files, root records and revocation lists, and cases naming which of each to pass and the expected code."""
    A, B, C, D, E = ("2026-11-17T09:00:00Z", "2026-11-17T10:00:00Z", "2026-11-18T09:00:00Z", "2026-11-19T09:00:00Z",
                     "2026-11-20T09:00:00Z")
    acct, k1, k2 = "acct_TEST0001", pub("dev"), pub("dev2")
    cert = signed({"v": 1, "kind": "popsnip.launch-key", "kid": "launch-test1", "pub": pub("launch"),
                   "not_before": "2026-11-16T00:00:00Z", "not_after": "2027-12-21T00:00:00Z"}, "release")
    cert2 = signed({"v": 1, "kind": "popsnip.launch-key", "kid": "launch-test2", "pub": pub("dev3"),
                    "not_before": "2026-11-16T00:00:00Z", "not_after": "2027-12-21T00:00:00Z"}, "release")
    texts = {"r1": {"index.html": "<!doctype html>v1", "app.js": "v1"},
             "r2": {"index.html": "<!doctype html>v2", "app.js": "v2"},
             "r3": {"index.html": "<!doctype html>v3", "app.js": "v3"}}

    def rel(name: str, version: int, prev: Optional[str], role: str) -> Dict[str, Any]:
        return signed({"v": 1, "kind": "popsnip.release", "app": "drumtoy", "version": version, "prev": prev,
                       "files": {p: file_hash(t) for p, t in texts[name].items()}, "permissions": ["midi"],
                       "dev_key": pub(role)}, role)
    r1 = rel("r1", 1, None, "dev")
    r2 = rel("r2", 2, R.record_id(r1), "dev")
    r3 = rel("r3", 3, R.record_id(r2), "dev2")
    r3_old = rel("r3", 3, R.record_id(r2), "dev")                       # v3, but by the key rotated away
    r1_badsig = dict(r1, signature=r2["signature"])                      # r1's body, another signature

    def chain(bodies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for b in bodies:
            e = dict(b, v=1, seq=len(out) + 1, prev=R.record_id(out[-1]) if out else R.GENESIS, kid="launch-test1")
            if e.get("path") == "old_key" and "old_key_sig" not in e:
                role = {k1: "dev", k2: "dev2"}[e["from_key"]]
                e["old_key_sig"] = sign_release.b64u(sign_release.sign(seed(role), R.signed_message(R.rekey_request(e))))
            out.append(signed(e, "launch"))
        return out

    def head(log: List[Dict[str, Any]], at: str) -> Dict[str, Any]:
        return signed({"v": 1, "kind": "popsnip.head", "seq": len(log), "head_hash": R.record_id(log[-1]), "at": at,
                       "kid": "launch-test1"}, "launch")

    def publish(r: Dict[str, Any], at: str) -> Dict[str, Any]:
        return {"kind": "popsnip.publish", "app": "drumtoy", "version": r["version"], "manifest": R.record_id(r),
                "dev_key": r["dev_key"], "published_at": at}
    nonce = lambda t: sign_release.b64u(hashlib.sha256(t.encode("ascii")).digest())   # noqa: E731
    rotate = {"kind": "popsnip.rekey", "app": "drumtoy", "from_key": k1, "to_key": k2, "from_account": acct,
              "to_account": acct, "path": "old_key", "requested_at": C, "effective_at": C, "challenge": nonce("acc-1")}
    launch = {"kind": "popsnip.launch", "app": "drumtoy", "account": acct, "dev_key": k1, "release0": R.record_id(r1),
              "launched_at": A, "pass_active": True, "pass_kind": "standard"}
    main = chain([launch, publish(r1, A), publish(r2, B), rotate, publish(r3, D)])
    wrongkey = chain([launch, publish(r1, A), publish(r2, B), rotate, publish(r3_old, D)])
    twice = chain([launch, publish(r1, A), publish(r2, B), rotate,
                   dict(rotate, from_key=k2, to_key=k1, requested_at=D, effective_at=D)])    # the same challenge
    badsig = chain([launch, publish(r1, A), publish(r2, B), dict(rotate, old_key_sig=r2["signature"]),
                    publish(r3, D)])
    late = dict(rotate, path="account_only", effective_at="2026-11-25T09:00:00Z", challenge=nonce("acc-2"))
    first4 = chain([launch, publish(r1, A), publish(r2, B), late])
    base_cancel = {"kind": "popsnip.rekey-cancel", "app": "drumtoy", "cancels": 4, "requested_at": C}
    cancels = chain([launch, publish(r1, A), publish(r2, B), late,
                     dict(base_cancel, cancels_id=R.record_id(first4[3])),      # the right id
                     dict(base_cancel, cancels_id=R.record_id(first4[2])),      # then another id
                     publish(r3_old, "2026-11-26T09:00:00Z")])
    forged_rel = signed({"v": 1, "kind": "popsnip.release", "app": "drumtoy", "version": 1, "prev": None,
                         "files": {p: file_hash(t) for p, t in texts["r1"].items()}, "permissions": ["midi"],
                         "dev_key": pub("dev4")}, "dev4")
    forged = chain([dict(launch, dev_key=pub("dev4"), release0=R.record_id(forged_rel), account="acct_TEST0009"),
                    publish(forged_rel, A)])
    fork_r2 = signed({"v": 1, "kind": "popsnip.release", "app": "drumtoy", "version": 2, "prev": R.record_id(r1),
                      "files": {p: file_hash(t) for p, t in texts["r2"].items()}, "permissions": ["midi"],
                      "dev_key": pub("dev4")}, "dev4")
    fork = chain([launch, publish(r1, A),                                   # the true entries 1 and 2, then two forged
                  dict(rotate, to_key=pub("dev4"), path="account_only", requested_at=B,          # by the revoked key
                       effective_at="2026-11-24T10:00:00Z", challenge=nonce("forge")),
                  publish(fork_r2, "2026-11-25T10:00:00Z")])
    tampered = [dict(e) for e in main]
    tampered[2] = dict(tampered[2], published_at=C)                        # changed after signing
    logs = {"main": main, "wrongkey": wrongkey, "twice": twice, "badsig": badsig, "tampered": tampered,
            "cancels": cancels, "forged": forged, "fork": fork, "short": main[:4]}
    heads = {"main": head(main, E), "wrongkey": head(wrongkey, E), "twice": head(twice, E), "badsig": head(badsig, E),
             "tampered": head(main, E), "short": head(main[:4], E), "cancels": head(cancels, "2026-11-27T09:00:00Z"),
             "forged": head(forged, E), "held2": head(main[:2], E), "fork": head(fork, "2026-11-26T09:00:00Z"),
             "main_by_test2": signed({"v": 1, "kind": "popsnip.head", "seq": len(main), "head_hash": R.record_id(main[-1]),
                                      "at": E, "kid": "launch-test2"}, "dev3")}

    def root(kind: str, **f: Any) -> Dict[str, Any]:
        return signed(dict({"v": 1, "kind": kind, "kid": "launch-test1", "at": E}, **f), "release")
    roots = {"none": [], "revoked_after_3": [root("popsnip.launch-key-revoked", after_seq=3)],
             "revoked_after_500": [root("popsnip.launch-key-revoked", after_seq=500)],
             "revoked_after_500_head_reaffirmed": [root("popsnip.launch-key-revoked", after_seq=500),
                                                   root("popsnip.reaffirm",
                                                        reaffirmed=[{"seq": 5, "id": R.record_id(main[4])}])],
             "test2_revoked_after_2": [root("popsnip.launch-key-revoked", after_seq=2, kid="launch-test2")],
             "unsigned": [signed({"v": 1, "kind": "popsnip.launch-key-revoked", "kid": "launch-test1", "after_seq": 3,
                                  "at": E}, "dev")],
             "malformed": [{"v": 1, "kind": "popsnip.reaffirm", "kid": "launch-test1"}],
             "revoked_after_3_reaffirmed": [root("popsnip.launch-key-revoked", after_seq=3),
                                            root("popsnip.reaffirm", reaffirmed=[{"seq": 4, "id": R.record_id(main[3])},
                                                                                 {"seq": 5, "id": R.record_id(main[4])}])]}

    def lst(entries: List[Dict[str, Any]], seq: int = 1, prev: str = R.GENESIS) -> Dict[str, Any]:
        pages = R.paginate(entries)
        index = signed({"v": 1, "kind": "popsnip.revocations", "seq": seq, "prev": prev, "at": E, "kid": "launch-test1",
                        "count": len(entries), "page_size": R.PAGE_SIZE, "pages": [R.record_id(p) for p in pages]},
                       "launch")
        return {"index": index, "pages": pages}

    def entry(n: int, target: Dict[str, str], action: str = "revoke", ground: str = "malware", **more: Any):
        return dict({"n": n, "target": target, "action": action, "ground": ground, "at": E, "by": "owner",
                     "notice": NOTICE + "r%d" % n}, **more)
    lists = {"release2": lst([entry(1, {"release": R.record_id(r2)})]),
             "app": lst([entry(1, {"app": "drumtoy"})]),
             "app_reinstated": lst([entry(1, {"app": "drumtoy"}), entry(2, {"app": "drumtoy"}, "reinstate")]),
             "k1_after_2": lst([entry(1, {"dev_key": k1}, ground="key_compromise", after_seq=2)]),
             "k1_all": lst([entry(1, {"dev_key": k1}, ground="key_compromise")])}
    lists["release2_then_app"] = lst([entry(1, {"release": R.record_id(r2)}), entry(2, {"app": "drumtoy"})], 2,
                                     R.record_id(lists["release2"]["index"]))
    broken = lst([entry(1, {"app": "drumtoy"})])
    lists["pages_wrong"] = {"index": broken["index"], "pages": [lists["release2"]["pages"][0]]}
    releases = {"r1": r1, "r2": r2, "r3": r3, "r3_old": r3_old, "r1_badsig": r1_badsig, "forged": forged_rel,
                "fork_r2": fork_r2}
    files = {k: dict(v) for k, v in texts.items()}
    files["r1_missing"] = {"index.html": texts["r1"]["index.html"]}
    files["r1_extra"] = dict(texts["r1"], **{"x.js": "x"})
    files["r1_changed"] = dict(texts["r1"], **{"app.js": "v1!"})
    files["forged"] = dict(texts["r1"])
    files["none"] = None

    def case(name: str, code: Optional[str], release: str = "r1", fls: Optional[str] = None, log: str = "main",
             hd: Optional[str] = None, rts: str = "none", lst_: Optional[str] = None, app: str = "drumtoy",
             pinned: str = "release", held_head: Optional[str] = None, held_list: Optional[str] = None
             ) -> Dict[str, Any]:
        return {"name": name, "code": code, "app": app, "release": release, "files": fls or release.split("_")[0],
                "log": log, "head": hd or log, "roots": rts, "list": lst_, "pinned": pinned, "held_head": held_head,
                "held_list": held_list}
    cases = [
        case("version 1, by the launch key", None),
        case("version 2", None, "r2"),
        case("version 3, by the key rotated to", None, "r3"),
        case("a version-3 publish by the key rotated away", "wrong_key", "r3_old", "r3", log="wrongkey"),
        case("a release the log never published", "not_published", "r3_old", "r3"),
        case("a release whose signature is another's", "release_signature", "r1_badsig", "r1"),
        case("a file missing", "files", fls="r1_missing"),
        case("a file too many", "files", fls="r1_extra"),
        case("a file changed", "files", fls="r1_changed"),
        case("a head that is not the snapshot's end", "head", hd="short"),
        case("an entry changed after signing", "log", log="tampered", hd="main"),
        case("certificates no pinned key signed", "cert", pinned="other"),
        case("a rotation challenge used twice", "repeated_challenge", "r2", log="twice"),
        case("a rotation the old key did not sign", "rekey_sig", log="badsig"),
        case("an app never launched", "no_binding", app="beattoy"),
        case("the launch key revoked after seq 3", "launch_key_revoked", "r1", rts="revoked_after_3"),
        case("... and entries 4 and 5 reaffirmed", None, "r3", rts="revoked_after_3_reaffirmed"),
        case("the release revoked", "revoked_release", "r2", lst_="release2"),
        case("another release stands", None, "r1", lst_="release2"),
        case("the app revoked", "revoked_app", "r3", lst_="app"),
        case("the app revoked, then reinstated", None, "r3", lst_="app_reinstated"),
        case("the key revoked after seq 2: version 1 stands", None, "r1", lst_="k1_after_2"),
        case("the key revoked after seq 2: version 2 does not", "revoked_key", "r2", lst_="k1_after_2"),
        case("the key revoked outright", "revoked_key", "r1", lst_="k1_all"),
        case("the new key is not the revoked one", None, "r3", lst_="k1_all"),
        case("the list's index with another list's page", "list_pages", lst_="pages_wrong"),
        case("the list signed by a revoked key", "list_key_revoked", "r1", rts="revoked_after_3_reaffirmed",
             lst_="release2"),
        # held state, other certified keys, and heads by a revoked key
        case("a head by another certified key", None, "r3", hd="main_by_test2"),
        case("a head by a key revoked before it", "launch_key_revoked", "r3", hd="main_by_test2",
             rts="test2_revoked_after_2"),
        # ANY head by a root-revoked key refuses, unless reaffirmed by seq and hash
        case("a short log from seq 1 by a revoked key, nothing held", "launch_key_revoked", "forged", log="forged",
             rts="revoked_after_500"),
        case("the same, held head at 5", "launch_key_revoked", "forged", log="forged", rts="revoked_after_500",
             held_head="main"),
        case("held at 2, true 1-2 and 3-4 forged by the revoked key below its cut", "launch_key_revoked", "fork_r2",
             "r2", log="fork", rts="revoked_after_500", held_head="held2"),
        case("a head by the revoked key that the owner reaffirmed", None, "r3", rts="revoked_after_500_head_reaffirmed"),
        case("a good log behind the head the device holds", "rollback", "r1", log="short", held_head="main"),
        case("the log the device holds, extended", None, "r3", held_head="short"),
        case("an older list than the one held", "list_rollback", "r1", lst_="release2", held_list="release2_then_app"),
        case("no list, and the device holds one", "list_rollback", "r1", held_list="release2"),
        case("the held list, extended", "revoked_app", "r1", lst_="release2_then_app", held_list="release2"),
        case("the held list itself", "revoked_release", "r2", lst_="release2", held_list="release2"),
        case("a valid cancel, then a cancel under another id: still cancelled", None, "r3_old", "r3", log="cancels"),
        case("files that are not a mapping", "malformed", fls="none"),
        case("a root record no pinned key signed", "roots", rts="unsigned"),
        case("a malformed root record", "roots", rts="malformed"),
    ]
    return {"about": ("Vectors for accept(), the device check for a Pop Snip app, written by "
                      "tools/popsnip_vectors.py: each case names its app, release, files, log, head, root records, "
                      "revocation list and pinned keys (\"release\": the test release key; \"other\": a key that "
                      "signed nothing here), the head and the list the device already holds (null: nothing), and the code accept() gives (null: accepted). "
                      "Files are ASCII text; null files are not a mapping."),
            "pinned": {"release": [pub("release")], "other": [pub("dev4")]}, "certs": [cert, cert2], "logs": logs,
            "heads": heads, "releases": releases, "files": files, "roots": roots, "lists": lists, "cases": cases}


def main(argv: List[str]) -> int:
    outs = [(OUT, json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=True) + "\n"),
            (OUT_ACCEPT, json.dumps(acceptance(), indent=1, sort_keys=True, ensure_ascii=True) + "\n")]
    if "--check" in argv:
        for out, text in outs:
            if not out.exists() or out.read_text(encoding="ascii") != text:
                print("%s differs from what %s makes" % (out.relative_to(ROOT), Path(__file__).name), file=sys.stderr)
                return 1
        return 0
    for out, text in outs:
        out.write_text(text, encoding="ascii")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
