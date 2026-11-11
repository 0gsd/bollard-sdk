# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus.attest: check a corpus against its attested edition.

An attested edition is four small files (the "record"), kept beside the corpus in
<root>/locker/<edition>/ and in the locker archive:

    ATTESTATION.json               canonical JSON: sorted keys, no whitespace, ASCII, no floats
    ATTESTATION.json.ed25519.sig   detached Ed25519 signature over those exact bytes
    ATTESTATION.json.mldsa65.sig   detached ML-DSA-65 signature over those exact bytes
    MANIFEST.tsv                   "path<TAB>size<TAB>sha256<TAB>md5", one line per archived file

and the corpus manifest's `attestation` block names the edition, the SHA-256 of MANIFEST.tsv
(`manifest_sha256`) and the signing identity (`keyid`: the first 16 hex digits of the SHA-256 of
the two public keys' DER encodings, Ed25519 then ML-DSA-65).

    result = verify_attestation(corpus, attestation=..., manifest_tsv=..., ed25519_sig=...,
                                mldsa65_sig=..., ed25519_pub=pem, mldsa65_pub=pem)
    result.status            "verified" | "failed" | "partial" | "not_checked"
    result.ed25519           "verified" | "failed" | "not_checked", and the same for
    result.mldsa65, result.manifest_hash, result.record, result.keyid

Each check reports for itself. "not_checked" means exactly that (a file or key was not supplied,
or this machine has no openssl that knows ML-DSA-65); it is never folded into "verified". The
whole is "verified" only when all five checks verified.

The caller supplies the public keys it trusts. This module never fetches a key and never reads
the locker archive.
"""

import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import _ed25519

VERIFIED = "verified"
FAILED = "failed"
NOT_CHECKED = "not_checked"

ATTESTATION_SCHEMA = "pboll/corpus-attestation/v1"
ATTESTATION_NAME = "ATTESTATION.json"
SIG_ED_NAME = "ATTESTATION.json.ed25519.sig"
SIG_ML_NAME = "ATTESTATION.json.mldsa65.sig"
MANIFEST_TSV_NAME = "MANIFEST.tsv"
MANIFEST_HEADER = "path\tsize\tsha256\tmd5"
LOCKER_DIRNAME = "locker"
KEY_FILES = ("ed25519.pub.pem", "mldsa65.pub.pem")
EDITION = re.compile(r"^[0-9]{8}-[0-9a-f]{12}\Z")
_HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"^[0-9a-f]{32}\Z")
CHECKS = ("manifest_hash", "record", "keyid", "ed25519", "mldsa65")


class AttestationError(ValueError):
    """A record file that is not in its canonical form."""


class AttestationResult:
    """What was checked and how it came out. See the module docstring."""

    def __init__(self, corpus_id: str = "", edition: str = ""):
        self.corpus_id = corpus_id
        self.edition = edition
        self.manifest_hash = NOT_CHECKED     # MANIFEST.tsv hashes to the manifest block's manifest_sha256
        self.record = NOT_CHECKED            # ATTESTATION.json is canonical and agrees with the block and the listing
        self.keyid = NOT_CHECKED             # the supplied public keys hash to the block's keyid
        self.ed25519 = NOT_CHECKED           # the Ed25519 signature over ATTESTATION.json
        self.mldsa65 = NOT_CHECKED           # the ML-DSA-65 signature over ATTESTATION.json
        self.problems: List[str] = []        # why something failed
        self.notes: List[str] = []           # why something was not checked
        self.entries: List[Dict[str, Any]] = []   # MANIFEST.tsv, parsed, when it was readable

    @property
    def status(self) -> str:
        states = [getattr(self, k) for k in CHECKS]
        if FAILED in states:
            return FAILED
        if all(s == VERIFIED for s in states):
            return VERIFIED
        return "partial" if VERIFIED in states else NOT_CHECKED

    @property
    def verified(self) -> bool:
        """True only when every check ran and passed."""
        return self.status == VERIFIED

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"corpus_id": self.corpus_id, "edition": self.edition, "status": self.status}
        out.update({k: getattr(self, k) for k in CHECKS})
        out["problems"], out["notes"] = list(self.problems), list(self.notes)
        return out

    def __repr__(self) -> str:
        return "AttestationResult(%s %s: %s)" % (self.corpus_id, self.edition, self.status)


# ── canonical forms ──────────────────────────────────────────────────────────────────────

def _no_floats(obj: Any) -> None:
    if isinstance(obj, float):
        raise AttestationError("floats are not allowed in canonical JSON")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise AttestationError("a key that is not a string")
            _no_floats(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _no_floats(v)


def canonical_json(obj: Any) -> bytes:
    """Sorted keys, no whitespace, ASCII only (anything else as \\u escapes), no floats."""
    _no_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def load_canonical(data: bytes) -> Dict[str, Any]:
    """Parse canonical JSON, refusing bytes that are not exactly their own canonical form."""
    try:
        obj = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AttestationError("not canonical JSON: %s" % exc) from None
    if not isinstance(obj, dict) or canonical_json(obj) != data:
        raise AttestationError("not canonical JSON (keys unsorted, whitespace, or bytes outside ASCII)")
    return obj


def render_manifest(entries) -> bytes:
    """MANIFEST.tsv for entries {path, size, sha256, md5}: sorted by path bytes, LF, final newline."""
    rows = sorted(entries, key=lambda e: e["path"].encode("utf-8"))
    seen, lines = set(), [MANIFEST_HEADER]
    for e in rows:
        p = e["path"]
        if p in seen:
            raise AttestationError("duplicate manifest path %s" % p)
        seen.add(p)
        if any(c in p for c in "\t\n\r") or p.startswith("/") or ".." in p.split("/"):
            raise AttestationError("unsafe manifest path %r" % p)
        lines.append("%s\t%d\t%s\t%s" % (p, int(e["size"]), e["sha256"], e["md5"]))
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_manifest(data: bytes) -> List[Dict[str, Any]]:
    """MANIFEST.tsv, parsed. Refuses a file that is not in canonical form."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise AttestationError("MANIFEST.tsv is not UTF-8") from None
    lines = text.split("\n")
    if not lines or lines[0] != MANIFEST_HEADER or lines[-1] != "":
        raise AttestationError("MANIFEST.tsv: bad header or no final newline")
    out = []
    for n, line in enumerate(lines[1:-1], 2):
        cols = line.split("\t")
        if len(cols) != 4 or not cols[1].isdigit() or not _HEX64.match(cols[2]) or not _HEX32.match(cols[3]):
            raise AttestationError("MANIFEST.tsv line %d is malformed" % n)
        out.append({"path": cols[0], "size": int(cols[1]), "sha256": cols[2], "md5": cols[3]})
    if render_manifest(out) != data:
        raise AttestationError("MANIFEST.tsv is not canonical (unsorted, duplicate or reformatted rows)")
    return out


def edition_id(created_at: str, manifest_tsv: bytes) -> str:
    """<UTC yyyymmdd of the attestation>-<first 12 hex digits of sha256(MANIFEST.tsv)>."""
    day = str(created_at)[:10].replace("-", "")
    if not re.match(r"^[0-9]{8}\Z", day):
        raise AttestationError("bad created_at %r" % (created_at,))
    return "%s-%s" % (day, hashlib.sha256(manifest_tsv).hexdigest()[:12])


# ── keys ─────────────────────────────────────────────────────────────────────────────────

def pem_der(pem: bytes) -> bytes:
    """The DER bytes inside a PEM block."""
    lines = [ln.strip() for ln in pem.decode("ascii", "replace").splitlines()]
    body = "".join(ln for ln in lines if ln and not ln.startswith("-----"))
    try:
        return base64.b64decode(body, validate=True)
    except ValueError:
        raise AttestationError("malformed PEM public key") from None


def keyid_for(ed25519_pub: bytes, mldsa65_pub: bytes) -> str:
    """The signing identity of a key pair (both as SubjectPublicKeyInfo PEM)."""
    return hashlib.sha256(pem_der(ed25519_pub) + pem_der(mldsa65_pub)).hexdigest()[:16]


def read_public_keys(pubkey_dir, keyid: str) -> Tuple[Optional[bytes], Optional[bytes]]:
    """(Ed25519 PEM, ML-DSA-65 PEM) from <pubkey_dir>/<keyid>/; None for a file that is not there."""
    out = []
    for name in KEY_FILES:
        try:
            out.append((Path(pubkey_dir) / keyid / name).read_bytes())
        except OSError:
            out.append(None)
    return out[0], out[1]


# ── ML-DSA-65, through an openssl binary when there is one that knows it ─────────────────

def find_openssl(path: Optional[str] = None) -> Optional[str]:
    """An openssl binary that lists ML-DSA-65 (OpenSSL 3.5 or later), or None."""
    exe = path or shutil.which("openssl")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "list", "-signature-algorithms"], capture_output=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return exe if b"ML-DSA-65" in out else None


