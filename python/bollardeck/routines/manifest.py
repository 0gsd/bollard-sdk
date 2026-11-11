# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.routines.manifest: reading a routine's `routine.yaml`.

    from bollardeck.routines import manifest
    m = manifest.parse_manifest(text, where="my_routine/routine.yaml")
    m["name"], m["version"], m["author"], m["hooks"], m["limits"], m["order"], m["description"]

The text is read with `bollardeck.routines.yamlsubset` and the document is checked against the
`routine-manifest` schema. Anything either refuses raises `ManifestError`, with the line or the
JSON pointer. Nothing is coerced: `version: 0.1` is a number and is refused (write `"0.1"` or
`0.1.0`), `api` is the integer 1 or absent, `order` is a whole number. A limit above its hard cap
is accepted and read as the cap, as the schema says; members the schema does not name are ignored.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from .. import schema as _schema
from . import yamlsubset
from .errors import RoutineError

__all__ = ["ManifestError", "parse_manifest", "manifest_problems", "API_VERSION", "HOOKS", "HARD_LIMITS",
           "MANIFEST_NAME", "ENTRY_NAME", "NAME_RE", "DEFAULT_ORDER"]

API_VERSION = 1
HOOKS: Tuple[str, ...] = ("on_plan", "on_part_candidate", "on_verdict", "on_overdub", "on_export", "on_drama")
MANIFEST_NAME = "routine.yaml"
ENTRY_NAME = "routine.py"
DEFAULT_ORDER = 100
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}\Z")

# Hard caps. A manifest's `limits` may tighten these, never loosen them.
HARD_LIMITS: Dict[str, float] = {
    "max_ms_per_call": 250.0,          # wall time of one hook call (measured, not pre-empted)
    "max_directives_per_verdict": 4,
    "max_notes_factor": 2.0,           # on_part_candidate: at most factor x input + 512 notes
    "max_overdub_notes_per_part": 512,
    "max_export_bytes": 16384,
    "max_added_shots": 32,
    "max_log_lines": 50,
}


class ManifestError(RoutineError, ValueError):
    """A `routine.yaml` that cannot be used."""


def manifest_problems(document: Any) -> list:
    """Every reason a parsed manifest does not fit the `routine-manifest` schema ([] = fine)."""
    return ["%s: %s" % (p.pointer or "(document)", p.message) for p in _schema.validate("routine-manifest", document)]


def parse_manifest(text: str, where: str = MANIFEST_NAME) -> Dict[str, Any]:
    """The manifest in `text` as {"name", "version", "author", "api", "hooks" (a tuple), "limits",
    "order", "description"}, defaults filled in. Raises `ManifestError`."""
    try:
        data = yamlsubset.loads(text)
    except yamlsubset.YamlError as exc:
        raise ManifestError("%s: %s" % (where, exc)) from exc
    if not isinstance(data, dict):
        raise ManifestError("%s: %s is not a mapping" % (where, MANIFEST_NAME))
    found = manifest_problems(data)
    if found:
        hint = ""
        if isinstance(data.get("version"), (int, float)) and not isinstance(data.get("version"), bool):
            hint = ' (put quotes around the version: version: "%s")' % data["version"]
        raise ManifestError("%s: %s%s" % (where, "; ".join(found), hint))
    return {"name": data["name"], "version": data["version"], "author": data["author"],
            "api": API_VERSION, "hooks": tuple(data["hooks"]), "limits": dict(data.get("limits") or {}),
            "order": int(data.get("order", DEFAULT_ORDER)), "description": data.get("description", "")}
