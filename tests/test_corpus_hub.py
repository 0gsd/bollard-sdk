# SPDX-License-Identifier: Apache-2.0
"""The hub client, its cache and revalidation, and discovery. Everything runs against a fake hub
on a loopback port; nothing here reaches a real service."""
import ast
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from _corpus_fakes import MORPUS, ROOT, Clock, FakeHub, Recorder, block, manifest, mrph5, write_local

from bollardeck.corpus import (Corpus, CorpusUnavailable, GateRequired, HubClient, HubError, HubUnreachable, Identity,
                               ManifestRefused, MissingCorpora, NotAvailable, config_from_env, discover)
from bollardeck.corpus import gate, model
from bollardeck.corpus import hub as hub_module
from bollardeck.corpus.licence import format_time

CID = "9001-PLACEHOLDERS"
PACKAGE = ROOT / "python" / "bollardeck" / "corpus"


class HubCase(unittest.TestCase):
    def setUp(self):
        self.hub = FakeHub()
        self.addCleanup(self.hub.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = pathlib.Path(self.tmp.name) / "cache"
        self.clock = Clock()

    def client(self, **kw):
        args = dict(token=self.hub.token, player="example-player", cache_dir=self.cache, clock=self.clock, timeout=5)
        args.update(kw)
        return HubClient(self.hub.url, **args)

    def set_licence(self, **flags):
        m = dict(self.hub.corpora[CID]["manifest"])
        m["licence"] = block(m["licence"]["scope"], **flags)
        self.hub.corpora[CID]["manifest"] = m


class Requests(HubCase):
    def test_token_identity_headers_and_gzip(self):
        self.hub.add(manifest())
        c = self.client(device="PBOLL-EXM-0001").corpus(CID)
        self.assertEqual(c.id, CID)
        path, headers = self.hub.requests[-1]
        self.assertEqual(path, "/api/corpi/" + CID)
        self.assertEqual(headers["authorization"], "Bearer " + self.hub.token)
        self.assertEqual((headers["x-pop-player"], headers["x-pop-device"]), ("example-player", "PBOLL-EXM-0001"))
        self.assertIn("gzip", headers["accept-encoding"])
        self.assertIn("bollard-sdk", headers["user-agent"])
        self.hub.gzip = False
        self.assertEqual(self.client(cache_dir=None).corpus(CID).id, CID)
        bare = self.client(player="", cache_dir=None, token=self.hub.token)
        bare.version()
        self.assertNotIn("x-pop-player", self.hub.requests[-1][1])
        self.assertNotIn("x-pop-device", self.hub.requests[-1][1])

    def test_a_wrong_token_is_an_unreachable_hub_not_a_missing_corpus(self):
        self.hub.add(manifest())
        with self.assertRaisesRegex(CorpusUnavailable, "unreachable"):
            self.client(token="wrong").corpus(CID)
        with self.assertRaises(HubUnreachable):
            self.client(token="").listing()

    def test_etag_revalidation(self):
        self.hub.add(manifest())
        client = self.client()
        client.corpus(CID)
        self.assertNotIn("if-none-match", self.hub.requests[-1][1])
        client.corpus(CID)
        self.assertIn("if-none-match", self.hub.requests[-1][1])
        self.assertEqual(client.stats["not_modified"], 1)
        other = self.client()                                   # a new process, same cache
        other.corpus(CID)
        self.assertEqual(other.stats["not_modified"], 1)
        rows = client.listing()
        self.assertEqual([r["id"] for r in rows], [CID])        # junk rows dropped
        client.listing()
        self.assertEqual(client.stats["not_modified"], 2)

    def test_a_hub_address_must_be_http_and_a_token_is_not_sent_in_the_clear(self):
        for bad in ("", "bollawax.org", "ftp://example.org", "file:///etc"):
            with self.assertRaises(ValueError, msg=bad):
                HubClient(bad)
        with self.assertRaisesRegex(ValueError, "plain http"):
            HubClient("http://hub.example", token="t")
        HubClient("http://hub.example")
        HubClient("http://hub.example", token="t", allow_insecure_token=True)
        HubClient("https://hub.example/", token="t")
        self.assertEqual(HubClient("https://hub.example/").base_url, "https://hub.example")

    def test_a_redirect_off_the_hub_is_refused_and_the_token_stays_home(self):
        elsewhere = Recorder()
        self.addCleanup(elsewhere.close)
        self.hub.add(manifest())
        self.hub.redirects["/api/corpi/" + CID] = elsewhere.url + "/api/corpi/" + CID
        with self.assertRaises(CorpusUnavailable):
            self.client().corpus(CID)
        self.assertEqual(elsewhere.requests, [], "the request, and the token with it, followed a redirect off the hub")
        self.hub.redirects["/api/corpi/" + CID] = "/api/corpi/9002-MOVED"
        self.hub.add(manifest(9002, "MOVED"))
        with self.assertRaises(ManifestRefused):                # followed on the same host; the id must still match
            self.client().corpus(CID)
        self.assertIn("/api/corpi/9002-MOVED", self.hub.paths())

    def test_a_client_asks_only_its_own_hub(self):
        client = self.client()
        with self.assertRaisesRegex(HubError, "not this hub"):
            client._get("http://127.0.0.1:1/api/corpi")
        self.assertIsNone(client._on_hub("https://elsewhere.example/api/corpi/x/art/a.png"))
        self.assertIsNone(client._on_hub("//elsewhere.example/a.png"))
        self.assertEqual(client._on_hub("/api/x"), self.hub.url + "/api/x")

    def test_latest_is_checked_against_its_schema(self):
        self.hub.release = json.loads((ROOT / "conformance" / "image-release" / "valid" / "single-image.json").read_text())
        self.assertEqual(self.client().latest()["version"], self.hub.release["version"])
        self.client().latest(profile="boll", arch="arm64")
        self.assertIn("profile=boll", self.hub.paths()[-1])
        self.hub.release = {"version": "not semver"}
        with self.assertRaisesRegex(HubError, "schema"):
            self.client(cache_dir=None).latest()

    def test_a_listing_for_a_person(self):
        self.hub.add(manifest())
        self.hub.add(manifest(9002, "PRIVATE", visibility="private", owner_email="ada@example.org"))
        client = self.client()
        self.assertEqual(len(client.listing()), 2)
        self.assertEqual([r["id"] for r in client.listing(for_email=" Mallory@Example.org ")], [CID])
        path, headers = self.hub.requests[-1]
        self.assertEqual((path, headers["x-pop-for"]), ("/api/corpi", "mallory@example.org"), "in a header, never in the URL")
        self.assertEqual(len(client.listing(for_email="ada@example.org")), 2)
        self.assertEqual(len(client.listing(acting_for="ada@example.org")), 2)
        self.assertEqual(client.cached_ids(), [CID, "9002-PRIVATE"])
        self.assertTrue(all("@" not in p and "%40" not in p and "for=" not in p for p in self.hub.paths()))

    def test_a_listing_says_when_it_came_from_the_cache(self):
        self.hub.add(manifest())
        self.hub.add(manifest(9002, "PRIVATE", visibility="private", owner_email="ada@example.org"))
        client = self.client()
        rows = client.listing()
        self.assertEqual((type(rows).__name__, isinstance(rows, list), rows.from_cache, len(rows)), ("Listing", True, False, 2))
        self.assertEqual(len(client.listing(acting_for="mallory@example.org")), 1)
        errors = client.stats["errors"]
        self.hub.fail = 503
        again = client.listing()
        self.assertEqual((again.from_cache, list(again), client.stats["errors"]), (True, list(rows), errors + 1))
        # One person's cached listing is never another's, nor the engine's.
        self.assertEqual(len(client.listing(acting_for="mallory@example.org")), 1)
        self.assertTrue(client.listing(acting_for="mallory@example.org").from_cache)
        with self.assertRaises(HubUnreachable):
            client.listing(acting_for="grace@example.org")
        with self.assertRaises(HubUnreachable):
            self.client(cache_dir=None).listing()

    def test_the_hub_s_rollout_switch_is_read_from_version(self):
        client = self.client(acting_for="ada@example.org")
        self.assertEqual(client.corpus_gate(), "enforce")
        self.assertNotIn("x-pop-for", self.hub.requests[-1][1], "the version is asked for nobody")
        self.hub.gate = "report"
        self.assertEqual((client.corpus_gate(), client.version()["corpus_gate"]), ("report", "report"))
        for unstated in (None, "sometimes", 1):
            self.hub.gate = unstated
            self.assertIsNone(client.corpus_gate())
        self.hub.fail = 503
        with self.assertRaises(HubUnreachable):
            client.corpus_gate()

    def test_unknown_ids_and_non_ids(self):
        with self.assertRaisesRegex(CorpusUnavailable, "does not serve"):
            self.client().corpus("9999-NOWHERE")
        for bad in ("../etc", "", None, "9001-BAD/..", "9001-OK\n"):
            with self.assertRaises(CorpusUnavailable):
                self.client().corpus(bad)
        self.assertEqual(len(self.hub.requests), 1)


class Revalidation(HubCase):
    def test_a_revocation_reaches_a_cached_corpus_at_the_next_revalidation(self):
        self.hub.add(manifest())
        c = self.client(revalidate_after=300).corpus(CID)
        v = c.may("study")
        self.assertTrue(v)
        self.assertIsNone(v.unverified_since)
        self.set_licence(revoked_at=format_time(self.clock.now - 5))
        self.clock.advance(60)
        self.assertTrue(c.may("study"), "inside the recheck interval the last answer stands")
        self.clock.advance(300)
        refused = c.may("study")
        self.assertEqual(refused.reason, "revoked")
        with self.assertRaisesRegex(GateRequired, "changed since"):
            c.study_pairs(v)                                    # the verdict from before no longer opens anything
        self.assertEqual(self.client().corpus(CID).may("study").reason, "revoked")   # and the cache holds it

    def test_offline_a_cached_corpus_keeps_working_and_says_since_when(self):
        self.hub.add(manifest())
        c = self.client(revalidate_after=300).corpus(CID)
        v = c.may("study")
        c.read_morpus("alpha.md", v)
        last_ok = self.clock.now
        self.hub.fail = 503
        self.clock.advance(3600)
        v = c.may("study")
        self.assertTrue(v)
        self.assertEqual(v.unverified_since, last_ok)
        self.assertEqual(v.as_dict()["unverified_since"], format_time(last_ok))
        self.assertEqual(c.read_morpus("alpha.md", v), MORPUS["alpha.md"])
        again = self.client().corpus(CID)                       # a restart while offline: from the cache
        v = again.may("study")
        self.assertTrue(v)
        self.assertEqual(v.unverified_since, last_ok)
        self.assertEqual(again.standing.reachable, False)

    def test_offline_means_no_answer_too(self):
        self.hub.add(manifest())
        client = self.client()
        c = client.corpus(CID)
        self.hub.close()
        self.addCleanup(setattr, self.hub, "close", lambda: None)
        self.clock.advance(3600)
        v = c.may("study")
        self.assertTrue(v)
        self.assertIsNotNone(v.unverified_since)
        with self.assertRaises(CorpusUnavailable):
            self.client(cache_dir=None).corpus(CID)             # nothing cached: nothing to give

    def test_an_expiry_the_device_holds_is_honoured_offline(self):
        expires = self.clock.now + 1000
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
        self.assertTrue(c.may("stream_audio"))
        self.hub.fail = 503
        self.clock.advance(900)
        v = c.may("stream_audio")
        self.assertTrue(v, "offline and before the date: the cached corpus keeps working")
        self.assertIsNotNone(v.unverified_since)
        self.clock.advance(1100)
        v = c.may("stream_audio")
        self.assertEqual((v.reason, v.pending), ("expired", None), "a date the device holds applies by the device's clock")
        self.assertIsNotNone(v.unverified_since)
        asked = len(self.hub.requests)
        self.clock.advance(10)
        c.may("stream_audio")
        self.assertEqual(len(self.hub.requests), asked, "an unreachable hub is not asked again before retry_after")
        self.hub.fail = 0
        self.clock.advance(31)
        v = c.may("stream_audio")
        self.assertEqual((v.reason, v.unverified_since, v.pending), ("expired", None, None))

    def test_a_revocation_made_while_offline_waits_for_the_next_contact(self):
        self.hub.add(manifest())
        c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
        self.assertTrue(c.may("study"))
        self.hub.fail = 503
        self.set_licence(revoked_at=format_time(self.clock.now + 10))     # news the device cannot hear
        self.clock.advance(3600)
        v = c.may("study")
        self.assertTrue(v, "a cached corpus keeps working until the device next reaches the network")
        self.assertIsNotNone(v.unverified_since)
        self.hub.fail = 0
        self.clock.advance(31)
        self.assertEqual(c.may("study").reason, "revoked")

    def test_a_date_already_known_online_is_not_forgiven_offline(self):
        self.hub.add(manifest(licence=block("full", revoked_at=format_time(self.clock.now - 10))))
        c = self.client().corpus(CID)
        self.assertEqual(c.may("study").reason, "revoked")
        self.hub.fail = 503
        self.clock.advance(3600)
        v = c.may("study")
        self.assertEqual(v.reason, "revoked")
        self.assertIsNotNone(v.unverified_since)

    def test_a_corpus_the_hub_stops_serving_is_withdrawn(self):
        self.hub.add(manifest())
        c = self.client(revalidate_after=10).corpus(CID)
        self.assertTrue(c.may("study"))
        entry = self.hub.corpora.pop(CID)
        self.clock.advance(11)
        self.assertEqual(c.may("study").reason, "withdrawn")
        self.assertEqual(c.may("see").reason, "withdrawn")
        self.assertEqual(self.client().corpus(CID).may("study").reason, "withdrawn")
        self.assertTrue((self.cache / CID / "corpus.json").is_file(), "nothing is deleted behind the caller's back")
        self.hub.corpora[CID] = entry
        self.clock.advance(11)
        self.assertTrue(c.may("study"), "served again: usable again")

    def test_a_manifest_the_hub_breaks_closes_the_corpus(self):
        self.hub.add(manifest())
        c = self.client(revalidate_after=10).corpus(CID)
        self.assertTrue(c.may("study"))
        self.hub.corpora[CID]["manifest"] = manifest(visibility="unlisted")
        self.clock.advance(11)
        self.assertEqual(c.may("study").reason, "manifest_invalid")
        self.assertEqual(c.name, "The Placeholders: Placeholders", "metadata stays the last good manifest's")
        with self.assertRaises(ManifestRefused):
            self.client().corpus(CID)
        self.hub.corpora[CID]["manifest"] = manifest(9002, "SWAPPED")
        self.clock.advance(11)
        self.assertEqual(c.may("study").reason, "manifest_invalid")
        self.hub.corpora[CID]["manifest"] = b"<html>not json</html>"
        self.clock.advance(11)
        v = c.may("study")
        self.assertEqual(v.reason, "manifest_invalid", "an unreadable answer leaves the last state standing")
        self.assertIsNotNone(v.unverified_since)

    def test_a_licence_widened_on_the_hub_is_picked_up(self):
        self.hub.add(manifest(licence="morpus_only"))
        c = self.client(revalidate_after=10).corpus(CID)
        self.assertEqual(c.may("export_morpus").reason, "not_granted")
        self.set_licence(export_morpus=True)
        c.refresh()
        self.assertTrue(c.may("export_morpus"))

    def test_the_cache_records_when_the_licence_was_last_revalidated(self):
        self.hub.add(manifest())
        self.client().corpus(CID)
        state = json.loads((self.cache / CID / ".remote.json").read_text())
        self.assertEqual(state["revalidated_at"], format_time(self.clock.now))
        self.assertEqual((state["base_url"], state["id"], state["reachable"]), (self.hub.url, CID, True))
        self.assertEqual(json.loads((self.cache / CID / "corpus.json").read_text())["id"], CID)
        other = FakeHub()
        self.addCleanup(other.close)
        with self.assertRaises(CorpusUnavailable):              # another hub's cache entry is not this hub's
            HubClient(other.url, token=other.token, cache_dir=self.cache, clock=self.clock).corpus(CID)


class Content(HubCase):
    def test_study_through_the_gate_and_into_the_cache(self):
        self.hub.add(manifest())
        c = self.client().corpus(CID)
        with self.assertRaises(GateRequired):
            c.study_pairs(c.may("stream_audio"))
        v = c.may("study")
        self.assertEqual(c.study_pairs(v), [("alpha.md", "alpha.mid"), ("beta.md", "beta.mid")])
        self.assertNotIn("../escape.md", c.morpus_index(v))
        self.assertEqual(c.read_morpus("alpha.mid", v), MORPUS["alpha.mid"])
        self.assertEqual(c.morpus_path("beta.mid", v), self.cache / CID / "morpus" / "beta.mid")
        self.assertEqual(c.dna(v)["made_up"], True)
        asked = len(self.hub.requests)
        c.read_morpus("alpha.mid", v)
        self.assertEqual(len(self.hub.requests), asked, "a cached file of the listed size is not fetched again")
        for bad in ("../x.md", "a/b.md", ".remote.json", ""):
            with self.assertRaises(NotAvailable):
                c.read_morpus(bad, v)
        with self.assertRaises(NotAvailable):
            c.read_morpus("missing.md", v)

    def test_morpus_is_kept_on_disk_only_where_the_licence_allows(self):
        self.hub.add(manifest(licence=block("full", device_copies=False)))
        on_device = self.client(device="PBOLL-EXM-0001").corpus(CID)
        v = on_device.may("study")
        self.assertEqual(on_device.read_morpus("alpha.md", v), MORPUS["alpha.md"])
        self.assertFalse((self.cache / CID / "morpus").exists(), "device_copies is off: nothing written on a device")
        with self.assertRaisesRegex(NotAvailable, "may not be kept"):
            on_device.morpus_path("alpha.md", v)
        server = self.client().corpus(CID)                       # not a device: store_morpus is enough
        server.read_morpus("alpha.md", server.may("study"))
        self.assertTrue((self.cache / CID / "morpus" / "alpha.md").is_file())
        nocache = self.client(cache_dir=None).corpus(CID)
        self.assertEqual(nocache.read_morpus("beta.md", nocache.may("study")), MORPUS["beta.md"])
        with self.assertRaises(NotAvailable):
            nocache.morpus_path("beta.md", nocache.may("study"))

    def test_a_packed_corpus_gives_its_midi_from_the_bundle(self):
        morpus = dict(MORPUS, **{"alpha.mrph5": mrph5(b"MThd-from-bundle")})
        self.hub.add(manifest(), morpus=morpus, packed=True)
        c = self.client().corpus(CID)
        self.assertEqual(c.read_morpus("alpha.mid", c.may("study")), b"MThd-from-bundle")
        with self.assertRaises(NotAvailable):
            c.read_morpus("beta.mid", c.may("study"))            # no bundle for this one

    def test_export_needs_export(self):
        morpus = dict(MORPUS, **{"alpha.mrph5": mrph5()})
        self.hub.add(manifest(licence=block("full", export_morpus=False)), morpus=morpus)
        c = self.client().corpus(CID)
        refused = c.may("export_morpus")
        self.assertEqual(refused.reason, "not_granted")
        for v in (refused, c.may("study")):
            with self.assertRaises(GateRequired):
                c.export_bundle("alpha", v)
        self.assertNotIn("/api/corpi/%s/mrph5/alpha" % CID, self.hub.paths())
        self.set_licence()
        c.refresh()
        self.assertEqual(c.export_bundle("alpha.mrph5", c.may("export_morpus")), morpus["alpha.mrph5"])

    def test_tracks_audio_and_art(self):
        elsewhere = "https://elsewhere.example"
        self.hub.add(manifest(), tracks={"tracks": [
            {"file": "b side/02 second.mp3", "title": "Second", "album": "B Side", "track_no": 2, "bytes": 10, "art": "cover.png"},
            {"file": "b side/01 first.mp3", "album": "B Side", "track_no": "1", "duration_sec": -4, "art": elsewhere + "/x.png"},
            {"file": "album.wbol", "url": "/api/corpi/%s/wbol/album/chapter/3" % CID, "album": "A"},
            {"file": "stolen.wbol", "url": elsewhere + "/api/corpi/%s/wbol/album/chapter/1" % CID},
            {"file": "other.wbol", "url": "/api/corpi/9002-OTHER/wbol/album/chapter/1"},
            {"file": "../climb.mp3"}, {"file": "notes.txt"}, "junk"]},
            audio={"b side/01 first.mp3": b"0123456789"}, art={"cover.png": b"PNG-made-up"})
        c = self.client().corpus(CID)
        v = c.may("stream_audio")
        tracks = c.tracks(v)
        self.assertEqual([t["file"] for t in tracks], ["album.wbol", "b side/01 first.mp3", "b side/02 second.mp3"])
        first = tracks[1]
        self.assertEqual((first["title"], first["track_no"], first["duration_sec"], first["art_url"]), ("01 first", 1, None, None))
        self.assertEqual(first["audio_url"], "%s/api/corpi/%s/audio/b%%20side/01%%20first.mp3" % (self.hub.url, CID))
        self.assertEqual(tracks[2]["art_url"], "%s/api/corpi/%s/art/cover.png" % (self.hub.url, CID))
        self.assertEqual((tracks[0]["audio_format"], tracks[0]["content_type"]), ("wbol/1", "audio/webm"))
        with c.open_audio(first, v, byte_range=(2, 5)) as audio:
            self.assertEqual(audio.read(), b"2345")
        self.assertEqual(self.hub.requests[-1][1]["range"], "bytes=2-5")
        with c.open_audio("b side/01 first.mp3", v) as audio:
            self.assertEqual(audio.read(), b"0123456789")
        for bad in ("../x.mp3", {"audio_url": elsewhere + "/a.mp3"}, {"audio_url": self.hub.url + "/api/corpi/9002-OTHER/audio/a.mp3"}, "gone.mp3"):
            with self.assertRaises(NotAvailable):
                c.open_audio(bad, v)
        self.assertEqual(c.read_art("cover.png", c.may("store_art")), b"PNG-made-up")
        with self.assertRaises(GateRequired):
            c.read_art("cover.png", v)

    def test_a_hub_that_says_not_licensed_is_believed(self):
        self.hub.add(manifest(), tracks={"audio": "not_licensed", "message": "MIDI-only corpus", "tracks": []})
        c = self.client().corpus(CID)
        with self.assertRaisesRegex(NotAvailable, "MIDI-only"):
            c.tracks(c.may("stream_audio"))

    def test_a_morpus_only_corpus_never_asks_the_hub_for_audio(self):
        self.hub.add(manifest(licence="morpus_only"), tracks={"tracks": [{"file": "a.mp3"}]}, audio={"a.mp3": b"x"})
        c = self.client().corpus(CID)
        v = c.may("stream_audio")
        self.assertEqual(v.reason, "not_granted")
        for call in (lambda: c.tracks(v), lambda: c.open_audio("a.mp3", v), lambda: c.tracks(c.may("study"))):
            with self.assertRaises(GateRequired):
                call()
        self.assertFalse([p for p in self.hub.paths() if "/tracks" in p or "/audio/" in p])


class DiscoveryAndSets(HubCase):
    def roots(self):
        base = pathlib.Path(self.tmp.name) / "corpora"
        write_local(base / CID, manifest(description="the local copy"))
        write_local(base / "9003-LOCALONLY", manifest(9003, "LOCALONLY", licence=None))
        write_local(base / "9004-BROKEN", manifest(9004, "BROKEN", visibility="unlisted"))
        write_local(base / ".rebuild-9005-HALF", manifest(9005, "HALF"))
        write_local(base / "_scratch", manifest(9006, "SCRATCH"))
        (base / "not-a-corpus").mkdir()
        write_local(base / "copy-of-9001", manifest(description="a second folder with the same id"))
        return base

    def test_local_roots_and_the_hub_together(self):
        base = self.roots()
        self.hub.add(manifest(description="the hub's copy"))
        self.hub.add(manifest(9002, "REMOTEONLY"))
        self.hub.add(manifest(9007, "BADREMOTE", licence=block("stream_only")))
        found = discover(roots=[base, base / "nowhere", base / CID], hub=self.client())
        self.assertEqual(found.corpora.ids, [CID, "9002-REMOTEONLY", "9003-LOCALONLY"])
        self.assertEqual(found.corpora.get(CID).source, "local")
        self.assertEqual(found.corpora.get(CID).description, "the local copy", "the first folder seen for an id wins")
        self.assertEqual(found.corpora.get("9002-REMOTEONLY").source, "hub")
        refused = {pathlib.Path(w).name: reason for w, reason, _ in found.refused}
        self.assertEqual(refused, {"9004-BROKEN": "manifest_invalid", "9007-BADREMOTE": "unknown_scope"})
        preferred = discover(roots=[base], hub=self.client(), prefer_remote=True)
        self.assertEqual(preferred.corpora.get(CID).description, "the hub's copy")
        self.assertEqual([c.id for c in discover(roots=[base / CID])], [CID])
        self.assertEqual(discover().corpora.ids, [])

    def test_a_hub_that_is_down_leaves_local_and_cached_corpora(self):
        base = self.roots()
        self.hub.add(manifest(9002, "REMOTEONLY"))
        self.assertIn("9002-REMOTEONLY", discover(roots=[base], hub=self.client()).corpora.ids)
        self.hub.fail = 503
        found = discover(roots=[base], hub=self.client())
        self.assertEqual(found.corpora.ids, [CID, "9002-REMOTEONLY", "9003-LOCALONLY"])
        v = found.corpora.get("9002-REMOTEONLY").may("study")
        self.assertTrue(v and v.unverified_since is not None)
        fresh = discover(roots=[base], hub=self.client(cache_dir=None))
        self.assertEqual(fresh.corpora.ids, [CID, "9003-LOCALONLY"])

    def test_missing_ids_are_an_error_unless_the_caller_asks_otherwise(self):
        corpora = discover(roots=[self.roots()]).corpora
        self.assertEqual(corpora.select(None).ids, corpora.ids)
        self.assertEqual(corpora.select([CID]).ids, [CID])
        self.assertEqual(corpora.select(CID).ids, [CID])
        with self.assertRaises(MissingCorpora) as ctx:
            corpora.select([CID, "9099-ABSENT", "9098-ALSO"])
        self.assertEqual(ctx.exception.missing, ["9099-ABSENT", "9098-ALSO"])
        with self.assertRaises(MissingCorpora):
            corpora.select(["9099-ABSENT"])
        self.assertEqual(corpora.select([]).ids, [], "an empty request is nothing, not everything")
        skipped = corpora.select([CID, "9099-ABSENT"], if_missing="skip")
        self.assertEqual((skipped.ids, skipped.missing, skipped.substituted), ([CID], ["9099-ABSENT"], False))
        self.assertEqual(corpora.select(["9099-ABSENT"], if_missing="skip").ids, [])
        everything = corpora.select(["9099-ABSENT"], if_missing="all")
        self.assertEqual((everything.ids, everything.missing, everything.substituted), (corpora.ids, ["9099-ABSENT"], True))
        partly = corpora.select([CID, "9099-ABSENT"], if_missing="all")
        self.assertEqual((partly.ids, partly.substituted), ([CID], False))
        with self.assertRaises(ValueError):
            corpora.select([CID], if_missing=True)

    def test_a_set_asks_the_gate_for_each_corpus(self):
        corpora = discover(roots=[self.roots()]).corpora
        yes, no = corpora.allowed("study")
        self.assertEqual([c.id for c, _ in yes], [CID])
        self.assertEqual([(c.id, v.reason) for c, v in no], [("9003-LOCALONLY", "licence_missing")])
        self.assertEqual([n["corpus_id"] for n in corpora.notices()], corpora.ids)

    def test_discovery_for_an_identity_leaves_out_what_it_may_not_see(self):
        base = pathlib.Path(self.tmp.name) / "c2"
        write_local(base / CID, manifest())
        write_local(base / "9002-PRIVATE", manifest(9002, "PRIVATE", visibility="private", owner_email="ada@example.org"))
        self.assertEqual(len(discover(roots=[base]).corpora), 2)
        mallory = discover(roots=[base], identity=Identity("mallory@example.org"))
        self.assertEqual(mallory.corpora.ids, [CID])
        self.assertEqual([(w, r) for w, r, _ in mallory.refused], [("9002-PRIVATE", "not_visible")])
        self.assertEqual(len(discover(roots=[base], identity=Identity("ada@example.org")).corpora), 2)


class Example(unittest.TestCase):
    def test_the_example_runs_and_shows_the_gate_at_work(self):
        out = subprocess.run([sys.executable, str(ROOT / "examples" / "corpus_from_a_fake_hub.py")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        for text in ("9001-OPEN        study         yes", "revoked: the licence was revoked", "licence_missing",
                     "not_visible", "first-song.md + first-song.mid", "no such corpus: 9099-ABSENT",
                     "notice: Used with the permission of The Placeholders."):
            self.assertIn(text, out.stdout)


class Configuration(unittest.TestCase):
    def test_config_from_env_reads_today_s_names(self):
        env = {"POPBOLLARD_BOLLAWAX_URL": " https://hub.example/ ", "POPBOLLARD_BOLLAWAX_TOKEN": "t",
               "POPBOLLARD_PLAYER_ID": "example-player", "POPBOLLARD_DATA_DIR": "/data",
               "POPBOLLARD_REMOTE_REFRESH_SEC": "60", "POPBOLLARD_REMOTE_TIMEOUT_SEC": "nonsense",
               "POPBOLLARD_CORPUS_DIRS": os.pathsep.join(["/a", " ", "/b"]), "POPBOLLARD_PREFER_REMOTE_CORPORA": "1"}
        cfg = config_from_env(env)
        self.assertEqual(cfg["roots"], [pathlib.Path("/a"), pathlib.Path("/b")])
        self.assertTrue(cfg["prefer_remote"])
        self.assertEqual(cfg["hub"], {"base_url": "https://hub.example/", "token": "t", "player": "example-player",
                                      "cache_dir": pathlib.Path("/data/corpus_cache"), "timeout": 10.0,
                                      "revalidate_after": 60.0})
        client = HubClient(**cfg["hub"])
        self.assertEqual((client.base_url, client.revalidate_after), ("https://hub.example", 60.0))
        self.assertEqual(config_from_env({"POPBOLLARD_CORPUS_CACHE_DIR": "/c", "POPBOLLARD_BOLLAWAX_URL": "https://h.example",
                                          "POPBOLLARD_DATA_DIR": "/data"})["hub"]["cache_dir"], pathlib.Path("/c"))
        self.assertEqual(config_from_env({}), {"hub": None, "roots": [], "prefer_remote": False})

    def test_the_environment_is_read_in_one_function_only(self):
        hits = []
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.Module))]:
                for n in ast.iter_child_nodes(fn) if isinstance(fn, ast.Module) else ast.walk(fn):
                    if isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv", "environb", "putenv"):
                        hits.append((path.name, getattr(fn, "name", "<module>")))
            self.assertNotIn("POPBOLLARD_", path.read_text(encoding="utf-8").replace("POPBOLLARD_BOLLAWAX_URL and friends", "")
                             if path.name != "hub.py" else "", path.name)
        self.assertEqual(set(hits), {("hub.py", "config_from_env")})

    def test_the_client_does_not_read_the_environment_by_itself(self):
        hub = FakeHub(token="")
        self.addCleanup(hub.close)
        hub.add(manifest())
        saved = dict(os.environ)
        os.environ.update({"POPBOLLARD_BOLLAWAX_TOKEN": "from-the-environment", "POPBOLLARD_PLAYER_ID": "env-player"})
        try:
            HubClient(hub.url).corpus(CID)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        headers = hub.requests[-1][1]
        self.assertNotIn("authorization", headers)
        self.assertNotIn("x-pop-player", headers)


