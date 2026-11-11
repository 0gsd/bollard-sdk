# SPDX-License-Identifier: Apache-2.0
"""Attestation checks (hashes, Ed25519 against RFC 8032, ML-DSA-65 through openssl when there is
one) and popboll.origin/1 discovery against a fake origin on a loopback port."""
import base64
import hashlib
import http.server
import json
import pathlib
import shutil
import subprocess
import tempfile
import threading
import unittest

from _corpus_fakes import MORPUS, ROOT, Recorder, ed25519_pem, ed25519_public, ed25519_sign, manifest, pem, write_local

from bollardeck.corpus import Corpus, OriginError, _ed25519, attest, fetch_origin
from bollardeck.corpus.attest import FAILED, NOT_CHECKED, VERIFIED, verify_attestation
from bollardeck.corpus.origin import parse_origin_manifest

# RFC 8032, section 7.1: (secret key, public key, message, signature), hex.
RFC8032 = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
     "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
    ("833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
     "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
     hashlib.sha512(b"abc").hexdigest(),
     "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
     "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"),
]

OPENSSL = attest.find_openssl()
SECRET = hashlib.sha256(b"a made-up signing key for the tests").digest()


class Ed25519(unittest.TestCase):
    def test_rfc_8032_vectors_verify(self):
        for secret, public, message, signature in RFC8032:
            pk, msg, sig = bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)
            self.assertTrue(_ed25519.verify(pk, msg, sig), public)
            # the vectors are transcribed correctly: the test signer reproduces them from the secret key
            self.assertEqual(ed25519_public(bytes.fromhex(secret)).hex(), public)
            self.assertEqual(ed25519_sign(bytes.fromhex(secret), msg).hex(), signature)

    def test_anything_else_does_not_verify(self):
        _, public, message, signature = RFC8032[2]
        pk, msg, sig = bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)
        self.assertFalse(_ed25519.verify(pk, msg + b"\x00", sig))
        self.assertFalse(_ed25519.verify(pk, b"", sig))
        self.assertFalse(_ed25519.verify(bytes.fromhex(RFC8032[0][1]), msg, sig))
        for i in (0, 31, 32, 63):
            bent = bytearray(sig)
            bent[i] ^= 1
            self.assertFalse(_ed25519.verify(pk, msg, bytes(bent)), i)
        # S must be below the group order: S + L is the same point and must still be refused
        s_plus_l = (int.from_bytes(sig[32:], "little") + _ed25519._L).to_bytes(32, "little")
        self.assertFalse(_ed25519.verify(pk, msg, sig[:32] + s_plus_l))
        for junk in (b"", sig[:63], sig + b"\x00", None, "text"):
            self.assertFalse(_ed25519.verify(pk, msg, junk))
        for junk in (b"", pk[:31], b"\xff" * 32, None):
            self.assertFalse(_ed25519.verify(junk, msg, sig))

    def test_public_keys_from_spki(self):
        raw = bytes.fromhex(RFC8032[0][1])
        self.assertEqual(_ed25519.raw_public_key(raw), raw)
        self.assertEqual(_ed25519.raw_public_key(attest.pem_der(ed25519_pem(raw))), raw)
        self.assertIsNone(_ed25519.raw_public_key(b"\x30\x2a" + raw))

    @unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
    def test_a_signature_openssl_makes_verifies_here(self):
        with tempfile.TemporaryDirectory() as td:
            t = pathlib.Path(td)
            made = subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(t / "k.pem")], capture_output=True)
            if made.returncode != 0:
                self.skipTest("this openssl has no Ed25519")
            subprocess.run(["openssl", "pkey", "-in", str(t / "k.pem"), "-pubout", "-out", str(t / "p.pem")], check=True, capture_output=True)
            (t / "msg").write_bytes(b"a made-up message")
            signed = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(t / "k.pem"), "-rawin", "-in", str(t / "msg"),
                                     "-out", str(t / "sig")], capture_output=True)
            if signed.returncode != 0:
                self.skipTest("this openssl cannot sign raw input")
            raw = _ed25519.raw_public_key(attest.pem_der((t / "p.pem").read_bytes()))
            self.assertTrue(_ed25519.verify(raw, b"a made-up message", (t / "sig").read_bytes()))
            self.assertFalse(_ed25519.verify(raw, b"another message", (t / "sig").read_bytes()))


