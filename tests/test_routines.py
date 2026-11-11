# SPDX-License-Identifier: Apache-2.0
"""The routine API: the YAML subset reader, the manifest, loading, the six hooks, the guard.

PyYAML is a cross-check here and never a runtime dependency: the one test that needs it skips
when it is not installed.
"""
import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from dataclasses import replace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import SPEAKS, schema  # noqa: E402
from bollardeck import routines  # noqa: E402
from bollardeck.routines import (Factory, ManifestError, RoutineError, RoutineSet, RoutineSetupError,  # noqa: E402
                                 load_routine, load_routines, manifest, sim, yamlsubset)

try:
    import yaml
except ImportError:
    yaml = None
    if os.environ.get("BOLLARD_SDK_REQUIRE_PYYAML"):
        raise

EXAMPLES = ROOT / "examples" / "routines"
MANIFEST = "name: %s\nversion: 0.1.0\nauthor: A Test\nhooks: [%s]\n"


def yaml_vectors():
    return json.loads((ROOT / "conformance" / "yaml" / "subset.json").read_text(encoding="utf-8"))["vectors"]


def schema_vectors(name):
    index = json.loads((ROOT / "conformance" / "index.json").read_text(encoding="utf-8"))
    for v in index["vectors"]:
        if v["schema"] == name:
            yield v, json.loads((ROOT / "conformance" / v["file"]).read_text(encoding="utf-8"))


