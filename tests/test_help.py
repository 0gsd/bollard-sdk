# SPDX-License-Identifier: Apache-2.0
"""bollardeck.help: the Python checks, and their agreement with js/bollardeck.help.js."""
import copy
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import constants, help  # noqa: E402

CONFORMANCE = ROOT / "conformance"
NODE = shutil.which("node")

SENTENCES = [
    "hi.",
    "press PLAY to start, or the space key; the queue runs left to right.",
    "this all seems very complicated, and it totally is, but how it works and why it is fun is pretty simple.",
    "a sentence with no pauses at all that simply goes on and on well past the width of two caption lines and then some more words",
    "one—two — three: four! five? six.",
    "supercalifragilisticexpialidociousandthensomemorelettersthatdonotfit short words after",
    "  leading and trailing spaces  ",
]


def vector(schema_name, valid, name):
    return json.loads((CONFORMANCE / schema_name / ("valid" if valid else "invalid") / (name + ".json")).read_text())


def node(script):
    return subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, check=True).stdout


class Checks(unittest.TestCase):
    def test_semantic_pack_problems(self):
        doc = vector("help-pack", True, "full")
        self.assertEqual(help.pack_problems(doc), [])
        bad = copy.deepcopy(doc)
        bad["pages"]["player"]["scenarios"]["player.play-blocked"]["topic"] = "player.nothing"
        bad["pages"]["player"]["topics"]["player.play"]["see"] = ["player.gone"]
        bad["pages"]["player"]["scenarios"]["player.offline"]["detector"] = "telepathy"
        self.assertEqual([(p.pointer, p.keyword) for p in help.pack_problems(bad)], [
            ("/pages/player/topics/player.play/see/0", "see"),
            ("/pages/player/scenarios/player.play-blocked/topic", "topic"),
            ("/pages/player/scenarios/player.offline/detector", "detector"),
        ])

    def test_a_link_may_hold_no_space_or_control_character(self):
        for href in ("/\t/evil.example", "/\n/evil.example", "/a b", "/x\x7f", "/\\evil.example"):
            doc = vector("help-pack", True, "full")
            doc["pages"]["player"]["topics"]["player.queue"]["body"] = [[{"a": "away", "href": href}]]
            kw = [p.keyword for p in help.pack_problems(doc)]     # refused: by the link check, or already by the schema
            self.assertTrue("href" in kw or "pattern" in kw, (href, kw))

    def test_director_problems_and_timeline(self):
        cap = vector("help-director", True, "capture")
        self.assertEqual(help.director_problems(cap), [])
        tour = help.timeline(cap, "tour")
        self.assertFalse(any(s["do"] in ("act", "cut") or s.get("capture_only") for s in tour))
        self.assertEqual(len(help.timeline(cap, "capture")), len(cap["steps"]))
        long = {"schema": "help-director/1", "id": "tour.a.b", "title": "t", "page": "p", "role": "r",
                "steps": [{"do": "spot", "target": "a.b", "pop": "@say"}, {"do": "hide"},
                          {"do": "say", "text": "x" * (constants.HELP_SAY_MAX_CHARS + 1)}]}
        self.assertEqual([p.keyword for p in help.director_problems(long)], ["pop", "say-length"])

    def test_captions_fit(self):
        for s in SENTENCES:
            cues = help.split_caption(s)
            self.assertTrue(cues, s)
            self.assertEqual(" ".join(c.replace("\n", " ") for c in cues), " ".join(s.split()))
            for c in cues:
                self.assertLessEqual(len(c.split("\n")), 2, s)

    def test_lint_and_read_text(self):
        doc = vector("help-pack", True, "full")
        got = help.lint(doc, {"player": {"owner": ["player.play"], "guest": ["player.play"]}})
        self.assertEqual(len(got), 4)
        self.assertTrue(all(p.keyword == "target" for p in got))
        cap = vector("help-director", True, "capture")
        self.assertEqual([p.pointer for p in help.lint_director(cap, {"player": {"owner": ["player.play"]}}, ["song.locked"])],
                         ["/steps/2/target", "/steps/10/until"])
        self.assertEqual(help.read_text(cap), [{"chapter": "hello", "text": "hi."}])


@unittest.skipUnless(NODE, "node is not installed")
class AgreesWithJavaScript(unittest.TestCase):
    def test_captions_and_reading_time(self):
        js = json.loads(node(
            "const h = require('./js/bollardeck.js').help; const s = %s;"
            "console.log(JSON.stringify(s.map((x) => [h.splitCaption(x), h.sayMs(x)])));" % json.dumps(SENTENCES)))
        self.assertEqual(js, [[help.split_caption(s), help.say_ms(s)] for s in SENTENCES])

    def test_problems_lint_and_text(self):
        names = [("help-pack", True, "full"), ("help-director", True, "capture")]
        docs = [vector(*n) for n in names]
        bad = copy.deepcopy(docs[0])
        bad["pages"]["player"]["scenarios"]["player.offline"]["detector"] = "telepathy"
        bad["pages"]["player"]["topics"]["player.queue"]["body"] = [[{"a": "away", "href": "/\\\\evil.example"}]]
        manifest = {"player": {"owner": ["player.play"], "guest": ["player.play"]}}
        script = (
            "const h = require('./js/bollardeck.js').help; const d = %s, bad = %s, m = %s;"
            "const pp = (l) => l.map((p) => [p.pointer, p.keyword]);"
            "console.log(JSON.stringify([pp(h.problems(bad)), pp(h.lint(d[0], m)), pp(h.directorProblems(d[1])),"
            " pp(h.lintDirector(d[1], m, ['song.locked'])), h.readText(d[1]), h.timeline(d[1], 'tour').map((s) => [s.index, s.hold])]));"
            % (json.dumps(docs), json.dumps(bad), json.dumps(manifest)))
        js = json.loads(node(script))
        pp = lambda lst: [[p.pointer, p.keyword] for p in lst]  # noqa: E731
        self.assertEqual(js, [pp(help.pack_problems(bad)), pp(help.lint(docs[0], manifest)), pp(help.director_problems(docs[1])),
                              pp(help.lint_director(docs[1], manifest, ["song.locked"])), help.read_text(docs[1]),
                              [[s["index"], s["hold"]] for s in help.timeline(docs[1], "tour")]])


if __name__ == "__main__":
    unittest.main()
