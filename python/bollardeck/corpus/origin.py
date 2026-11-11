# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus.origin: discover a self-hosted corpus (popboll.origin/1).

An artist who keeps their recordings on their own server puts a discovery file at the base of
the folder, <base>popboll-corpus.json, and a manifest of the recordings beside it.

    origin = fetch_origin("https://files.example/popboll/", auth=("basic", "reader", "..."))
    origin.live, origin.status, origin.scope, origin.problems
    rows = origin.manifest()        # [{"path", "size", "sha256"}, ...]

What this does: fetch the discovery file, check it against the "origin" schema, fetch and parse
the manifest, and report what does not meet the rules of the hosting page. What it does not do:
download a recording. An origin is not yet a corpus (it has no corpus id and no
popboll.licence/1 block), so the gate has nothing to judge; recordings are pulled by the hub,
which then serves the corpus like any other.

Rules enforced: HTTPS only (plain http is allowed for a loopback address when
allow_http_loopback=True, for tests); a redirect is followed once and only on the same scheme,
host and port, so the credential never leaves the origin; the discovery file is at most 64 KiB
and the manifest at most 4 MiB; manifest paths are relative, sorted, free of "..", and name
recordings in the accepted formats.
"""

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .. import schema as _schema

DISCOVERY_NAME = "popboll-corpus.json"
SCHEMA = "popboll.origin/1"
MAX_DISCOVERY_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 3
RECORDING_EXTS = (".mp3", ".wav", ".flac", ".aif", ".aiff", ".m4a")
_HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
_LOOPBACK = ("localhost", "127.0.0.1", "::1")


class OriginError(Exception):
    """The origin cannot be used: unreachable, not HTTPS, or its files do not fit the format."""


def _origin_of(url: str) -> Tuple[str, str, int]:
    parts = urllib.parse.urlsplit(url)
    scheme = (parts.scheme or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    return scheme, (parts.hostname or "").lower(), port or {"http": 80, "https": 443}.get(scheme, 0)


class _OneRedirectSameHost(urllib.request.HTTPRedirectHandler):
    max_redirections = 1

    def __init__(self, origin):
        self._origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin_of(newurl) != self._origin:
            raise OriginError("refused a redirect away from the origin's host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_origin_manifest(data: bytes) -> List[Dict[str, Any]]:
    """An origin's MANIFEST.tsv: "path<TAB>size<TAB>sha256" per recording, LF, UTF-8, sorted by
    path, no header. Raises OriginError naming the first line that breaks a rule."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise OriginError("the manifest is not UTF-8") from None
    if "\r" in text:
        raise OriginError("the manifest must use LF line endings")
    if text and not text.endswith("\n"):
        raise OriginError("the manifest has no final newline")
    rows: List[Dict[str, Any]] = []
    for n, line in enumerate(text.split("\n")[:-1], 1):
        cols = line.split("\t")
        if len(cols) != 3 or not cols[1].isdigit() or not _HEX64.match(cols[2]):
            raise OriginError("manifest line %d is not path, size, sha256" % n)
        path = cols[0]
        segs = path.split("/")
        if (not path or path.startswith("/") or "\\" in path or any(s in ("", ".", "..") for s in segs)
                or any(ord(c) < 32 or ord(c) == 127 for c in path)):
            raise OriginError("manifest line %d: %r is not a safe relative path" % (n, path))
        if len(segs) - 1 > MAX_DEPTH:
            raise OriginError("manifest line %d: deeper than %d folders" % (n, MAX_DEPTH))
        if not path.lower().endswith(RECORDING_EXTS):
            raise OriginError("manifest line %d: %r is not a recording format this accepts" % (n, path))
        rows.append({"path": path, "size": int(cols[1]), "sha256": cols[2]})
    paths = [r["path"] for r in rows]
    if len(set(paths)) != len(paths):
        raise OriginError("the manifest lists a path twice")
    if paths != sorted(paths, key=lambda p: p.encode("utf-8")):
        raise OriginError("the manifest is not sorted by path")
    return rows


