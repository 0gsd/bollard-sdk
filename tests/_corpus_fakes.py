# SPDX-License-Identifier: Apache-2.0
"""Stand-ins for the corpus tests: a fake hub on a loopback port, made-up manifests, and an
Ed25519 signer (the SDK itself only verifies). Nothing here talks to a real service."""
import base64
import gzip
import hashlib
import http.server
import io
import json
import pathlib
import sys
import threading
import urllib.parse
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck.corpus import _ed25519  # noqa: E402


def manifest(number=9001, slug="PLACEHOLDERS", licence="full", **extra):
    """A made-up manifest. `licence` is a scope name, a block, or None for no block at all."""
    m = {"schema_version": 1, "id": "%04d-%s" % (number, slug), "number": number, "slug": slug,
         "name": "The Placeholders: %s" % slug.title(), "artist": "The Placeholders",
         "display_label": "%04d-%s" % (number, slug)}
    if isinstance(licence, str):
        m["licence"] = {"schema": "popboll.licence/1", "version": 1, "scope": licence}
    elif licence is not None:
        m["licence"] = licence
    m.update(extra)
    return m


def block(scope="full", **flags):
    out = {"schema": "popboll.licence/1", "version": 1, "scope": scope}
    out.update(flags)
    return out


def mrph5(midi=b"MThd-combined"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("combined.mid", midi)
    return buf.getvalue()


MORPUS = {
    "alpha.md": b"# Alpha\nnotes for a made-up song\n",
    "alpha.mid": b"MThd-alpha",
    "beta.md": b"# Beta\n",
    "beta.mid": b"MThd-beta",
    "STATUS.md": b"built\n",
    "corpus_dna.json": b'{"song_shapes": [], "made_up": true}',
}


class Clock:
    """A clock the tests move by hand."""

    def __init__(self, start=1900000000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeHub:
    """A hub that serves what the test puts in it, and records what it was asked."""

    def __init__(self, token="s3cr3t-for-tests"):
        self.token = token
        self.corpora = {}            # id -> {"manifest", "morpus": {name: bytes}, "tracks": [...], "audio": {...}, "art": {...}, "mrph5": {...}}
        self.requests = []           # (path, headers dict)
        self.fail = 0                # an HTTP status every request gets while non-zero
        self.redirects = {}          # path -> Location
        self.release = None
        self.gzip = True
        self.gate = "enforce"        # what /api/version states as corpus_gate; None states nothing
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_GET(self):
                hub._serve(self)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True)
        self.thread.start()

    def add(self, m, morpus=None, **more):
        entry = {"manifest": m, "morpus": dict(MORPUS if morpus is None else morpus),
                 "tracks": [], "audio": {}, "art": {}, "mrph5": {}}
        entry.update(more)
        self.corpora[m["id"]] = entry
        return entry

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def paths(self):
        return [p for p, _ in self.requests]

    # ---- serving ---------------------------------------------------------------------
    def _send(self, h, status, body=b"", ctype="application/json", headers=None):
        etag = '"%s"' % hashlib.sha1(body).hexdigest()[:20]
        if status == 200 and h.headers.get("If-None-Match") == etag:
            status, body = 304, b""
        extra = dict(headers or {})
        # gzip == "all": a hub (or something in front of it) that compresses whatever it is allowed to.
        if status in (200, 206) and self.gzip and "gzip" in (h.headers.get("Accept-Encoding") or "") and (
                ctype == "application/json" or self.gzip == "all"):
            body = gzip.compress(body)
            extra["Content-Encoding"] = "gzip"
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(body)))
        if status in (200, 304):
            h.send_header("ETag", etag)
        for k, v in extra.items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(body)

    def _serve(self, h):
        parts = urllib.parse.urlsplit(h.path)
        self.requests.append((h.path, {k.lower(): v for k, v in h.headers.items()}))
        if self.fail:
            return self._send(h, self.fail, b'{"error":"down"}')
        if parts.path in self.redirects:
            return self._send(h, 302, headers={"Location": self.redirects[parts.path]})
        if parts.path == "/api/version":
            about = {"service": "fake-hub", "version": "0.0.0"}
            if self.gate is not None:
                about["corpus_gate"] = self.gate
            return self._send(h, 200, json.dumps(about).encode())
        if self.token and h.headers.get("Authorization") != "Bearer " + self.token:
            return self._send(h, 401, b'{"error":"unauthorized"}')
        segs = [urllib.parse.unquote(s) for s in parts.path[len("/api/"):].split("/")] if parts.path.startswith("/api/") else []
        query = urllib.parse.parse_qs(parts.query)
        if segs == ["bollawax", "latest"] and self.release is not None:
            return self._send(h, 200, json.dumps(self.release).encode())
        # Who is asking, as a 0.2.4 hub reads it: a named person (X-Pop-For, or ?for=), else the
        # holder of the read token (the engine), else nobody.
        who = ((query.get("for") or [""])[0] or h.headers.get("X-Pop-For") or "").strip().lower()

        def people(m):
            return [str(x).strip().lower() for x in [m.get("owner_email")] + list(m.get("access", [])) if x]

        if segs == ["corpi"]:
            rows = []
            for cid, e in sorted(self.corpora.items()):
                m = e["manifest"]
                if who and isinstance(m, dict) and m.get("visibility", "public") != "public" and who not in people(m):
                    continue
                rows.append({"id": cid, "name": m.get("name") if isinstance(m, dict) else ""})
            return self._send(h, 200, json.dumps(rows + [{"id": "not an id"}, "junk"]).encode())
        if len(segs) < 2 or segs[0] != "corpi" or segs[1] not in self.corpora:
            return self._send(h, 404, b'{"error":"not found"}')
        e = self.corpora[segs[1]]
        rest = segs[2:]
        m = e["manifest"]
        private = isinstance(m, dict) and m.get("visibility", "public") != "public"
        if private and who and who not in people(m):
            return self._send(h, 404, b'{"error":"not_visible"}')
        study_only = private and not who          # the token alone is study only
        if not rest:
            if study_only:
                m = redact_people(m)
            body = m if isinstance(m, bytes) else json.dumps(m).encode()
            return self._send(h, 200, body)
        if study_only and rest[0] != "morpus":
            return self._send(h, 404, b'{"error":"not_visible"}')
        if rest == ["morpus"]:
            return self._send(h, 200, json.dumps(
                [{"name": n, "size": len(b), "updated": "2031-01-01T00:00:00Z"} for n, b in sorted(e["morpus"].items())]
                + [{"name": "../escape.md", "size": 1}]).encode())
        if rest[0] == "morpus" and len(rest) == 2 and rest[1] in e["morpus"] and not (
                e.get("packed") and rest[1].endswith(".mid")):
            return self._send(h, 200, e["morpus"][rest[1]], "application/octet-stream")
        if rest[0] == "mrph5" and len(rest) == 2 and rest[1] + ".mrph5" in e["morpus"]:
            return self._send(h, 200, e["morpus"][rest[1] + ".mrph5"], "application/octet-stream")
        if rest == ["tracks"]:
            return self._send(h, 200, json.dumps(e["tracks"]).encode())
        def ranged(data, ctype):
            rng = h.headers.get("Range")
            more = {"Accept-Ranges": "bytes", "Set-Cookie": "never=relayed"}
            if rng:
                start, _, end = rng[len("bytes="):].partition("-")
                size = len(data)
                if start == "":                              # a suffix range: the last n bytes
                    first, last = max(0, size - int(end)), size - 1
                else:
                    first, last = int(start), min(int(end), size - 1) if end else size - 1
                if first >= size:
                    return self._send(h, 416, b"", ctype, dict(more, **{"Content-Range": "bytes */%d" % size}))
                more["Content-Range"] = "bytes %d-%d/%d" % (first, last, size)
                return self._send(h, 206, data[first:last + 1], ctype, more)
            return self._send(h, 200, data, ctype, more)
        if rest[0] == "audio" and "/".join(rest[1:]) in e["audio"]:
            return ranged(e["audio"]["/".join(rest[1:])], "audio/mpeg")
        if rest[0] == "attestation" and len(rest) == 3 and rest[2] in e.get("locker", {}).get(rest[1], {}):
            return self._send(h, 200, e["locker"][rest[1]][rest[2]], "application/octet-stream")
        if rest[0] == "art" and len(rest) == 2 and rest[1] in e["art"]:
            if h.headers.get("Range"):
                return ranged(e["art"][rest[1]], "image/png")
            return self._send(h, 200, e["art"][rest[1]], "image/png")
        return self._send(h, 404, b'{"error":"not found"}')


