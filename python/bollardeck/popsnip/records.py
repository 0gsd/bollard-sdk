# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.popsnip.records: the signed records of Pop Snip apps, and the one canonical form every signature covers.
Standard library only. The JavaScript twin, js/bollardeck.popsnip.js, is held to the same vectors
(conformance/popsnip/records.json) byte for byte.

A Pop Snip app lives at its own name, <name>.popsnip.app. Its developer signs each release; Pop Boll's countersigning
service signs the launch that binds the name to the developer's key, and logs every release, key change and transfer
in a public, append-only log; the pinned Bollawax release key certifies the service's launch keys. A device accepts an
app from those records alone, and never asks whether a developer's pass is active.

    canonical(record)       the record minus `signature`: JSON, keys sorted at every depth, no spaces, every string
                            printable ASCII (0x20-0x7e), every number an integer within +-(2**53 - 1)
    signed_message(record)  CONTEXT + canonical(record): what an Ed25519 signature over a record covers
    record_id(record)       sha256 of canonical(record), lowercase hex: a release's id, a log entry's id (what the
                            next entry's `prev` names), a list's id
    parse(text)             strict JSON: one object, no repeated key, no fraction, exponent, NaN or Infinity
    check(record, signed)   the record's shape for its kind, or RecordError(code); the first failure decides the code
                            (signed=False: a record about to be signed, without its signature)
    rekey_request(entry)    what a rotation's `old_key_sig` covers (signed by the old developer key)

Why the form is narrower than JSON. Python's json.dumps(ensure_ascii=True) and JavaScript's JSON.stringify agree byte
for byte only on printable ASCII strings and safe integers: Python escapes DEL (0x7f) and every non-ASCII character,
JavaScript writes them raw, and the two print fractions differently. So a record is refused, before anything is
signed or checked, unless it stays inside that common ground. Display names and descriptions live in a release's
files, which are covered by hash.

Why CONTEXT. The pinned release key signs Bollawax's own release records (over this same JSON form, with no prefix)
and also launch-key certificates, root revocations and reaffirmations. Every Pop Snip signature covers
CONTEXT + canonical(record), so no Pop Snip record's signature ever verifies as a release record's, nor the other way
round, whatever fields either grows later.

A verifier never hashes or verifies the bytes it received: it parses them strictly, checks the record, and verifies
the signature over CONTEXT + canonical(record) as made here. Two spellings of one record are one record.

Who signs what (SIGNER): "release" is the pinned release key (offline), "launch" a launch key certified by it (the
countersigning service, in a KMS), "dev" the developer key named in the record. This module checks shapes only; it
never verifies a signature and reads no clock, store or network.
"""
from __future__ import annotations

import base64
import calendar
import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..corpus import _ed25519 as _E

V = 1
CONTEXT = b"popsnip/1\n"
GENESIS = "0" * 64                       # the `prev` of the first entry in a chain (seq 1)
MAX_INT = 2 ** 53 - 1                    # the largest integer JavaScript holds exactly
MAX_VERSION = 2 ** 31 - 1
REKEY_DELAY = 7 * 86400                  # account-only rotations and every transfer: seven days
GROUNDS = ("malware", "legal", "impersonation", "fraud", "key_compromise", "withdrawn_by_developer")
PASS_KINDS = ("standard", "glass_lifetime")
LOG_KINDS = ("popsnip.launch", "popsnip.publish", "popsnip.rekey", "popsnip.rekey-cancel")
MAX_FILES = 4096
MAX_PERMISSIONS = 32
MAX_CSP = 2048
MAX_REVOCATIONS = 100000
MAX_DEPTH = 32                           # objects and arrays nested deeper are refused as bad_json


class RecordError(ValueError):
    """Why a record was refused: `code` is one of the codes the shared vectors name (and the JS twin gives)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── canonical bytes ─────────────────────────────────────────────────────────────────────────────
_PRINTABLE = re.compile(r"[\x20-\x7e]*")


def _common_ground(value: Any, depth: int = 1) -> None:
    """Every key and string printable ASCII, every number a safe integer, objects and arrays at most MAX_DEPTH deep;
    keys walked in sorted order (so the first refusal is the same in both twins)."""
    if isinstance(value, (dict, list)) and depth > MAX_DEPTH:
        raise RecordError("bad_json")
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise RecordError("not_ascii")
        for k in sorted(value):
            if not _PRINTABLE.fullmatch(k):
                raise RecordError("not_ascii")
            _common_ground(value[k], depth + 1)
    elif isinstance(value, list):
        for item in value:
            _common_ground(item, depth + 1)
    elif isinstance(value, str):
        if not _PRINTABLE.fullmatch(value):
            raise RecordError("not_ascii")
    elif value is None or isinstance(value, bool):
        pass
    elif isinstance(value, int):
        if not -MAX_INT <= value <= MAX_INT:
            raise RecordError("bad_number")
    else:
        raise RecordError("bad_number")              # floats, and anything that is not JSON


def canonical(record: Dict[str, Any]) -> bytes:
    if not isinstance(record, dict):
        raise RecordError("not_object")
    body = {k: v for k, v in record.items() if k != "signature"}
    _common_ground(body)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def signed_message(record: Dict[str, Any]) -> bytes:
    return CONTEXT + canonical(record)


def record_id(record: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical(record)).hexdigest()


# ── strict parsing ──────────────────────────────────────────────────────────────────────────────
def _no_repeats(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise RecordError("duplicate_key")
        out[k] = v
    return out


def _no_fractions(text: str) -> Any:
    raise RecordError("bad_number")


def _not_json(text: str) -> Any:
    raise RecordError("bad_json")                  # NaN, Infinity and -Infinity are not JSON


_OUT_OF_RANGE = float("inf")             # an integer literal past 2**53 - 1: refused later as bad_number, as in JS
_BRACKET_OR_QUOTE = re.compile(r'["\[\]{}]')
_QUOTE_OR_ESCAPE = re.compile(r'["\\]')


def _int(text: str) -> Any:
    digits = text.lstrip("-")
    if len(digits) > 16 or (len(digits) == 16 and digits > "9007199254740991"):
        return _OUT_OF_RANGE                    # never int() on a long literal (Python caps them at 4300 digits)
    return int(text)


def too_deep(text: str) -> bool:
    """True when objects and arrays nest more than MAX_DEPTH deep, counted in one pass over the text before it is
    parsed: outside a string a bracket opens or closes a level and a quote opens a string; inside one a quote closes
    it and a backslash takes the next character with it. No recursion, so no input can exhaust the stack; text that
    is not JSON is the parser's to refuse. The JS twin counts the same way."""
    depth, at = 0, 0
    while True:
        m = _BRACKET_OR_QUOTE.search(text, at)
        if m is None:
            return False
        c, at = m.group(), m.end()
        if c == '"':
            while True:
                m = _QUOTE_OR_ESCAPE.search(text, at)
                if m is None:
                    return False
                at = m.end()
                if m.group() == '"':
                    break
                at += 1
        elif c in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                return True
        else:
            depth -= 1


def parse(data: Any) -> Dict[str, Any]:
    """One JSON object, read strictly. Bytes must be UTF-8. The shape is check()'s job."""
    if isinstance(data, (bytes, bytearray)):
        try:
            data = bytes(data).decode("utf-8")
        except UnicodeDecodeError:
            raise RecordError("bad_json") from None
    if not isinstance(data, str):
        raise RecordError("bad_json")
    if too_deep(data):                             # first, before anything is parsed: the same answer in JS
        raise RecordError("bad_json")
    try:
        value = json.loads(data, object_pairs_hook=_no_repeats, parse_float=_no_fractions, parse_int=_int,
                           parse_constant=_not_json)
    except RecordError:
        raise
    except (ValueError, RecursionError):
        raise RecordError("bad_json") from None
    if not isinstance(value, dict):
        raise RecordError("not_object")
    return value


# ── field shapes ────────────────────────────────────────────────────────────────────────────────
_APP = re.compile(r"[a-z][a-z0-9-]{1,30}[a-z0-9]")
_ACCOUNT = re.compile(r"acct_[A-Za-z0-9]{8,40}")
_KID = re.compile(r"[a-z0-9][a-z0-9-]{0,38}[a-z0-9]")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_B64U = re.compile(r"[A-Za-z0-9_-]+")
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
_PERMISSION = re.compile(r"[a-z][a-z0-9-]{0,31}")
_NOTICE = re.compile(r"https://popboll\.com/dev/notices/[A-Za-z0-9._-]{1,64}")


def _is_int(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _b64u_bytes(v: Any, n: int) -> bool:
    """Unpadded base64url of exactly n bytes, in its one canonical spelling (the unused low bits are zero)."""
    if not isinstance(v, str) or len(v) != (4 * n + 2) // 3 or not _B64U.fullmatch(v):
        return False
    raw = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
    return len(raw) == n and base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") == v


_IDENTITY = (0, 1, 1, 0)


def _point(v: Any) -> bool:
    """A public key that can sign: 32 bytes in their one spelling, the canonical encoding of a point on the curve
    (y below p; x = 0 only with the sign bit clear), and not one of the 8 points of small order. A small-order key
    has no secret behind it, and verifiers (Python's, the browser's) disagree about signatures by one."""
    if not _b64u_bytes(v, 32):
        return False
    a = _E._decode(base64.urlsafe_b64decode(v + "="))
    return a is not None and not _E._equal(_E._mul(8, a), _IDENTITY)


def to_seconds(text: str) -> int:
    """A record's UTC time as seconds since the epoch (the shape is checked first)."""
    m = _TIME.fullmatch(text)
    if not m:
        raise RecordError("bad_time")
    return calendar.timegm(tuple(int(g) for g in m.groups()) + (0, 0, 0))


def _time(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    m = _TIME.fullmatch(v)
    if not m:
        return False
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    if not (1970 <= y <= 9999 and 1 <= mo <= 12 and h <= 23 and mi <= 59 and s <= 59):
        return False
    return 1 <= d <= calendar.monthrange(y, mo)[1]


def _app(v: Any) -> bool:
    return isinstance(v, str) and _APP.fullmatch(v) is not None and "--" not in v


def _hex64(v: Any) -> bool:
    return isinstance(v, str) and _HEX64.fullmatch(v) is not None


def _path(p: Any) -> bool:
    if not isinstance(p, str) or not 1 <= len(p) <= 256:
        return False
    return all(_SEGMENT.fullmatch(seg) for seg in p.split("/"))


def _files(v: Any) -> bool:
    if not isinstance(v, dict) or not 1 <= len(v) <= MAX_FILES:
        return False
    folded, dirs = set(), set()
    for p, h in v.items():
        if not _path(p) or not _hex64(h) or p.lower() in folded:     # no two names that differ only in case
            return False
        folded.add(p.lower())
        parts = p.lower().split("/")
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return not (dirs & folded)                                        # no name is also a folder


def _permissions(v: Any) -> bool:
    if not isinstance(v, list) or len(v) > MAX_PERMISSIONS:
        return False
    if not all(isinstance(p, str) and _PERMISSION.fullmatch(p) for p in v):
        return False
    return all(a < b for a, b in zip(v, v[1:]))              # sorted, no repeats


def _target(v: Any) -> bool:
    if not isinstance(v, dict) or len(v) != 1:
        return False
    (k, x), = v.items()
    return {"release": _hex64, "app": _app, "dev_key": _point}.get(k, lambda y: False)(x)


_REVOCATION_FIELDS = {"n", "target", "action", "ground", "at", "by", "notice", "after_seq"}


def _revocation_entries(v: Any) -> bool:
    if not isinstance(v, list) or len(v) > MAX_REVOCATIONS:
        return False
    for i, e in enumerate(v):
        if not isinstance(e, dict) or not set(e) <= _REVOCATION_FIELDS or not (_REVOCATION_FIELDS - {"after_seq"}) <= set(e):
            return False
        if e["n"] != i + 1 or not _is_int(e["n"], 1, MAX_INT) or not _target(e["target"]):
            return False
        if e["action"] not in ("revoke", "reinstate") or e["ground"] not in GROUNDS or not _time(e["at"]):
            return False
        if e["by"] not in ("owner", "delegate", "developer") or not isinstance(e["notice"], str) \
                or not _NOTICE.fullmatch(e["notice"]):
            return False
        if (e["by"] == "developer") != (e["ground"] == "withdrawn_by_developer"):
            return False
        if "after_seq" in e and not _is_int(e["after_seq"], 0, MAX_INT):
            return False
    return True


def _reaffirmed(v: Any) -> bool:
    if not isinstance(v, list) or not 1 <= len(v) <= MAX_REVOCATIONS:
        return False
    last = 0
    for e in v:
        if not isinstance(e, dict) or set(e) != {"seq", "id"} or not _is_int(e["seq"], 1, MAX_INT) or not _hex64(e["id"]):
            return False
        if e["seq"] <= last:
            return False
        last = e["seq"]
    return True


_KEY = _point
_NONCE = lambda v: _b64u_bytes(v, 32)                        # noqa: E731  32 random bytes, not a point
_SIG = lambda v: _b64u_bytes(v, 64)                          # noqa: E731
_SEQ = lambda v: _is_int(v, 1, MAX_INT)                      # noqa: E731

FIELD_CHECKS: Dict[str, Callable[[Any], bool]] = {
    "app": _app, "account": lambda v: isinstance(v, str) and _ACCOUNT.fullmatch(v) is not None,
    "from_account": lambda v: isinstance(v, str) and _ACCOUNT.fullmatch(v) is not None,
    "to_account": lambda v: isinstance(v, str) and _ACCOUNT.fullmatch(v) is not None,
    "kid": lambda v: isinstance(v, str) and _KID.fullmatch(v) is not None,
    "pub": _KEY, "dev_key": _KEY, "from_key": _KEY, "to_key": _KEY, "challenge": _NONCE,
    "signature": _SIG, "old_key_sig": _SIG,
    "release0": _hex64, "manifest": _hex64, "head_hash": _hex64, "cancels_id": _hex64,
    "launched_at": _time, "published_at": _time, "requested_at": _time, "effective_at": _time, "at": _time,
    "not_before": _time, "not_after": _time,
    "pass_active": lambda v: v is True, "pass_kind": lambda v: v in PASS_KINDS,
    "seq": _SEQ, "cancels": _SEQ, "after_seq": lambda v: _is_int(v, 0, MAX_INT),
    "version": lambda v: _is_int(v, 1, MAX_VERSION),
    "path": lambda v: v in ("old_key", "account_only"),
    "files": _files, "permissions": _permissions,
    "csp": lambda v: isinstance(v, str) and 1 <= len(v) <= MAX_CSP,
    "entries": _revocation_entries, "reaffirmed": _reaffirmed,
    "prev": _hex64,                                          # a chain's: GENESIS at seq 1 (a rule)
}
# a field whose shape depends on the kind: a release's `prev` is null for version 1 (a rule) and a hash after
KIND_FIELD_CHECKS: Dict[Tuple[str, str], Callable[[Any], bool]] = {
    ("popsnip.release", "prev"): lambda v: v is None or _hex64(v),
}

# kind -> (signer, required fields, optional fields)
_LOG = ("seq", "prev", "kid", "signature")
KINDS: Dict[str, Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = {
    "popsnip.launch-key": ("release", ("kid", "pub", "not_before", "not_after", "signature"), ()),
    "popsnip.launch-key-revoked": ("release", ("kid", "after_seq", "at", "signature"), ()),
    "popsnip.reaffirm": ("release", ("kid", "reaffirmed", "at", "signature"), ()),
    "popsnip.launch": ("launch", ("app", "account", "dev_key", "release0", "launched_at", "pass_active", "pass_kind")
                       + _LOG, ()),
    "popsnip.publish": ("launch", ("app", "version", "manifest", "dev_key", "published_at") + _LOG, ()),
    "popsnip.rekey": ("launch", ("app", "from_key", "to_key", "from_account", "to_account", "path", "requested_at",
                                 "effective_at", "challenge") + _LOG, ("old_key_sig",)),
    "popsnip.rekey-cancel": ("launch", ("app", "cancels", "cancels_id", "requested_at") + _LOG, ()),
    "popsnip.head": ("launch", ("seq", "head_hash", "at", "kid", "signature"), ()),
    "popsnip.revocations": ("launch", ("seq", "prev", "at", "entries", "kid", "signature"), ()),
    "popsnip.release": ("dev", ("app", "version", "prev", "files", "permissions", "dev_key", "signature"), ("csp",)),
    "popsnip.key-proof": ("dev", ("account", "dev_key", "challenge", "signature"), ()),
    # what an old_key rotation's old key signs (its signature travels as the rotation's old_key_sig)
    "popsnip.rekey-request": ("dev", ("app", "from_key", "to_key", "from_account", "to_account", "path",
                                      "challenge"), ()),
}
SIGNER = {kind: spec[0] for kind, spec in KINDS.items()}
TIME_FIELD = {"popsnip.launch": "launched_at", "popsnip.publish": "published_at", "popsnip.rekey": "requested_at",
              "popsnip.rekey-cancel": "requested_at"}


def _rules(r: Dict[str, Any]) -> Optional[str]:
    """Rules between fields, in a fixed order; the name of the first broken one."""
    kind = r["kind"]
    if "prev" in r and kind != "popsnip.release" and (r["seq"] == 1) != (r["prev"] == GENESIS):
        return "genesis"
    if kind == "popsnip.release" and (r["version"] == 1) != (r["prev"] is None):
        return "first_release"
    if kind == "popsnip.launch-key" and to_seconds(r["not_after"]) <= to_seconds(r["not_before"]):
        return "window"
    if kind == "popsnip.rekey-request":
        if r["path"] != "old_key":
            return "request_path"
        if r["from_key"] == r["to_key"]:
            return "same_key"
    if kind == "popsnip.rekey":
        if ("old_key_sig" in r) != (r["path"] == "old_key"):
            return "old_key_sig"
        if r["from_key"] == r["to_key"]:
            return "same_key"
        delay = to_seconds(r["effective_at"]) - to_seconds(r["requested_at"])
        waits = r["path"] == "account_only" or r["from_account"] != r["to_account"]
        if delay != (REKEY_DELAY if waits else 0):
            return "delay"
    if kind == "popsnip.rekey-cancel" and r["cancels"] >= r["seq"]:
        return "cancels"
    return None


def check(record: Any, signed: bool = True) -> Dict[str, Any]:
    """The record, when its shape is right for its kind; else RecordError(code). Codes, in the order they are tried:
    not_object, not_ascii | bad_number | bad_json (anywhere, keys in sorted order), unknown_kind, bad_version,
    unknown_field:<f>, missing_field:<f>, bad_field:<f> (fields in sorted order), rule:<name>.

    signed=False (False itself, nothing else) checks a record about to be signed: `signature` is then not required, and refused if present
    (unknown_field:signature). A signer checks before it signs and again after."""
    if not isinstance(record, dict):
        raise RecordError("not_object")
    _common_ground(record)
    kind = record.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise RecordError("unknown_kind")
    if not _is_int(record.get("v"), V, V):
        raise RecordError("bad_version")
    _signer, required, optional = KINDS[kind]
    if signed is False:                            # only False: None and anything else check a signed record, as in JS
        required = tuple(f for f in required if f != "signature")
    allowed = set(required) | set(optional) | {"v", "kind"}
    for f in sorted(record):
        if f not in allowed:
            raise RecordError("unknown_field:" + f)
    for f in sorted(required):
        if f not in record:
            raise RecordError("missing_field:" + f)
    for f in sorted(record):
        if f in ("v", "kind"):
            continue
        if not KIND_FIELD_CHECKS.get((kind, f), FIELD_CHECKS[f])(record[f]):
            raise RecordError("bad_field:" + f)
    broken = _rules(record)
    if broken:
        raise RecordError("rule:" + broken)
    return record


def rekey_request(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The request an old_key rotation's old key signs (over CONTEXT + its canonical bytes): the rotation's own fields
    the developer knows before the service writes the entry, with the service's one-time challenge. A kind of its
    own (popsnip.rekey-request), so check() reads it."""
    out = {"v": V, "kind": "popsnip.rekey-request"}
    for f in ("app", "from_key", "to_key", "from_account", "to_account", "path", "challenge"):
        if f not in entry:
            raise RecordError("missing_field:" + f)
        out[f] = entry[f]
    return out


def utc_now() -> str:
    """This machine's clock in the records' form (for tools; checks never read a clock)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