if __name__ == "__main__":
    unittest.main()


class ActingFor(HubCase):
    """The read token alone is study only for a corpus that is not public; a named
    person (X-Pop-For) is needed for its tracks, audio, art and bundles."""

    PRIVATE = "9002-PRIVATE"

    def setUp(self):
        super().setUp()
        self.full = manifest(9002, "PRIVATE", licence=dict(block("full"), granted_by={"legal_name": "Ada Example"},
                                                            statements=[{"key": "mine", "text": "I am Ada Example and these are mine."}]),
                             visibility="private", owner_email="ada@example.org", access=["grace@example.org"],
                             license_note="Used with the permission of Ada Example.")
        self.hub.add(self.full, tracks={"tracks": [{"file": "one.mp3"}]}, audio={"one.mp3": b"0123456789"},
                     art={"cover.png": b"PNG-made-up"}, morpus=dict(MORPUS, **{"alpha.mrph5": mrph5()}))

    def test_the_token_alone_studies_and_gets_a_manifest_without_the_people(self):
        c = self.client().corpus(self.PRIVATE)
        self.assertNotIn("x-pop-for", self.hub.requests[-1][1])
        m = c.manifest()
        for gone in ("owner_email", "access", "license_note"):
            self.assertNotIn(gone, m)
        self.assertEqual(set(m["licence"]), {"schema", "version", "scope"})
        engine = Identity(service=True)
        v = c.may("study", engine)
        self.assertTrue(v)
        self.assertEqual(c.dna(v)["made_up"], True)
        self.assertEqual(c.read_morpus("alpha.md", v), MORPUS["alpha.md"])
        # The gate on the redacted manifest answers as it does on the whole one, for the engine and for nobody.
        for who in (engine, None):
            for cap in ("see", "study", "stream_audio", "export_morpus"):
                whole = gate.judge(self.full, cap, who, self.clock.now)
                self.assertEqual((c.may(cap, who).reason, c.may(cap, who).allowed), (whole.reason, whole.allowed), cap)
        self.assertEqual(c.may("study").reason, "not_visible")
        # What study does not need, the hub does not give the engine: the reason says the hub answered 404.
        for call in (lambda: c.tracks(c.may("stream_audio", engine)),
                     lambda: c.open_audio("one.mp3", c.may("stream_audio", engine)),
                     lambda: c.open_audio_ranged("one.mp3", c.may("stream_audio", engine)),
                     lambda: c.read_art("cover.png", c.may("store_art", engine)),
                     lambda: c.export_bundle("alpha", c.may("export_morpus", engine))):
            with self.assertRaises(NotAvailable) as caught:
                call()
            self.assertEqual((caught.exception.reason, caught.exception.status), ("not_found", 404))

    def test_a_named_person_reaches_the_rest_and_the_name_is_never_in_a_url(self):
        client = self.client(acting_for=" Ada@Example.org ")
        self.assertEqual(client.acting_for, "ada@example.org")
        c = client.corpus(self.PRIVATE)
        ada = Identity(email="ada@example.org")
        self.assertEqual(c.manifest()["owner_email"], "ada@example.org")
        v = c.may("stream_audio", ada)
        self.assertEqual([t["file"] for t in c.tracks(v)], ["one.mp3"])
        with c.open_audio("one.mp3", v) as audio:
            self.assertEqual(audio.read(), b"0123456789")
        self.assertEqual(c.read_art("cover.png", c.may("store_art", ada)), b"PNG-made-up")
        self.assertEqual(c.export_bundle("alpha", c.may("export_morpus", ada)), mrph5())
        self.assertEqual(c.read_morpus("alpha.md", c.may("study", ada)), MORPUS["alpha.md"])
        asked = [(p, h.get("x-pop-for")) for p, h in self.hub.requests]
        self.assertTrue(all(who == "ada@example.org" for _, who in asked), asked)
        self.assertTrue(all("@" not in p and "%40" not in p and "for=" not in p for p, _ in asked), asked)
        # Per call, on a client that acts for nobody; and "" on a client that acts for someone.
        plain = self.client()
        grace = plain.corpus(self.PRIVATE, acting_for="grace@example.org")
        self.assertEqual(self.hub.requests[-1][1]["x-pop-for"], "grace@example.org")
        self.assertTrue(grace.tracks(grace.may("stream_audio", Identity(email="grace@example.org"))))
        self.assertNotIn("owner_email", client.corpus(self.PRIVATE, acting_for="").manifest())
        found, refused = plain.corpora(acting_for="grace@example.org")
        self.assertEqual(([x.id for x in found], refused), ([self.PRIVATE], []))

    def test_someone_who_is_not_on_the_list_gets_what_an_unknown_corpus_gets(self):
        with self.assertRaises(CorpusUnavailable) as caught:
            self.client(acting_for="mallory@example.org").corpus(self.PRIVATE)
        self.assertEqual((caught.exception.reason, caught.exception.status), ("not_served", 404))

    def test_a_person_s_copy_is_cached_apart_from_the_engine_s(self):
        engine = self.client().corpus(self.PRIVATE)
        ada = self.client(acting_for="ada@example.org").corpus(self.PRIVATE)
        self.assertEqual(engine.root, self.cache / self.PRIVATE)
        self.assertEqual(ada.root.parent.parent, self.cache / ".for")
        self.assertNotIn("ada", str(ada.root))
        self.assertNotIn("owner_email", json.loads((engine.root / "corpus.json").read_text()))
        self.assertIn("owner_email", json.loads((ada.root / "corpus.json").read_text()))
        self.hub.fail = 503                       # offline, each still gets its own
        self.assertNotIn("owner_email", self.client().corpus(self.PRIVATE).manifest())
        self.assertIn("owner_email", self.client(acting_for="ada@example.org").corpus(self.PRIVATE).manifest())
        with self.assertRaises(CorpusUnavailable):
            self.client(acting_for="grace@example.org").corpus(self.PRIVATE)

    def test_a_name_that_cannot_be_a_header_is_refused(self):
        for bad in ("ada@example.org\r\nX-Evil: 1", "a b@example.org", "ädä@example.org", "x" * 400):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.client(acting_for=bad)
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.client().corpus(self.PRIVATE, acting_for=bad)
        self.assertEqual(self.client(acting_for=None).acting_for, "")


