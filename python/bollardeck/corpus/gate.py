# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus.gate: the one decision "may this caller do this with this corpus, now?".

    verdict = judge(manifest, "study", identity=Identity(email="ada@example.org"), now="2031-02-03T00:00:00Z")
    verdict.allowed, verdict.reason, verdict.detail

`judge` never raises and fails closed: anything it cannot read, does not know or is not sure of
is a refusal with a reason. Corpus.may() is the same decision for a loaded corpus, and every
accessor that hands out corpus content demands the Verdict it returned (see admit()).

The checks, in order. The first that fails is the reason:

    bad_clock            the time given as "now" is not a UTC time
    unknown_capability   the capability asked for is not one this code knows
    manifest_invalid     the manifest does not fit the corpus-manifest schema, or its id does
                         not match its number and slug
    licence_ambiguous    "licence" and "license" are both blocks and differ
    unknown_scope        the licence names a scope this code does not know
    newer_version        the licence is a newer version than this code understands
    withdrawn            the hub that served this corpus no longer serves it to this client
    not_visible          the corpus is private and this identity is neither its owner nor on
                         its access list
    (the capability "see" is decided here: it asks about visibility only)
    licence_missing      the manifest has no licence block
    licence_invalid      the block passed the schema and still cannot be read (30 February)
    revoked              revoked_at has passed
    expired              expires_at has passed
    not_granted          the licence does not include the capability
    allowed

Offline. A corpus held in a cache, whose hub could not be reached, keeps
working on the licence block it holds, and every verdict then carries `unverified_since`, the
last revalidation.

  * A date the device already holds is honoured by its own clock, online or not: an
    `expires_at` that has passed closes the gate offline too.
  * News the device has not heard waits for the next contact: a revocation made on the hub
    reaches a cached corpus when the block is next revalidated, and applies at once then.
  * One case sits between the two: a `revoked_at` already in the cached block that was still
    in the future at the last revalidation and passes while the hub is unreachable. It is
    treated as revocation news: the corpus keeps working, the verdict's `pending` is
    "revoked", and it closes at the next contact. A `revoked_at` that had already passed when
    the block was last revalidated closes the gate as usual.
  * A clock that is set back does not reopen a licence. The gate never reads a time earlier
    than the latest one the cache has witnessed: the last revalidation (`revalidated_at`, a
    moment the hub confirmed) and `witnessed_at`, the latest time the cache has seen on the
    device's own clock. `revoked_at` and `expires_at` are compared with the later of the clock
    and those. A corpus in a local folder has neither, and follows the clock as given.