class Origin:
    """A self-hosted corpus as its discovery file describes it."""

    def __init__(self, base: str, discovery: Dict[str, Any], etag: str, last_modified: str, problems: List[str],
                 fetch):
        self.base = base
        self.discovery = discovery
        self.etag = etag
        self.last_modified = last_modified
        self.problems = problems          # rules of the hosting page this origin does not meet
        self._fetch = fetch

    @property
    def status(self) -> str:
        return self.discovery["status"]

    @property
    def live(self) -> bool:
        """True when the artist says it is live and nothing in `problems` says otherwise."""
        return self.status == "live" and not self.problems

    @property
    def name(self) -> str:
        return self.discovery["corpus"]["name"]

    @property
    def artist(self) -> str:
        return self.discovery["corpus"]["artist"]

    @property
    def scope(self) -> str:
        return self.discovery["licence"]["scope"]

    def url(self, rel: str) -> str:
        """The absolute URL of a path inside the folder (spaces and the like percent-encoded)."""
        return self.base + urllib.parse.quote(rel, safe="/")

    def manifest(self) -> List[Dict[str, Any]]:
        """Fetch and parse the manifest of recordings. Raises OriginError."""
        status, body, _ = self._fetch(self.url(self.discovery["files"]["manifest"]), MAX_MANIFEST_BYTES)
        if status != 200:
            raise OriginError("the origin answered %d for its manifest" % status)
        return parse_origin_manifest(body)

    def summary(self) -> Dict[str, Any]:
        return {"base": self.base, "name": self.name, "artist": self.artist, "scope": self.scope,
                "status": self.status, "live": self.live, "auth": self.discovery["auth"]["type"],
                "etag": self.etag, "last_modified": self.last_modified, "problems": list(self.problems)}


def fetch_origin(base: str, *, auth: Optional[Tuple[str, ...]] = None, timeout: float = 10.0,
                 allow_http_loopback: bool = False, user_agent: str = "bollard-sdk origin client") -> Origin:
    """Discover the self-hosted corpus at `base`. `auth` is None, ("basic", user, password) or
    ("bearer", token). Raises OriginError when the origin cannot be reached or its discovery
    file does not fit popboll.origin/1."""
    base = str(base or "").strip()
    if not base.endswith("/"):
        base += "/"
    origin = _origin_of(base)
    loop_ok = allow_http_loopback and origin[0] == "http" and origin[1] in _LOOPBACK
    if not origin[1] or (origin[0] != "https" and not loop_ok):
        raise OriginError("an origin is served over HTTPS: %r is refused" % base)
    kind = auth[0] if auth else "none"
    headers = {"User-Agent": user_agent}
    if kind == "basic" and auth is not None and len(auth) == 3:
        headers["Authorization"] = "Basic " + base64.b64encode(("%s:%s" % (auth[1], auth[2])).encode("utf-8")).decode("ascii")
    elif kind == "bearer" and auth is not None and len(auth) == 2:
        headers["Authorization"] = "Bearer " + auth[1]
    elif kind != "none":
        raise OriginError('auth is None, ("basic", user, password) or ("bearer", token)')
    opener = urllib.request.build_opener(_OneRedirectSameHost(origin))

    def fetch(url: str, limit: int) -> Tuple[int, bytes, Any]:
        if _origin_of(url) != origin:
            raise OriginError("refused to leave the origin's host")
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
                body = resp.read(limit + 1)
                if len(body) > limit:
                    raise OriginError("the origin sent more than %d bytes" % limit)
                return resp.status, body, resp.headers
        except urllib.error.HTTPError as exc:
            return exc.code, b"", exc.headers
        except OriginError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OriginError("the origin is not answering (%s)" % getattr(exc, "reason", exc)) from None

    status, body, got = fetch(base + DISCOVERY_NAME, MAX_DISCOVERY_BYTES)
    if status in (401, 403):
        raise OriginError("the origin refused the credential (%d)" % status)
    if status != 200:
        raise OriginError("the origin answered %d for %s" % (status, DISCOVERY_NAME))
    try:
        discovery = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise OriginError("%s is not UTF-8 JSON" % DISCOVERY_NAME) from None
    found = _schema.validate("origin", discovery)
    if found:
        raise OriginError("%s does not fit %s: %s" % (DISCOVERY_NAME, SCHEMA, "; ".join(str(p) for p in found[:5])))
    etag, modified = str(got.get("ETag") or ""), str(got.get("Last-Modified") or "")
    problems: List[str] = []
    if not etag and not modified:
        problems.append("the discovery file is served without ETag or Last-Modified")
    if discovery["auth"]["type"] != kind:
        problems.append("auth.type says %s, and this request used %s" % (discovery["auth"]["type"], kind))
    if discovery["status"] != "live":
        problems.append("the artist has set status to %s" % discovery["status"])
    return Origin(base, discovery, etag, modified, problems, fetch)