def _openssl_verify(exe: str, pub_pem: bytes, data: bytes, sig: bytes) -> bool:
    with tempfile.TemporaryDirectory(prefix="bollard-verify-") as td:
        t = Path(td)
        (t / "pub.pem").write_bytes(pub_pem)
        (t / "msg").write_bytes(data)
        (t / "sig").write_bytes(sig)
        try:
            r = subprocess.run([exe, "pkeyutl", "-verify", "-pubin", "-inkey", str(t / "pub.pem"), "-rawin",
                                "-in", str(t / "msg"), "-sigfile", str(t / "sig")], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return False
    return r.returncode == 0 and b"Signature Verified Successfully" in r.stdout


# ── the check ────────────────────────────────────────────────────────────────────────────

def verify_attestation(corpus: Any, *, attestation: Optional[bytes] = None, manifest_tsv: Optional[bytes] = None,
                       ed25519_sig: Optional[bytes] = None, mldsa65_sig: Optional[bytes] = None,
                       ed25519_pub: Optional[bytes] = None, mldsa65_pub: Optional[bytes] = None,
                       openssl: Optional[str] = None) -> AttestationResult:
    """Check a corpus (a Corpus, or a manifest dict) against its record. Never raises for bad
    input: what is wrong is in `problems`, what could not be checked is in `notes`."""
    manifest = corpus.manifest() if hasattr(corpus, "manifest") and callable(corpus.manifest) else corpus
    manifest = manifest if isinstance(manifest, Mapping) else {}
    block = manifest.get("attestation")
    res = AttestationResult(str(manifest.get("id") or ""))
    if not isinstance(block, Mapping) or not _HEX64.match(str(block.get("manifest_sha256") or "")):
        res.notes.append("the manifest carries no attestation block")
        return res
    res.edition = str(block.get("edition") or "")
    want_hash, want_keyid = block["manifest_sha256"], str(block.get("keyid") or "")

    # 1. the listing hashes to what the manifest names
    if manifest_tsv is None:
        res.notes.append("manifest_hash: MANIFEST.tsv was not supplied")
    elif hashlib.sha256(manifest_tsv).hexdigest() != want_hash:
        res.manifest_hash = FAILED
        res.problems.append("MANIFEST.tsv does not hash to the manifest's manifest_sha256")
    else:
        try:
            res.entries = parse_manifest(manifest_tsv)
            res.manifest_hash = VERIFIED
        except AttestationError as exc:
            res.manifest_hash = FAILED
            res.problems.append(str(exc))

    # 2. the attestation document is canonical and says the same things
    att: Dict[str, Any] = {}
    if attestation is None:
        res.notes.append("record: ATTESTATION.json was not supplied")
    else:
        bad: List[str] = []
        try:
            att = load_canonical(attestation)
        except AttestationError as exc:
            bad.append("ATTESTATION.json: %s" % exc)
        if att:
            listed = att.get("manifest") if isinstance(att.get("manifest"), dict) else {}
            if att.get("schema") != ATTESTATION_SCHEMA:
                bad.append("unknown attestation schema %r" % (att.get("schema"),))
            if (att.get("corpus") or {}).get("id") != res.corpus_id:
                bad.append("the attestation is for another corpus")
            if att.get("edition") != res.edition or not EDITION.match(res.edition):
                bad.append("the attestation's edition is not the manifest's")
            if (att.get("signer") or {}).get("keyid") != want_keyid:
                bad.append("the attestation's keyid is not the manifest's")
            if listed.get("sha256") != want_hash:
                bad.append("the attestation's manifest hash is not the manifest's")
            if manifest_tsv is not None and res.manifest_hash == VERIFIED:
                if "sha3_512" in listed and hashlib.sha3_512(manifest_tsv).hexdigest() != listed["sha3_512"]:
                    bad.append("MANIFEST.tsv sha3-512 does not match the attestation")
                if (len(res.entries) != listed.get("files")
                        or sum(e["size"] for e in res.entries) != listed.get("bytes")):
                    bad.append("MANIFEST.tsv file count or bytes do not match the attestation")
                try:
                    if res.edition != edition_id(str(att.get("created_at", "")), manifest_tsv):
                        bad.append("the edition id does not match created_at and the manifest hash")
                except AttestationError as exc:
                    bad.append(str(exc))
        if bad:
            res.record = FAILED
            res.problems.extend(bad)
        elif manifest_tsv is None or res.manifest_hash != VERIFIED:
            res.notes.append("record: not checked against a verified MANIFEST.tsv")
        else:
            res.record = VERIFIED

    # 3. the keys are the ones the manifest names
    if ed25519_pub is None or mldsa65_pub is None:
        res.notes.append("keyid: needs both public keys")
    else:
        try:
            ok = keyid_for(ed25519_pub, mldsa65_pub) == want_keyid
        except AttestationError as exc:
            ok = False
            res.problems.append(str(exc))
        res.keyid = VERIFIED if ok else FAILED
        if not ok:
            res.problems.append("the public keys do not hash to keyid %s" % want_keyid)

    # 4. Ed25519
    if attestation is None or ed25519_sig is None or ed25519_pub is None:
        res.notes.append("ed25519: needs ATTESTATION.json, its signature and the public key")
    else:
        try:
            raw = _ed25519.raw_public_key(pem_der(ed25519_pub) if b"-----" in ed25519_pub else ed25519_pub)
        except AttestationError:
            raw = None
        ok = raw is not None and _ed25519.verify(raw, attestation, ed25519_sig)
        res.ed25519 = VERIFIED if ok else FAILED
        if not ok:
            res.problems.append("the Ed25519 signature does not verify")

    # 5. ML-DSA-65
    if attestation is None or mldsa65_sig is None or mldsa65_pub is None:
        res.notes.append("mldsa65: needs ATTESTATION.json, its signature and the public key")
    else:
        exe = find_openssl(openssl)
        if exe is None:
            res.notes.append("mldsa65: no openssl here knows ML-DSA-65 (needs OpenSSL 3.5 or later)")
        else:
            ok = _openssl_verify(exe, mldsa65_pub, attestation, mldsa65_sig)
            res.mldsa65 = VERIFIED if ok else FAILED
            if not ok:
                res.problems.append("the ML-DSA-65 signature does not verify")
    return res


# ── records and files on disk ────────────────────────────────────────────────────────────

def read_local_record(root, edition: str) -> Dict[str, Optional[bytes]]:
    """The four record files from <root>/locker/<edition>/, as keyword arguments for
    verify_attestation(); None for a file that is not there."""
    if not EDITION.match(str(edition or "")):
        raise AttestationError("%r is not an edition id" % (edition,))
    base = Path(root) / LOCKER_DIRNAME / edition
    out: Dict[str, Optional[bytes]] = {}
    for key, name in (("attestation", ATTESTATION_NAME), ("manifest_tsv", MANIFEST_TSV_NAME),
                      ("ed25519_sig", SIG_ED_NAME), ("mldsa65_sig", SIG_ML_NAME)):
        try:
            out[key] = (base / name).read_bytes()
        except OSError:
            out[key] = None
    return out


def archived_manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    """corpus.json as an edition archives it: without `attestation` (it describes the archive)
    and `form_stats` (derived), indented by two, not ASCII-escaped, one final newline."""
    data = {k: v for k, v in manifest.items() if k not in ("attestation", "form_stats")}
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def verify_local_files(root, entries) -> Dict[str, Any]:
    """Re-hash a local corpus root against a parsed MANIFEST.tsv:
    {"checked": n, "problems": ["<path>: missing" | "<path>: differs", ...]}. This reads the
    files' bytes only to hash them; it hands none of them out."""
    root = Path(root)
    problems = []
    for e in entries:
        rel = e["path"]
        if rel.startswith("/") or ".." in rel.split("/"):
            problems.append("%s: unsafe path" % rel)
            continue
        path = root / rel
        try:
            if rel == "corpus.json":
                data = archived_manifest_bytes(json.loads(path.read_text(encoding="utf-8")))
                size, digest = len(data), hashlib.sha256(data).hexdigest()
            else:
                h, size = hashlib.sha256(), 0
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                        size += len(chunk)
                digest = h.hexdigest()
        except (OSError, ValueError, AttributeError):
            problems.append("%s: missing" % rel)
            continue
        if digest != e["sha256"] or size != e["size"]:
            problems.append("%s: differs" % rel)
    return {"root": str(root), "checked": len(entries), "problems": problems}