The hub's own contract. A hub's read token alone is study only for a corpus that is
not public: a client that holds the token and names nobody is the platform's engine, and the
hub gives it the morpus and a manifest with the people taken out (no `owner_email`, `access`,
`license_note`, `granted_by` or `statements`), and answers 404 for tracks, audio, art and
bundles. Those need a named person, sent as `X-Pop-For` (HubClient's `acting_for`), who is the
owner or on the access list. A redacted manifest fits the schema and is judged exactly as the
whole one is for `Identity(service=True)` and for nobody; it cannot be judged for a named
person, because the names are not in it (`not_visible`), and the hub never sends it to one.
The vectors are in conformance/corpus-gate/visibility.json.
"""

import hashlib
import json
from typing import Any, Dict, Mapping, Optional, Tuple

from .. import schema as _schema
from . import licence as _licence
from .licence import CAPABILITIES, Licence, format_time, to_epoch

SEE = "see"
ALIASES = {"study": "musicians_may_study"}
ALL_CAPABILITIES: Tuple[str, ...] = CAPABILITIES + (SEE,)

ALLOWED = "allowed"
REASONS: Tuple[str, ...] = (
    "bad_clock", "unknown_capability", "manifest_invalid", "licence_ambiguous", "unknown_scope", "newer_version",
    "withdrawn", "not_visible", "licence_missing", "licence_invalid", "revoked", "expired",
    "not_granted", ALLOWED,
)

_SEAL = object()


def canonical_capability(capability: Any) -> Optional[str]:
    """The capability's canonical name ("study" is "musicians_may_study"), or None."""
    if not isinstance(capability, str):
        return None
    name = ALIASES.get(capability, capability)
    return name if name in ALL_CAPABILITIES else None


def norm_email(email: Any) -> str:
    return email.strip().lower() if isinstance(email, str) else ""


class Identity:
    """Who is asking. `email` is a person (compared trimmed and lower-cased). `service=True`
    says the caller is the platform's own engine acting under the hub's token, which sees
    private corpora the way an unfiltered hub listing does; never set it for a person."""

    __slots__ = ("email", "service", "player", "device")

    def __init__(self, email: str = "", service: bool = False, player: str = "", device: str = ""):
        self.email = norm_email(email)
        self.service = service is True
        self.player = str(player or "")
        self.device = str(device or "")

    @classmethod
    def anonymous(cls) -> "Identity":
        return cls()

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "Identity":
        data = data or {}
        return cls(email=data.get("email") or "", service=data.get("service") is True,
                   player=data.get("player") or "", device=data.get("device") or "")

    def __repr__(self) -> str:
        return "Identity(email=%r, service=%r)" % (self.email, self.service)


class Standing:
    """How fresh the manifest in hand is. A corpus read from a local folder is "local": the
    manifest is the truth and the clock applies. A corpus from a hub records when its licence
    block was last revalidated and whether the hub answered the last time it was asked."""

    __slots__ = ("source", "revalidated_at", "reachable", "withdrawn", "witnessed_at")

    def __init__(self, source: str = "local", revalidated_at: Optional[float] = None,
                 reachable: bool = True, withdrawn: bool = False, witnessed_at: Optional[float] = None):
        self.source = source
        self.revalidated_at = revalidated_at
        self.reachable = bool(reachable)
        self.withdrawn = bool(withdrawn)
        self.witnessed_at = witnessed_at        # the latest time the cache has seen on any clock, or None

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "Standing":
        data = data or {}
        return cls(source=str(data.get("source") or "local"),
                   revalidated_at=_licence.parse_time(data.get("revalidated_at")),
                   reachable=data.get("reachable", True) is not False,
                   withdrawn=data.get("withdrawn") is True,
                   witnessed_at=_licence.parse_time(data.get("witnessed_at")))

    @property
    def floor(self) -> Optional[float]:
        """The earliest "now" the gate will believe: the latest time this cache has witnessed."""
        seen = [t for t in (self.revalidated_at, self.witnessed_at) if isinstance(t, (int, float))]
        return max(seen) if seen and self.source != "local" else None

    @property
    def unverified(self) -> bool:
        return self.source != "local" and not self.reachable

    def _key(self) -> str:
        return "%s|%r|%r|%r" % (self.source, self.revalidated_at, self.reachable, self.withdrawn)


class Reading:
    """A manifest, read for the gate: either refused whole, or its licence and settings."""

    __slots__ = ("corpus_id", "refusal", "problems", "licence", "visibility", "owner_email", "access", "stamp")

    def __init__(self, corpus_id, refusal, problems, licence, visibility="public", owner_email="", access=()):
        self.corpus_id = corpus_id
        self.refusal = refusal                  # None, or a reason from REASONS
        self.problems = tuple(problems)
        self.licence = licence
        self.visibility = visibility
        self.owner_email = owner_email
        self.access = tuple(access)
        body = json.dumps([corpus_id, refusal, licence.block(), licence.status, visibility, owner_email,
                           list(self.access)], sort_keys=True, default=str)
        self.stamp = hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_manifest(manifest: Any) -> Reading:
    """Read a manifest for the gate. Never raises, never reads part of a manifest that fails."""
    closed = Licence.from_block(None)
    cid = manifest.get("id") if isinstance(manifest, Mapping) and isinstance(manifest.get("id"), str) else ""
    problems = _schema.validate("corpus-manifest", manifest)
    if problems:
        said = [str(p) for p in problems]
        reason = "manifest_invalid"
        if isinstance(manifest, Mapping):
            # Say the more useful thing when the only trouble is a licence from the future.
            blocks = [manifest.get(k) for k in ("licence", "license") if isinstance(manifest.get(k), Mapping)]
            elsewhere = [p for p in problems if not p.pointer.startswith(("/licence", "/license"))]
            statuses = {Licence.from_block(b).status for b in blocks}
            if not elsewhere and statuses & {_licence.UNKNOWN_SCOPE, _licence.NEWER_VERSION}:
                reason = _licence.UNKNOWN_SCOPE if _licence.UNKNOWN_SCOPE in statuses else _licence.NEWER_VERSION
        return Reading(cid, reason, said, closed)
    if manifest["id"] != "%04d-%s" % (manifest["number"], manifest["slug"]):
        return Reading(cid, "manifest_invalid",
                       ["#/id: %r is not number %r and slug %r joined" % (manifest["id"], manifest["number"], manifest["slug"])],
                       closed)
    main, alias = manifest.get("licence"), manifest.get("license")
    alias = alias if isinstance(alias, Mapping) else None      # "license": "CC BY" is a note, not a block
    if main is not None and alias is not None and dict(main) != dict(alias):
        return Reading(cid, "licence_ambiguous",
                       ['#/license: "licence" and "license" are both licence blocks and differ'], closed)
    block = main if main is not None else alias
    return Reading(cid, None, [], Licence.from_block(block), manifest.get("visibility", "public"),
                   norm_email(manifest.get("owner_email")), [norm_email(a) for a in manifest.get("access", [])])


class Verdict:
    """The gate's answer. Truthy when allowed. Only the gate makes one."""

    __slots__ = ("allowed", "reason", "capability", "corpus_id", "detail", "scope", "checked_at",
                 "unverified_since", "pending", "valid_until", "_stamp")

    def __init__(self, seal, allowed, reason, capability, corpus_id, detail, scope, checked_at,
                 unverified_since=None, pending=None, valid_until=None, stamp=""):
        if seal is not _SEAL:
            raise TypeError("a Verdict comes from the gate: call Corpus.may() or gate.judge()")
        s = object.__setattr__
        s(self, "allowed", allowed is True and reason == ALLOWED)
        s(self, "reason", reason)
        s(self, "capability", capability)
        s(self, "corpus_id", corpus_id)
        s(self, "detail", detail)
        s(self, "scope", scope)
        s(self, "checked_at", checked_at)                 # epoch seconds: the clock the gate used
        s(self, "unverified_since", unverified_since)     # epoch seconds, or None
        s(self, "pending", pending)                       # None, or "revoked" (see the module docstring)
        s(self, "valid_until", valid_until)               # epoch seconds, or None
        s(self, "_stamp", stamp)

    def __setattr__(self, name, value):
        raise AttributeError("a Verdict does not change")

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        return "Verdict(%s %s on %s: %s)" % ("allowed" if self.allowed else "refused", self.capability,
                                             self.corpus_id or "?", self.reason)

    def as_dict(self) -> Dict[str, Any]:
        """Plain values for a UI or a log. Times are UTC strings."""
        return {
            "allowed": self.allowed, "reason": self.reason, "capability": self.capability,
            "corpus_id": self.corpus_id, "detail": self.detail, "scope": self.scope,
            "checked_at": format_time(self.checked_at),
            "unverified_since": format_time(self.unverified_since) if self.unverified_since is not None else None,
            "pending": self.pending,
        }


_DETAIL = {
    "licence_missing": "this corpus has no licence block, so nothing is allowed",
    "licence_ambiguous": 'the manifest carries two different licence blocks ("licence" and "license")',
    "unknown_scope": "the licence names a scope this software does not know",
    "newer_version": "the licence is a newer version than this software understands",
    "withdrawn": "the hub no longer serves this corpus to this client",
    "not_visible": "this corpus is private and you are not on its access list",
}


def stamp_of(reading: Reading, standing: Standing) -> str:
    """What a Verdict is bound to: the licence and settings as read, and how fresh they are."""
    return hashlib.sha256(("%s|%s" % (reading.stamp, standing._key())).encode("utf-8")).hexdigest()


def decide(reading: Reading, capability: Any, identity: Optional[Identity] = None, now: Any = None,
           standing: Optional[Standing] = None) -> Verdict:
    """The decision for a manifest already read. Never raises."""
    identity = identity if isinstance(identity, Identity) else Identity.anonymous()
    standing = standing if isinstance(standing, Standing) else Standing()
    try:
        t = to_epoch(now)
    except Exception:
        return Verdict(_SEAL, False, "bad_clock", str(capability), reading.corpus_id,
                       "the clock given to the gate is not a UTC time", "", 0.0)
    cap = canonical_capability(capability)
    lic = reading.licence
    unverified = standing.revalidated_at if standing.unverified else None
    stamp = stamp_of(reading, standing)

    checked_at = t

    def answer(reason, detail="", pending=None, valid_until=None):
        return Verdict(_SEAL, reason == ALLOWED, reason, cap or str(capability), reading.corpus_id,
                       detail or _DETAIL.get(reason, ""), lic.scope, checked_at, unverified, pending, valid_until, stamp)

    if cap is None:
        return answer("unknown_capability", "%r is not a capability (known: %s)" % (capability, ", ".join(ALL_CAPABILITIES)))
    if reading.refusal:
        return answer(reading.refusal, "; ".join(reading.problems[:3]) or _DETAIL.get(reading.refusal, ""))
    if standing.withdrawn:
        return answer("withdrawn")
    if reading.visibility != "public" and not identity.service:
        if not identity.email or (identity.email != reading.owner_email and identity.email not in reading.access):
            return answer("not_visible")
    if cap == SEE:
        return answer(ALLOWED)
    if lic.status == _licence.MISSING:
        return answer("licence_missing")
    if lic.status != _licence.OK:
        reason = lic.status if lic.status in (_licence.UNKNOWN_SCOPE, _licence.NEWER_VERSION) else "licence_invalid"
        return answer(reason, "; ".join(lic.problems[:3]))

    pending = None
    closes = [(lic.revoked_at, "revoked"), (lic.expires_at, "expired")]
    floor = standing.floor
    if floor is not None and floor > t:
        t = floor                               # the clock was set back: time does not run backwards here
    for moment, name in closes:
        if moment is None or moment > t:
            continue
        known_online = standing.revalidated_at is None or moment <= standing.revalidated_at
        # An expiry is a date the device holds: its own clock applies it, online or not.
        if name == "expired" or not standing.unverified or known_online:
            return answer(name, "the licence %s at %s" % ("was revoked" if name == "revoked" else "expired",
                                                          format_time(moment)))
        pending = pending or name
    if not lic.grants(cap):
        return answer("not_granted", lic.why_off(cap))
    ahead = [m for m, _ in closes if m is not None and m > t]
    detail = ""
    if pending:
        detail = "the licence's revocation date passed while this device was offline; it keeps working until the hub is reached"
    return answer(ALLOWED, detail, pending, min(ahead) if ahead else None)


def judge(manifest: Any, capability: Any, identity: Optional[Identity] = None, now: Any = None,
          standing: Optional[Standing] = None) -> Verdict:
    """The gate, for a manifest dict. Never raises; refuses what it cannot read."""
    return decide(read_manifest(manifest), capability, identity, now, standing)


# ── admission: what a content accessor demands ───────────────────────────────────────────

class GateRequired(PermissionError):
    """Corpus content was asked for without an allowed, current Verdict for it."""

    def __init__(self, message: str, verdict: Optional[Verdict] = None):
        super().__init__(message)
        self.verdict = verdict


class Grant:
    """Proof that the gate allowed one of `capabilities` for one corpus. Stores accept nothing
    else. Only admit() makes one."""

    __slots__ = ("corpus_id", "capability", "_seal")

    def __init__(self, seal, corpus_id: str, capability: str):
        if seal is not _SEAL:
            raise TypeError("a Grant comes from gate.admit()")
        object.__setattr__(self, "corpus_id", corpus_id)
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "_seal", seal)

    def __setattr__(self, name, value):
        raise AttributeError("a Grant does not change")


