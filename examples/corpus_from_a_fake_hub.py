# SPDX-License-Identifier: Apache-2.0
"""
List and read corpora from a hub, respecting each one's licence and settings.

This starts a tiny stand-in hub on a loopback port (three made-up corpora), then does what any
client does: find the corpora, ask the gate, read what the gate allows, show the notices.
Nothing here talks to a real service. Run it from the repository root:

    python3 examples/corpus_from_a_fake_hub.py
"""
import http.server
import json
import pathlib
import sys
import tempfile
import threading
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "python"))

from bollardeck.corpus import GateRequired, HubClient, Identity, MissingCorpora, discover  # noqa: E402

TOKEN = "example-token"


def manifest(number, slug, licence, **more):
    m = {"schema_version": 1, "id": "%04d-%s" % (number, slug), "number": number, "slug": slug,
         "name": "The Placeholders: %s" % slug.title(), "artist": "The Placeholders",
         "display_label": "%04d-%s" % (number, slug), "licence": licence}
    m.update(more)
    return m


CORPORA = {
    "9001-OPEN": manifest(9001, "OPEN", {"schema": "popboll.licence/1", "version": 1, "scope": "morpus_only"},
                          license_note="Used with the permission of The Placeholders."),
    "9002-REVOKED": manifest(9002, "REVOKED", {"schema": "popboll.licence/1", "version": 1, "scope": "full",
                                               "revoked_at": "2001-01-01T00:00:00Z"}),
    "9003-UNLICENSED": manifest(9003, "UNLICENSED", None),
    "9004-PRIVATE": manifest(9004, "PRIVATE", {"schema": "popboll.licence/1", "version": 1, "scope": "full"},
                             visibility="private", owner_email="ada@example.org"),
}
MORPUS = {"first-song.md": b"# First Song\nA made-up song in C.\n", "first-song.mid": b"MThd (not really)",
          "corpus_dna.json": b'{"song_shapes": ["AABA"]}'}


class Hub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        segs = [urllib.parse.unquote(s) for s in path.split("/")[2:]] if path.startswith("/api/") else []
        body = None
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401)
            self.end_headers()
            return
        if segs == ["corpi"]:
            body = json.dumps([{"id": cid, "name": m["name"]} for cid, m in sorted(CORPORA.items())]).encode()
        elif len(segs) >= 2 and segs[0] == "corpi" and segs[1] in CORPORA:
            if len(segs) == 2:
                body = json.dumps(CORPORA[segs[1]]).encode()
            elif segs[2:] == ["morpus"]:
                body = json.dumps([{"name": n, "size": len(b)} for n, b in sorted(MORPUS.items())]).encode()
            elif len(segs) == 4 and segs[2] == "morpus":
                body = MORPUS.get(segs[3])
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Length", str(len(body or b"")))
        self.end_headers()
        self.wfile.write(body or b"")


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hub)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as cache:
            hub = HubClient("http://127.0.0.1:%d" % server.server_address[1], token=TOKEN,
                            player="example-player", cache_dir=cache)
            found = discover(hub=hub)

            print("Corpora on the hub, and what a visitor may do with each:")
            visitor = Identity(email="visitor@example.org")
            for corpus in found.corpora:
                for capability in ("see", "study", "stream_audio"):
                    verdict = corpus.may(capability, identity=visitor)
                    print("  %-16s %-13s %-8s %s" % (corpus.id, capability, "yes" if verdict else "no",
                                                    "" if verdict else "%s: %s" % (verdict.reason, verdict.detail)))

            print("\nReading 9001-OPEN:")
            corpus = found.corpora.get("9001-OPEN")
            verdict = corpus.may("study", identity=visitor)
            for notes, midi in corpus.study_pairs(verdict):
                text = corpus.read_morpus(notes, verdict).decode("utf-8")
                print("  %s + %s: %s" % (notes, midi, text.splitlines()[0]))
            print("  song shapes:", corpus.dna(verdict)["song_shapes"])
            for line in corpus.notices()["lines"]:
                print("  notice:", line)

            print("\nContent is not reachable without the gate's yes:")
            revoked = found.corpora.get("9002-REVOKED")
            try:
                revoked.study_pairs(revoked.may("study"))
            except GateRequired as exc:
                print("  9002-REVOKED:", exc)
            try:
                corpus.tracks(verdict)                       # a "study" verdict does not open the recordings
            except GateRequired as exc:
                print("  9001-OPEN recordings:", exc)

            print("\nAsking for a corpus that is not there is an error, not a quiet substitution:")
            try:
                found.corpora.select(["9001-OPEN", "9099-ABSENT"])
            except MissingCorpora as exc:
                print(" ", exc)
            print("  with if_missing=\"skip\":", found.corpora.select(["9001-OPEN", "9099-ABSENT"], if_missing="skip").ids)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
