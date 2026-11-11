# SPDX-License-Identifier: Apache-2.0
"""The corpus model and the gate: the behaviour vectors, the reader's decisions, and the proof
that corpus content cannot be reached without the gate's answer."""
import ast
import inspect
import json
import pathlib
import tempfile
import unittest

from _corpus_fakes import MORPUS, ROOT, Clock, block, manifest, write_local

import bollardeck.corpus as corpus_pkg
from bollardeck import schema
from bollardeck.corpus import (CAPABILITIES, Corpus, GateRequired, Identity, Licence, ManifestRefused, NotAvailable,
                               Standing, Verdict, judge)
from bollardeck.corpus import gate, hub, licence, model

GATE_VECTORS = ROOT / "conformance" / "corpus-gate"
PACKAGE = ROOT / "python" / "bollardeck" / "corpus"


def gate_cases():
    for path in sorted(GATE_VECTORS.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for case in doc["cases"]:
            yield path.name, doc, case


class GateVectors(unittest.TestCase):
    def test_every_vector_file_is_well_formed(self):
        files = sorted(GATE_VECTORS.glob("*.json"))
        self.assertGreaterEqual(len(files), 6)
        for path in files:
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(doc), {"version", "about", "manifests", "cases"}, path.name)
            self.assertEqual(doc["version"], 1)
            names = [c["name"] for c in doc["cases"]]
            self.assertEqual(len(names), len(set(names)), path.name)
            used = {c["manifest"] for c in doc["cases"]}
            self.assertEqual(used, set(doc["manifests"]), "%s: a manifest no case uses, or the reverse" % path.name)
            for c in doc["cases"]:
                self.assertLessEqual(set(c), {"name", "manifest", "capability", "clock", "identity", "standing", "expect", "why"})
                self.assertLessEqual({"allowed", "reason"}, set(c["expect"]), c["name"])
                self.assertIn(c["expect"]["reason"], gate.REASONS, c["name"])
                self.assertEqual(c["expect"]["allowed"], c["expect"]["reason"] == "allowed", c["name"])

    def test_the_gate_gives_every_vector_its_verdict(self):
        count = 0
        for name, doc, c in gate_cases():
            v = judge(doc["manifests"][c["manifest"]], c["capability"], Identity.from_dict(c.get("identity")),
                      c["clock"], Standing.from_dict(c.get("standing")))
            got = {"allowed": v.allowed, "reason": v.reason, "pending": v.pending,
                   "unverified_since": v.as_dict()["unverified_since"], "capability_answered": v.capability}
            for key, want in c["expect"].items():
                self.assertEqual(got[key], want, "%s: %s: %s (%s)" % (name, c["name"], key, v.detail))
            self.assertEqual(bool(v), v.allowed)
            count += 1
        self.assertGreaterEqual(count, 100)

    def test_every_reason_and_every_capability_has_a_vector(self):
        reasons = {c["expect"]["reason"] for _, _, c in gate_cases()}
        self.assertEqual(reasons, set(gate.REASONS))
        asked = {c["capability"] for _, _, c in gate_cases() if isinstance(c["capability"], str)}
        self.assertLessEqual(set(gate.ALL_CAPABILITIES) | {"study"}, asked)

    def test_manifests_in_the_vectors_are_invalid_only_where_the_verdict_says_so(self):
        for name, doc, c in gate_cases():
            m = doc["manifests"][c["manifest"]]
            if schema.validate("corpus-manifest", m):
                self.assertIn(c["expect"]["reason"], ("manifest_invalid", "unknown_scope", "newer_version"),
                              "%s: %s" % (name, c["name"]))

    def test_the_capability_list_is_the_licence_schema_s(self):
        props = schema.load("licence")["properties"]
        self.assertEqual({k for k, v in props.items() if v.get("type") == "boolean"}, set(CAPABILITIES))
        self.assertEqual(set(schema.load("licence")["properties"]["scope"]["enum"]), set(licence.SCOPES))