def redact_people(m):
    """A manifest as a hub gives it to the engine for a corpus that is not public."""
    out = {k: v for k, v in m.items() if k not in ("owner_email", "access", "license_note")}
    for key in ("licence", "license"):
        if isinstance(out.get(key), dict):
            out[key] = {k: v for k, v in out[key].items() if k not in ("granted_by", "statements")}
    return out


class Recorder:
    """A second server that must never be asked anything: it records whoever does."""

    def __init__(self):
        self.requests = []
        rec = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                rec.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def write_local(root, m, morpus=None, files=None):
    """A corpus folder on disk."""
    root = pathlib.Path(root)
    (root / "morpus").mkdir(parents=True, exist_ok=True)
    (root / "corpus.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    for name, data in (MORPUS if morpus is None else morpus).items():
        (root / "morpus" / name).write_bytes(data)
    for rel, data in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


# ── Ed25519 signing, for building test records. The SDK has no signing code. ─────────────

def _encode(pt):
    zinv = pow(pt[2], _ed25519._P - 2, _ed25519._P)
    x, y = pt[0] * zinv % _ed25519._P, pt[1] * zinv % _ed25519._P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _expand(secret):
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public(secret):
    return _encode(_ed25519._mul(_expand(secret)[0], _ed25519._G))


def ed25519_sign(secret, message):
    a, prefix = _expand(secret)
    pub = _encode(_ed25519._mul(a, _ed25519._G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _ed25519._L
    big_r = _encode(_ed25519._mul(r, _ed25519._G))
    h = int.from_bytes(hashlib.sha512(big_r + pub + message).digest(), "little") % _ed25519._L
    return big_r + ((r + h * a) % _ed25519._L).to_bytes(32, "little")


def pem(der, label="PUBLIC KEY"):
    body = base64.encodebytes(der).decode("ascii")
    return ("-----BEGIN %s-----\n%s-----END %s-----\n" % (label, body, label)).encode("ascii")


def ed25519_pem(raw_public):
    return pem(_ed25519.SPKI_PREFIX + raw_public)
