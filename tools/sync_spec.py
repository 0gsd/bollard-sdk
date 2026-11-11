#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sync_spec.py: keep spec/ an exact copy of the public specification pages.

The pages are written in the popbollard repository (docs/public/spec/) and published at
popboll.com/spec. This repository carries unchanged copies, with their checksums in
spec/SOURCES.json.

    tools/sync_spec.py sync  --from /path/to/popbollard   copy the pages and rewrite SOURCES.json
    tools/sync_spec.py check                              spec/ matches SOURCES.json (CI runs this)
    tools/sync_spec.py check --from /path/to/popbollard   and popbollard's pages match too

Standard library only.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec"
SOURCES = SPEC / "SOURCES.json"
SOURCE_DIR = "docs/public/spec"
# The pages carried here. The Glass Snipler and PWHAMSS pages are published at popboll.com/spec
# and are not copied.
PAGES = ("index.md", "bollard.md", "bollardeck.md", "popsniplish.md")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_commit(checkout):
    try:
        out = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def sync(checkout):
    src = pathlib.Path(checkout) / SOURCE_DIR
    pages = {}
    for name in PAGES:
        data = (src / name).read_bytes()
        (SPEC / name).write_bytes(data)
        pages[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    record = {
        "schema": "bollard-sdk.spec-sources/1",
        "source_repository": "popbollard",
        "source_path": SOURCE_DIR,
        "source_commit": source_commit(checkout),
        "published_at": "https://popboll.com/spec",
        "licence": "CC-BY-4.0",
        "attribution": "Pop Boll, by Graham Smith, CC BY 4.0",
        "pages": pages,
    }
    SOURCES.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def problems(checkout=None):
    """Every way spec/ disagrees with SOURCES.json (and with `checkout`, when given)."""
    found = []
    if not SOURCES.exists():
        return ["spec/SOURCES.json is missing"]
    record = json.loads(SOURCES.read_text())
    pages = record.get("pages", {})
    if sorted(pages) != sorted(PAGES):
        found.append("SOURCES.json lists %s, expected %s" % (sorted(pages), sorted(PAGES)))
    on_disk = sorted(p.name for p in SPEC.glob("*.md"))
    if on_disk != sorted(PAGES):
        found.append("spec/ holds %s, expected %s" % (on_disk, sorted(PAGES)))
    for name, entry in pages.items():
        path = SPEC / name
        if not path.exists():
            found.append("%s is missing" % name)
        elif sha256(path) != entry.get("sha256"):
            found.append("%s differs from its recorded checksum (edit the source, then sync)" % name)
    if checkout is not None:
        src = pathlib.Path(checkout) / SOURCE_DIR
        for name, entry in pages.items():
            upstream = src / name
            if not upstream.exists():
                found.append("%s is missing upstream" % name)
            elif sha256(upstream) != entry.get("sha256"):
                found.append("%s has changed upstream since the last sync" % name)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("command", choices=("sync", "check"))
    parser.add_argument("--from", dest="checkout", help="a popbollard checkout")
    args = parser.parse_args(argv)
    if args.command == "sync":
        if not args.checkout:
            parser.error("sync needs --from")
        record = sync(args.checkout)
        print("synced %d pages from %s" % (len(record["pages"]), record["source_commit"][:12]))
        return 0
    found = problems(args.checkout)
    for line in found:
        print("spec: " + line, file=sys.stderr)
    if not found:
        print("spec: ok (%d pages)" % len(PAGES))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