class GateFailsClosed(unittest.TestCase):
    def test_garbage_never_raises_and_never_allows(self):
        for junk in (None, 7, "full", [], {}, {"id": 3}, {"licence": {"scope": "full"}}, manifest(licence=7)):
            for cap in ("study", "see", None, 3.5, ["study"]):
                for now in (None, "2031-01-01", "not a time", True, [], 1e12):
                    v = judge(junk, cap, None, now)
                    self.assertIsInstance(v, Verdict)
                    self.assertFalse(v.allowed, (junk, cap, now))

    def test_a_bad_clock_refuses(self):
        v = judge(manifest(), "study", None, "2031-06-01T12:00:00+09:00")
        self.assertEqual(v.reason, "bad_clock")

    def test_identity_and_standing_of_the_wrong_type_are_the_safe_defaults(self):
        private = manifest(visibility="private", owner_email="ada@example.org")
        self.assertEqual(judge(private, "study", "ada@example.org", "2031-01-01").reason, "not_visible")
        self.assertEqual(judge(private, "study", {"service": True}, "2031-01-01").reason, "not_visible")
        self.assertFalse(Identity(service="yes").service)

    def test_a_verdict_cannot_be_made_or_changed_by_hand(self):
        with self.assertRaises(TypeError):
            Verdict(object(), True, "allowed", "musicians_may_study", "9001-PLACEHOLDERS", "", "full", 0.0)
        with self.assertRaises(TypeError):
            gate.Grant(object(), "9001-PLACEHOLDERS", "musicians_may_study")
        v = judge(manifest(licence=None), "study")
        with self.assertRaises(AttributeError):
            v.allowed = True
        with self.assertRaises(AttributeError):
            v.extra = 1
        forged = Verdict(gate._SEAL, True, "revoked", "musicians_may_study", "x", "", "full", 0.0)
        self.assertFalse(forged.allowed, "allowed is true only together with the reason allowed")

    def test_a_refusal_says_why_in_words(self):
        for m, cap, text in (
                (manifest(licence=None), "study", "no licence block"),
                (manifest(licence="morpus_only"), "stream_audio", "never allows stream_audio"),
                (manifest(licence=block("full", export_morpus=False)), "export_morpus", "switches export_morpus off"),
                (manifest(licence="morpus_only"), "export_morpus", "does not include export_morpus"),
                (manifest(licence=block("full", revoked_at="2031-01-01")), "study", "revoked at 2031-01-01T00:00:00Z"),
                (manifest(visibility="private"), "see", "private")):
            v = judge(m, cap, None, "2031-06-01")
            self.assertFalse(v)
            self.assertIn(text, v.detail, v)
        d = judge(manifest(), "study", None, "2031-06-01").as_dict()
        self.assertEqual(d["checked_at"], "2031-06-01T00:00:00Z")
        json.dumps(d)


class LicenceReader(unittest.TestCase):
    def test_times_are_utc_only(self):
        self.assertEqual(licence.parse_time("1970-01-02"), 86400.0)
        self.assertEqual(licence.parse_time("1970-01-01T00:00:01Z"), 1.0)
        self.assertEqual(licence.parse_time("1970-01-01T00:00:01.250"), 1.25)
        self.assertIsNone(licence.parse_time(None))
        self.assertIsNone(licence.parse_time(""))
        for bad in ("2031-06-01T12:00:00+09:00", "2031-06-01T12:00:00-00:00", "2031-6-1", "2031-06-01 whenever",
                    "2031-02-30", "2031-06-01T12:00", "2031-06-01T12:00:00Z\n", 5, True):
            with self.assertRaises(licence.BadTime, msg=repr(bad)):
                licence.parse_time(bad)
        self.assertEqual(licence.parse_time("2032-02-29"), licence.parse_time("2032-02-29T00:00:00Z"))

    def test_the_reader_and_the_schema_agree_on_what_a_time_looks_like(self):
        for text in ("2031-06-01", "2031-06-01T12:00:00", "2031-06-01T12:00:00Z", "2031-06-01T12:00:00.5Z",
                     "2031-06-01T12:00:00+09:00", "2031-6-1", "2031-13-01", "2031-06-01T24:00:00Z",
                     "2031-06-01T12:00:00z", " 2031-06-01", "2031-06-01\n", "20310601"):
            fits = not schema.validate("licence#/$defs/time", text)
            try:
                licence.parse_time(text)
                reads = True
            except licence.BadTime:
                reads = False
            self.assertEqual(reads, fits, text)

    def test_a_block_on_paper(self):
        lic = Licence.from_block(block("morpus_only", store_art=True))
        self.assertEqual(lic.status, "ok")
        self.assertTrue(lic.grants("store_art") and lic.grants("musicians_may_study"))
        self.assertFalse(lic.grants("stream_audio") or lic.grants("nonsense"))
        self.assertEqual(Licence.from_block(None).status, "missing")
        self.assertEqual(Licence.from_block("full").status, "invalid")
        self.assertEqual(Licence.from_block(block("stream_only")).status, "unknown_scope")
        self.assertEqual(Licence.from_block(block(version=3)).status, "newer_version")
        self.assertEqual(Licence.from_block(block("morpus_only", store_audio=True)).status, "invalid")
        for closed in (None, "full", block("stream_only"), block(version=3)):
            self.assertFalse(any(Licence.from_block(closed).flags.values()))
        with self.assertRaises(AttributeError):
            lic.status = "ok"

    def test_the_reader_agrees_with_the_schema_on_every_licence_vector(self):
        index = json.loads((ROOT / "conformance" / "index.json").read_text())
        for v in index["vectors"]:
            if v["schema"] != "licence":
                continue
            doc = json.loads((ROOT / "conformance" / v["file"]).read_text())
            self.assertEqual(Licence.from_block(doc).status == "ok", v["valid"], v["file"])


