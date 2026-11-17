# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.popsnip.accept: the device check for a Pop Snip app. Standard
library and bollardeck.corpus._ed25519 only.

    accept(app, release, files, log, head, certs, root_records, revocations, pinned, held_head, held_list) -> Verdict

It reads only what it is given: the device's log snapshot (every entry from seq 1 to the head), the signed head, the
launch-key certificates, the release key's root records (launch-key revocations and reaffirmations), the revocation
list, the release and its files, and the pinned release keys. It never reads the environment, the disk or the network,
and it has no argument a lapsed pass could change: a lapse cannot reach it. There is no unsigned mode.

A record is never checked by the bytes it arrived in: every signature is verified over CONTEXT + canonical(record) as
made here, from the parsed record.

`held_head` and `held_list` are what the device already holds (a head it accepted, and a list as (index, pages)); a
log or a list that does not extend them is refused, so an older list, no list, or a shorter log written from seq 1
by a compromised key never wins. None means the device holds nothing yet; an image
should bake in a head and a list, so that no device starts with nothing.

The checks, in order; the first that fails names the refusal (Verdict.code):
    malformed            an argument is not the shape the check needs (it never raises)
    roots                a root record that is malformed or not signed by a pinned key
    cert                 no certificate a pinned key signed names the head's or an entry's key
    head                 the head is not signed by a certified key, or does not name the snapshot's last entry
    log                  an entry does not follow the one before (seq, prev, time), has a wrong shape, a bad signature,
                         or a time outside its key's certificate window
    launch_key_revoked   an entry a root-revoked key signed after the revocation's after_seq, not reaffirmed by seq
                         and id; or ANY head a root-revoked key signed, unless a reaffirmation names that head's seq and
                         head_hash (entries at or below after_seq still count under a good head)
    rollback             the log does not extend the head the device holds
    no_binding           no popsnip.launch for the app
    rekey_sig            an old_key rotation whose old_key_sig the old key did not make
    repeated_challenge   a rotation challenge used twice in the app's log
    not_published        no popsnip.publish of this release (its id) for the app
    version              the publish entry's version is not the release's
    wrong_key            the release's key is not the app's key at its publish entry (the key walk)
    release_signature    the developer's signature does not verify
    files                the files are not exactly the manifest's, each with its sha256
    list_signature       the revocation list's newest index is not signed by a certified key
    list_key_revoked     ... or by a root-revoked one (the service re-signs; wait for it)
    list_pages           the list's pages are not the index's
    list_rollback        the list does not extend the list the device holds (or there is none and it holds one)
    revoked_release      the newest entry for this release revokes it
    revoked_app          the newest entry for this app revokes it
    revoked_key          the newest entry for the release's key revokes it (for publishes after its after_seq)
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

from ..corpus import _ed25519 as _E
from . import records as R


class Verdict(NamedTuple):
    ok: bool
    code: Optional[str]
    detail: str = ""


