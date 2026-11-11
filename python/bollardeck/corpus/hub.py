# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus.hub: the one client for a Bollawax hub (bollawax.org or a stand-in).

    hub = HubClient("https://bollawax.org", token="...", player="my-player", cache_dir="/var/cache/corpora")
    corpus = hub.corpus("9001-PLACEHOLDERS")
    verdict = corpus.may("study")

What it speaks (all GET):

    /api/corpi                          the listing
    /api/corpi/<ID>                     the manifest (ETag)
    /api/corpi/<ID>/morpus              the morpus index
    /api/corpi/<ID>/morpus/<name>       one morpus file
    /api/corpi/<ID>/mrph5/<slug>        one MRPH5 bundle
    /api/corpi/<ID>/tracks              the playlist
    /api/corpi/<ID>/audio/<path>        one recording (Range)
    /api/corpi/<ID>/art/<name>          one cover
    /api/bollawax/latest[?profile=&arch=]   the image release record
    /api/version                        {..., "corpus_gate": "enforce" | "report"}

Every request carries the bearer token (when there is one), X-Pop-Player and X-Pop-Device (when
given), asks for gzip, and revalidates with If-None-Match when a copy is cached. A redirect to
another scheme, host or port is refused, so the token never leaves the hub; so is any URL a
listing returns that points elsewhere.

Who the client acts for. A hub's read token alone is STUDY ONLY for a corpus that
is not public: the client is then the platform's engine, and the hub gives it the morpus and a
manifest with the people taken out, and answers 404 for tracks, audio, art and bundles. To reach
those, name the person the client acts for: `HubClient(..., acting_for="ada@example.org")`, or
per call (`hub.corpus(id, acting_for=...)`, `hub.listing(acting_for=...)`). The name travels in
the header X-Pop-For and never in a URL. It is what the caller says and the hub checks nothing
(sign-in arrives with 0.2.5): it narrows what a token holder gets and proves nothing. A corpus
fetched for a person is cached apart from the engine's copy, under <cache>/.for/<hash>/, so a
manifest with addresses in it never replaces the redacted one a device studies from.

What a hub owes in return, since the same URL now answers differently for different people:
every corpus route (the listing included) must answer with `Vary: X-Pop-For, Authorization`,
and nothing of a corpus that is not public may be sent with shared caching (`Cache-Control:
private, no-store`), so no cache between the hub and a client hands one person's answer to
another. Bollawax 0.2.4 does both. The JavaScript client also asks its own browser cache to
keep nothing of a request made in a person's name.

The hub's rollout switch. `/api/version` states `corpus_gate`: "enforce" (the hub refuses what
the gate refuses, a manifest with no licence block included) or "report" (it still answers the
old way for those, and counts what it would refuse). `hub.corpus_gate()` reads it. It is
information for a host: this client's own gate always enforces, and there is no way to read
content the gate refuses (see "A report-only window" in the package docstring).

The public methods return metadata (listings, release records) and Corpus objects. Corpus
content is fetched only by the private store behind a Corpus, which takes a Grant from the gate.

Cache (when cache_dir is given), laid out like a corpus root so plain files can be read:

    <cache>/<ID>/corpus.json         the manifest as the hub last served it
    <cache>/<ID>/.remote.json        ETags, the morpus index, and when the licence block was
                                     last revalidated ("revalidated_at")
    <cache>/<ID>/morpus/<name>       morpus files, fetched on first use, kept only when the
                                     licence lets them be stored here
    <cache>/.remote_index.json       the ids the hub listed last time
    <cache>/.http/<hash>.json        other JSON answers (listing, release record) with their ETags
    <cache>/.for/<hash>/<ID>/...     the same layout, for a corpus fetched for a named person