class Reasons(HubCase):
    def test_corpus_unavailable_says_why(self):
        client = self.client()
        for cid in ("nope", 7, "../9001-X"):
            with self.assertRaises(CorpusUnavailable) as caught:
                client.corpus(cid)
            self.assertEqual((caught.exception.reason, caught.exception.status), ("bad_id", None))
        with self.assertRaises(CorpusUnavailable) as caught:
            client.corpus("9009-ABSENT")
        self.assertEqual((caught.exception.reason, caught.exception.status), ("not_served", 404))
        self.hub.fail = 503
        with self.assertRaises(CorpusUnavailable) as caught:
            client.corpus("9008-NEVERSEEN")
        self.assertEqual((caught.exception.reason, caught.exception.status), ("unreachable", 503))
        self.hub.fail = 0
        with self.assertRaises(CorpusUnavailable) as caught:
            self.client(token="wrong").corpus("9008-NEVERSEEN")
        self.assertEqual((caught.exception.reason, caught.exception.status), ("unreachable", 401))
        self.hub.close()
        with self.assertRaises(CorpusUnavailable) as caught:
            self.client(timeout=1).corpus("9007-NOBODYHOME")
        self.assertEqual((caught.exception.reason, caught.exception.status), ("unreachable", None))

    def test_not_available_says_why(self):
        self.hub.add(manifest(), tracks={"audio": "not_licensed", "tracks": []}, audio={"one.mp3": b"0123456789"})
        c = self.client(cache_dir=None).corpus(CID)

        def why(call):
            with self.assertRaises(NotAvailable) as caught:
                call()
            self.assertIn(caught.exception.reason, model.NOT_AVAILABLE_REASONS)
            return caught.exception.reason, caught.exception.status

        study, audio = c.may("study"), c.may("stream_audio")
        self.assertEqual(why(lambda: c.read_morpus("absent.md", study)), ("not_found", 404))
        self.assertEqual(why(lambda: c.read_morpus("../x", study)), ("bad_name", None))
        self.assertEqual(why(lambda: c.morpus_path("alpha.md", study)), ("not_kept", None))
        self.assertEqual(why(lambda: c.tracks(audio)), ("not_licensed", 200))
        self.assertEqual(why(lambda: c.open_audio("gone.mp3", audio)), ("not_found", 404))
        self.assertEqual(why(lambda: c.open_audio("../x.mp3", audio)), ("bad_name", None))
        self.assertEqual(why(lambda: c.open_audio("one.mp3", audio, byte_range=(5, 2))), ("bad_range", 416))
        self.assertEqual(why(lambda: c.open_audio("one.mp3", audio, byte_range=(50, None))), ("bad_range", 416))
        self.assertEqual(why(lambda: c.read_art("cover.png", c.may("store_art"))), ("not_found", 404))
        self.assertEqual(why(lambda: c.export_bundle("absent", c.may("export_morpus"))), ("not_found", 404))
        self.hub.fail = 503
        self.assertEqual(why(lambda: c.read_morpus("alpha.md", study)), ("unreachable", 503))
        self.assertEqual(why(lambda: c.open_audio("one.mp3", audio)), ("unreachable", 503))
        self.assertEqual(why(lambda: c.tracks(audio)), ("unreachable", 503))
        bare = Corpus.from_manifest(manifest())
        self.assertEqual(why(lambda: bare.tracks(bare.may("stream_audio"))), ("no_store", None))
        self.assertEqual(NotAvailable("x").reason, "not_found")