class _Refused(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _b64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signed_by(record: Dict[str, Any], pub: Optional[bytes]) -> bool:
    return pub is not None and _E.verify(pub, R.signed_message(record), _b64(record["signature"]))


def _pinned(record: Any, kind: str, pinned: List[bytes]) -> Optional[Dict[str, Any]]:
    try:
        R.check(record)
    except R.RecordError:
        return None
    if record["kind"] != kind:
        return None
    return record if any(_signed_by(record, k) for k in pinned) else None


def _roots(certs: List[Any], root_records: List[Any], pinned: List[bytes]):
    keys: Dict[str, Tuple[bytes, int, int]] = {}             # kid -> (pub, not_before, not_after)
    for c in certs:
        c = _pinned(c, "popsnip.launch-key", pinned)
        if c is not None:
            keys[c["kid"]] = (_b64(c["pub"]), R.to_seconds(c["not_before"]), R.to_seconds(c["not_after"]))
    revoked: Dict[str, int] = {}
    reaffirmed: Dict[str, Dict[int, str]] = {}
    for rec in root_records:
        r = _pinned(rec, "popsnip.launch-key-revoked", pinned)
        if r is not None:
            revoked[r["kid"]] = min(r["after_seq"], revoked.get(r["kid"], r["after_seq"]))
            continue
        a = _pinned(rec, "popsnip.reaffirm", pinned)
        if a is None:                                        # a root record nobody pinned signed is never ignored
            raise _Refused("roots", "a root record is malformed or not signed by a pinned release key")
        for e in a["reaffirmed"]:
            reaffirmed.setdefault(a["kid"], {})[e["seq"]] = e["id"]
    return keys, revoked, reaffirmed


def _check_log(log: List[Any], head: Any, keys, revoked, reaffirmed) -> None:
    try:
        R.check(head)
    except R.RecordError:
        raise _Refused("head", "the head is malformed") from None
    if head["kind"] != "popsnip.head":
        raise _Refused("head", "not a head")
    if head["kid"] not in keys:
        raise _Refused("cert", "no certificate for the head's key %s" % head["kid"])
    if not _signed_by(head, keys[head["kid"]][0]):
        raise _Refused("head", "the head's signature does not verify")
    if head["kid"] in revoked and reaffirmed.get(head["kid"], {}).get(head["seq"]) != head["head_hash"]:
        # a head by a root-revoked key at ANY seq, unless the owner
        # reaffirmed that head's seq and head_hash. Below after_seq too: the revoked key's holder can sign a head over
        # true entries plus forged ones at or below the cut, and fork any device behind it
        raise _Refused("launch_key_revoked", "the head is signed by %s, which is revoked" % head["kid"])
    prev_id, prev_time = R.GENESIS, ""
    for n, e in enumerate(log, 1):
        try:
            R.check(e)
        except R.RecordError as err:
            raise _Refused("log", "entry %d is malformed (%s)" % (n, err.code)) from None
        if e["kind"] not in R.LOG_KINDS or e["seq"] != n or e["prev"] != prev_id:
            raise _Refused("log", "entry %d does not follow the one before" % n)
        t = e[R.TIME_FIELD[e["kind"]]]
        if t < prev_time:
            raise _Refused("log", "entry %d is earlier than the one before" % n)
        if e["kid"] not in keys:
            raise _Refused("cert", "no certificate for key %s (entry %d)" % (e["kid"], n))
        pub, start, end = keys[e["kid"]]
        if not start <= R.to_seconds(t) < end or not _signed_by(e, pub):
            raise _Refused("log", "entry %d is not signed by its key inside its certificate's window" % n)
        if e["kid"] in revoked and n > revoked[e["kid"]] and reaffirmed.get(e["kid"], {}).get(n) != R.record_id(e):
            raise _Refused("launch_key_revoked", "entry %d is signed by %s after its revocation" % (n, e["kid"]))
        prev_id, prev_time = R.record_id(e), t
    if head["seq"] != len(log) or not log or head["head_hash"] != R.record_id(log[-1]):
        raise _Refused("head", "the head does not name the snapshot's last entry")


def _state(entries: List[Dict[str, Any]], app: str, at: str, seq: int) -> Tuple[str, str]:
    """(account, key) for the app at log time `at`, for an entry at position `seq` (the key walk; the `states`
    vectors): changes with a lower seq and effective_at not after `at`, in effective_at order then seq, not cancelled
    before `seq`; a change whose from_key or from_account is not current then changes nothing."""
    binding = next(e for e in entries if e["kind"] == "popsnip.launch" and e["app"] == app)
    key, account = binding["dev_key"], binding["account"]
    rekeys = {e["seq"]: e for e in entries if e["kind"] == "popsnip.rekey" and e["app"] == app}
    cancelled = set()                                        # every valid cancel counts, whatever else names the seq
    for c in entries:
        if c["kind"] == "popsnip.rekey-cancel" and c["app"] == app and c["seq"] < seq:
            e = rekeys.get(c["cancels"])
            if e is not None and c["cancels_id"] == R.record_id(e) and c["requested_at"] < e["effective_at"]:
                cancelled.add(e["seq"])
    changes = [e for s, e in rekeys.items() if s < seq and e["effective_at"] <= at and s not in cancelled]
    for e in sorted(changes, key=lambda e: (e["effective_at"], e["seq"])):
        if (e["from_key"], e["from_account"]) == (key, account):
            key, account = e["to_key"], e["to_account"]
    return account, key


def _check_rekeys(entries: List[Dict[str, Any]], app: str) -> None:
    seen: Set[str] = set()
    for e in entries:
        if e["kind"] != "popsnip.rekey" or e["app"] != app:
            continue
        if e["challenge"] in seen:
            raise _Refused("repeated_challenge", "entry %d reuses a rotation challenge" % e["seq"])
        seen.add(e["challenge"])
        if e["path"] == "old_key":
            req = R.rekey_request(e)
            if not _E.verify(_b64(e["from_key"]), R.signed_message(req), _b64(e["old_key_sig"])):
                raise _Refused("rekey_sig", "entry %d's old_key_sig is not the old key's" % e["seq"])


def _check_list(revocations: Any, keys, revoked) -> List[Dict[str, Any]]:
    if revocations is None:
        return []
    index, pages = revocations
    try:
        R.check(index)
    except R.RecordError:
        raise _Refused("list_signature", "the list's index is malformed") from None
    if index["kind"] != "popsnip.revocations" or index["kid"] not in keys \
            or not _signed_by(index, keys[index["kid"]][0]):
        raise _Refused("list_signature", "the list's index is not signed by a certified key")
    if index["kid"] in revoked:
        raise _Refused("list_key_revoked", "the list's newest index is signed by a revoked key; wait for its re-sign")
    try:
        return R.check_list(index, pages)
    except R.RecordError:
        raise _Refused("list_pages", "the list's pages are not its index's") from None


def _held_list(held_list: Any, index: Optional[Dict[str, Any]], entries: List[Dict[str, Any]]) -> None:
    if held_list is None:
        return
    h_index, h_pages = held_list
    R.check(h_index)
    h_entries = R.check_list(h_index, h_pages)
    if index is None:
        raise _Refused("list_rollback", "the device holds a list, and none was given")
    if index["seq"] == h_index["seq"]:
        if R.record_id(index) != R.record_id(h_index):
            raise _Refused("list_rollback", "another list at the seq the device holds")
        return
    try:
        R.check_extends(h_index, h_entries, index, entries)
    except R.RecordError:
        raise _Refused("list_rollback", "the list does not extend the one the device holds") from None


def accept(app: str, release: Any, files: Dict[str, bytes], log: List[Any], head: Any, certs: List[Any],
           root_records: List[Any], revocations: Any, pinned: List[bytes], held_head: Any = None,
           held_list: Any = None) -> Verdict:
    """The verdict on one release of one app, from the records given and nothing else (see the module's docstring)."""
    try:
        return _accept(app, release, files, log, head, certs, root_records, revocations, pinned, held_head, held_list)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, StopIteration, R.RecordError) as e:
        return Verdict(False, "malformed", "an argument is not the shape the check needs (%s)" % type(e).__name__)


