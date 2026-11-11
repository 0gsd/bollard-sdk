# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.routines.yamlsubset: a reader for the part of YAML a `routine.yaml` uses.

The SDK runs on the standard library, which has no YAML reader, and a routine manifest is a dozen
lines. So this reads a small, strict subset and refuses everything else with the line number, so
that a manifest never means one thing here and another to a full YAML reader.

    from bollardeck.routines import yamlsubset
    yamlsubset.loads("name: demo\\nhooks: [on_plan]\\nlimits:\\n  max_ms_per_call: 20\\n")
    # {"name": "demo", "hooks": ["on_plan"], "limits": {"max_ms_per_call": 20}}

## What it reads

- Block mappings, nested by indentation (spaces only): `key: value`. Keys are plain words
  (`[A-Za-z_][A-Za-z0-9_.-]*`). A key may not appear twice in one mapping.
- Block sequences of scalars: `- value` lines, under a key or at the top.
- Flow sequences and flow mappings of scalars on one line: `[a, b]`, `{a: 1, b: 2}`.
- Scalars: `null` / `~` / nothing; `true` / `false`; whole numbers (`12`, `-3`); decimals
  (`0.5`, `-2.25`); 'single' and "double" quoted strings (in double quotes: `\\\\ \\" \\/ \\n \\t`);
  anything else plain is a string (`0.1.0`, `Example Hacker`).
- Block scalars: `|` (lines kept) and `>` (lines folded into paragraphs), with `-` to drop the
  final newline.
- Comments (`#` at the start of a line or after a space), blank lines, one leading `---`.
- A document that is one JSON object: a text whose first character that says something is `{`
  is read as JSON (the specification says a manifest may be JSON). Any JSON object is taken,
  nested and over as many lines as it likes, as long as a YAML reader would read it the same:
  no key twice in one object, no exponent in a number (`1e3`), no tab outside a string, no
  `NaN` or `Infinity`, no `\\ud800` to `\\udfff` escape (write the character itself), nothing
  nested more than 64 deep, and nothing after it but blank lines and comments. A one-line flow
  mapping in this subset's own style (`{name: demo, order: 5}`) is taken at the top too.

## What it refuses

Tabs in indentation; anchors, aliases, tags and merge keys (`&` `*` `!` `<<`); `?` keys; a
mapping inside a sequence item; collections nested inside a flow collection, or a flow collection
that runs over a line (but see the JSON object above); a document that is a flow sequence; a
plain scalar that runs over a line; `%` directives; more than one
document; block scalar indicators other than `|`, `>`, `|-`, `>-`; a more-indented line inside a
folded scalar.

It also refuses any plain scalar that YAML 1.1 and YAML 1.2 read differently, because readers in
the field disagree about them: `yes` `no` `on` `off` `y` `n`; numbers with a leading zero,
underscores, a base prefix or an exponent (`010`, `1_000`, `0x1F`, `1e3`, `1.`); `1:30`; `.inf`
and `.nan`; and anything shaped like a date (`2026-01-01`). Put quotes around the value to say it
is a string, or write the number plainly.

The vectors are `conformance/yaml/subset.json`.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["YamlError", "loads"]


class YamlError(ValueError):
    """Text that is not in the subset. `line` is the 1-based line number, or 0 for the whole text."""

    def __init__(self, message: str, line: int = 0):
        self.line = line
        super().__init__("line %d: %s" % (line, message) if line else message)


_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)[ ]*:(?:[ ]+(.*))?\Z", re.S)
_INT_RE = re.compile(r"^[-+]?(0|[1-9][0-9]*)\Z")
_FLOAT_RE = re.compile(r"^[-+]?(0|[1-9][0-9]*)\.[0-9]+\Z")
_NUMBERISH_RE = re.compile(r"^[-+]?(\.[0-9]|[0-9])[0-9_]*(\.[0-9_]*)?([eE][-+]?[0-9]+)?\Z")
_BASE_RE = re.compile(r"^[-+]?0[xXoObB][0-9A-Fa-f_]+\Z")
_SEXAGESIMAL_RE = re.compile(r"^[-+]?[0-9][0-9_]*(:[0-9]{1,2})+(\.[0-9_]*)?\Z")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}([Tt ].*)?\Z")
_SPECIAL_FLOAT_RE = re.compile(r"^[-+]?\.(inf|Inf|INF|nan|NaN|NAN)\Z")
_NULLS = {"", "~", "null", "Null", "NULL"}
_TRUE, _FALSE = {"true", "True", "TRUE"}, {"false", "False", "FALSE"}
_AMBIGUOUS = {"yes", "no", "on", "off", "y", "n"}
_ESCAPES = {"\\": "\\", '"': '"', "/": "/", "n": "\n", "t": "\t"}
_BLOCK_RE = re.compile(r"^([|>])(-?)\Z")


