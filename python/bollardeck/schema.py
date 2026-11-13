# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.schema: check a document against one of the platform's JSON Schemas.

    import bollardeck.schema as schema
    problems = schema.validate("licence", block)        # [] when the block is fine
    for p in problems:
        print(p.pointer, p.message)                      # "/scope", "is not one of ..."

The schemas are the files under schema/ in the SDK repository (JSON Schema draft 2020-12). They
travel inside the package as bollardeck/_schemas.py, which tools/generate.py writes, so an
installed SDK needs no data files. `names()` lists them.

This is a small validator, standard library only. It implements exactly the keywords in
KEYWORDS below, which are the ones the SDK's schemas use, and it REFUSES a schema that uses
any other keyword (UnsupportedSchema): a keyword it skipped would be a rule it silently did not
enforce. `format` is not implemented and is refused; the schemas use `pattern`.

Where it is deliberately exact:
  * true and false are never numbers, and 1 and 1.0 are the same number (as JSON Schema says);
  * `pattern` follows ECMA 262 where Python differs in a way that matters: `$` matches only at
    the very end (Python's would also match before a final newline), and \\d, \\w and \\s are
    ASCII only.
"""

import json
import math
import re
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple
from urllib.parse import urldefrag, urljoin

DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Keywords that say nothing about validity.
ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "title", "description", "examples", "default"})
# Keywords that hold schemas: one, a list of them, or a mapping of them.
_ONE = frozenset({"additionalProperties", "items", "not", "if", "then"})
_LIST = frozenset({"allOf", "anyOf", "prefixItems"})
_MAP = frozenset({"properties", "$defs"})
# Every keyword this validator enforces.
KEYWORDS = frozenset({
    "$ref", "$defs", "type", "enum", "const",
    "minimum", "maximum", "exclusiveMinimum",
    "minLength", "pattern",
    "items", "prefixItems", "minItems", "maxItems",
    "properties", "required", "additionalProperties", "minProperties",
    "allOf", "anyOf", "not", "if", "then",
})
TYPES = ("null", "boolean", "object", "array", "number", "integer", "string")


class UnsupportedSchema(ValueError):
    """A schema uses something this validator does not implement, or is not a schema at all."""


class Problem(NamedTuple):
    """One thing wrong with a document. `pointer` is an RFC 6901 JSON pointer into the document
    ("" is the document itself); `keyword` is the schema keyword that refused it."""
    pointer: str
    message: str
    keyword: str

    def __str__(self) -> str:
        return "#%s: %s" % (self.pointer, self.message)


# ── the schemas ──────────────────────────────────────────────────────────────────────────

_PARSED: Dict[str, Any] = {}
_BY_ID: Dict[str, Any] = {}


def names() -> List[str]:
    """The schema names validate() takes, e.g. "corpus-manifest", "licence"."""
    from ._schemas import SCHEMAS
    return sorted(SCHEMAS)


def load(name: str) -> Any:
    """The schema called `name`, parsed and checked. Treat it as read-only."""
    _load_all()
    if name not in _PARSED:
        raise KeyError("no schema called %r (known: %s)" % (name, ", ".join(sorted(_PARSED))))
    return _PARSED[name]


def _load_all() -> None:
    if _PARSED:
        return
    from ._schemas import SCHEMAS
    parsed = {name: json.loads(text) for name, text in SCHEMAS.items()}
    by_id = {}
    for name, schema in parsed.items():
        check_schema(schema, name)
        by_id[schema["$id"]] = schema
    _BY_ID.update(by_id)
    _PARSED.update(parsed)


def check_schema(schema: Any, where: str = "schema") -> None:
    """Raises UnsupportedSchema unless every keyword in `schema` is one this validator implements
    and is well formed enough to enforce."""
    if not isinstance(schema, dict) or not isinstance(schema.get("$id"), str):
        raise UnsupportedSchema("%s: a schema document must be an object with an $id" % where)
    if schema.get("$schema") != DIALECT:
        raise UnsupportedSchema("%s: $schema must be %s" % (where, DIALECT))
    for path, node in _subschemas(schema, ""):
        if isinstance(node, bool):
            continue
        if not isinstance(node, dict):
            raise UnsupportedSchema("%s#%s: a schema must be an object or a boolean" % (where, path))
        unknown = sorted(set(node) - KEYWORDS - ANNOTATIONS)
        if unknown:
            raise UnsupportedSchema("%s#%s: keyword(s) not implemented: %s" % (where, path, ", ".join(unknown)))
        if path and "$id" in node:
            raise UnsupportedSchema("%s#%s: $id inside a schema is not implemented" % (where, path))
        types = node.get("type")
        for t in (types if isinstance(types, list) else [types] if "type" in node else []):
            if t not in TYPES:
                raise UnsupportedSchema("%s#%s: unknown type %r" % (where, path, t))
        if "pattern" in node:
            try:
                _regex(node["pattern"])
            except (re.error, TypeError) as exc:
                raise UnsupportedSchema("%s#%s: pattern does not compile: %s" % (where, path, exc))
        if "then" in node and "if" not in node:
            raise UnsupportedSchema("%s#%s: then without if" % (where, path))


def _subschemas(node: Any, path: str) -> Iterator[Tuple[str, Any]]:
    yield path, node
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        here = "%s/%s" % (path, key)
        if key in _ONE:
            yield from _subschemas(value, here)
        elif key in _LIST and isinstance(value, list):
            for i, sub in enumerate(value):
                yield from _subschemas(sub, "%s/%d" % (here, i))
        elif key in _MAP and isinstance(value, dict):
            for name, sub in value.items():
                yield from _subschemas(sub, "%s/%s" % (here, _escape(name)))


# ── validating ───────────────────────────────────────────────────────────────────────────

def validate(name: str, value: Any) -> List[Problem]:
    """Every problem with `value` as a document of the schema `name` ([] when it is fine).
    `name` may point inside a schema: "cue#/$defs/cue" checks one cue, not a cue list."""
    name, _, fragment = name.partition("#")
    root = load(name)
    node = _resolve_pointer(root, fragment, name)
    problems: List[Problem] = []
    _check(node, value, "", root, problems)
    return problems


def is_valid(name: str, value: Any) -> bool:
    return not validate(name, value)


def _escape(token: str) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _resolve_pointer(root: Any, pointer: str, where: str) -> Any:
    node = root
    for raw in pointer.split("/")[1:] if pointer else []:
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            raise UnsupportedSchema("%s: nothing at #%s" % (where, pointer))
        node = node[token]
    return node


def _resolve_ref(ref: str, root: Any) -> Tuple[Any, Any]:
    """(schema, its root document) for a $ref seen inside `root`."""
    url, fragment = urldefrag(urljoin(root["$id"], ref))
    if url not in _BY_ID:
        raise UnsupportedSchema("$ref %r: no schema with $id %s" % (ref, url))
    target_root = _BY_ID[url]
    if fragment and not fragment.startswith("/"):
        raise UnsupportedSchema("$ref %r: only JSON pointer fragments are implemented" % ref)
    return _resolve_pointer(target_root, fragment, url), target_root


_REGEX: Dict[str, "re.Pattern[str]"] = {}


def _regex(pattern: str) -> "re.Pattern[str]":
    """`pattern` compiled with ECMA 262's reading of `$` (the very end, never before a newline)."""
    if pattern not in _REGEX:
        out, in_class, i = [], False, 0
        while i < len(pattern):
            ch = pattern[i]
            if ch == "\\":
                out.append(pattern[i:i + 2])
                i += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            out.append("\\Z" if ch == "$" and not in_class else ch)
            i += 1
        _REGEX[pattern] = re.compile("".join(out), re.ASCII)
    return _REGEX[pattern]


def _is_number(v: Any) -> bool:
    """A JSON number: never a bool, and never NaN or an infinity (JSON cannot carry them, and JS's
    validator, whose input is parsed JSON, never sees one)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return not isinstance(v, float) or math.isfinite(v)


def _is_type(v: Any, t: str) -> bool:
    if t == "null":
        return v is None
    if t == "boolean":
        return isinstance(v, bool)
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "number":
        return _is_number(v)
    return _is_number(v) and (isinstance(v, int) or v.is_integer())     # integer: 1.0 counts


def _same(a: Any, b: Any) -> bool:
    """JSON equality: 1 == 1.0, but true is not 1 and key order does not matter."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _show(v: Any) -> str:
    text = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 60 else text[:57] + "..."


def _passes(schema: Any, value: Any, root: Any) -> bool:
    found: List[Problem] = []
    _check(schema, value, "", root, found)
    return not found


def _check(schema: Any, value: Any, at: str, root: Any, out: List[Problem]) -> None:
    if schema is True:
        return
    if schema is False:
        out.append(Problem(at, "is not allowed here", "false"))
        return

    def bad(keyword: str, message: str, where: Optional[str] = None) -> None:
        out.append(Problem(at if where is None else where, message, keyword))

    if "$ref" in schema:
        target, target_root = _resolve_ref(schema["$ref"], root)
        _check(target, value, at, target_root, out)

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            bad("type", "must be %s, not %s" % (" or ".join(types), _show(value)))
            return                      # the rest would only repeat the same mistake
    if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
        bad("enum", "must be one of %s, not %s" % (", ".join(_show(e) for e in schema["enum"]), _show(value)))
    if "const" in schema and not _same(value, schema["const"]):
        bad("const", "must be %s, not %s" % (_show(schema["const"]), _show(value)))

    if _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            bad("minimum", "must be at least %s, not %s" % (schema["minimum"], _show(value)))
        if "maximum" in schema and value > schema["maximum"]:
            bad("maximum", "must be at most %s, not %s" % (schema["maximum"], _show(value)))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            bad("exclusiveMinimum", "must be more than %s, not %s" % (schema["exclusiveMinimum"], _show(value)))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            bad("minLength", "must be at least %d character(s) long" % schema["minLength"])
        if "pattern" in schema and not _regex(schema["pattern"]).search(value):
            bad("pattern", "%s does not match %s" % (_show(value), schema["pattern"]))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            bad("minItems", "must have at least %d item(s), not %d" % (schema["minItems"], len(value)))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            bad("maxItems", "must have at most %d item(s), not %d" % (schema["maxItems"], len(value)))
        prefix = schema.get("prefixItems", [])
        for i, item in enumerate(value):
            if i < len(prefix):
                _check(prefix[i], item, "%s/%d" % (at, i), root, out)
            elif "items" in schema:
                _check(schema["items"], item, "%s/%d" % (at, i), root, out)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                bad("required", "is missing %r" % key)
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            bad("minProperties", "must have at least %d member(s)" % schema["minProperties"])
        for key, item in value.items():
            here = "%s/%s" % (at, _escape(key))
            if key in props:
                _check(props[key], item, here, root, out)
            elif "additionalProperties" in schema:
                if schema["additionalProperties"] is False:
                    bad("additionalProperties", "is not a known member", here)
                else:
                    _check(schema["additionalProperties"], item, here, root, out)

    for sub in schema.get("allOf", []):
        _check(sub, value, at, root, out)
    if "anyOf" in schema:
        tries = []
        for sub in schema["anyOf"]:
            found: List[Problem] = []
            _check(sub, value, at, root, found)
            if not found:
                break
            tries.append(found)
        else:
            bad("anyOf", "fits none of the %d allowed shapes" % len(schema["anyOf"]))
            # Add the nearest miss: a shape the value got inside of says more than one it is not.
            shallow = ("type", "const", "enum", "not")
            out.extend(min(tries, key=lambda found: (
                any(p.pointer == at and p.keyword in shallow for p in found), len(found))))
    if "not" in schema and _passes(schema["not"], value, root):
        bad("not", "must not be %s" % _show(value))
    if "if" in schema and "then" in schema and _passes(schema["if"], value, root):
        _check(schema["then"], value, at, root, out)