def _accept(app: str, release: Any, files: Dict[str, bytes], log: List[Any], head: Any, certs: List[Any],
            root_records: List[Any], revocations: Any, pinned: List[bytes], held_head: Any,
            held_list: Any) -> Verdict:
    try:
        keys, revoked, reaffirmed = _roots(certs, root_records, pinned)
        _check_log(log, head, keys, revoked, reaffirmed)
        if held_head is not None:
            R.check(held_head)
            h = held_head["seq"]
            if head["seq"] < h or R.record_id(log[h - 1]) != held_head["head_hash"]:
                raise _Refused("rollback", "the log does not extend the head the device holds (seq %d)" % h)
        if not any(e["kind"] == "popsnip.launch" and e["app"] == app for e in log):
            raise _Refused("no_binding", "%s was never launched" % app)
        _check_rekeys(log, app)
        try:
            R.check(release)
        except R.RecordError as err:
            raise _Refused("release_signature", "the release is malformed (%s)" % err.code) from None
        rid = R.record_id(release)
        pub = next((e for e in log if e["kind"] == "popsnip.publish" and e["app"] == app and e["manifest"] == rid
                    and release["kind"] == "popsnip.release" and release["app"] == app), None)
        if pub is None:
            raise _Refused("not_published", "this release of %s is not in the log" % app)
        if pub["version"] != release["version"]:
            raise _Refused("version", "the log publishes it as version %d" % pub["version"])
        _account, key = _state(log, app, pub["published_at"], pub["seq"])
        if release["dev_key"] != key or pub["dev_key"] != key:
            raise _Refused("wrong_key", "the app's key at entry %d is another" % pub["seq"])
        if not _signed_by(release, _b64(release["dev_key"])):
            raise _Refused("release_signature", "the developer's signature does not verify")
        want = release["files"]
        if set(files) != set(want) or any(hashlib.sha256(files[p]).hexdigest() != h for p, h in want.items()):
            raise _Refused("files", "the files are not exactly the release's")
        latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
        listed = _check_list(revocations, keys, revoked)
        _held_list(held_list, revocations[0] if revocations is not None else None, listed)
        for e in listed:
            (kind, value), = e["target"].items()
            latest[(kind, value)] = e
        for code, target in (("revoked_release", ("release", rid)), ("revoked_app", ("app", app)),
                             ("revoked_key", ("dev_key", release["dev_key"]))):
            e = latest.get(target)
            if e is None or e["action"] != "revoke":
                continue
            if code == "revoked_key" and "after_seq" in e and pub["seq"] <= e["after_seq"]:
                continue                                     # released before the theft: it stands
            raise _Refused(code, "%s (%s, %s)" % (code, e["ground"], e["notice"]))
    except _Refused as r:
        return Verdict(False, r.code, r.detail)
    return Verdict(True, None, "accepted")