def _strip_comment(text: str, line: int) -> str:
    """`text` without its trailing comment, quote-aware; right-stripped."""
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = ""
        elif quote == "'":
            if ch == "'":
                if text[i + 1:i + 2] == "'":
                    i += 1
                else:
                    quote = ""
        elif ch in "\"'" and (i == 0 or text[i - 1] in " [{,:"):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] == " "):
            return text[:i].rstrip(" ")
        i += 1
    if quote:
        raise YamlError("a quoted string is not closed on its line", line)
    return text.rstrip(" ")


def _scalar(text: str, line: int) -> Any:
    """One scalar: quoted, or plain and typed."""
    if text[:1] == '"':
        if len(text) < 2 or text[-1] != '"':
            raise YamlError("a double-quoted string must end on its line, with nothing after it", line)
        out, i, body = [], 0, text[1:-1]
        while i < len(body):
            ch = body[i]
            if ch == '"':
                raise YamlError("an unescaped double quote inside a double-quoted string", line)
            if ch == "\\":
                i += 1
                if i >= len(body) or body[i] not in _ESCAPES:
                    raise YamlError("escape \\%s is outside the subset (use \\\\ \\\" \\/ \\n \\t)" % body[i:i + 1], line)
                out.append(_ESCAPES[body[i]])
            else:
                out.append(ch)
            i += 1
        return "".join(out)
    if text[:1] == "'":
        if len(text) < 2 or text[-1] != "'":
            raise YamlError("a single-quoted string must end on its line, with nothing after it", line)
        body = text[1:-1]
        if "'" in body.replace("''", ""):
            raise YamlError("a quote inside a single-quoted string is written twice ('')", line)
        return body.replace("''", "'")
    if text in _NULLS:
        return None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if text[:1] in "&*!|>%@`" or text[:2] in ("? ", "- ") or text in ("?", "-") or text[:1] in "[]{},":
        raise YamlError("%r starts with a character that is outside the subset here; quote it if it is text" % text, line)
    if ": " in text or text.endswith(":") or " #" in text:
        raise YamlError("%r: a plain value may not contain ': ' or end with ':'; quote it" % text, line)
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    if (text.lower() in _AMBIGUOUS or _NUMBERISH_RE.match(text) or _BASE_RE.match(text)
            or _SEXAGESIMAL_RE.match(text) or _DATE_RE.match(text) or _SPECIAL_FLOAT_RE.match(text)):
        raise YamlError("%r is read differently by different YAML readers; quote it if it is text, "
                        "or write the number plainly" % text, line)
    return text


def _split_flow(body: str, line: int) -> List[str]:
    """The items of a flow collection's inside, split on commas outside quotes."""
    items, quote, start, i = [], "", 0, 0
    while i < len(body):
        ch = body[i]
        if quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = ""
        elif quote == "'":
            if ch == "'":
                if body[i + 1:i + 2] == "'":
                    i += 1
                else:
                    quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "[]{}":
            raise YamlError("a collection inside a flow collection is outside the subset", line)
        elif ch == ",":
            items.append(body[start:i].strip(" "))
            start = i + 1
        i += 1
    last = body[start:].strip(" ")
    if items or last:
        items.append(last)
    if any(item == "" for item in items):
        raise YamlError("an empty item in a flow collection", line)
    return items


def _inline(text: str, line: int) -> Any:
    """A value written on one line: a flow sequence, a flow mapping or a scalar."""
    if text[:1] == "[":
        if text[-1] != "]":
            raise YamlError("a flow sequence must close on its line", line)
        return [_scalar(item, line) for item in _split_flow(text[1:-1], line)]
    if text[:1] == "{":
        if text[-1] != "}":
            raise YamlError("a flow mapping must close on its line", line)
        out: Dict[str, Any] = {}
        for item in _split_flow(text[1:-1], line):
            m = _KEY_RE.match(item)
            if not m:
                raise YamlError("%r is not `key: value`" % item, line)
            if m.group(1) in out:
                raise YamlError("key %r appears twice" % m.group(1), line)
            out[m.group(1)] = _scalar(m.group(2) or "", line)
        return out
    return _scalar(text, line)