Revalidation. Before a corpus is used (Corpus.may), its manifest is revalidated when the last
check is older than `revalidate_after` seconds. The hub answering 200 or 304 refreshes the
licence block; 404 or 410 marks the corpus withdrawn, and the gate refuses it. When the hub
cannot be reached (no network, a timeout, 5xx, or 401/403/429) the cached corpus keeps working
and every Verdict carries `unverified_since`; the next try is `retry_after` seconds later.
"""

import gzip
import hashlib
import http.client
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Mapping, Optional, Tuple

from .. import schema as _schema
from . import gate as _gate
from .licence import Licence, format_time, parse_time
from .model import (DNA_NAME, MANIFEST_NAME, MORPUS_DIRNAME, RELAY_HEADERS, Corpus, ManifestRefused, NotAvailable,
                    RangedAudio, _NoStore, range_value, safe_name, safe_rel_path)

STATE_NAME = ".remote.json"
INDEX_NAME = ".remote_index.json"
HTTP_DIRNAME = ".http"
HEADER_PLAYER = "X-Pop-Player"
HEADER_DEVICE = "X-Pop-Device"
HEADER_FOR = "X-Pop-For"
FOR_DIRNAME = ".for"
VERSION_GATE_KEY = "corpus_gate"
GATE_MODES = ("enforce", "report")
USER_AGENT = "bollard-sdk corpus client"
CORPUS_ID = re.compile(r"^[0-9]{4}-[A-Za-z0-9_]+\Z")
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
_LOOPBACK = ("localhost", "127.0.0.1", "::1")

# The environment variables Pop Boll's own programs use today. Read only by config_from_env().
ENV_URL = "POPBOLLARD_BOLLAWAX_URL"
ENV_TOKEN = "POPBOLLARD_BOLLAWAX_TOKEN"
ENV_PLAYER_ID = "POPBOLLARD_PLAYER_ID"
ENV_CORPUS_DIRS = "POPBOLLARD_CORPUS_DIRS"
ENV_CACHE_DIR = "POPBOLLARD_CORPUS_CACHE_DIR"
ENV_DATA_DIR = "POPBOLLARD_DATA_DIR"
ENV_REMOTE_REFRESH = "POPBOLLARD_REMOTE_REFRESH_SEC"
ENV_REMOTE_TIMEOUT = "POPBOLLARD_REMOTE_TIMEOUT_SEC"
ENV_PREFER_REMOTE = "POPBOLLARD_PREFER_REMOTE_CORPORA"


class HubError(Exception):
    """The hub answered, and the answer cannot be used. `status` is the HTTP status when the
    trouble was one, else None."""

    def __init__(self, message: str = "", status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class HubUnreachable(HubError):
    """The hub did not answer (`status` None), or would not talk to this client just now
    (`status` 401, 403, 429 or 5xx)."""


class CorpusUnavailable(LookupError):
    """The corpus is not on the hub (or the hub is unreachable) and nothing is cached.
    `reason` is "bad_id" (not a corpus id, nothing was asked), "not_served" (the hub answered
    404 or 410: `status`) or "unreachable" (`status` is what the hub answered, or None when it
    did not answer at all)."""

    def __init__(self, message: str = "", reason: str = "unreachable", status: Optional[int] = None):
        super().__init__(message)
        self.reason = reason
        self.status = status


class Listing(list):
    """A hub's corpus listing: a list of rows that also says where it came from. `from_cache`
    is True when the hub could not be reached and these are the rows it gave last time."""

    from_cache = False


def person(value: Any) -> str:
    """The name of the person a client acts for, as it is sent in X-Pop-For: trimmed and
    lower-cased, "" for nobody. Raises ValueError for a name that cannot be a header value."""
    if value is not None and not isinstance(value, str):
        raise ValueError("the person a client acts for is a string (an address), not %r" % (value,))
    name = _gate.norm_email(value)
    if any(not 0x21 <= ord(ch) <= 0x7e for ch in name) or len(name) > 320:
        raise ValueError("%r cannot be sent as the person a client acts for (printable ASCII, no spaces)" % (value,))
    return name


def config_from_env(environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """THE ONLY PLACE THIS PACKAGE READS THE ENVIRONMENT. Returns plain settings:

        {"hub": {...keyword arguments for HubClient, or None when no hub is configured},
         "roots": [Path, ...]      from POPBOLLARD_CORPUS_DIRS (os.pathsep-separated)
         "prefer_remote": bool}    from POPBOLLARD_PREFER_REMOTE_CORPORA=1

    Nothing else in bollardeck.corpus looks at os.environ: pass these on yourself.
    """
    env = os.environ if environ is None else environ

    def text(name: str) -> str:
        return (env.get(name) or "").strip()

    def number(name: str, default: float) -> float:
        try:
            return float(text(name) or default)
        except ValueError:
            return default

    cache = text(ENV_CACHE_DIR) or (os.path.join(text(ENV_DATA_DIR), "corpus_cache") if text(ENV_DATA_DIR) else "")
    hub = None
    if text(ENV_URL):
        hub = {"base_url": text(ENV_URL), "token": text(ENV_TOKEN), "player": text(ENV_PLAYER_ID),
               "cache_dir": Path(cache).expanduser() if cache else None,
               "timeout": number(ENV_REMOTE_TIMEOUT, 10.0), "revalidate_after": number(ENV_REMOTE_REFRESH, 300.0)}
    roots = [Path(p).expanduser() for p in text(ENV_CORPUS_DIRS).split(os.pathsep) if p.strip()]
    return {"hub": hub, "roots": roots, "prefer_remote": text(ENV_PREFER_REMOTE) == "1"}


def _origin_of(url: str) -> Tuple[str, str, int]:
    parts = urllib.parse.urlsplit(url)
    scheme = (parts.scheme or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    return scheme, (parts.hostname or "").lower(), port or {"http": 80, "https": 443}.get(scheme, 0)


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only when it stays on the hub's scheme, host and port."""

    def __init__(self, origin):
        self._origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin_of(newurl) != self._origin:
            raise HubError("refused a redirect away from the hub (to %s)" % urllib.parse.urlsplit(newurl).netloc)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%d.%d.tmp" % (path.name, os.getpid(), threading.get_ident()))
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class HubClient:
    """One hub. Configure it with arguments; config_from_env() gives today's environment names."""

    def __init__(self, base_url: str, token: str = "", *, player: str = "", device: str = "",
                 cache_dir=None, timeout: float = 10.0, revalidate_after: float = 300.0,
                 retry_after: float = 30.0, user_agent: str = USER_AGENT, allow_insecure_token: bool = False,
                 clock=time.time, acting_for: str = ""):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self._origin = _origin_of(self.base_url)
        if self._origin[0] not in ("http", "https") or not self._origin[1]:
            raise ValueError("a hub address is http(s)://host[:port], not %r" % base_url)
        if token and self._origin[0] == "http" and self._origin[1] not in _LOOPBACK and not allow_insecure_token:
            raise ValueError("refusing to send a token over plain http to %s" % self._origin[1])
        self._token = str(token or "")
        self.player = str(player or "")
        self.device = str(device or "")
        self.acting_for = person(acting_for)      # the person this client acts for; "" is nobody (the engine)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = float(timeout)
        self.revalidate_after = float(revalidate_after)
        self.retry_after = float(retry_after)
        self.user_agent = user_agent
        self._clock = clock
        self._opener = urllib.request.build_opener(_SameHostRedirects(self._origin))
        self._lock = threading.Lock()
        self.stats = {"requests": 0, "not_modified": 0, "bytes": 0, "errors": 0}

    def __repr__(self) -> str:
        return "HubClient(%s)" % self.base_url

    # ---- URLs ------------------------------------------------------------------------
    def _url(self, *parts: str, query: Optional[Mapping[str, str]] = None, safe: str = "") -> str:
        url = self.base_url + "/api/" + "/".join(urllib.parse.quote(p, safe=safe) for p in parts)
        q = {k: v for k, v in (query or {}).items() if v}
        return url + ("?" + urllib.parse.urlencode(q) if q else "")

    def _on_hub(self, ref: Any) -> Optional[str]:
        """An absolute URL on this hub for a reference a listing returned, or None."""
        ref = ref.strip() if isinstance(ref, str) else ""
        if not ref:
            return None
        if ref.startswith("/") and not ref.startswith("//"):
            ref = self.base_url + ref
        return ref if ref.startswith(("http://", "https://")) and _origin_of(ref) == self._origin else None

    # ---- one request -----------------------------------------------------------------
    def _who(self, acting_for: Optional[str]) -> str:
        """The person a call acts for: the call's own, else the client's. "" is nobody."""
        return self.acting_for if acting_for is None else person(acting_for)

    def _open(self, url: str, etag: str = "", byte_range: Optional[Tuple[Optional[int], Optional[int]]] = None,
              accept: str = "", acting_for: Optional[str] = None, as_stored: bool = False):
        """Open one GET on the hub. Returns the response; HTTP error statuses come back as the
        HTTPError (readable like a response). Raises HubUnreachable on network failure.
        `as_stored` asks for the bytes as they are, never compressed: for a body that is handed
        on unread (a recording)."""
        if _origin_of(url) != self._origin:
            raise HubError("refused to ask %s: not this hub" % urllib.parse.urlsplit(url).netloc)
        headers = {"User-Agent": self.user_agent}
        if accept:
            headers["Accept"] = accept
        if self.player:
            headers[HEADER_PLAYER] = self.player
        if self.device:
            headers[HEADER_DEVICE] = self.device
        who = self._who(acting_for)
        if who:
            headers[HEADER_FOR] = who             # in a header, never in the URL
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        if etag:
            headers["If-None-Match"] = etag
        if byte_range:
            headers["Range"] = range_value(byte_range)
        if as_stored or byte_range:
            headers["Accept-Encoding"] = "identity"
        else:
            headers["Accept-Encoding"] = "gzip"
        with self._lock:
            self.stats["requests"] += 1
        try:
            return self._opener.open(urllib.request.Request(url, headers=headers), timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            return exc
        except HubError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            # http.client.HTTPException: an answer that is not HTTP (a bad status line, a
            # connection closed mid-headers). Nothing usable answered.
            with self._lock:
                self.stats["errors"] += 1
            raise HubUnreachable("%s is not answering (%s)" % (self._origin[1], getattr(exc, "reason", None) or repr(exc))) from None

    def _get(self, url: str, etag: str = "", accept: str = "", max_bytes: int = MAX_JSON_BYTES,
             acting_for: Optional[str] = None) -> Tuple[int, bytes, str]:
        """(status, body, etag). 200, 304, 404 and 410 are returned; the hub being down, busy
        or unwilling (5xx, 401, 403, 429) raises HubUnreachable; anything else raises HubError."""
        resp = self._open(url, etag=etag, accept=accept, acting_for=acting_for)
        try:
            status = getattr(resp, "status", None) or resp.getcode()
            if status == 304:
                with self._lock:
                    self.stats["not_modified"] += 1
                return 304, b"", str(resp.headers.get("ETag") or etag)
            if status in (404, 410):
                return status, b"", ""
            if status in (401, 403, 429) or status >= 500:
                with self._lock:
                    self.stats["errors"] += 1
                raise HubUnreachable("%s answered %d" % (self._origin[1], status), status)
            if status != 200:
                raise HubError("%s answered %d" % (self._origin[1], status), status)
            try:
                body = resp.read(max_bytes + 1)
                if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                    with gzip.GzipFile(fileobj=io.BytesIO(body)) as gz:
                        body = gz.read(max_bytes + 1)
            except (OSError, EOFError, http.client.HTTPException) as exc:
                raise HubUnreachable("%s: the answer broke off (%s)" % (self._origin[1], exc)) from None
            if len(body) > max_bytes:
                raise HubError("%s sent more than %d bytes" % (self._origin[1], max_bytes))
            with self._lock:
                self.stats["bytes"] += len(body)
            return 200, body, str(resp.headers.get("ETag") or "")
        finally:
            resp.close()

    def _get_json(self, url: str, keep: bool = True, acting_for: Optional[str] = None) -> Tuple[Any, bool]:
        """(parsed JSON, fresh). With a cache, revalidates by ETag and falls back to the cached
        answer when the hub is unreachable (fresh is then False). An answer is cached for the
        person it was asked for, and never given to another."""
        slot = None
        saved: Dict[str, Any] = {}
        who = self._who(acting_for)
        if self.cache_dir is not None and keep:
            key = url + ("\n" + who if who else "")
            slot = self.cache_dir / HTTP_DIRNAME / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + ".json")
            saved = _read_json(slot)
            if saved.get("url") != url or saved.get("for", "") != who:
                saved = {}
        try:
            status, body, etag = self._get(url, etag=saved.get("etag", ""), accept="application/json", acting_for=who)
        except HubUnreachable:
            if "body" in saved:
                return saved["body"], False
            raise
        if status == 304 and "body" in saved:
            return saved["body"], True
        if status != 200:
            raise HubError("%s answered %d for %s" % (self._origin[1], status, urllib.parse.urlsplit(url).path), status)
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HubError("%s sent something that is not JSON" % self._origin[1]) from None
        if slot is not None:
            record = {"url": url, "etag": etag, "body": data}
            if who:
                record["for"] = who
            _atomic_write(slot, json.dumps(record).encode("utf-8"))
        return data, True

    # ---- metadata --------------------------------------------------------------------
    def version(self) -> Dict[str, Any]:
        """What the hub says about itself at /api/version, as it wrote it."""
        data, _ = self._get_json(self._url("version"), keep=False, acting_for="")
        return data if isinstance(data, dict) else {}

    def corpus_gate(self) -> Optional[str]:
        """The hub's rollout switch, from /api/version: "enforce" or "report", or None when the
        hub does not state one (a hub from before 0.2.4) or states something else. Read-only,
        and information for the host: this client's gate always enforces. Raises HubError when
        the hub cannot be asked."""
        mode = self.version().get(VERSION_GATE_KEY)
        return mode if mode in GATE_MODES else None

    def latest(self, profile: str = "", arch: str = "") -> Dict[str, Any]:
        """The image release record (schema image-release). Raises HubError when the hub's
        answer does not fit the schema."""
        data, _ = self._get_json(self._url("bollawax", "latest", query={"profile": profile, "arch": arch}), acting_for="")
        problems = _schema.validate("image-release", data)
        if problems:
            raise HubError("the release record does not fit its schema: %s" % "; ".join(str(p) for p in problems[:3]))
        return data

    def listing(self, for_email: str = "", acting_for: Optional[str] = None) -> "Listing":
        """The hub's corpus listing: one summary row per corpus, as the hub wrote it. For a
        person (`acting_for`, or the client's own; `for_email` is the older name for the same
        thing), only what that person may see. The name is sent as X-Pop-For, not in the URL.
        Rows without a corpus id are dropped. The result is a list whose `from_cache` is True
        when the hub could not be reached and the rows are the ones it gave last time."""
        who = person(for_email) or self._who(acting_for)
        data, fresh = self._get_json(self._url("corpi"), acting_for=who)
        rows = Listing(r for r in (data if isinstance(data, list) else [])
                       if isinstance(r, dict) and isinstance(r.get("id"), str) and CORPUS_ID.match(r["id"]))
        rows.from_cache = not fresh
        if fresh and not who and self.cache_dir is not None:
            _atomic_write(self.cache_dir / INDEX_NAME, json.dumps(
                {"base_url": self.base_url, "ids": [r["id"] for r in rows],
                 "checked_at": format_time(self._clock())}, indent=1).encode("utf-8"))
        return rows

    def cached_ids(self) -> List[str]:
        """The ids this hub listed the last time it answered (from the cache)."""
        if self.cache_dir is None:
            return []
        idx = _read_json(self.cache_dir / INDEX_NAME)
        if idx.get("base_url") != self.base_url or not isinstance(idx.get("ids"), list):
            return []
        return [i for i in idx["ids"] if isinstance(i, str) and CORPUS_ID.match(i)]

    # ---- corpora ---------------------------------------------------------------------
    def corpus(self, corpus_id: str, acting_for: Optional[str] = None) -> Corpus:
        """One corpus, revalidated now when the hub answers, from the cache when it does not.
        `acting_for` names the person every request for this corpus is made for (default: the
        client's own; "" for nobody). Raises CorpusUnavailable (nothing to give: its `reason`
        and `status` say why) or ManifestRefused (the SDK will not read it)."""
        if not isinstance(corpus_id, str) or not CORPUS_ID.match(corpus_id):
            raise CorpusUnavailable("%r is not a corpus id" % (corpus_id,), "bad_id")
        store = _HubStore(self, corpus_id, self._who(acting_for))
        store.freshen(float(self._clock()), force=True)
        manifest = store.manifest
        if manifest is None:
            if store.state.get("withdrawn_at"):
                raise CorpusUnavailable("%s: the hub does not serve it" % corpus_id, "not_served",
                                        store.state.get("last_status") or 404)
            raise CorpusUnavailable("%s: the hub is unreachable (%s) and nothing is cached"
                                    % (corpus_id, store.state.get("last_error", "no answer")),
                                    "unreachable", store.state.get("last_status"))
        if manifest.get("id") != corpus_id:
            raise ManifestRefused("manifest_invalid", ("#/id: asked for %s, got %r" % (corpus_id, manifest.get("id")),),
                                  self._url("corpi", corpus_id))
        return Corpus(manifest, store=store, clock=self._clock, where=self._url("corpi", corpus_id))

    def corpora(self, acting_for: Optional[str] = None) -> Tuple[List[Corpus], List[Tuple[str, str, Tuple[str, ...]]]]:
        """(every corpus the hub lists, [(id, reason, problems) for each one refused]). When the
        hub is unreachable, the corpora it listed last time come from the cache."""
        who = self._who(acting_for)
        try:
            ids = [r["id"] for r in self.listing(acting_for=who)]
        except HubError:
            ids = self.cached_ids() if not who else []
        found: List[Corpus] = []
        refused: List[Tuple[str, str, Tuple[str, ...]]] = []
        for cid in ids:
            try:
                found.append(self.corpus(cid, acting_for=who))
            except ManifestRefused as exc:
                refused.append((cid, exc.reason, exc.problems))
            except (CorpusUnavailable, HubError) as exc:
                refused.append((cid, "unavailable", (str(exc),)))
        return found, refused