class Relay(HubCase):
    """Corpus.open_audio_ranged: the source's status and headers, for a relay."""

    def setUp(self):
        super().setUp()
        self.hub.add(manifest(), audio={"one.mp3": b"0123456789"})
        self.c = self.client().corpus(CID)
        self.v = self.c.may("stream_audio")

    def test_whole_ranged_suffix_and_past_the_end(self):
        cases = [
            (dict(), None, 200, b"0123456789", None),
            (dict(byte_range=(2, 5)), "bytes=2-5", 206, b"2345", "bytes 2-5/10"),
            (dict(byte_range=(7, None)), "bytes=7-", 206, b"789", "bytes 7-9/10"),
            (dict(byte_range=(None, 3)), "bytes=-3", 206, b"789", "bytes 7-9/10"),
            (dict(range_header="bytes=0-0"), "bytes=0-0", 206, b"0", "bytes 0-0/10"),
            (dict(range_header="bytes=-4"), "bytes=-4", 206, b"6789", "bytes 6-9/10"),
            (dict(range_header="bytes=4-"), "bytes=4-", 206, b"456789", "bytes 4-9/10"),
            (dict(range_header="bytes=40-"), "bytes=40-", 416, b"", "bytes */10"),
        ]
        for kw, sent, status, body, content_range in cases:
            with self.subTest(kw):
                with self.c.open_audio_ranged("one.mp3", self.v, **kw) as got:
                    self.assertEqual((got.status, got.read()), (status, body))
                    self.assertEqual(got.headers.get("Content-Range"), content_range)
                    self.assertEqual(got.headers["Accept-Ranges"], "bytes")
                    self.assertEqual(got.headers["Content-Length"], str(len(body)))
                    if status != 416:
                        self.assertEqual(got.headers["Content-Type"], "audio/mpeg")
                    self.assertLessEqual(set(got.headers), set(model.RELAY_HEADERS), "nothing else is passed on")
                self.assertEqual(self.hub.requests[-1][1].get("range"), sent)
                if sent:
                    self.assertNotIn("gzip", self.hub.requests[-1][1].get("accept-encoding", ""))

    def test_a_range_this_does_not_read_is_refused_before_the_hub_is_asked(self):
        asked = len(self.hub.requests)
        for bad in ("bytes=0-1,4-5", "bytes=5-2", "bytes=-0", "bytes=-", "items=0-1", "bytes= 0-1", "bytes=0-1\r\nX: y", "", 5):
            with self.assertRaises(NotAvailable, msg=repr(bad)) as caught:
                self.c.open_audio_ranged("one.mp3", self.v, range_header=bad)
            self.assertEqual((caught.exception.reason, caught.exception.status), ("bad_range", 416))
        for bad in ((5, 2), (-1, None), (None, 0), (None, None), (1.5, 2), (True, 2), "0-1", (1, 2, 3)):
            with self.assertRaises(NotAvailable, msg=repr(bad)):
                self.c.open_audio_ranged("one.mp3", self.v, byte_range=bad)
        with self.assertRaises(NotAvailable):
            self.c.open_audio_ranged("one.mp3", self.v, byte_range=(0, 1), range_header="bytes=0-1")
        self.assertEqual(len(self.hub.requests), asked)

    def test_it_takes_the_gate_like_any_accessor(self):
        with self.assertRaises(GateRequired):
            self.c.open_audio_ranged("one.mp3", self.c.may("study"))
        with self.assertRaises(GateRequired):
            self.c.open_audio_ranged("one.mp3", None)
        with self.assertRaises(NotAvailable) as caught:
            self.c.open_audio_ranged("gone.mp3", self.v)
        self.assertEqual((caught.exception.reason, caught.exception.status), ("not_found", 404))

    def test_a_local_corpus_answers_the_same_way(self):
        root = write_local(pathlib.Path(self.tmp.name) / "local" / CID, manifest(), files={"one.mp3": b"0123456789", "empty.mp3": b""})
        c = Corpus.load(root)
        v = c.may("stream_audio")
        for kw, status, body, content_range in [(dict(), 200, b"0123456789", None), (dict(byte_range=(2, 5)), 206, b"2345", "bytes 2-5/10"),
                                                (dict(range_header="bytes=-3"), 206, b"789", "bytes 7-9/10"),
                                                (dict(range_header="bytes=-30"), 206, b"0123456789", "bytes 0-9/10"),
                                                (dict(range_header="bytes=8-99"), 206, b"89", "bytes 8-9/10"),
                                                (dict(range_header="bytes=10-"), 416, b"", "bytes */10")]:
            with c.open_audio_ranged("one.mp3", v, **kw) as got:
                self.assertEqual((got.status, got.read(), got.headers.get("Content-Range"), got.headers["Content-Length"]),
                                 (status, body, content_range, str(len(body))), kw)
        with c.open_audio_ranged("one.mp3", v, byte_range=(2, 8)) as got:
            self.assertEqual((got.read(3), got.read(100), got.read()), (b"234", b"5678", b""))
        with c.open_audio_ranged("empty.mp3", v, byte_range=(0, None)) as got:
            self.assertEqual(got.status, 416)
        with c.open_audio("one.mp3", v, byte_range=(None, 4)) as fh:
            self.assertEqual(fh.read(), b"6789")