class CorpusReader(unittest.TestCase):
    def test_a_manifest_that_fails_is_refused_whole_with_its_problems(self):
        with self.assertRaises(ManifestRefused) as ctx:
            Corpus.from_manifest(manifest(visibility="unlisted", track_count="many"))
        self.assertEqual(ctx.exception.reason, "manifest_invalid")
        self.assertTrue(any("/visibility" in p for p in ctx.exception.problems))
        for bad, reason in ((manifest(licence=block("stream_only")), "unknown_scope"),
                            (manifest(licence=block(version=2)), "newer_version"),
                            (manifest(licence="morpus_only", license=block("full")), "licence_ambiguous"),
                            (dict(manifest(), id="9009-PLACEHOLDERS"), "manifest_invalid"),
                            ("not a manifest", "manifest_invalid")):
            with self.assertRaises(ManifestRefused) as ctx:
                Corpus.from_manifest(bad)
            self.assertEqual(ctx.exception.reason, reason)

    def test_every_invalid_manifest_vector_is_refused_and_every_valid_one_loads(self):
        index = json.loads((ROOT / "conformance" / "index.json").read_text())
        for v in index["vectors"]:
            if v["schema"] != "corpus-manifest":
                continue
            doc = json.loads((ROOT / "conformance" / v["file"]).read_text())
            if v["valid"]:
                Corpus.from_manifest(doc)
            else:
                with self.assertRaises(ManifestRefused, msg=v["file"]):
                    Corpus.from_manifest(doc)

    def test_a_loaded_corpus_with_no_licence_allows_nothing(self):
        c = Corpus.from_manifest(manifest(licence=None))
        self.assertEqual(c.licence.status, "missing")
        for cap in CAPABILITIES:
            self.assertEqual(c.may(cap).reason, "licence_missing")
        self.assertTrue(c.may("see"))

    def test_metadata_and_copies(self):
        m = manifest(description="made up", form_cap={"max_song_sec": 200}, visibility="private",
                     owner_email="ada@example.org", extra_member={"kept": True})
        c = Corpus.from_manifest(m)
        m["name"] = "changed after loading"
        self.assertEqual((c.id, c.number, c.slug, c.artist), ("9001-PLACEHOLDERS", 9001, "PLACEHOLDERS", "The Placeholders"))
        self.assertEqual(c.name, "The Placeholders: Placeholders")
        self.assertEqual(c.manifest()["extra_member"], {"kept": True})
        c.manifest()["id"] = "x"
        c.form_cap["max_song_sec"] = 1
        self.assertEqual((c.id, c.form_cap), ("9001-PLACEHOLDERS", {"max_song_sec": 200}))
        self.assertEqual((c.visibility, c.source, c.root, c.attestation), ("private", "manifest", None, None))
        self.assertEqual(c.summary()["licence"]["scope"], "full")

    def test_load_reads_a_folder_and_refuses_one_without_a_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = write_local(pathlib.Path(td) / "9001-PLACEHOLDERS", manifest())
            self.assertEqual(Corpus.load(root).source, "local")
            self.assertEqual(Corpus.load(root / "morpus").id, "9001-PLACEHOLDERS")
            (pathlib.Path(td) / "empty").mkdir()
            for bad in ("empty", "nowhere"):
                with self.assertRaises(ManifestRefused):
                    Corpus.load(pathlib.Path(td) / bad)
            (root / "corpus.json").write_text("{not json")
            with self.assertRaises(ManifestRefused):
                Corpus.load(root)

    def test_notices(self):
        c = Corpus.from_manifest(manifest(
            license_note="  Used with the permission of The Placeholders.  ", edition="PB 9001: Example Edition",
            midi_sources=[
                {"file": "a.mid", "title": "A", "source_url": "https://example.org/a", "source_licence": "CC-BY 4.0",
                 "attribution": "A, sequenced by Ada Example, CC BY 4.0"},
                {"file": "b.mid", "source_url": "https://example.org/b", "source_licence": "CC0"},
                {"file": "c.mid", "source_url": "https://example.org/c", "source_licence": "CC-BY 4.0",
                 "attribution": "A, sequenced by Ada Example, CC BY 4.0"}]))
        n = c.notices()
        self.assertEqual(n["lines"], ["PB 9001: Example Edition", "Used with the permission of The Placeholders.",
                                      "A, sequenced by Ada Example, CC BY 4.0"])
        self.assertEqual([a["file"] for a in n["attributions"]], ["a.mid", "c.mid"])
        self.assertEqual(n["attributions"][0]["source_url"], "https://example.org/a")
        plain = Corpus.from_manifest(manifest(licence=None)).notices()
        self.assertEqual(plain["lines"], ["PB 9001 — PLACEHOLDERS Edition"])
        self.assertEqual((plain["license_note"], plain["attributions"]), ("", []))