def admit(verdict: Any, corpus_id: str, stamp: str, capabilities: Tuple[str, ...], now: float,
          max_age: float) -> Grant:
    """Turn a Verdict into a Grant, or raise GateRequired saying why not."""
    if not isinstance(verdict, Verdict):
        raise GateRequired("corpus content needs a Verdict from Corpus.may(); got %s" % type(verdict).__name__)
    if not verdict.allowed:
        raise GateRequired("refused: %s (%s)" % (verdict.reason, verdict.detail), verdict)
    if verdict.corpus_id != corpus_id:
        raise GateRequired("that Verdict is for %s, not %s" % (verdict.corpus_id, corpus_id), verdict)
    if verdict.capability not in capabilities:
        raise GateRequired("that Verdict allows %s; this needs %s" % (verdict.capability, " or ".join(capabilities)), verdict)
    if verdict._stamp != stamp:
        raise GateRequired("the corpus has changed since that Verdict; ask the gate again", verdict)
    if now - verdict.checked_at > max_age or now < verdict.checked_at - 1:
        raise GateRequired("that Verdict is too old; ask the gate again", verdict)
    if verdict.valid_until is not None and now >= verdict.valid_until:
        raise GateRequired("the licence has closed since that Verdict; ask the gate again", verdict)
    return Grant(_SEAL, corpus_id, verdict.capability)


def check_grant(grant: Any, corpus_id: str) -> None:
    """What every store method calls first."""
    if not isinstance(grant, Grant) or getattr(grant, "_seal", None) is not _SEAL or grant.corpus_id != corpus_id:
        raise GateRequired("corpus content is reached through Corpus accessors and a Verdict, not directly")