class _Reader:
    def __init__(self, text: str):
        if "\r" in text.replace("\r\n", "\n"):
            raise YamlError("a bare carriage return")
        self.raw = text.replace("\r\n", "\n").split("\n")
        self.i = 0

    def _indent(self, n: int) -> int:
        line = self.raw[n]
        width = len(line) - len(line.lstrip(" "))
        if line[width:width + 1] == "\t":
            raise YamlError("a tab in the indentation (use spaces)", n + 1)
        return width

    def peek(self) -> Optional[Tuple[int, int, str]]:
        """(index, indent, content) of the next line that says something, or None at the end."""
        n = self.i
        while n < len(self.raw):
            if self.raw[n].strip(" \t"):
                indent = self._indent(n)
                content = _strip_comment(self.raw[n][indent:], n + 1)
                if content:
                    return n, indent, content
            n += 1
        return None

    def block(self, indent: int) -> Any:
        nxt = self.peek()
        assert nxt is not None
        n, _ind, content = nxt
        return self.sequence(indent) if content == "-" or content.startswith("- ") else self.mapping(indent)

    def sequence(self, indent: int) -> List[Any]:
        out: List[Any] = []
        while True:
            nxt = self.peek()
            if nxt is None or nxt[1] < indent:
                return out
            n, ind, content = nxt
            if ind > indent:
                raise YamlError("this line is indented more than the list it follows", n + 1)
            if not (content == "-" or content.startswith("- ")):
                return out
            item = content[1:].strip(" ")
            if _KEY_RE.match(item) and item[:1] not in "\"'":
                raise YamlError("a mapping inside a list item is outside the subset", n + 1)
            self.i = n + 1
            out.append(_inline(item, n + 1))

    def mapping(self, indent: int) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        while True:
            nxt = self.peek()
            if nxt is None or nxt[1] < indent:
                return out
            n, ind, content = nxt
            if ind > indent:
                raise YamlError("this line is indented more than the mapping it belongs to", n + 1)
            if content == "-" or content.startswith("- "):
                raise YamlError("a list item where a `key: value` was expected", n + 1)
            m = _KEY_RE.match(content)
            if not m:
                raise YamlError("%r is not `key: value` (keys are plain words; a value that runs over "
                                "a line is outside the subset)" % content, n + 1)
            key, rest = m.group(1), (m.group(2) or "").strip(" ")
            if key in out:
                raise YamlError("key %r appears twice" % key, n + 1)
            self.i = n + 1
            if _BLOCK_RE.match(rest):
                out[key] = self.block_scalar(indent, rest, n + 1)
            elif rest[:1] in ("|", ">"):
                raise YamlError("block scalar indicator %r is outside the subset (use |, >, |- or >-)" % rest, n + 1)
            elif rest:
                out[key] = _inline(rest, n + 1)
            else:
                after = self.peek()
                if after is not None and after[1] > indent:
                    out[key] = self.block(after[1])
                elif after is not None and after[1] == indent and (after[2] == "-" or after[2].startswith("- ")):
                    out[key] = self.sequence(indent)
                else:
                    out[key] = None

    def block_scalar(self, parent_indent: int, indicator: str, line: int) -> str:
        style, chomp = _BLOCK_RE.match(indicator).groups()  # type: ignore[union-attr]
        lines: List[Optional[str]] = []                      # None is a blank line
        block_indent: Optional[int] = None
        while self.i < len(self.raw):
            raw = self.raw[self.i]
            if not raw.strip(" \t"):
                lines.append(None)
                self.i += 1
                continue
            ind = self._indent(self.i)
            if ind <= parent_indent:
                break
            if block_indent is None:
                block_indent = ind
            if ind < block_indent:
                raise YamlError("this line is indented less than the first line of its block scalar", self.i + 1)
            if style == ">" and ind > block_indent:
                raise YamlError("a more-indented line inside a folded (>) scalar is outside the subset", self.i + 1)
            lines.append(raw[block_indent:].rstrip(" "))
            self.i += 1
        while lines and lines[-1] is None:
            lines.pop()
        while lines and lines[0] is None and style == ">":
            lines.pop(0)
        if not lines:
            return ""
        if style == "|":
            text = "\n".join("" if x is None else x for x in lines)
        else:
            text, blanks, started = "", 0, False
            for x in lines:
                if x is None:
                    blanks += 1
                    continue
                if started:
                    text += "\n" * blanks if blanks else " "
                text += x
                blanks, started = 0, True
        return text if chomp == "-" else text + "\n"


_JSON_EXPONENT_RE = re.compile(r"[eE]")