# ── no content without the gate ──────────────────────────────────────────────────────────

# Corpus members that are metadata: free to read. Anything else public must take a Verdict.
CORPUS_METADATA = {"from_manifest", "load", "id", "number", "slug", "name", "artist", "display_label", "description",
                   "edition_label", "licence", "visibility", "form_cap", "attestation", "source", "root", "standing",
                   "manifest", "manifest_view", "summary", "notices", "refresh", "may"}
# Store members that are about freshness, not content.
STORE_FRESHNESS = {"standing", "freshen"}
# HubClient's public surface: metadata and Corpus objects only.
HUB_PUBLIC = {"version", "corpus_gate", "latest", "listing", "cached_ids", "corpus", "corpora"}
# One sample call per accessor: the arguments before the verdict.
ACCESSOR_ARGS = {"morpus_index": (), "study_pairs": (), "read_morpus": ("alpha.md",), "morpus_path": ("alpha.md",),
                 "dna": (), "export_bundle": ("alpha",), "tracks": (), "open_audio": ("song.mp3",),
                 "open_audio_ranged": ("song.mp3",), "read_art": ("cover.png",)}
ACCESSOR_NEEDS = {"morpus_index": "study", "study_pairs": "study", "read_morpus": "study", "morpus_path": "study",
                  "dna": "study", "export_bundle": "export_morpus", "tracks": "stream_audio",
                  "open_audio": "stream_audio", "open_audio_ranged": "stream_audio", "read_art": "store_art"}


def class_node(module, name):
    tree = ast.parse(pathlib.Path(inspect.getsourcefile(module)).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == name)


def methods(node):
    return [n for n in node.body if isinstance(n, ast.FunctionDef)]


def is_call(node, dotted):
    """Is `node` a call to the dotted name, e.g. "self._admit" or "_gate.check_grant"?"""
    return isinstance(node, ast.Call) and ast.unparse(node.func) == dotted


def body_without_docstring(fn):
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    return body


