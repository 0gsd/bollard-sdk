# SPDX-License-Identifier: Apache-2.0
"""The repository's own rules: one version everywhere, spec/ unchanged, and nothing but open files."""
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import bollardeck  # noqa: E402


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tracked_files():
    """Files git tracks (or would: untracked and not ignored), relative to the root."""
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, check=True)
    return sorted(line for line in out.stdout.splitlines() if line and (ROOT / line).is_file())


class Version(unittest.TestCase):
    def test_python_version_is_semver_like(self):
        self.assertRegex(bollardeck.__version__, r"^\d+\.\d+\.\d+(\.dev\d+|rc\d+)?$")

    def test_js_carries_the_same_version_and_wire_names(self):
        text = (ROOT / "js" / "bollardeck.js").read_text()
        self.assertIn('version: "%s"' % bollardeck.__version__, text)
        self.assertIn('minBollawax: "%s"' % bollardeck.MIN_BOLLAWAX, text)
        for key, value in bollardeck.SPEAKS.items():
            self.assertIn("%s: %s" % (key, json.dumps(value)), text)

    def test_c_header_carries_the_same_version(self):
        text = (ROOT / "c" / "bollardeck.h").read_text()
        self.assertIn('#define BOLLARDECK_SDK_VERSION "%s"' % bollardeck.__version__, text)
        self.assertIn('#define BOLLARDECK_WIRE "%s"' % bollardeck.SPEAKS["bollardeck"], text)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_node_loads_both_entry_points(self):
        script = (
            "const a = require('./js/bollardeck.js');"
            "import('./js/bollardeck.mjs').then(m => {"
            " console.log(JSON.stringify([a.version, m.default.version, m.version, a.speaks]));"
            "});"
        )
        out = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True)
        common, module_default, module_named, speaks = json.loads(out.stdout)
        self.assertEqual({common, module_default, module_named}, {bollardeck.__version__})
        self.assertEqual(speaks, bollardeck.SPEAKS)


class Package(unittest.TestCase):
    def test_every_subpackage_imports_with_the_standard_library_only(self):
        for name in ("corpus", "device", "deck", "pxs", "routines", "snipler"):
            module = __import__("bollardeck." + name, fromlist=["_"])
            self.assertTrue(module.__doc__ and module.__doc__.strip(), name)
        text = (ROOT / "pyproject.toml").read_text()
        self.assertIn("dependencies = []", text)


class Spec(unittest.TestCase):
    def test_spec_pages_match_their_recorded_checksums(self):
        self.assertEqual(load_tool("sync_spec").problems(), [])

    def test_sources_record_names_the_licence_and_attribution(self):
        record = json.loads((ROOT / "spec" / "SOURCES.json").read_text())
        self.assertEqual(record["licence"], "CC-BY-4.0")
        self.assertEqual(record["attribution"], "Pop Boll, by Graham Smith, CC BY 4.0")
        self.assertRegex(record["source_commit"], r"^[0-9a-f]{40}$")


# Only Apache-2.0 code and CC BY specification text may live here. Nothing from the Bollawax
# core, the Glass Snipler codebase, owner data or corpora, ever.
CODE_SUFFIXES = {".py", ".js", ".mjs", ".h", ".c", ".sh", ".yml", ".yaml", ".toml"}
CODE_SUFFIXES |= {".html"}          # examples/browser/: a page is code, and carries the SPDX line too
PLAIN_SUFFIXES = {".md", ".txt", ".json"}
PLAIN_NAMES = {"LICENSE", "NOTICE", ".gitignore"}
SPDX = re.compile(r"SPDX-License-Identifier: Apache-2\.0")
NO_HEADER_NEEDED = {"pyproject.toml"}


class OpenFilesOnly(unittest.TestCase):
    def test_every_file_is_of_a_known_kind(self):
        for rel in tracked_files():
            path = pathlib.PurePosixPath(rel)
            known = path.suffix in CODE_SUFFIXES | PLAIN_SUFFIXES or path.name in PLAIN_NAMES
            self.assertTrue(known, "%s: not a kind of file this repository carries" % rel)

    def test_code_files_carry_the_apache_spdx_line(self):
        for rel in tracked_files():
            path = pathlib.PurePosixPath(rel)
            if path.suffix not in CODE_SUFFIXES or path.name in NO_HEADER_NEEDED:
                continue
            head = "\n".join((ROOT / rel).read_text().splitlines()[:5])
            self.assertRegex(head, SPDX, "%s: no Apache-2.0 SPDX line in its first five lines" % rel)

    def test_markdown_outside_spec_is_not_a_spec_copy(self):
        for rel in tracked_files():
            if rel.endswith(".md") and rel.startswith("spec/"):
                self.assertIn(pathlib.PurePosixPath(rel).name, load_tool("sync_spec").PAGES)

    def test_no_reserved_material_outside_the_spec_copies(self):
        # The spec pages may describe what stays reserved; nothing else here may claim to be.
        for rel in tracked_files():
            if rel.startswith("spec/") or rel.startswith("LICENSES/") or rel == "LICENSE":
                continue
            if rel == "tests/test_skeleton.py":
                continue
            text = (ROOT / rel).read_text(errors="replace").lower()
            self.assertNotIn("all rights reserved", text, rel)


if __name__ == "__main__":
    unittest.main()