def _json_number(text: str) -> Any:
    if _JSON_EXPONENT_RE.search(text):
        raise ValueError("%s: a number with an exponent is read differently by different YAML readers; "
                         "write it plainly" % text)
    return float(text)


def _json_constant(text: str) -> Any:
    raise ValueError("%s is not JSON" % text)


def _json_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("key %r appears twice" % key)
        out[key] = value
    return out


_JSON_SURROGATE_RE = re.compile(r"(?<!\\)(?:\\\\)*\\u[dD][89a-fA-F]")
MAX_JSON_DEPTH = 64


def _json_trouble(value: Any) -> str:
    """What is wrong with a parsed JSON value that json.loads let through, or ""."""
    stack = [(value, 1)]
    while stack:
        v, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            return "nested more than %d deep" % MAX_JSON_DEPTH
        if isinstance(v, str):
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in v):
                return "a string holds half of a surrogate pair, which is not text"
        elif isinstance(v, dict):
            stack.extend((k, depth) for k in v)
            stack.extend((x, depth + 1) for x in v.values())
        elif isinstance(v, list):
            stack.extend((x, depth + 1) for x in v)
    return ""


def _json_document(reader: "_Reader", n: int) -> Dict[str, Any]:
    """The document that starts with `{` on line index n: one JSON object, or a one-line flow
    mapping of this subset's own."""
    text = "\n".join(reader.raw[n:])
    try:
        if "\t" in text:
            raise ValueError("a tab (use spaces)")
        if _JSON_SURROGATE_RE.search(text):
            raise ValueError("a \\ud800 to \\udfff escape is read differently by different YAML readers; write the character itself")
        value, end = json.JSONDecoder(object_pairs_hook=_json_pairs, parse_float=_json_number,
                                      parse_constant=_json_constant).raw_decode(text)
    except RecursionError:
        problem, line = "nested more than %d deep" % MAX_JSON_DEPTH, n + 1
    except json.JSONDecodeError as exc:
        problem, line = "not a JSON object: %s" % exc.msg, n + exc.lineno
    except ValueError as exc:
        problem, line = str(exc), n + 1 + text.count("\n", 0, text.find("\t")) if "\t" in text else n + 1
    else:
        trouble = _json_trouble(value)
        if trouble:
            raise YamlError("the JSON object is %s" % trouble if trouble.startswith("nested") else "in the JSON object, %s" % trouble, n + 1)
        reader.i = n + text.count("\n", 0, end)
        tail = _strip_comment(reader.raw[reader.i][len(text[:end].rsplit("\n", 1)[-1]):], reader.i + 1)
        if tail.strip(" "):
            raise YamlError("unexpected text after the JSON object", reader.i + 1)
        reader.i += 1
        return value
    content = _strip_comment(reader.raw[n], n + 1)
    reader.i = n + 1
    if content[-1:] == "}" and content[1:].lstrip(" ")[:1] != '"' and reader.peek() is None:
        return _inline(content, n + 1)                  # {key: value, ...} on one line
    raise YamlError("a document that starts with { is one JSON object, or a flow mapping on one line (%s)" % problem, line)


def loads(text: str) -> Any:
    """The value a document in the subset stands for: a dict, a list, or None for an empty
    document. Raises `YamlError` for anything outside the subset."""
    if not isinstance(text, str):
        raise YamlError("not text")
    if text[:1] == "﻿":
        text = text[1:]
    reader = _Reader(text)
    first = reader.peek()
    if first is not None and first[2] == "---":
        if first[1] != 0:
            raise YamlError("--- must start its line", first[0] + 1)
        reader.i = first[0] + 1
        first = reader.peek()
    if first is None:
        return None
    n, indent, content = first
    if content[:1] == "%":
        raise YamlError("directives are outside the subset", n + 1)
    if content in ("---", "...") or content.startswith("--- "):
        raise YamlError("more than one document, or a document end marker, is outside the subset", n + 1)
    if indent != 0:
        raise YamlError("the document's first line must not be indented", n + 1)
    if content[:1] == "{":
        value = _json_document(reader, n)
    elif not (content == "-" or content.startswith("- ") or _KEY_RE.match(content)):
        raise YamlError("a document is a mapping or a list; %r is neither" % content, n + 1)
    else:
        value = reader.block(0)
    rest = reader.peek()
    if rest is not None:
        if rest[2] in ("---", "...") or rest[2].startswith("--- "):
            raise YamlError("more than one document, or a document end marker, is outside the subset", rest[0] + 1)
        raise YamlError("unexpected text after the document's value", rest[0] + 1)
    return value