class NoContentWithoutTheGate(unittest.TestCase):
    def accessors(self):
        return sorted(n for n, f in inspect.getmembers(Corpus, inspect.isfunction)
                      if not n.startswith("_") and n not in CORPUS_METADATA)

    def test_every_public_corpus_member_is_metadata_or_takes_a_verdict(self):
        public = {n for n in vars(Corpus) if not n.startswith("_")}
        self.assertEqual(public - CORPUS_METADATA, set(ACCESSOR_ARGS),
                         "a new public member of Corpus must be listed as metadata or be a gated accessor")
        for name in self.accessors():
            params = list(inspect.signature(getattr(Corpus, name)).parameters)
            self.assertIn("verdict", params, name)
            self.assertIs(inspect.signature(getattr(Corpus, name)).parameters["verdict"].default, inspect.Parameter.empty,
                          "%s: the verdict must not be optional" % name)

    def test_every_accessor_reaches_the_store_only_through_admit(self):
        node = class_node(model, "Corpus")
        seen = 0
        for fn in methods(node):
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
                func = ast.unparse(call.func)
                if not func.startswith("self._store.") or func.count(".") != 2:
                    continue
                if func.split(".")[-1] in STORE_FRESHNESS:
                    continue
                seen += 1
                self.assertNotIn(fn.name, CORPUS_METADATA, "%s reaches for content" % fn.name)
                self.assertTrue(call.args and is_call(call.args[0], "self._admit"),
                                "%s: %s is not handed self._admit(verdict, ...)" % (fn.name, func))
                self.assertEqual(ast.unparse(call.args[0].args[0]), "verdict", fn.name)
        self.assertEqual(seen, len(ACCESSOR_ARGS))

    def test_every_store_content_method_checks_its_grant_first(self):
        checked = 0
        for module, name in ((model, "_NoStore"), (model, "_LocalStore"), (hub, "_HubStore")):
            for fn in methods(class_node(module, name)):
                if fn.name.startswith("__") or fn.name in STORE_FRESHNESS:
                    continue
                args = [a.arg for a in fn.args.args]
                if fn.name.startswith("_") and "grant" not in args:
                    continue                      # a private helper; the next test covers who may call it
                self.assertEqual(args[:2], ["self", "grant"], "%s.%s" % (name, fn.name))
                first = body_without_docstring(fn)[0]
                value = getattr(first, "value", None)
                ok = is_call(value, "_gate.check_grant") or (
                    isinstance(first, ast.Return) and is_call(value, "self._nothing"))
                self.assertTrue(ok, "%s.%s does not check its grant before anything else" % (name, fn.name))
                if is_call(value, "_gate.check_grant"):
                    self.assertEqual([ast.unparse(a) for a in value.args], ["grant", "self.corpus_id"])
                checked += 1
        self.assertGreaterEqual(checked, 2 * len(ACCESSOR_ARGS))

    def test_private_store_helpers_that_fetch_are_called_only_after_a_grant_check(self):
        node = class_node(hub, "_HubStore")
        for helper in ("_fetch", "_track", "_index"):
            callers = [fn for fn in methods(node)
                       if any(is_call(n, "self." + helper) for n in ast.walk(fn)) and fn.name != helper]
            self.assertTrue(callers, helper)
            for fn in callers:
                self.assertIn("grant", [a.arg for a in fn.args.args], "%s calls %s without a grant" % (fn.name, helper))

    def test_the_hub_client_s_public_surface_is_metadata_and_corpus_objects(self):
        public = {n for n, f in vars(hub.HubClient).items() if not n.startswith("_") and callable(f)}
        self.assertEqual(public, HUB_PUBLIC, "a new public HubClient method must not hand out corpus content")
        # and the raw request methods are used only by the client itself and the store behind a Corpus
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and n.attr in ("_get", "_open", "_get_json", "_opener"):
                    self.assertEqual(path.name, "hub.py", "%s reaches into the hub client" % path.name)

    def test_only_the_corpus_and_the_hub_touch_a_store(self):
        for path in PACKAGE.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if path.name not in ("model.py", "hub.py"):
                for word in ("_store", "_HubStore", "_LocalStore", "_NoStore"):
                    self.assertNotIn(word, text, path.name)
        for name in corpus_pkg.__all__:
            self.assertFalse(name.startswith("_"))
        self.assertFalse({"_HubStore", "_LocalStore", "_NoStore", "Grant"} & set(corpus_pkg.__all__))

    def test_files_are_opened_only_where_the_gate_or_a_hash_stands_guard(self):
        # Reading bytes off disk or the network happens in: the stores (grant-checked above), the
        # hub client's own cache of JSON answers, the attestation checker (hashes, and the
        # record's own four files), and the origin client (discovery file and listing).
        allowed = {"model.py", "hub.py", "attest.py", "origin.py"}
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                opens = (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open") or (
                    isinstance(n, ast.Attribute) and n.attr in ("read_bytes", "read_text", "urlopen", "build_opener"))
                if opens:
                    self.assertIn(path.name, allowed, "%s reads files or the network" % path.name)

    # ---- and in behaviour ------------------------------------------------------------
    def local(self, td, m=None, clock=None, **kw):
        root = write_local(pathlib.Path(td) / "c", m or manifest(), files={"song.mp3": b"ID3-made-up", "art/cover.png": b"PNG"})
        return Corpus.load(root, **({"clock": clock} if clock else {}), **kw)

    def call(self, c, name, verdict):
        return getattr(c, name)(*ACCESSOR_ARGS[name], verdict)

    def test_the_mapping_of_accessors_is_complete(self):
        self.assertEqual(self.accessors(), sorted(ACCESSOR_ARGS))
        self.assertEqual(set(ACCESSOR_NEEDS), set(ACCESSOR_ARGS))

    def test_no_accessor_works_without_an_allowed_verdict_for_it(self):
        with tempfile.TemporaryDirectory() as td:
            c = self.local(td)
            other = Corpus.from_manifest(manifest(9002, "OTHER"))
            closed = self.local(td + "/closed", manifest(licence=block("full", revoked_at="2001-01-01")))
            for name in self.accessors():
                need = ACCESSOR_NEEDS[name]
                wrong = "transcode"
                for bad in (None, True, "allowed", {"allowed": True}, c.may("see"), c.may(wrong),
                            other.may(need), closed.may(need), judge(c.manifest(), need, None, 0)):
                    with self.assertRaises(GateRequired, msg="%s with %r" % (name, bad)):
                        self.call(c, name, bad)
                with self.assertRaises(GateRequired):
                    self.call(closed, name, closed.may(need))
                with self.assertRaises(TypeError):
                    getattr(c, name)(*ACCESSOR_ARGS[name])
                try:
                    out = self.call(c, name, c.may(need))    # and with the right verdict it gets through
                    getattr(out, "close", lambda: None)()
                except NotAvailable:
                    pass                                     # the gate let it through; the folder has none

    def test_with_the_right_verdict_the_content_comes_out(self):
        with tempfile.TemporaryDirectory() as td:
            c = self.local(td)
            v = c.may("study")
            self.assertEqual(c.study_pairs(v), [("alpha.md", "alpha.mid"), ("beta.md", "beta.mid")])
            self.assertEqual(c.read_morpus("alpha.mid", v), MORPUS["alpha.mid"])
            self.assertEqual(c.morpus_path("beta.md", v).read_bytes(), MORPUS["beta.md"])
            self.assertEqual(c.dna(v)["made_up"], True)
            self.assertIn("STATUS.md", c.morpus_index(v))
            with c.open_audio("song.mp3", c.may("stream_audio"), byte_range=(4, None)) as fh:
                self.assertEqual(fh.read(), b"made-up")
            self.assertEqual(c.read_art("art/cover.png", c.may("store_art")), b"PNG")
            self.assertEqual(c.read_morpus("alpha.md", c.may("export_morpus")), MORPUS["alpha.md"])

    def test_a_verdict_goes_stale(self):
        with tempfile.TemporaryDirectory() as td:
            clock = Clock()
            c = self.local(td, manifest(licence=block("full", expires_at=licence.format_time(clock.now + 600))), clock)
            v = c.may("study")
            self.assertTrue(c.study_pairs(v))
            clock.advance(601)
            with self.assertRaisesRegex(GateRequired, "closed since"):
                c.study_pairs(v)
            self.assertEqual(c.may("study").reason, "expired")
            fresh = self.local(td + "/b", clock=clock)
            v = fresh.may("study")
            clock.advance(model.VERDICT_TTL_SEC + 1)
            with self.assertRaisesRegex(GateRequired, "too old"):
                fresh.study_pairs(v)
            self.assertTrue(fresh.study_pairs(fresh.may("study")))

    def test_a_store_refuses_anything_that_is_not_a_grant_for_its_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            c = self.local(td)
            store = c._store
            other = Corpus.from_manifest(manifest(9002, "OTHER"))
            foreign = gate.admit(other.may("study"), other.id, gate.stamp_of(other._reading, other.standing),
                                 ("musicians_may_study",), 0.0 + other._clock(), 900)
            for bad in (None, True, c.may("study"), foreign, object()):
                with self.assertRaises(GateRequired):
                    store.morpus_index(bad)
                with self.assertRaises(GateRequired):
                    store.read_morpus(bad, "alpha.md")
                with self.assertRaises(GateRequired):
                    store.open_audio(bad, "song.mp3", None)

    def test_local_paths_cannot_climb_out_of_the_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            c = self.local(td)
            (pathlib.Path(td) / "outside.md").write_text("not yours")
            (c.root / "morpus" / "link.md").symlink_to(pathlib.Path(td) / "outside.md")
            v, a = c.may("study"), c.may("stream_audio")
            for name in ("../outside.md", "/etc/hosts", ".hidden", "a/b.md", "link.md", ""):
                with self.assertRaises(NotAvailable, msg=name):
                    c.read_morpus(name, v)
            for name in ("../outside.md", "morpus/alpha.mid", "corpus.json", "art/cover.png", "/etc/hosts", "nope.mp3"):
                with self.assertRaises(NotAvailable, msg=name):
                    c.open_audio(name, a)


if __name__ == "__main__":
    unittest.main()
