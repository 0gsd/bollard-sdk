# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.help: check help packs and director scripts, the twin of js/bollardeck.help.js's checks.

Help runs in a browser (js/bollardeck.help.js and the page helpers in js/bollardeck.dom.js). This module is
for the tools around it: a build that compiles help content, a test that a page still has every control its
help points at, a capture that turns a director script into a video and its captions.

    from bollardeck import help

    help.pack_problems(doc)               [] when doc is a usable help-pack/1 document
    help.director_problems(doc)           [] when doc is a usable help-director/1 script
    help.lint(pack, manifest)             targets a pack names that a page does not have;
                                          manifest is {page: {role: [target ids]}}
    help.lint_director(script, manifest, signals=None)
    help.say_ms(text) / help.hold_ms(step)    how long a step stays up (the same numbers as JS)
    help.split_caption(text)              the caption cues of a say line (the same cues as JS)
    help.read_text(script)                [{"chapter", "text"}]: the say lines, one paragraph per chapter

Problems are bollardeck.schema.Problem tuples (pointer, message, keyword), as the JS gives them.
Standard library only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import constants, schema
from .schema import Problem

ID_RE = re.compile(r"^[a-z][a-z0-9-]*([.][a-z0-9][a-z0-9-]*)+$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
# A browser drops tabs and newlines from a URL and reads \ as /: "/\host" or "/<tab>/host" would leave the site.
BAD_HREF = re.compile(r"[\x00-\x20\x7f\\]")
_PIECE_RE = re.compile(r"(?<=[.!?;:,—])\s+")

__all__ = ["pack_problems", "director_problems", "lint", "lint_director", "say_ms", "hold_ms",
           "split_caption", "read_text", "timeline"]


def _esc(s: str) -> str:
    return str(s).replace("~", "~0").replace("/", "~1")


def _hrefs(content: Mapping[str, Any], at: str, out: List[Problem]) -> None:
    """A link's href is a path on this site; a backslash could turn it into another site in a browser."""
    def body(b: Any, where: str) -> None:
        for i, para in enumerate(b or []):
            for j, bit in enumerate(para):
                if isinstance(bit, dict) and isinstance(bit.get("href"), str) and BAD_HREF.search(bit["href"]):
                    out.append(Problem("%s/%d/%d/href" % (where, i, j),
                                       "a link may not hold a backslash, a space or a control character", "href"))
    body(content.get("body"), at + "/body")
    for k, v in enumerate(content.get("variants") or []):
        body(v.get("body"), "%s/variants/%d/body" % (at, k))


def pack_problems(doc: Any) -> List[Problem]:
    out = list(schema.validate("help-pack", doc))
    if out:
        return out
    for page, p in doc["pages"].items():
        at = "/pages/" + _esc(page)
        topics = p.get("topics") or {}
        if not NAME_RE.match(page):
            out.append(Problem(at, "a page key must be a name (lowercase, digits, _ and -)", "page-name"))
        for role, c in (p.get("intro") or {}).items():
            if not NAME_RE.match(role):
                out.append(Problem(at + "/intro/" + _esc(role), "an intro key must be a role name", "role-name"))
            _hrefs(c, at + "/intro/" + _esc(role), out)
        for tid, t in topics.items():
            tat = at + "/topics/" + _esc(tid)
            if not ID_RE.match(tid):
                out.append(Problem(tat, "a topic key must be a help id", "topic-id"))
            _hrefs(t, tat, out)
            for i, s in enumerate(t.get("see") or []):
                if s not in topics:
                    out.append(Problem(tat + "/see/%d" % i, "names no topic on this page: " + s, "see"))
        for sid, s in (p.get("scenarios") or {}).items():
            sat = at + "/scenarios/" + _esc(sid)
            if not ID_RE.match(sid):
                out.append(Problem(sat, "a scenario key must be a help id", "scenario-id"))
            if s["topic"] not in topics:
                out.append(Problem(sat + "/topic", "names no topic on this page: " + s["topic"], "topic"))
            if not s["detector"].startswith("x-") and s["detector"] not in constants.HELP_DETECTORS:
                out.append(Problem(sat + "/detector",
                                   "is not a built-in detector (a page's own start with x-): " + s["detector"], "detector"))
    return out


def _words(text: str) -> int:
    return len(str(text).split())


def say_ms(text: str) -> int:
    return max(constants.HELP_SAY_MIN_MS, constants.HELP_SAY_MS_PER_WORD * _words(text))


def hold_ms(step: Mapping[str, Any]) -> int:
    if isinstance(step.get("hold_ms"), int):
        return step["hold_ms"]
    if step["do"] == "say":
        return step["ms"] if isinstance(step.get("ms"), int) else say_ms(step["text"])
    return constants.HELP_HOLD_MS.get(step["do"], 0)


def _wrap(text: str, width: int) -> List[str]:
    lines: List[str] = []
    line = ""
    for w in str(text).split():
        if line and len(line + " " + w) > width:
            lines.append(line)
            line = w
        else:
            line = line + " " + w if line else w
    if line:
        lines.append(line)
    return lines


def split_caption(text: str) -> List[str]:
    """The same cues as bollardeck.help.splitCaption in JS (conformance: tests/test_help.py)."""
    width = constants.HELP_CAPTION_LINE
    pieces = [p for p in _PIECE_RE.split(str(text).strip()) if p]
    cues: List[str] = []
    cur = ""

    def fits(s: str) -> bool:
        return len(_wrap(s, width)) <= 2

    def push(s: str) -> None:
        if s:
            cues.append("\n".join(_wrap(s, width)))

    for p in pieces:
        nxt = cur + " " + p if cur else p
        if fits(nxt):
            cur = nxt
            continue
        push(cur)
        cur = ""
        if fits(p):
            cur = p
            continue
        lines = _wrap(p, width)
        for i in range(0, len(lines), 2):
            chunk = " ".join(lines[i:i + 2])
            if i + 2 >= len(lines):
                cur = chunk
            else:
                push(chunk)
    push(cur)
    return cues


def timeline(script: Mapping[str, Any], mode: str = "capture") -> List[Dict[str, Any]]:
    tour = mode == "tour"
    out = []
    for i, s in enumerate(script["steps"]):
        if tour and (s.get("capture_only") or s["do"] in ("act", "cut")):
            continue
        out.append(dict(s, index=i, hold=hold_ms(s)))
    return out


def director_problems(doc: Any) -> List[Problem]:
    out = list(schema.validate("help-director", doc))
    if out:
        return out
    most = constants.HELP_SAY_MAX_CHARS
    steps = doc["steps"]
    for i, s in enumerate(steps):
        at = "/steps/%d" % i
        if s["do"] == "say" and len(s["text"]) > most:
            out.append(Problem(at + "/text", "is longer than %d characters" % most, "say-length"))
        if s.get("pop") == "@say":
            nxt = next((r for r in steps[i + 1:] if r["do"] in ("say", "spot", "hide")), None)
            if nxt is None or nxt["do"] != "say":
                out.append(Problem(at + "/pop", "@say needs a say step before the next spot or hide", "pop"))
    length = sum(0 if s["do"] == "cut" else s["hold"] + (s["ms"] if s["do"] == "wait" and isinstance(s.get("ms"), int) else 0)
                 for s in timeline(doc, "capture"))
    if length > constants.HELP_SCRIPT_MAX_MS:
        out.append(Problem("/steps", "runs %d ms, more than %d" % (length, constants.HELP_SCRIPT_MAX_MS), "length"))
    return out


def lint(pack: Mapping[str, Any], manifest: Mapping[str, Mapping[str, Sequence[str]]]) -> List[Problem]:
    out: List[Problem] = []
    for page, pg in pack["pages"].items():
        known = manifest.get(page)
        if not known:
            out.append(Problem("/pages/" + _esc(page), "the manifest has no page " + page, "page"))
            continue

        def check(at: str, target: str, when: Optional[Mapping[str, Any]]) -> None:
            roles = (when or {}).get("roles") or list(known)
            for role in roles:
                if role in known and target not in known[role]:
                    out.append(Problem(at, "%s is not on %s for %s" % (target, page, role), "target"))

        topics = pg.get("topics") or {}
        for tid, t in topics.items():
            for i, target in enumerate(t.get("targets") or []):
                check("/pages/%s/topics/%s/targets/%d" % (_esc(page), _esc(tid), i), target, t.get("when"))
        for sid, s in (pg.get("scenarios") or {}).items():
            if s.get("target"):
                check("/pages/%s/scenarios/%s/target" % (_esc(page), _esc(sid)), s["target"],
                      s.get("when") or (topics.get(s["topic"]) or {}).get("when"))
    return out


def lint_director(script: Mapping[str, Any], manifest: Mapping[str, Mapping[str, Sequence[str]]],
                  signals: Optional[Iterable[str]] = None) -> List[Problem]:
    known = (manifest.get(script["page"]) or {}).get(script["role"])
    if not known:
        return [Problem("/page", "the manifest has no %s for %s" % (script["page"], script["role"]), "page")]
    sig = None if signals is None else set(signals)
    out: List[Problem] = []
    for i, s in enumerate(script["steps"]):
        if s.get("target") and s["target"] not in known:
            out.append(Problem("/steps/%d/target" % i, "%s is not on %s for %s" % (s["target"], script["page"], script["role"]), "target"))
        u = s.get("until") or ""
        if u.startswith("visible:") and u[8:] not in known:
            out.append(Problem("/steps/%d/until" % i, u[8:] + " is not on the page", "target"))
        if u.startswith("signal:") and sig is not None and u[7:] not in sig:
            out.append(Problem("/steps/%d/until" % i, "no such signal: " + u[7:], "signal"))
    return out


def read_text(script: Mapping[str, Any]) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    cur: Optional[Dict[str, Optional[str]]] = None
    for s in script["steps"]:
        if s["do"] == "chapter":
            cur = {"chapter": s["title"], "text": ""}
            out.append(cur)
        if s["do"] != "say":
            continue
        if cur is None:
            cur = {"chapter": None, "text": ""}
            out.append(cur)
        cur["text"] = cur["text"] + " " + s["text"] if cur["text"] else s["text"]
    return [c for c in out if c["text"]]