class Folder(unittest.TestCase):
    """A temp folder to write routines into, with the routine switches of the environment cleared."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name)
        saved = {k: os.environ.pop(k) for k in list(os.environ)
                 if k in ("POPBOLLARD_ROUTINES", "POPBOLLARD_NO_ROUTINES", "POPBOLLARD_DATA_DIR", "K_SERVICE",
                          "POPBOLLARD_CLOUD_RUN")}
        self.addCleanup(os.environ.update, saved)

    def routine(self, name, code, hooks=None, extra="", where=None):
        """Write a routine folder and return its path. `hooks` defaults to every on_* function in the code."""
        code = textwrap.dedent(code)
        hooks = hooks or [h for h in routines.HOOKS if ("def %s(" % h) in code]
        folder = (where or self.tmp) / name
        folder.mkdir(parents=True)
        (folder / "routine.yaml").write_text(MANIFEST % (name, ", ".join(hooks)) + extra)
        (folder / "routine.py").write_text(code)
        return folder

    def run_one(self, name, code, **kw):
        """Load one routine and run a sim song; returns (song, the routine's failure record or None)."""
        path = self.routine(name, code, **kw)
        rset = load_routines([path], factory=sim.FACTORY)
        self.assertEqual(rset.load_failures, [], "the routine must load")
        song = sim.run_song(rset, seed=3)
        failed = [f for f in song["meta"]["routines_failed"] if f["name"] == name]
        return song, (failed[0] if failed else None)


# ── the YAML subset ──────────────────────────────────────────────────────────────────────

class YamlSubset(unittest.TestCase):
    def test_vectors(self):
        for v in yaml_vectors():
            with self.subTest(v["name"]):
                if v.get("error"):
                    with self.assertRaises(yamlsubset.YamlError) as caught:
                        yamlsubset.loads(v["text"])
                    if "line" in v:
                        self.assertEqual(caught.exception.line, v["line"], str(caught.exception))
                else:
                    got = yamlsubset.loads(v["text"])
                    self.assertEqual(json.dumps(got, sort_keys=True), json.dumps(v["value"], sort_keys=True))

    def test_vectors_are_well_formed_and_cover_both_ways(self):
        names = [v["name"] for v in yaml_vectors()]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(sum(1 for v in yaml_vectors() if "value" in v), 20)
        self.assertGreaterEqual(sum(1 for v in yaml_vectors() if v.get("error")), 30)
        for v in yaml_vectors():
            self.assertTrue(("value" in v) != bool(v.get("error")), v["name"])

    @unittest.skipUnless(yaml, "PyYAML is not installed")
    def test_a_full_yaml_reader_agrees_on_everything_the_subset_accepts(self):
        for v in yaml_vectors():
            if "value" in v:
                self.assertEqual(yaml.safe_load(v["text"]), v["value"], v["name"])
        for path in sorted(EXAMPLES.glob("*/routine.yaml")):
            text = path.read_text(encoding="utf-8")
            self.assertEqual(yamlsubset.loads(text), yaml.safe_load(text), path.parent.name)

    def test_what_the_subset_refuses_never_reads_as_something_else(self):
        for text in ("a: b\n  c\n", "a: [1, 2\n", "- a: 1\n", "a: 1\na: 2\n", "\ta: 1\n", "a: !!python/object:os.system x\n"):
            with self.assertRaises(yamlsubset.YamlError, msg=text):
                yamlsubset.loads(text)
        with self.assertRaises(yamlsubset.YamlError):
            yamlsubset.loads(b"a: 1")


# ── the manifest ─────────────────────────────────────────────────────────────────────────

class Manifest(unittest.TestCase):
    def test_a_manifest_may_be_json(self):
        # spec/bollardeck.md: "routine.yaml  manifest (YAML; JSON also parses)".
        text = json.dumps({"name": "json_demo", "version": "0.1.0", "author": "A Test", "hooks": ["on_plan"],
                           "limits": {"max_ms_per_call": 20}, "extra": {"nested": [1, {"deep": None}]}}, indent=2)
        m = manifest.parse_manifest(text)
        self.assertEqual((m["name"], m["hooks"], m["limits"], m["order"]), ("json_demo", ("on_plan",), {"max_ms_per_call": 20}, 100))
        self.assertEqual(m, manifest.parse_manifest("name: json_demo\nversion: 0.1.0\nauthor: A Test\nhooks: [on_plan]\n"
                                                    "limits:\n  max_ms_per_call: 20\n"))
        with self.assertRaises(manifest.ManifestError) as caught:
            manifest.parse_manifest('{"name": "json_demo", "version": 0.1, "author": "A", "hooks": ["on_plan"]}')
        self.assertIn("quotes around the version", str(caught.exception))
        with self.assertRaises(manifest.ManifestError):
            manifest.parse_manifest('["not", "a", "mapping"]')

    def test_the_examples_parse(self):
        seen = {}
        for path in sorted(EXAMPLES.glob("*/routine.yaml")):
            m = manifest.parse_manifest(path.read_text(encoding="utf-8"), str(path))
            self.assertEqual(m["name"], path.parent.name)
            self.assertEqual((m["version"], m["author"], m["api"]), ("0.1.0", "Pop Boll examples", 1))
            seen[m["name"]] = m
        self.assertEqual(sorted(seen), ["judge_heckler", "mixolydian_bridge", "tour_guide"])
        self.assertEqual(seen["judge_heckler"]["hooks"], ("on_verdict",))
        self.assertEqual(seen["judge_heckler"]["limits"], {"max_ms_per_call": 20, "max_directives_per_verdict": 1})
        self.assertEqual((seen["mixolydian_bridge"]["order"], seen["tour_guide"]["order"]), (100, 200))
        self.assertTrue(seen["tour_guide"]["description"].startswith("Doubles the last note"))

    def test_defaults(self):
        m = manifest.parse_manifest("name: ab\nversion: '1'\nauthor: x\nhooks: [on_plan]\nfuture_member: 3\n")
        self.assertEqual(m, {"name": "ab", "version": "1", "author": "x", "api": 1, "hooks": ("on_plan",),
                             "limits": {}, "order": 100, "description": ""})

    def test_schema_vectors_get_the_same_verdict_from_the_loader(self):
        # The manifest vectors are JSON documents; written out as YAML flow text they must be
        # accepted or refused by the loader exactly as the schema says.
        for v, doc in schema_vectors("routine-manifest"):
            with self.subTest(v["file"]):
                self.assertEqual(manifest.manifest_problems(doc) == [], v["valid"])

    def test_the_schema_decides_and_nothing_is_coerced(self):
        base = "name: ab\nauthor: x\nhooks: [on_plan]\n"
        good = ("version: 0.1.0\n", "version: '0.1'\n", "version: \"1\"\napi: 1\n", "version: v1\norder: -5\n",
                "version: v1\nlimits: {max_ms_per_call: 9999}\n", "version: v1\nlimits:\n  max_notes_factor: 1.5\n")
        for extra in good:
            manifest.parse_manifest(base + extra)
        bad = {
            "version: 0.1\n": "/version",                       # a number: today's loader would str() it
            "version: 1\n": "/version",
            "version: v1\napi: '1'\n": "/api",                   # today: int('1') == 1
            "version: v1\napi: true\n": "/api",
            "version: v1\napi: 2\n": "/api",
            "version: v1\norder: 1.9\n": "/order",               # today: truncated to 1
            "version: v1\norder: '5'\n": "/order",
            "version: v1\nlimits: {max_ms_per_call: fast}\n": "/limits/max_ms_per_call",   # today: read as the cap
            "version: v1\nlimits: {max_ms_per_call: true}\n": "/limits/max_ms_per_call",
            "version: v1\nlimits: {max_speed: 3}\n": "/limits/max_speed",
            "version: v1\nlimits:\n": "/limits",                 # today: None read as no limits
            "version: v1\ndescription:\n": "/description",
            "version: ' '\n": "/version",
        }
        for extra, pointer in bad.items():
            with self.assertRaises(ManifestError, msg=extra) as caught:
                manifest.parse_manifest(base + extra, "here")
            self.assertIn(pointer + ":", str(caught.exception), extra)
            self.assertTrue(str(caught.exception).startswith("here: "))
        with self.assertRaises(ManifestError) as caught:
            manifest.parse_manifest(base + "version: 0.1\n")
        self.assertIn('version: "0.1"', str(caught.exception))       # the hint
        for text in ("", "- a\n", "name: Ab\nversion: v1\nauthor: x\nhooks: [on_plan]\n",
                     "name: ab\nversion: v1\nauthor: x\nhooks: []\n", "name: ab\nversion: v1\nauthor: x\nhooks: [on_song]\n",
                     "name: ab\nversion: v1\nauthor: x\n", "name: ab\nversion: v1\nauthor: x\nhooks: on_plan\n",
                     "name: ab\nversion: yes\nauthor: x\nhooks: [on_plan]\n"):
            with self.assertRaises(ManifestError, msg=text):
                manifest.parse_manifest(text)
        self.assertTrue(issubclass(ManifestError, RoutineError))

    def test_the_constants_agree_with_the_schema_and_the_package(self):
        body = schema.load("routine-manifest")["properties"]
        self.assertEqual(tuple(body["hooks"]["items"]["enum"]), routines.HOOKS)
        self.assertEqual(sorted(body["limits"]["properties"]), sorted(routines.HARD_LIMITS))
        self.assertEqual(body["name"]["pattern"], routines.NAME_RE.pattern.replace(r"\Z", "$"))
        self.assertEqual(routines.API_VERSION, SPEAKS["routine_api"])


# ── loading ──────────────────────────────────────────────────────────────────────────────

class Loading(Folder):
    def test_a_json_manifest_loads(self):
        folder = self.routine("json_routine", "def on_plan(ctx, plan):\n    return None\n")
        (folder / "routine.yaml").write_text(json.dumps({"name": "json_routine", "version": "0.1.0", "author": "A Test",
                                                         "hooks": ["on_plan"]}))
        rset = load_routines([folder], factory=sim.FACTORY)
        self.assertEqual((rset.load_failures, bool(rset)), ([], True))

    def test_the_examples_load_in_order(self):
        rset = load_routines([EXAMPLES], factory=sim.FACTORY)
        self.assertEqual(rset.names, ["judge_heckler", "mixolydian_bridge", "tour_guide"])
        self.assertEqual(rset.load_failures, [])
        self.assertTrue(rset)
        self.assertFalse(RoutineSet([]))

    def test_discovery_order_duplicates_and_failures(self):
        ok = "def on_export(meta, ctx):\n    return {'seen': True}\n"
        self.routine("bb_second", ok, where=self.tmp / "data" / "routines")
        self.routine("aa_first", ok, extra="order: 200\n", where=self.tmp / "data" / "routines")
        self.routine("_hidden", ok, where=self.tmp / "data" / "routines")
        other = self.tmp / "elsewhere"
        self.routine("aa_first", ok, where=other)                       # a second routine of the same name
        broken = self.routine("zz_broken", "def on_export(meta, ctx):\n    return {}\n", hooks=["on_plan"], where=other)
        (other / "no_manifest").mkdir()
        os.environ["POPBOLLARD_ROUTINES"] = str(other)
        rset = load_routines(data_dir=self.tmp / "data", factory=sim.FACTORY)
        self.assertEqual(rset.names, ["bb_second", "aa_first"])         # order 100 before order 200
        self.assertEqual([(f["name"], f["hook"]) for f in rset.load_failures], [("aa_first", "load"), ("zz_broken", "load")])
        self.assertIn("duplicate name", rset.load_failures[0]["error"])
        self.assertIn("does not define", rset.load_failures[1]["error"])
        self.assertEqual(rset.load_failures[1]["where"], str(broken))
        song = sim.run_song(rset)
        self.assertEqual([f["name"] for f in song["meta"]["routines_failed"]], ["aa_first", "zz_broken"])
        self.assertEqual(sorted(song["meta"]["routine_meta"]), ["aa_first", "bb_second"])

    def test_default_dirs_need_a_data_dir_or_the_environment(self):
        self.assertEqual(routines.default_routine_dirs(), [])
        os.environ["POPBOLLARD_DATA_DIR"] = str(self.tmp)
        os.environ["POPBOLLARD_ROUTINES"] = os.pathsep.join(["/x", "/y"])
        self.assertEqual(routines.default_routine_dirs(), [self.tmp / "routines", pathlib.Path("/x"), pathlib.Path("/y")])
        self.assertEqual(routines.default_routine_dirs(pathlib.Path("/d"))[0], pathlib.Path("/d/routines"))

    def test_switches(self):
        path = self.routine("ok_routine", "def on_export(meta, ctx):\n    return None\n")
        self.assertTrue(load_routines([path]))
        for key in ("POPBOLLARD_NO_ROUTINES", "K_SERVICE", "POPBOLLARD_CLOUD_RUN"):
            os.environ[key] = "1"
            self.assertFalse(load_routines([path]), key)
            del os.environ[key]

    def test_a_zip_is_a_routine_and_writes_beside_itself(self):
        src = self.routine("zipped", """
            def on_export(meta, ctx):
                (ctx.folder / "seen.txt").write_text(meta["song_id"])
                return {"folder": ctx.folder.name}
            """)
        archive = self.tmp / "zipped.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for f in src.iterdir():
                zf.write(f, "zipped/" + f.name)
        (self.tmp / "zipped.data").mkdir()
        self.assertTrue(routines.is_package(archive))
        rset = load_routines([archive], factory=sim.FACTORY)
        song = sim.run_song(rset)
        self.assertEqual(song["meta"]["routines_failed"], [])
        self.assertEqual(song["meta"]["routine_meta"]["zipped"], {"folder": "zipped.data"})
        self.assertEqual((self.tmp / "zipped.data" / "seen.txt").read_text(), "sim-0001")
        self.assertFalse(routines.is_package(self.tmp / "zipped.data"))

    def test_banned_imports_are_refused_before_anything_runs(self):
        for line in ("import socket", "from urllib import request", "import subprocess as sp", "import ctypes.util"):
            with self.assertRaises(RoutineError, msg=line):
                routines.check_source(line + "\n", "x")
        routines.check_source("import json, math\nfrom dataclasses import replace\nfrom . import nothing\n", "x")
        path = self.routine("dialler", "import socket\n\ndef on_export(meta, ctx):\n    return None\n")
        rset = load_routines([path])
        self.assertEqual((rset.names, len(rset.load_failures)), ([], 1))
        self.assertIn("import of 'socket'", rset.load_failures[0]["error"])
        with self.assertRaises(RoutineError):
            load_routine(path)

    def test_the_host_names_its_own_modules_a_routine_may_not_import(self):
        # The SDK lists only generic modules; a host passes the names of its own.
        self.assertEqual(routines.BANNED_IMPORTS, frozenset({
            "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
            "telnetlib", "xmlrpc", "asyncio", "subprocess", "multiprocessing", "ctypes", "cffi"}))
        code = "import my_engine.state\n\ndef on_export(meta, ctx):\n    return None\n"
        routines.check_source(code, "x")                                # nothing of the host's is banned by default
        with self.assertRaises(RoutineError):
            routines.check_source(code, "x", banned_imports=["my_engine"])
        with self.assertRaises(RoutineError):
            routines.check_source("from my_corpus_writer import save\n", "x", banned_imports={"my_corpus_writer"})
        with self.assertRaises(RoutineError):
            routines.check_source("import socket\n", "x", banned_imports=["my_engine"])   # the generic list still holds
        path = self.routine("reacher", code)
        rset = load_routines([path], banned_imports=["my_engine"])
        self.assertEqual(rset.names, [])
        self.assertIn("import of 'my_engine.state'", rset.load_failures[0]["error"])
        with self.assertRaises(RoutineError):
            load_routine(path, banned_imports=("my_engine",))
        for bad in ("my_engine", ["my_engine.state"], [""], [7]):
            with self.assertRaises(RoutineSetupError, msg=repr(bad)):
                load_routines([path], banned_imports=bad)

    def test_a_bad_manifest_is_a_load_failure(self):
        path = self.routine("coerced", "def on_export(meta, ctx):\n    return None\n")
        (path / "routine.yaml").write_text("name: coerced\nversion: 0.1\nauthor: x\nhooks: [on_export]\n")
        rset = load_routines([path])
        self.assertEqual(rset.names, [])
        self.assertIn("/version", rset.load_failures[0]["error"])

    def test_listing(self):
        out = subprocess.run([sys.executable, "-m", "bollardeck.routines", str(EXAMPLES)], capture_output=True, text=True,
                             env=dict(os.environ, PYTHONPATH=str(ROOT / "python")), check=True)
        lines = out.stdout.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("mixolydian_bridge 0.1.0 by Pop Boll examples  hooks=on_plan", lines[1])


# ── the hooks ────────────────────────────────────────────────────────────────────────────

class Hooks(Folder):
    def test_the_examples_do_what_they_say(self):
        rset = load_routines([EXAMPLES], factory=sim.FACTORY)
        plain = sim.run_song(RoutineSet([], factory=sim.FACTORY), seed=7)
        song = sim.run_song(rset, seed=7)
        self.assertEqual(song["meta"]["routines_failed"], [])
        applied = {a["name"]: a for a in song["meta"]["routines_applied"]}
        self.assertEqual(sorted(applied), ["judge_heckler", "mixolydian_bridge", "tour_guide"])
        self.assertEqual(applied["mixolydian_bridge"]["hooks_called"], {"on_plan": 1})
        bridge = [p for p in song["plan"].parts if p.category == "Bridge"]
        self.assertEqual([p.progression for p in bridge], [["I", "bVII", "IV", "I"]])
        self.assertEqual([p.progression for p in song["plan"].parts if p.category != "Bridge"],
                         [p.progression for p in plain["plan"].parts if p.category != "Bridge"])
        heckled = [t for t in song["takes"] if t["routine_directives"]]
        self.assertTrue(heckled and all(t["routine_directives"] == ["MORE_HOOK"] for t in heckled))
        self.assertEqual(len(applied["judge_heckler"]["log"]), len(heckled))
        self.assertEqual(song["overdubs"], [{"routine": "tour_guide", "part_index": 1, "notes_added": 1}])
        self.assertEqual(song["bus"].locked_parts[1][-1].origin_tag, "routine:tour_guide")
        self.assertEqual(len(song["bus"].locked_parts[2]), len(plain["bus"].locked_parts[2]) + 1)
        self.assertEqual(song["meta"]["routine_meta"]["tour_guide"]["song"], "sim-0001")
        first = song["film"]["shots"][0]
        self.assertEqual((first["kind"], first["by_routine"], first["t_ms"]), ("title_card", "tour_guide", 0))
        self.assertEqual(song["film"]["total_ms"], plain["film"]["total_ms"] + 1200)
        self.assertEqual(song["film"]["kinds"], {"title_card": 1, "part": 4})
        self.assertNotIn("routines_applied", plain["meta"])

    def test_the_same_seed_gives_the_same_song(self):
        a = sim.run_song(load_routines([EXAMPLES], factory=sim.FACTORY), seed=11)
        b = sim.run_song(load_routines([EXAMPLES], factory=sim.FACTORY), seed=11)
        self.assertEqual(a["meta"], b["meta"])
        self.assertEqual(a["bus"], b["bus"])
        self.assertEqual(a["film"], b["film"])

    def test_ctx(self):
        song, failed = self.run_one("looker", """
            def on_plan(plan, ctx):
                a, b = ctx.rng.random(), ctx.rng.random()
                ctx.log(f"{ctx.hook} {ctx.routine_name} {ctx.routine_version} api={ctx.api} song={ctx.song_id}")
                ctx.log(f"corpus={list(ctx.corpus.ids)} labels={len(ctx.corpus.labels)} dna={dict(ctx.corpus.dna)}")
                ctx.log(f"device={dict(ctx.device)} part={ctx.part} take={ctx.take} folder={ctx.folder.name}")
                ctx.log(f"roster={sorted(ctx.roster)} taste={dict(ctx.taste_dna)} rng={a != b}")
                try:
                    ctx.corpus.ids = ()
                except AttributeError:
                    ctx.log("corpus is read-only")
                try:
                    ctx.device["serial"] = "x"
                except TypeError:
                    ctx.log("device is read-only")
                for i in range(100):
                    ctx.log(f"line {i}")
            def on_verdict(part, verdicts, ctx):
                assert ctx.part["label"] == part.label and ctx.take == 1
                try:
                    verdicts[0].score = 1.0
                except Exception as exc:
                    ctx.log(type(exc).__name__)
            """, extra="limits: {max_log_lines: 7}\n")
        self.assertIsNone(failed)
        log = song["meta"]["routines_applied"][0]["log"]
        self.assertEqual(log[0], "on_plan looker 0.1.0 api=1 song=sim-0001")
        self.assertEqual(log[1], "corpus=['0000-SIM'] labels=1 dna={}")
        self.assertEqual(log[2], "device={'serial': '', 'song_id_prefix': 'pb0000'} part=None take=None folder=looker")
        self.assertEqual(log[3], "roster=['judges', 'musicians'] taste={} rng=True")
        self.assertEqual(log[4:6], ["corpus is read-only", "device is read-only"])
        self.assertEqual(len(log), 7, "the log is capped by the manifest's own limit")
        rset = load_routines([self.tmp / "looker"], factory=sim.FACTORY)
        song = sim.run_song(rset, device_serial="PB0042-UNOQ-AB12")
        self.assertIn("'song_id_prefix': 'pb0042'", song["meta"]["routines_applied"][0]["log"][2])

    def test_on_plan_keeps_only_what_it_may_change(self):
        song, failed = self.run_one("planner", """
            def on_plan(plan, ctx):
                plan.parts.reverse()
                plan.parts[0].energy = 0.25
                plan.parts[0].bars = 12
                plan.parts[0].label = "x" * 99
                plan.parts[0].progression = ["V", "IV"]
            """)
        self.assertIsNone(failed)
        parts = song["plan"].parts
        self.assertEqual([p.part_index for p in parts], [1, 2, 3, 4])
        self.assertEqual([p.category for p in parts], ["Chorus", "Bridge", "Chorus", "Verse"])
        self.assertEqual((parts[0].energy, parts[0].bars, parts[0].progression, len(parts[0].label)), (0.25, 12, ["V", "IV"], 40))
        self.assertEqual(song["plan"].total_bars, 12 + 4 + 8 + 8)
        refused = {
            "plan.parts[0].category = 'Intro'": "may not change part.category",
            "plan.parts[0].progression = ['H7']": "chords from the chord library",
            "plan.parts[0].progression = []": "chords from the chord library",
            "plan.parts[0].energy = 1.5": "outside 0-1",
            "plan.parts[0].bars = 6": "multiple of 4",
            "plan.parts.pop()": "not add or remove",
            "plan.bpm = 999": "may not change plan.bpm",
            "return 'a plan'": "must return the plan",
            "raise KeyError('oops')": "KeyError",
        }
        for i, (line, why) in enumerate(refused.items()):
            song, failed = self.run_one("planner%d" % i, "def on_plan(plan, ctx):\n    %s\n" % line)
            self.assertIsNotNone(failed, line)
            self.assertIn(why, failed["error"], line)
            self.assertEqual(failed["hook"], "on_plan")
            self.assertEqual(song["plan"], sim.demo_plan(3), "a refused change leaves the plan as it was: " + line)
            self.assertEqual(song["meta"]["routines_applied"], [], "a failed routine is not listed as applied")

    def test_a_suite_keeps_its_order(self):
        path = self.routine("shuffler", "def on_plan(plan, ctx):\n    plan.parts.reverse()\n")
        rset = load_routines([path], factory=sim.FACTORY)
        rset.begin_song(song_id="s", rng_seed=1)
        plan = replace(sim.demo_plan(1), form="suite")
        self.assertEqual([p.part_index for p in rset.plan(plan).parts], [1, 2, 3, 4])
        self.assertIn("suite", rset.report()["routines_failed"][0]["error"])

    def test_on_part_candidate(self):
        song, failed = self.run_one("thinner", "def on_part_candidate(part, notes, ctx):\n    return notes[::2]\n")
        self.assertIsNone(failed)
        self.assertEqual([t["notes"] for t in song["takes"]], [16, 16, 8, 16])
        refused = {
            "return 'notes'": "must return a list",
            "return notes * 40": "at most",
            "return [1]": "not a NoteEvent",
            "from dataclasses import replace\n    return [replace(notes[0], pitch=200)]": "invalid note",
            "from dataclasses import replace\n    return [replace(notes[0], start_tick=10**9)]": "invalid note",
        }
        for i, (line, why) in enumerate(refused.items()):
            song, failed = self.run_one("thinner%d" % i, "def on_part_candidate(part, notes, ctx):\n    %s\n" % line)
            self.assertIsNotNone(failed, line)
            self.assertIn(why, failed["error"], line)
            self.assertEqual(failed["where"], "on_part_candidate part 1 take 1")
            self.assertEqual([t["notes"] for t in song["takes"]], [32, 32, 16, 32], line)

    def test_on_verdict(self):
        song, failed = self.run_one("critic", """
            def on_verdict(part, verdicts, ctx):
                assert len(verdicts) == 7 and verdicts[1].judge_id.startswith("J2")
                return {"directives": ["MORE_COWBELL", "MORE_COWBELL", "LESS_REVERB"], "veto": ctx.take < 2, "reason": "x"}
            """)
        self.assertIsNone(failed)
        self.assertEqual([(t["part_index"], t["take"]) for t in song["takes"]][:4], [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual(song["takes"][0]["vetoed_by"], ["critic"])
        self.assertEqual(song["takes"][1]["routine_directives"], ["MORE_COWBELL", "LESS_REVERB"])
        refused = {
            "return ['MORE_COWBELL']": "None or a mapping",
            "return {'directives': ['more']}": "codes matching",
            "return {'directives': ['AAA', 'BBB', 'CCC', 'DDD', 'EEE']}": "must be <= 4",
            "return {'score': 1.0}": "may only return",
        }
        for i, (line, why) in enumerate(refused.items()):
            _song, failed = self.run_one("critic%d" % i, "def on_verdict(part, verdicts, ctx):\n    %s\n" % line)
            self.assertIsNotNone(failed, line)
            self.assertIn(why, failed["error"], line)

    def test_on_overdub_export_and_drama_refusals(self):
        refused = [
            ("on_overdub(plan, bus, ctx)", "return {99: []}", "not a locked part"),
            ("on_overdub(plan, bus, ctx)", "return [1]", "must return None or"),
            ("on_overdub(plan, bus, ctx)", "return {1: list(bus['locked_parts'][1]) * 40}", "too many overdub notes"),
            ("on_overdub(plan, bus, ctx)", "return {1: ['note']}", "invalid overdub note"),
            ("on_overdub(plan, bus, ctx)", "bus['locked_parts'][1] = ()", "TypeError"),
            ("on_export(meta, ctx)", "return ['x']", "None or a mapping"),
            ("on_export(meta, ctx)", "return {'blob': 'x' * 20000}", "over 16384 bytes"),
            ("on_export(meta, ctx)", "return {'x': object()}", "TypeError"),
            ("on_export(meta, ctx)", "meta['song_id'] = 'forged'", "TypeError"),
            ("on_drama(shots, ctx)", "return shots[1:]", "removed or changed 1 original"),
            ("on_drama(shots, ctx)", "return 'film'", "must return a list"),
            ("on_drama(shots, ctx)", "return shots + [{'kind': 'x', 'duration_ms': 5}]", "needs a str kind"),
            ("on_drama(shots, ctx)", "return shots + [{'kind': 'x', 'duration_ms': 500}] * 33", "limit 32"),
        ]
        for i, (signature, line, why) in enumerate(refused):
            song, failed = self.run_one("late%d" % i, "def %s:\n    %s\n" % (signature, line))
            where = "%s -> %s" % (signature, line)
            if signature.startswith("on_drama"):
                failed = next((f for f in song["film"]["routines_failed"]), None)
                self.assertEqual(len(song["film"]["shots"]), 4, where)
            self.assertIsNotNone(failed, where)
            self.assertIn(why, failed["error"], where)
        song, failed = self.run_one("mover", "def on_drama(shots, ctx):\n    return shots[::-1]\n")
        self.assertEqual([s["data"]["label"] for s in song["film"]["shots"]], ["Chorus 2", "Bridge", "Chorus 1", "Verse 1"])
        self.assertEqual([s["t_ms"] for s in song["film"]["shots"]], [0, 4000, 6000, 10000])

    def test_a_failed_routine_is_off_for_the_rest_of_the_song_only(self):
        path = self.routine("flaky", """
            CALLS = []
            def on_part_candidate(part, notes, ctx):
                CALLS.append(part.part_index)
                if part.part_index == 2:
                    raise RuntimeError("part two is cursed")
            def on_export(meta, ctx):
                return {"calls": CALLS}
            """)
        rset = load_routines([path], factory=sim.FACTORY)
        song = sim.run_song(rset)
        self.assertEqual(rset.routines[0].module.CALLS, [1, 2])       # not called for parts 3 and 4, nor on_export
        self.assertNotIn("routine_meta", song["meta"])
        self.assertEqual(song["meta"]["routines_failed"][0]["where"], "on_part_candidate part 2 take 1")
        again = sim.run_song(rset, song_id="sim-0002")                 # a new song starts clean
        self.assertEqual(again["meta"]["routines_failed"][0]["where"], "on_part_candidate part 2 take 1")
        self.assertEqual(rset.routines[0].module.CALLS, [1, 2, 1, 2])

    def test_limits_tighten_and_never_loosen(self):
        slow = "import time\n\ndef on_export(meta, ctx):\n    time.sleep(0.03)\n    return {}\n"
        _song, failed = self.run_one("slow_tight", slow, extra="limits: {max_ms_per_call: 5}\n")
        self.assertIn("limit 5 ms", failed["error"])
        _song, failed = self.run_one("slow_default", slow)
        self.assertIsNone(failed)
        path = self.routine("greedy", "def on_export(meta, ctx):\n    return {}\n", extra="limits: {max_ms_per_call: 99999, max_log_lines: 0}\n")
        r = load_routine(path)
        self.assertEqual((r.limit("max_ms_per_call"), r.limit("max_log_lines"), r.limit("max_added_shots")), (250.0, 0.0, 32))

    def test_the_guard(self):
        outside = self.tmp / "outside.txt"
        refused = {
            "open(%r, 'w').write('x')" % str(outside): "outside the routine's folder",
            "__import__('os').remove(%r)" % str(outside): "outside the routine's folder",
            "__import__('os').system('true')": "is not allowed inside a routine",
            "__import__('soc' + 'ket').socket()": "is not allowed inside a routine",
            "__import__('sub' + 'process').run(['true'])": "is not allowed inside a routine",
            "open(%r).read()" % str(self.tmp / "soul_keystore.json"): "may not read the device's soul",
            "__import__('sqlite3').connect(%r)" % str(self.tmp / "state.db"): "outside the routine's folder",
        }
        outside.write_text("kept")
        (self.tmp / "soul_keystore.json").write_text("{}")
        for i, (line, why) in enumerate(refused.items()):
            _song, failed = self.run_one("guarded%d" % i, "def on_export(meta, ctx):\n    %s\n" % line)
            self.assertIsNotNone(failed, line)
            self.assertIn("PermissionError", failed["error"], line)
            self.assertIn(why, failed["error"], line)
        self.assertEqual(outside.read_text(), "kept")
        song, failed = self.run_one("tidy", """
            import pathlib, sqlite3
            def on_export(meta, ctx):
                (ctx.folder / "notes.txt").write_text("mine")
                sqlite3.connect(":memory:").close()
                return {"read": pathlib.Path(%r).read_text()}
            """ % str(outside))
        self.assertIsNone(failed)                                    # reading elsewhere and writing at home are fine
        self.assertEqual(song["meta"]["routine_meta"]["tidy"], {"read": "kept"})
        self.assertEqual((self.tmp / "tidy" / "notes.txt").read_text(), "mine")
        outside.write_text("the guard is off outside a hook")        # and this test may write again

    def test_a_factory_is_needed_only_by_the_hooks_that_use_it(self):
        path = self.routine("needs_notes", "def on_part_candidate(part, notes, ctx):\n    return notes\n")
        rset = load_routines([path])
        rset.begin_song(song_id="s", rng_seed=1)
        plan = sim.demo_plan(1)
        self.assertIs(rset.plan(plan), plan)                         # no on_plan routine: nothing asked
        self.assertEqual(rset.overdub(plan, sim.Bus()), [])
        self.assertEqual(rset.drama(sim.demo_film(plan))["total_ms"], 14000)
        with self.assertRaises(RoutineSetupError):
            rset.part_candidate(plan.parts[0], sim.demo_notes(plan.parts[0]), 1)
        rset.factory = Factory(chords={"I"}, note_type=sim.NoteEvent, ticks_per_bar=1920)
        self.assertEqual(len(rset.part_candidate(plan.parts[0], sim.demo_notes(plan.parts[0]), 1)), 32)

    def test_freeze_and_thaw(self):
        value = {"a": [1, {"b": {2, 3}}], "c": (4, 5)}
        frozen = routines.freeze(value)
        with self.assertRaises(TypeError):
            frozen["a"] = 1
        self.assertEqual(frozen["a"][1]["b"], frozenset({2, 3}))
        self.assertEqual(routines.thaw(frozen), {"a": [1, {"b": [2, 3]}], "c": [4, 5]})
        self.assertEqual(routines.freeze(sim.demo_plan(1))["parts"][0]["label"], "Verse 1")

    def test_a_checkpointed_state_resumes(self):
        rset = load_routines([EXAMPLES], factory=sim.FACTORY)
        state = {}
        rset.begin_song(song_id="s", rng_seed=1, state=state)
        rset.plan(sim.demo_plan(1))
        saved = copy.deepcopy(state)
        self.assertEqual(saved["applied"]["mixolydian_bridge"]["hooks_called"], {"on_plan": 1})
        fresh = load_routines([EXAMPLES], factory=sim.FACTORY)
        fresh.begin_song(song_id="s", rng_seed=1, state=saved)
        self.assertEqual(fresh.report()["routines_applied"][1]["hooks_called"], {"on_plan": 1})


class Docs(unittest.TestCase):
    def test_usage_guides(self):
        from bollardeck.routines import runner
        for module in (routines, manifest, yamlsubset, sim, runner):
            self.assertGreater(len(module.__doc__ or ""), 300, module.__name__)
        for hook in routines.HOOKS:
            self.assertIn("`%s(" % hook, routines.__doc__)

    def test_nothing_from_a_device_is_imported(self):
        text = (ROOT / "python" / "bollardeck" / "routines" / "runner.py").read_text()
        for word in ("pop_theory", "drama_director", "import yaml", "from device_identity", "REPO_ROOT"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