class _HubStore(_NoStore):
    """A corpus on a hub, mirrored lazily into the cache. Private: content methods take a Grant."""

    source = "hub"

    def __init__(self, client: HubClient, corpus_id: str, acting_for: str = ""):
        super().__init__(corpus_id)
        self._client = client
        self._for = acting_for                  # every request of this store is made for this person
        base = client.cache_dir
        if base is not None and acting_for:     # a person's copy is kept apart from the engine's
            base = base / FOR_DIRNAME / hashlib.sha256(acting_for.encode("utf-8")).hexdigest()[:24]
        self.root = base / corpus_id if base is not None else None
        self.state: Dict[str, Any] = {}
        self.manifest: Optional[Dict[str, Any]] = None
        self._licence = Licence.from_block(None)
        if self.root is not None:
            state = _read_json(self.root / STATE_NAME)
            if (state.get("base_url") == client.base_url and state.get("id") == corpus_id
                    and state.get("for", "") == acting_for):
                self.state = state
                cached = _read_json(self.root / MANIFEST_NAME)
                if cached:
                    self._set_manifest(cached)
        if not self.state:
            self.state = {"base_url": client.base_url, "id": corpus_id}
            if acting_for:
                self.state["for"] = acting_for

    # ---- freshness (no content) --------------------------------------------------------
    def _set_manifest(self, manifest: Dict[str, Any]) -> None:
        self.manifest = manifest
        self._licence = _gate.read_manifest(manifest).licence

    def _time(self, key: str) -> Optional[float]:
        try:
            return parse_time(self.state.get(key))
        except ValueError:
            return None

    def _save(self) -> None:
        if self.root is not None:
            _atomic_write(self.root / STATE_NAME, (json.dumps(self.state, indent=1) + "\n").encode("utf-8"))

    def standing(self) -> _gate.Standing:
        return _gate.Standing("hub", self._time("revalidated_at"), self.state.get("reachable", True) is not False,
                              bool(self.state.get("withdrawn_at")), self._time("witnessed_at"))

    def freshen(self, now: float, force: bool = False, witness: bool = True) -> Optional[Dict[str, Any]]:
        """Revalidate the manifest when due. Returns the new manifest when the hub sent one.
        `witness` says `now` is this machine's own clock, read just now, and not a time a
        caller supplied: only such a time is recorded as witnessed."""
        st, c = self.state, self._client
        attempted = self._time("attempted_at")
        wait = c.revalidate_after if st.get("reachable", True) is not False else c.retry_after
        if not force and attempted is not None and 0 <= now - attempted < wait:
            return None
        st["attempted_at"] = format_time(now)
        # The latest time this cache has seen on its own clock since the hub last confirmed
        # the block: the gate reads no time before it, so a clock that is set back while the
        # hub cannot be reached does not reopen a licence that has closed.
        seen = self._time("witnessed_at")
        if witness and (seen is None or now > seen):
            st["witnessed_at"] = format_time(now)
        try:
            status, body, etag = c._get(c._url("corpi", self.corpus_id),
                                        etag=st.get("manifest_etag", "") if self.manifest is not None else "",
                                        accept="application/json", acting_for=self._for)
            fresh = None
            if status == 200:
                try:
                    fresh = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    fresh = None
                if not isinstance(fresh, dict):
                    raise HubUnreachable("the hub sent a manifest that is not a JSON object")
        except HubError as exc:
            st["reachable"], st["last_error"], st["last_status"] = False, str(exc), exc.status
            self._save()
            return None
        st["reachable"] = True
        st.pop("last_error", None)
        st["last_status"] = status
        st["revalidated_at"] = st["checked_at"] = format_time(now)
        # The hub answered: this moment is confirmed, and the floor starts again from it. One
        # wrong reading of the clock (a device that woke up in 2051) heals at the next contact.
        st["witnessed_at"] = st["revalidated_at"]
        if status in (404, 410):
            st["withdrawn_at"] = st.get("withdrawn_at") or format_time(now)
            self._save()
            return None
        st.pop("withdrawn_at", None)
        if fresh is not None:
            st["manifest_etag"] = etag
            self._set_manifest(fresh)
            if self.root is not None:
                _atomic_write(self.root / MANIFEST_NAME, body)
        self._save()
        return fresh

    def _may_keep(self) -> bool:
        """May a morpus file be written to this machine's disk? The licence must let the morpus
        be stored, and on a device (a client that names one) let copies sit on devices."""
        if self.root is None or not self._licence.grants("store_morpus"):
            return False
        return self._licence.grants("device_copies") or not self._client.device

    def _fetch(self, url: str, what: str, max_bytes: int = MAX_FILE_BYTES, etag: str = "") -> Tuple[int, bytes, str]:
        """(status, body, etag) for one file of this corpus: 200, 304 (with `etag`), 404 or 410."""
        try:
            return self._client._get(url, etag=etag, max_bytes=max_bytes, acting_for=self._for)
        except HubUnreachable as exc:
            raise NotAvailable("%s: could not fetch %s (%s)" % (self.corpus_id, what, exc), "unreachable", exc.status) from None
        except HubError as exc:
            raise NotAvailable("%s: could not fetch %s (%s)" % (self.corpus_id, what, exc), "bad_answer", exc.status) from None

    # ---- content: a Grant first, every time --------------------------------------------
    def morpus_index(self, grant) -> List[str]:
        _gate.check_grant(grant, self.corpus_id)
        return sorted(self._index(grant))

    def _index(self, grant) -> Dict[str, Dict[str, Any]]:
        _gate.check_grant(grant, self.corpus_id)
        st, c = self.state, self._client
        try:
            status, body, etag = c._get(c._url("corpi", self.corpus_id, "morpus"),
                                        etag=st.get("morpus_etag", "") if isinstance(st.get("morpus"), list) else "",
                                        accept="application/json", acting_for=self._for)
            if status == 200:
                rows = json.loads(body.decode("utf-8"))
                st["morpus"] = [{"name": r["name"], "size": int(r.get("size", 0) or 0), "updated": str(r.get("updated", ""))}
                                for r in (rows if isinstance(rows, list) else [])
                                if isinstance(r, dict) and safe_name(r.get("name"))]
                st["morpus_etag"] = etag
                self._save()
        except (HubError, ValueError, UnicodeDecodeError, TypeError):
            pass                                  # offline or unreadable: the index from last time
        if not isinstance(st.get("morpus"), list):
            raise NotAvailable("%s: the morpus index is not cached and the hub is not answering" % self.corpus_id,
                               "unreachable")
        return {r["name"]: r for r in st["morpus"] if isinstance(r, dict) and safe_name(r.get("name"))}

    def read_morpus(self, grant, name: str) -> bytes:
        _gate.check_grant(grant, self.corpus_id)
        if not safe_name(name):
            raise NotAvailable("%s: %r is not a morpus file name" % (self.corpus_id, name), "bad_name")
        path = self.root / MORPUS_DIRNAME / name if self.root is not None else None
        known = {r.get("name"): r for r in self.state.get("morpus") or [] if isinstance(r, dict)}
        have = path is not None and path.is_file()
        if have and name != DNA_NAME:
            want = known.get(name, {}).get("size")
            if not isinstance(want, int) or want <= 0 or path.stat().st_size == want:
                return path.read_bytes()
        # The DNA is rebuilt in place under one name, so it is asked for again each time: with
        # the ETag of the copy on disk, so a DNA that has not changed is not sent again.
        etags = self.state.get("morpus_etags") if isinstance(self.state.get("morpus_etags"), dict) else {}
        etag = etags.get(name, "") if have and name == DNA_NAME and isinstance(etags.get(name), str) else ""
        c = self._client
        try:
            status, body, new_etag = self._fetch(c._url("corpi", self.corpus_id, "morpus", name), name, etag=etag)
        except NotAvailable:
            if have:
                return path.read_bytes()          # offline: the copy from last time
            raise
        if status == 304 and have:
            return path.read_bytes()
        if status != 200 and name.endswith(".mid") and name[:-4] + ".mrph5" in self._index(grant):
            # A packed corpus withholds the raw MIDI; its MRPH5 bundle carries the combined file.
            status, bundle, _ = self._fetch(c._url("corpi", self.corpus_id, "morpus", name[:-4] + ".mrph5"), name)
            if status == 200:
                try:
                    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
                        body = z.read("combined.mid")
                except (zipfile.BadZipFile, KeyError):
                    raise NotAvailable("%s: the bundle for %s cannot be read" % (self.corpus_id, name), "bad_answer", 200) from None
        if status != 200:
            raise NotAvailable("%s: the hub has no %s" % (self.corpus_id, name), "not_found", status)
        if path is not None and self._may_keep():
            _atomic_write(path, body)
            if name == DNA_NAME:                  # the ETag is kept only with the bytes it names
                self.state["morpus_etags"] = dict(etags, **{name: new_etag}) if new_etag else {
                    k: v for k, v in etags.items() if k != name}
                self._save()
        return body

    def morpus_path(self, grant, name: str) -> Path:
        _gate.check_grant(grant, self.corpus_id)
        if not self._may_keep():
            raise NotAvailable("%s: morpus files may not be kept on this machine (no cache, or the licence "
                               "does not let them be stored here)" % self.corpus_id, "not_kept")
        self.read_morpus(grant, name)
        return self.root / MORPUS_DIRNAME / name

    def export_bundle(self, grant, slug: str) -> bytes:
        _gate.check_grant(grant, self.corpus_id)
        slug = slug[:-6] if isinstance(slug, str) and slug.endswith(".mrph5") else slug
        if not safe_name(slug):
            raise NotAvailable("%s: %r is not a bundle name" % (self.corpus_id, slug), "bad_name")
        status, body, _ = self._fetch(self._client._url("corpi", self.corpus_id, "mrph5", slug), slug + ".mrph5")
        if status != 200:
            raise NotAvailable("%s: the hub has no bundle %s" % (self.corpus_id, slug), "not_found", status)
        return body

    def tracks(self, grant) -> List[Dict[str, Any]]:
        _gate.check_grant(grant, self.corpus_id)
        c = self._client
        status, body, _ = self._fetch(c._url("corpi", self.corpus_id, "tracks"), "the track listing", MAX_JSON_BYTES)
        if status != 200:
            raise NotAvailable("%s: the hub has no track listing for this caller" % self.corpus_id, "not_found", status)
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict) and data.get("audio") == "not_licensed":
            raise NotAvailable("%s: %s" % (self.corpus_id, data.get("message") or "the hub has no recordings to give"),
                               "not_licensed", status)
        rows = data.get("tracks") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise NotAvailable("%s: the hub sent no usable track listing" % self.corpus_id, "bad_answer", status)
        out = [t for t in (self._track(r) for r in rows if isinstance(r, dict)) if t]
        out.sort(key=lambda t: (t["album"].lower(), t["track_no"] or 0, t["file"].lower()))
        return out

    def _track(self, raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        c, cid = self._client, self.corpus_id
        file = safe_rel_path(raw.get("file"))
        low = file.lower()
        if not file or not low.endswith((".mp3", ".wbol")):
            return None
        packed = low.endswith(".wbol")
        if packed:                                # only the hub's own chapter extract, never another host
            url = c._on_hub(raw.get("url"))
            tail = url[len(c._url("corpi", cid, "wbol")) + 1:].split("/") if url and url.startswith(c._url("corpi", cid, "wbol") + "/") else []
            if len(tail) != 3 or tail[1] != "chapter" or not tail[2].isdigit() or not tail[0] or ".." in tail[0]:
                return None
        else:
            url = c._url("corpi", cid, "audio", file, safe="/")
        art = raw.get("art_url") or raw.get("art")
        art = art.strip() if isinstance(art, str) else ""
        art_url = (c._on_hub(art) if art.startswith(("/", "http://", "https://"))
                   else c._url("corpi", cid, "art", art) if safe_name(art) else None)

        def num(v, kind):
            try:
                n = kind(v)
            except (TypeError, ValueError):
                return None
            return n if n >= 0 else None

        return {"file": file, "title": str(raw.get("title") or file.rsplit("/", 1)[-1].rsplit(".", 1)[0]),
                "album": str(raw.get("album") or ""), "track_no": num(raw.get("track_no"), int),
                "artist": str(raw.get("artist") or ""), "duration_sec": num(raw.get("duration_sec"), float),
                "bytes": num(raw.get("bytes"), int), "audio_url": url, "art_url": art_url,
                "content_type": "audio/webm" if packed else "audio/mpeg",
                "audio_format": "wbol/1" if packed else "mp3"}

    def _audio_url(self, file: Any) -> str:
        c = self._client
        if isinstance(file, Mapping):             # a row from tracks()
            url = c._on_hub(file.get("audio_url"))
            if not url or not url.startswith(c._url("corpi", self.corpus_id) + "/"):
                raise NotAvailable("%s: that track does not point into this corpus" % self.corpus_id, "bad_name")
            return url
        rel = safe_rel_path(file)
        if not rel:
            raise NotAvailable("%s: %r is not a recording's path" % (self.corpus_id, file), "bad_name")
        return c._url("corpi", self.corpus_id, "audio", rel, safe="/")

    def _open_audio(self, file: Any, byte_range, accepted: Tuple[int, ...]):
        try:
            resp = self._client._open(self._audio_url(file), byte_range=byte_range, acting_for=self._for, as_stored=True)
        except HubUnreachable as exc:
            raise NotAvailable("%s: could not open the recording (%s)" % (self.corpus_id, exc), "unreachable", exc.status) from None
        except HubError as exc:
            raise NotAvailable("%s: could not open the recording (%s)" % (self.corpus_id, exc), "bad_answer", exc.status) from None
        status = getattr(resp, "status", None) or resp.getcode()
        if status not in accepted:
            resp.close()
            reason = ("not_found" if status in (404, 410) else "bad_range" if status == 416
                      else "unreachable" if status in (401, 403, 429) or status >= 500 else "bad_answer")
            raise NotAvailable("%s: the hub answered %d for that recording" % (self.corpus_id, status), reason, status)
        return status, resp

    def open_audio(self, grant, file: Any, byte_range: Optional[Tuple[Optional[int], Optional[int]]]) -> BinaryIO:
        _gate.check_grant(grant, self.corpus_id)
        return self._open_audio(file, byte_range, (200, 206))[1]

    def open_audio_ranged(self, grant, file: Any, byte_range) -> RangedAudio:
        _gate.check_grant(grant, self.corpus_id)
        status, resp = self._open_audio(file, byte_range, (200, 206, 416))
        headers = {name: str(resp.headers.get(name)) for name in RELAY_HEADERS if resp.headers.get(name) is not None}
        return RangedAudio(status, headers, resp)

    def read_art(self, grant, name: str) -> bytes:
        _gate.check_grant(grant, self.corpus_id)
        base = name.split("/")[-1] if isinstance(name, str) else ""
        if not safe_name(base):
            raise NotAvailable("%s: %r is not an art file name" % (self.corpus_id, name), "bad_name")
        status, body, _ = self._fetch(self._client._url("corpi", self.corpus_id, "art", base), base)
        if status != 200:
            raise NotAvailable("%s: the hub has no art %s" % (self.corpus_id, base), "not_found", status)
        return body