class Dna(HubCase):
    def test_the_dna_is_revalidated_with_its_etag_not_fetched_again(self):
        entry = self.hub.add(manifest())
        client = self.client()
        c = client.corpus(CID)
        v = c.may("study")
        self.assertTrue(c.dna(v)["made_up"])
        self.assertNotIn("if-none-match", self.hub.requests[-1][1])
        before = (client.stats["bytes"], client.stats["not_modified"])
        self.assertTrue(c.dna(v)["made_up"])
        path, headers = self.hub.requests[-1]
        self.assertTrue(path.endswith("/morpus/corpus_dna.json") and headers.get("if-none-match"), headers)
        self.assertEqual((client.stats["bytes"], client.stats["not_modified"]), (before[0], before[1] + 1), "no body came back")
        entry["morpus"]["corpus_dna.json"] = b'{"song_shapes": [1], "made_up": "again"}'
        self.assertEqual(c.dna(v)["made_up"], "again")              # a rebuilt DNA is picked up at once
        fresh = self.client().corpus(CID)                           # a new process, same cache: still conditional
        self.assertEqual(fresh.dna(fresh.may("study"))["made_up"], "again")
        self.assertTrue(self.hub.requests[-1][1].get("if-none-match"))
        self.hub.fail = 503
        self.assertEqual(c.dna(c.may("study"))["made_up"], "again")  # offline: the copy from last time

    def test_an_etag_is_never_sent_without_the_bytes_it_names(self):
        # A licence that does not let the morpus be kept: nothing is on disk, so nothing is conditional.
        self.hub.add(manifest(licence=block("full", device_copies=False)))
        c = self.client(device="PBOLL-EXM-0001").corpus(CID)
        v = c.may("study")
        for _ in range(2):
            self.assertTrue(c.dna(v)["made_up"])
            self.assertNotIn("if-none-match", self.hub.requests[-1][1])
        # A cached file that was removed by hand is fetched whole again.
        self.hub.add(manifest())
        c = self.client().corpus(CID)
        v = c.may("study")
        c.dna(v)
        (c.root / "morpus" / "corpus_dna.json").unlink()
        self.assertTrue(c.dna(v)["made_up"])
        self.assertNotIn("if-none-match", self.hub.requests[-1][1])