def build_edition(td, real_mldsa=False):
    """A made-up corpus folder with an attested edition beside it. Returns everything a check needs."""
    td = pathlib.Path(td)
    ed_pub = ed25519_pem(ed25519_public(SECRET))
    if real_mldsa:
        subprocess.run([OPENSSL, "genpkey", "-algorithm", "ML-DSA-65", "-out", str(td / "ml.key.pem")], check=True, capture_output=True)
        subprocess.run([OPENSSL, "pkey", "-in", str(td / "ml.key.pem"), "-pubout", "-out", str(td / "ml.pub.pem")], check=True, capture_output=True)
        ml_pub = (td / "ml.pub.pem").read_bytes()
    else:
        ml_pub = pem(b"\x30\x03\x02\x01\x07" + b"not a real ML-DSA-65 key")
    keyid = attest.keyid_for(ed_pub, ml_pub)
    m = manifest(description="attested — made up")
    root = write_local(td / m["id"], m, files={"art/cover.png": b"PNG-made-up"})
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        data = attest.archived_manifest_bytes(m) if rel == "corpus.json" else path.read_bytes()
        entries.append({"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "md5": hashlib.md5(data, usedforsecurity=False).hexdigest()})
    tsv = attest.render_manifest(entries)
    created = "2031-02-03T06:00:00Z"
    edition = attest.edition_id(created, tsv)
    att = attest.canonical_json({
        "schema": attest.ATTESTATION_SCHEMA, "corpus": {"id": m["id"], "name": m["name"]}, "created_at": created,
        "edition": edition, "signer": {"keyid": keyid},
        "manifest": {"sha256": hashlib.sha256(tsv).hexdigest(), "sha3_512": hashlib.sha3_512(tsv).hexdigest(),
                     "files": len(entries), "bytes": sum(e["size"] for e in entries)}})
    if real_mldsa:
        (td / "att").write_bytes(att)
        subprocess.run([OPENSSL, "pkeyutl", "-sign", "-inkey", str(td / "ml.key.pem"), "-rawin", "-in", str(td / "att"),
                        "-out", str(td / "ml.sig")], check=True, capture_output=True)
        ml_sig = (td / "ml.sig").read_bytes()
    else:
        ml_sig = b"\x00" * 64
    m["attestation"] = {"attested": True, "edition": edition, "manifest_sha256": hashlib.sha256(tsv).hexdigest(),
                        "keyid": keyid, "attested_at": created, "held": True}
    m["form_stats"] = {"v": "stats/1", "tracks": 2}
    (root / "corpus.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    record = root / "locker" / edition
    record.mkdir(parents=True)
    for name, data in ((attest.ATTESTATION_NAME, att), (attest.MANIFEST_TSV_NAME, tsv),
                       (attest.SIG_ED_NAME, ed25519_sign(SECRET, att)), (attest.SIG_ML_NAME, ml_sig)):
        (record / name).write_bytes(data)
    keys = td / "keys" / keyid
    keys.mkdir(parents=True)
    (keys / "ed25519.pub.pem").write_bytes(ed_pub)
    (keys / "mldsa65.pub.pem").write_bytes(ml_pub)
    return {"root": root, "keys": td / "keys", "edition": edition, "keyid": keyid, "ed_pub": ed_pub, "ml_pub": ml_pub}


class Attestation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.e = build_edition(self.tmp.name)
        self.corpus = Corpus.load(self.e["root"])
        self.record = attest.read_local_record(self.e["root"], self.e["edition"])
        self.keys = dict(zip(("ed25519_pub", "mldsa65_pub"), attest.read_public_keys(self.e["keys"], self.e["keyid"])))

    def check(self, **changes):
        args = dict(self.record, **self.keys)
        args.update(changes)
        return verify_attestation(self.corpus, **args)

    def test_everything_but_mldsa_verifies_and_the_whole_is_not_called_verified(self):
        res = self.check(openssl="/nonexistent/openssl")
        self.assertEqual((res.manifest_hash, res.record, res.keyid, res.ed25519), (VERIFIED,) * 4)
        self.assertEqual(res.mldsa65, NOT_CHECKED)
        self.assertEqual(res.status, "partial")
        self.assertFalse(res.verified, "not checked is never reported as verified")
        self.assertEqual(res.problems, [])
        self.assertTrue(any("ML-DSA-65" in n for n in res.notes))
        self.assertEqual(res.as_dict()["mldsa65"], "not_checked")
        self.assertEqual((res.corpus_id, res.edition), (self.corpus.id, self.e["edition"]))

    @unittest.skipUnless(OPENSSL, "no openssl here knows ML-DSA-65")
    def test_a_signature_that_is_not_mldsa_fails_where_openssl_can_check(self):
        res = self.check()
        self.assertEqual(res.mldsa65, FAILED)
        self.assertEqual(res.status, "failed")

    @unittest.skipUnless(OPENSSL, "no openssl here knows ML-DSA-65")
    def test_with_a_real_mldsa_key_everything_verifies(self):
        with tempfile.TemporaryDirectory() as td:
            e = build_edition(td, real_mldsa=True)
            ed, ml = attest.read_public_keys(e["keys"], e["keyid"])
            record = attest.read_local_record(e["root"], e["edition"])
            res = verify_attestation(Corpus.load(e["root"]), ed25519_pub=ed, mldsa65_pub=ml, **record)
            self.assertEqual(res.problems, [])
            self.assertEqual((res.status, res.verified, res.mldsa65), ("verified", True, VERIFIED))
            bent = bytearray(record["mldsa65_sig"])
            bent[10] ^= 1
            res = verify_attestation(Corpus.load(e["root"]), ed25519_pub=ed, mldsa65_pub=ml,
                                     **dict(record, mldsa65_sig=bytes(bent)))
            self.assertEqual((res.mldsa65, res.ed25519, res.status), (FAILED, VERIFIED, "failed"))

    def test_what_is_not_supplied_is_not_checked(self):
        res = verify_attestation(self.corpus)
        self.assertEqual([getattr(res, k) for k in attest.CHECKS], [NOT_CHECKED] * 5)
        self.assertEqual((res.status, res.verified, len(res.notes)), ("not_checked", False, 5))
        res = self.check(mldsa65_pub=None, mldsa65_sig=None)
        self.assertEqual((res.ed25519, res.keyid, res.mldsa65, res.status), (VERIFIED, NOT_CHECKED, NOT_CHECKED, "partial"))
        res = self.check(manifest_tsv=None, openssl="/nonexistent/openssl")
        self.assertEqual((res.manifest_hash, res.record, res.ed25519), (NOT_CHECKED, NOT_CHECKED, VERIFIED))
        plain = verify_attestation(Corpus.from_manifest(manifest()), **self.record)
        self.assertEqual(plain.status, "not_checked")
        self.assertIn("no attestation block", plain.notes[0])
        self.assertEqual(verify_attestation("not a corpus").status, "not_checked")

    def test_each_tampering_fails_its_own_check(self):
        tsv, att = self.record["manifest_tsv"], self.record["attestation"]
        nossl = {"openssl": "/nonexistent/openssl"}
        res = self.check(manifest_tsv=tsv.replace(b"alpha.md", b"alpha.mx"), **nossl)
        self.assertEqual((res.manifest_hash, res.status), (FAILED, "failed"))
        res = self.check(attestation=att.replace(b"9001-PLACEHOLDERS", b"9001-PLACEHOLDERZ"), **nossl)
        self.assertEqual((res.record, res.ed25519), (FAILED, FAILED))
        res = self.check(attestation=json.dumps(json.loads(att), indent=1).encode(), **nossl)
        self.assertEqual(res.record, FAILED, "a reformatted attestation is not the signed bytes")
        self.assertIn("canonical", " ".join(res.problems))
        other = ed25519_pem(ed25519_public(b"\x01" * 32))
        res = self.check(ed25519_pub=other, **nossl)
        self.assertEqual((res.ed25519, res.keyid), (FAILED, FAILED))
        res = self.check(ed25519_sig=ed25519_sign(b"\x01" * 32, att), **nossl)
        self.assertEqual((res.ed25519, res.keyid, res.record), (FAILED, VERIFIED, VERIFIED))
        res = self.check(ed25519_pub=b"-----BEGIN PUBLIC KEY-----\n!!!\n-----END PUBLIC KEY-----\n", **nossl)
        self.assertEqual(res.ed25519, FAILED)
        m = self.corpus.manifest()
        m["attestation"]["manifest_sha256"] = "0" * 64
        res = verify_attestation(m, **dict(self.record, **self.keys), **nossl)
        self.assertEqual((res.manifest_hash, res.record), (FAILED, FAILED))
        m = self.corpus.manifest()
        m["attestation"]["edition"] = "20310204-" + self.e["edition"][9:]
        self.assertEqual(verify_attestation(m, **dict(self.record, **self.keys), **nossl).record, FAILED)

    def test_the_listing_must_be_canonical(self):
        tsv = self.record["manifest_tsv"]
        entries = attest.parse_manifest(tsv)
        self.assertEqual(attest.render_manifest(reversed(entries)), tsv)
        lines = tsv.decode().split("\n")
        for bad in ("\n".join([lines[0], lines[2], lines[1]] + lines[3:]), tsv.decode().rstrip("\n"),
                    tsv.decode().replace("\t", " ", 1), "\n".join(lines[1:]), tsv.decode() + lines[1] + "\n"):
            with self.assertRaises(attest.AttestationError):
                attest.parse_manifest(bad.encode())
        with self.assertRaises(attest.AttestationError):
            attest.render_manifest([dict(entries[0], path="../up.md")])
        with self.assertRaises(attest.AttestationError):
            attest.canonical_json({"ratio": 0.5})
        with self.assertRaises(attest.AttestationError):
            attest.read_local_record(self.e["root"], "../../etc")

    def test_local_files_are_rehashed_against_the_listing(self):
        entries = attest.parse_manifest(self.record["manifest_tsv"])
        rep = attest.verify_local_files(self.e["root"], entries)
        self.assertEqual((rep["checked"], rep["problems"]), (len(entries), []),
                         "corpus.json is compared without its attestation and form_stats members")
        (self.e["root"] / "morpus" / "alpha.mid").write_bytes(b"changed")
        (self.e["root"] / "morpus" / "beta.md").unlink()
        rep = attest.verify_local_files(self.e["root"], entries)
        self.assertEqual(rep["problems"], ["morpus/alpha.mid: differs", "morpus/beta.md: missing"])

    def test_the_manifest_vector_s_attestation_block_is_usable_as_is(self):
        full = json.loads((ROOT / "conformance" / "corpus-manifest" / "valid" / "full.json").read_text())
        res = verify_attestation(Corpus.from_manifest(full), manifest_tsv=b"path\tsize\tsha256\tmd5\n")
        self.assertEqual((res.manifest_hash, res.edition), (FAILED, "20310203-0123456789ab"))


# ── popboll.origin/1 ─────────────────────────────────────────────────────────────────────

SHA = "ab" * 32
TSV = ("album one/01 opener.mp3\t7\t%s\nep/02 second.flac\t9\t%s\n" % (SHA, SHA)).encode()


class FakeOrigin:
    def __init__(self, discovery, tsv=TSV, want_auth=None):
        self.files = {"/popboll/popboll-corpus.json": json.dumps(discovery).encode(), "/popboll/MANIFEST.tsv": tsv}
        self.want_auth = want_auth
        self.redirects = {}
        self.etag = True
        self.requests = []
        origin = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                origin.requests.append((self.path, self.headers.get("Authorization")))
                if self.path in origin.redirects:
                    self.send_response(302)
                    self.send_header("Location", origin.redirects[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = origin.files.get(self.path)
                status = 404 if body is None else 200
                if origin.want_auth and self.headers.get("Authorization") != origin.want_auth:
                    status, body = 401, None
                self.send_response(status)
                self.send_header("Content-Length", str(len(body or b"")))
                if status == 200 and origin.etag:
                    self.send_header("ETag", '"made-up"')
                self.end_headers()
                self.wfile.write(body or b"")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:%d/popboll/" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class OriginDiscovery(unittest.TestCase):
    def discovery(self, **changes):
        doc = json.loads((ROOT / "conformance" / "origin" / "valid" / "typical.json").read_text())
        doc.update(changes)
        return doc

    def origin(self, discovery=None, **kw):
        o = FakeOrigin(discovery or self.discovery(), **kw)
        self.addCleanup(o.close)
        return o

    def test_discover_and_list(self):
        basic = "Basic " + base64.b64encode(b"reader:made-up").decode()
        o = self.origin(want_auth=basic)
        found = fetch_origin(o.base.rstrip("/"), auth=("basic", "reader", "made-up"), allow_http_loopback=True)
        self.assertEqual((found.name, found.artist, found.scope, found.status), (
            "The Placeholders: Home Recordings", "The Placeholders", "full", "live"))
        self.assertEqual((found.live, found.problems, found.etag), (True, [], '"made-up"'))
        rows = found.manifest()
        self.assertEqual([r["path"] for r in rows], ["album one/01 opener.mp3", "ep/02 second.flac"])
        self.assertEqual(rows[0], {"path": "album one/01 opener.mp3", "size": 7, "sha256": SHA})
        self.assertEqual(found.url("album one/01 opener.mp3"), o.base + "album%20one/01%20opener.mp3")
        self.assertEqual(found.summary()["auth"], "basic")
        self.assertEqual({a for _, a in o.requests}, {basic})
        with self.assertRaisesRegex(OriginError, "refused the credential"):
            fetch_origin(o.base, allow_http_loopback=True)

    def test_https_only(self):
        o = self.origin()
        for base in (o.base, "http://files.example/popboll/", "ftp://files.example/", "", "files.example/popboll"):
            with self.assertRaisesRegex(OriginError, "HTTPS"):
                fetch_origin(base)
        with self.assertRaisesRegex(OriginError, "HTTPS"):
            fetch_origin("http://files.example/popboll/", allow_http_loopback=True)
        self.assertEqual(o.requests, [])

    def test_what_the_origin_gets_wrong_is_reported(self):
        o = self.origin(self.discovery(status="paused", auth={"type": "bearer"}))
        o.etag = False
        found = fetch_origin(o.base, allow_http_loopback=True)
        self.assertFalse(found.live)
        self.assertEqual(len(found.problems), 3)
        self.assertIn("paused", " ".join(found.problems))
        self.assertIn("auth.type says bearer", " ".join(found.problems))
        bearer = self.origin(self.discovery(auth={"type": "bearer"}), want_auth="Bearer made-up-token")
        self.assertTrue(fetch_origin(bearer.base, auth=("bearer", "made-up-token"), allow_http_loopback=True).live)
        with self.assertRaises(OriginError):
            fetch_origin(bearer.base, auth=("digest", "x"), allow_http_loopback=True)

    def test_a_discovery_file_that_does_not_fit_is_refused(self):
        for doc in (self.discovery(schema="popboll.origin/2"), self.discovery(auth={"type": "basic", "password": "x"}), ["list"]):
            o = self.origin(doc)
            with self.assertRaisesRegex(OriginError, "does not fit"):
                fetch_origin(o.base, allow_http_loopback=True)
        o = self.origin()
        o.files["/popboll/popboll-corpus.json"] = b"{" + b" " * (64 * 1024) + b"}"
        with self.assertRaisesRegex(OriginError, "more than"):
            fetch_origin(o.base, allow_http_loopback=True)
        o.files["/popboll/popboll-corpus.json"] = b"<html>"
        with self.assertRaisesRegex(OriginError, "not UTF-8 JSON"):
            fetch_origin(o.base, allow_http_loopback=True)
        del o.files["/popboll/popboll-corpus.json"]
        with self.assertRaisesRegex(OriginError, "404"):
            fetch_origin(o.base, allow_http_loopback=True)
        o.close()
        with self.assertRaisesRegex(OriginError, "not answering"):
            fetch_origin(o.base, allow_http_loopback=True, timeout=2)

    def test_redirects_stay_on_the_host_and_the_credential_with_them(self):
        elsewhere = Recorder()
        self.addCleanup(elsewhere.close)
        o = self.origin()
        o.redirects["/popboll/popboll-corpus.json"] = elsewhere.url + "/popboll-corpus.json"
        with self.assertRaisesRegex(OriginError, "redirect"):
            fetch_origin(o.base, auth=("bearer", "made-up-token"), allow_http_loopback=True)
        self.assertEqual(elsewhere.requests, [])
        o.redirects = {"/popboll/popboll-corpus.json": "/popboll/moved.json"}
        o.files["/popboll/moved.json"] = o.files["/popboll/popboll-corpus.json"]
        self.assertEqual(fetch_origin(o.base, allow_http_loopback=True).status, "live")
        o.redirects["/popboll/moved.json"] = "/popboll/again.json"
        o.files["/popboll/again.json"] = o.files["/popboll/popboll-corpus.json"]
        with self.assertRaises(OriginError):                     # followed once, not twice
            fetch_origin(o.base, allow_http_loopback=True)

    def test_the_origin_manifest_rules(self):
        self.assertEqual(parse_origin_manifest(b""), [])
        self.assertEqual(len(parse_origin_manifest(TSV)), 2)
        row = "%s\t1\t" + SHA + "\n"
        for bad in (TSV.replace(b"\n", b"\r\n"), TSV.rstrip(b"\n"), TSV + TSV, b"".join(reversed(TSV.splitlines(True))),
                    (row % "../up.mp3").encode(), (row % "/abs.mp3").encode(), (row % "a//b.mp3").encode(),
                    (row % "notes.txt").encode(), (row % "a/b/c/d/e.mp3").encode(), (row % "back\\slash.mp3").encode(),
                    b"a.mp3\tmany\t" + SHA.encode() + b"\n", b"a.mp3\t1\tABCD\n", b"a.mp3\t1\n", b"\xff\xfe\n",
                    b"path\tsize\tsha256\n"):
            with self.assertRaises(OriginError, msg=repr(bad[:40])):
                parse_origin_manifest(bad)
        self.assertEqual(len(parse_origin_manifest((row % "a/b/c/deep.MP3").encode())), 1)
        o = self.origin(tsv=b"zz.mp3\t1\t" + SHA.encode() + b"\naa.mp3\t1\t" + SHA.encode() + b"\n")
        with self.assertRaisesRegex(OriginError, "sorted"):
            fetch_origin(o.base, allow_http_loopback=True).manifest()


if __name__ == "__main__":
    unittest.main()
