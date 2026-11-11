# SPDX-License-Identifier: Apache-2.0
"""
An optional reality check for the corpus reader: what does it make of the real manifests in a
popbollard checkout?

It runs only when BOLLARD_SDK_POPBOLLARD names a popbollard checkout, and it only reads. It
copies nothing from there: it prints, per manifest, the corpus id and the gate's reason, never
the manifest's content.

    BOLLARD_SDK_POPBOLLARD=/path/to/popbollard python3 -m unittest tests.test_corpus_reality -v

Expected today: every manifest loads; the ones written before licences existed are refused by
the gate as licence_missing until they are given real blocks.
"""
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck.corpus import Corpus, ManifestRefused  # noqa: E402

ENV = "BOLLARD_SDK_POPBOLLARD"
CHECKOUT = pathlib.Path(os.environ[ENV]).expanduser() if os.environ.get(ENV) else None
SKIP_DIRS = {".git", ".claude", "node_modules", ".venv", "__pycache__"}


@unittest.skipUnless(CHECKOUT, "set %s to a popbollard checkout to run the reality check" % ENV)
class CorpusReality(unittest.TestCase):
    def test_every_real_manifest_loads_and_the_gate_answers_for_it(self):
        paths = []
        for folder, dirs, files in os.walk(CHECKOUT):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            if "corpus.json" in files:
                paths.append(pathlib.Path(folder) / "corpus.json")
        self.assertTrue(paths, "no corpus.json in %s" % CHECKOUT)
        refused = []
        for path in paths:
            rel = path.relative_to(CHECKOUT)
            try:
                c = Corpus.from_manifest(json.loads(path.read_text(encoding="utf-8")))
            except ManifestRefused as exc:
                refused.append("%s: %s (%d problems)" % (rel, exc.reason, len(exc.problems)))
                continue
            study = c.may("study")
            self.assertIn(study.reason, ("allowed", "licence_missing", "not_visible"), rel)
            print("  %-48s %-22s study: %s" % (rel, c.id, study.reason))
        self.assertEqual(refused, [], "real manifests the reader refuses")


if __name__ == "__main__":
    unittest.main()