class ClockSetBack(HubCase):
    def test_an_expired_licence_does_not_reopen_when_the_clock_is_set_back(self):
        expires = self.clock.now + 1000
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        client = self.client(revalidate_after=300, retry_after=30)
        c = client.corpus(CID)
        self.assertTrue(c.may("study"))
        self.hub.fail = 503
        self.clock.advance(2000)
        self.assertEqual(c.may("study").reason, "expired")
        self.clock.advance(-1500)                                     # back to before the date
        v = c.may("study")
        self.assertEqual((v.reason, v.allowed), ("expired", False), "the cache has seen a later time than this clock")
        self.assertEqual(v.checked_at, self.clock.now, "the verdict still says what the clock said")
        again = self.client(revalidate_after=300, retry_after=30).corpus(CID)       # a new process, same cache
        self.assertEqual(again.may("study").reason, "expired")
        self.assertEqual(again.may("see").reason, "allowed")
        state = json.loads((self.cache / CID / ".remote.json").read_text())
        self.assertEqual(state["witnessed_at"], format_time(self.clock.now + 1500))

    def test_a_clock_set_back_to_before_the_last_revalidation(self):
        expires = self.clock.now + 1000
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
        self.clock.advance(1200)
        self.assertEqual(c.may("study").reason, "expired")            # the hub was reached after the date
        self.hub.fail = 503
        self.clock.advance(-1100)
        self.assertEqual(c.may("study").reason, "expired")

    def test_before_the_date_a_clock_set_back_changes_nothing(self):
        expires = self.clock.now + 5000
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
        self.hub.fail = 503
        self.clock.advance(1000)
        self.assertTrue(c.may("study"))
        self.clock.advance(-900)
        v = c.may("study")
        self.assertTrue(v)
        self.clock.advance(4900)                                      # past the date on the real clock
        self.assertEqual(c.may("study").reason, "expired")

    def test_one_wrong_reading_of_the_clock_heals_at_the_next_contact(self):
        # A device whose clock read twenty years ahead for one call must not be closed for good.
        expires = self.clock.now + 30 * 86400
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
        self.assertTrue(c.may("study"))
        right = self.clock.now
        self.clock.now = right + 20 * 365 * 86400
        self.assertEqual(c.may("study").reason, "expired")            # it is told it is 2051, and believes it
        self.clock.now = right + 60                                    # the clock is corrected
        self.assertTrue(c.may("study"), "the same object, once the hub has answered again")
        again = self.client(revalidate_after=300, retry_after=30).corpus(CID)       # a new process on the same cache
        v = again.may("study")
        self.assertEqual((v.reason, v.allowed), ("allowed", True))
        again.refresh()
        self.assertTrue(again.may("study"))
        state = json.loads((self.cache / CID / ".remote.json").read_text())
        self.assertEqual((state["witnessed_at"], state["revalidated_at"]), (format_time(self.clock.now),) * 2)

    def test_the_wrong_reading_offline_stays_until_the_hub_is_reached(self):
        expires = self.clock.now + 30 * 86400
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
        right = self.clock.now
        self.hub.fail = 503
        self.clock.now = right + 20 * 365 * 86400
        self.assertEqual(c.may("study").reason, "expired")
        self.clock.now = right + 60
        self.assertEqual(c.may("study").reason, "expired", "offline, a clock set back is not believed")
        self.hub.fail = 0
        self.clock.advance(31)
        self.assertTrue(c.may("study"), "the hub confirms the block: the floor starts again")

    def test_asking_about_another_time_leaves_no_trace(self):
        expires = self.clock.now + 30 * 86400
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        for fail in (0, 503):
            with self.subTest(hub_answers=not fail):
                c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
                path = self.cache / CID / ".remote.json"
                self.hub.fail = fail
                self.clock.advance(400)                                # a revalidation is due
                self.assertTrue(c.may("study"))
                before, asked = path.read_text(), len(self.hub.requests)
                year_on = self.clock.now + 365 * 86400
                self.assertEqual(c.may("study", now=year_on).reason, "expired")       # what if it were next year?
                self.assertEqual(c.may("study", now=format_time(year_on)).reason, "expired")
                self.assertEqual((path.read_text(), len(self.hub.requests)), (before, asked), "nothing written, nobody asked")
                self.assertTrue(c.may("study"))
                self.clock.advance(400)
                self.assertTrue(c.may("study"))
                self.assertTrue(self.client().corpus(CID).may("study") if not fail else c.may("study"))
                self.hub.fail = 0

    def test_a_time_given_to_refresh_is_recorded_but_not_witnessed_offline(self):
        expires = self.clock.now + 30 * 86400
        self.hub.add(manifest(licence=block("full", expires_at=format_time(expires))))
        c = self.client(revalidate_after=300, retry_after=30).corpus(CID)
        seen = json.loads((self.cache / CID / ".remote.json").read_text())["witnessed_at"]
        self.hub.fail = 503
        c.refresh(now=self.clock.now + 365 * 86400)
        self.assertEqual(json.loads((self.cache / CID / ".remote.json").read_text())["witnessed_at"], seen)
        self.assertTrue(c.may("study"))


