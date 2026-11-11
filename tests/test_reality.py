# SPDX-License-Identifier: Apache-2.0
"""
An optional reality check: do the real files in a popbollard checkout fit the schemas?

It runs only when BOLLARD_SDK_POPBOLLARD names a popbollard checkout, and it only reads. Nothing
from that checkout is copied here: a mismatch is reported as a file, a JSON pointer and the
schema keyword that refused it, never as the file's content.

    BOLLARD_SDK_POPBOLLARD=/path/to/popbollard python3 -m unittest tests.test_reality -v

A mismatch is a finding, not always a bug here: fix the schema only when it was wrong about what
the platform does today, and report the rest.
"""
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import schema  # noqa: E402

ENV = "BOLLARD_SDK_POPBOLLARD"
CHECKOUT = pathlib.Path(os.environ[ENV]).expanduser() if os.environ.get(ENV) else None
SKIP_DIRS = {".git", ".claude", "node_modules", ".venv", "__pycache__"}


def find(name):
    """Every file called `name` in the checkout, skipping other worktrees and vendored folders."""
    found = []
    for folder, dirs, files in os.walk(CHECKOUT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        if name in files:
            found.append(pathlib.Path(folder) / name)
    return found


def cue_list_of(line):
    """The cue list a hal cue line stands for: "1:on:a 2:off:- 3:pulse:go", every button named."""
    cues = []
    for part in line.split():
        button, state, role = part.split(":")
        cues.append({"button": int(button), "state": state, "role": None if role == "-" else role})
    return cues


@unittest.skipUnless(CHECKOUT, "set %s to a popbollard checkout to run the reality check" % ENV)
class Reality(unittest.TestCase):
    def setUp(self):
        self.assertTrue((CHECKOUT / "routines.py").is_file(), "%s is not a popbollard checkout" % CHECKOUT)

    def check(self, name, documents):
        """`documents` is [(path, where in the file, value)]; fails with every mismatch at once."""
        self.assertTrue(documents, "nothing to check against the %s schema" % name)
        findings = []
        for path, where, value in documents:
            for p in schema.validate(name, value):
                findings.append("%s%s  #%s  (%s)" % (path.relative_to(CHECKOUT), where, p.pointer, p.keyword))
        self.assertEqual(findings, [], "%d mismatch(es) with the %s schema:\n  %s"
                         % (len(findings), name, "\n  ".join(findings)))

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_example_routine_manifests(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed (routine.yaml is YAML)")
        paths = sorted((CHECKOUT / "examples" / "routines").glob("*/routine.yaml"))
        self.check("routine-manifest", [(p, "", yaml.safe_load(p.read_text(encoding="utf-8"))) for p in paths])

    def test_maker_registry(self):
        path = CHECKOUT / "makers.json"
        if not path.is_file():
            # From Bollawax 0.2.4 the registry is the SDK's own (constants/makers.json) and the
            # checkout carries no copy to compare.
            self.skipTest("the checkout holds no makers.json (the registry is the SDK's from 0.2.4)")
        self.check("makers", [(path, "", self.read_json(path))])

    def test_corpus_manifests_and_their_licence_blocks(self):
        paths = find("corpus.json")
        self.check("corpus-manifest", [(p, "", self.read_json(p)) for p in paths])
        blocks = [(p, " licence", self.read_json(p)["licence"]) for p in paths
                  if isinstance(self.read_json(p).get("licence"), dict)]
        self.check("licence", blocks)

    def test_hal_cue_fixture(self):
        path = CHECKOUT / "tests" / "fixtures" / "hal_sim_cues.txt"
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.check("cue", [(path, " line %d" % (i + 1), cue_list_of(line)) for i, line in enumerate(lines)])

    def test_device_identity_files(self):
        paths = find("device_identity.json")
        if not paths:
            self.skipTest("the checkout holds no device_identity.json")
        self.check("device-identity", [(p, "", self.read_json(p)) for p in paths])

    def test_image_release_records(self):
        paths = [p for p in find("latest.json") if "images" in p.parts or "bollawax" in p.parts]
        if not paths:
            self.skipTest("the checkout holds no latest.json")
        self.check("image-release", [(p, "", self.read_json(p)) for p in paths])


if __name__ == "__main__":
    unittest.main()