class ReviewFixes(HubCase):
    def test_a_recording_is_never_asked_for_compressed(self):
        self.hub.gzip = "all"                      # this hub would gzip audio for anyone who accepts it
        self.hub.add(manifest(), audio={"one.mp3": b"0123456789" * 40})
        c = self.client().corpus(CID)
        v = c.may("stream_audio")
        for call in (lambda: c.open_audio_ranged("one.mp3", v), lambda: c.open_audio_ranged("one.mp3", v, byte_range=(0, 99)),
                     lambda: c.open_audio("one.mp3", v), lambda: c.open_audio("one.mp3", v, byte_range=(0, 99))):
            with call() as got:
                body = got.read()
            self.assertEqual(body, (b"0123456789" * 40)[:len(body)])
            self.assertIn(len(body), (100, 400))
            self.assertEqual(self.hub.requests[-1][1]["accept-encoding"], "identity")
            self.assertNotIn("Content-Encoding", getattr(got, "headers", {}) if isinstance(got, model.RangedAudio) else {})
        self.assertTrue(c.dna(c.may("study"))["made_up"], "JSON may still come compressed, and is read")

    def test_copies_of_the_read_only_manifest_are_plain_and_yours(self):
        import copy
        import pickle
        m = manifest(access=["grace@example.org"], visibility="private", owner_email="ada@example.org")
        c = Corpus.from_manifest(m)
        view = c.manifest_view()
        self.assertIs(view, c.manifest_view())
        for make in (copy.deepcopy, lambda v: pickle.loads(pickle.dumps(v)), lambda v: json.loads(json.dumps(v))):
            mine = make(view)
            self.assertEqual((mine, type(mine), type(mine["licence"]), type(mine["access"])), (m, dict, dict, list))
            mine["access"].append("x")
            mine["licence"]["scope"] = "changed"
        shallow = copy.copy(view)
        self.assertIs(type(shallow), dict)
        shallow["name"] = "changed"
        self.assertEqual(Corpus.from_manifest(view).manifest(), m)
        self.assertEqual(gate.judge(view, "study", Identity(email="ada@example.org"), self.clock.now).reason, "allowed")
        for change in (lambda: view.__init__({"name": "x"}), lambda: view.__init__(name="x"), lambda: view["access"].__init__(["x"]),
                       lambda: view.update(name="x"), lambda: view["access"].append("x"), lambda: view["licence"].pop("scope"),
                       lambda: view.__setitem__("name", "x"), lambda: view["access"].sort(), lambda: view.setdefault("zz", 1)):
            with self.assertRaises(TypeError):
                change()
        self.assertEqual((view, c.manifest()), (m, m), "nothing changed")
        with self.assertRaises(TypeError):
            model.FrozenDict({"a": 1})

    def test_a_name_that_is_not_a_string_is_refused_not_read_as_nobody(self):
        for bad in (7, ["ada@example.org"], {"email": "ada@example.org"}, True, b"ada@example.org"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.client(acting_for=bad)
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.client().listing(acting_for=bad)
        self.assertEqual(self.client(acting_for=None).acting_for, "")

    def test_the_release_record_is_asked_for_nobody(self):
        self.hub.release = {"not": "a release"}
        with self.assertRaises(HubError):
            self.client(acting_for="ada@example.org").latest()
        self.assertEqual(self.hub.requests[-1][0], "/api/bollawax/latest")
        self.assertNotIn("x-pop-for", self.hub.requests[-1][1])

    def test_an_answer_that_is_not_http_is_an_unreachable_hub(self):
        import socket
        import threading
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(8)
        self.addCleanup(server.close)

        def serve():
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return
                conn.recv(4096)
                conn.sendall(b"this is not http\r\n\r\n")
                conn.close()

        threading.Thread(target=serve, daemon=True).start()
        client = HubClient("http://127.0.0.1:%d" % server.getsockname()[1], cache_dir=None, timeout=5)
        for call in (client.listing, client.corpus_gate, client.version, client.latest):
            with self.assertRaises(HubUnreachable) as caught:
                call()
            self.assertIsNone(caught.exception.status)
        with self.assertRaises(CorpusUnavailable) as caught:
            client.corpus(CID)
        self.assertEqual((caught.exception.reason, caught.exception.status), ("unreachable", None))
