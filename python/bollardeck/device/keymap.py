# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.keymap: what a gesture means.

The keymap is data (`bollardeck.constants.KEYMAP`, generated from constants/constants.json; its
format is the `keymap` schema, version 2). This module answers one question about it: given a
gesture and what the device is showing, what is meant?

    from bollardeck.device import keymap

    keymap.resolve("tap1")                       # Resolution("idle",   "do",     "skip_to_frontier")
    keymap.resolve("tap1", prompt="abc")         # Resolution("prompt", "choice", "A")
    keymap.resolve("tap3x3", prompt="spectrum")  # Resolution("prompt", "choice", 2)
    keymap.resolve("hold1", prompt="abc")        # Resolution("prompt", "do",     "replay")
    keymap.resolve("hold1", prompt="game")       # Resolution("prompt", None,     None): taken, does nothing
    keymap.resolve("hold3", prompt="abc")        # Resolution("always", "do",     "power")
    keymap.resolve("tap2")                       # Resolution(None,     None,     None): not the keymap's
    keymap.resolve("tap2", context="pocket")     # Resolution("pocket", "do",     "whats_on")

## What a meaning is

The keymap says what each value is, so no reader has to know which words are verbs:

- `{"choice": x}`: answer the prompt with x (an option's key such as "A", or a number, a position
  on a spectrum). `kind` is "choice" and `value` is x.
- `{"do": name}`: a verb, something the device does ("replay", "pass", "power"). `kind` is "do"
  and `value` is the name. Entries in `idle` and `always` are verbs written as bare names.
- `null`, in `prompt` only: the prompt takes the gesture and nothing happens. `kind` is None.

The verb "raw" on a kind of prompt means that kind wants press and release times themselves, not
gestures: `wants_raw(kind)` says so, and a host then gives that prompt the button edges and does
not run them through the gesture engine.

## The rule

`resolve(gesture, prompt=None, keymap=KEYMAP, context=None)`; `prompt` is the kind of prompt
showing, or None when none is; `context` is the device context, one of `CONTEXTS` ("pocket": a
cart with no dock), or None.

1. If `always` names the gesture, that verb is the answer, whatever is showing.
2. Otherwise, while a prompt is showing: if `prompt` names the gesture and that entry has a
   member for this kind of prompt, that member is the answer (a choice, a verb, or nothing).
   `idle` is never consulted while a prompt is showing.
3. Otherwise, with no prompt showing and a context given: if the keymap's map for that context
   (`pocket`, optional) names the gesture, that verb is the answer.
4. Otherwise, with no prompt showing: if `idle` names the gesture, that verb is the answer.
5. Otherwise there is no answer (`source` None). The gesture is not the keymap's business and
   the device's ordinary controls may act on it.

`Resolution.handled` is True for 1 to 4. The vectors are `conformance/gestures/resolve.json`.
A keymap without a `pocket` map, and every call that gives no context, behave exactly as before
the context existed.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, NamedTuple, Optional

from .. import schema as _schema
from ..constants import GESTURES, KEYMAP, KEYMAP_CONTEXTS, POCKET_VERBS, PROMPT_KINDS
from .gestures import combos_from_keymap

__all__ = ["Resolution", "resolve", "is_gesture", "wants_raw", "problems", "combos_from_keymap", "dumps", "KEYMAP",
           "PROMPT_KINDS", "RAW", "VERSION", "CONTEXTS", "POCKET_VERBS"]

RAW = "raw"
VERSION = 2
CONTEXTS = tuple(KEYMAP_CONTEXTS)


class Resolution(NamedTuple):
    """`source` is "always", "prompt", "pocket", "idle" or None. `kind` is "choice" (answer the prompt with
    `value`), "do" (`value` is a verb's name) or None (nothing happens)."""
    source: Optional[str]
    kind: Optional[str]
    value: Any

    @property
    def handled(self) -> bool:
        """Did the keymap claim the gesture (even to do nothing with it)?"""
        return self.source is not None

    @property
    def action(self) -> Any:
        """The verb's name when this is a verb, else None."""
        return self.value if self.kind == "do" else None

    @property
    def choice(self) -> Any:
        """The answer when this is a choice, else None. Check `kind`: a choice may be 0."""
        return self.value if self.kind == "choice" else None

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "kind": self.kind, "value": self.value}


def _meaning(source: str, meaning: Any) -> Resolution:
    """A prompt member as a Resolution."""
    if meaning is None:
        return Resolution(source, None, None)
    if isinstance(meaning, Mapping) and len(meaning) == 1:
        if "choice" in meaning:
            return Resolution(source, "choice", meaning["choice"])
        if "do" in meaning:
            return Resolution(source, "do", meaning["do"])
    raise ValueError("%r is not a keymap meaning: {\"choice\": x}, {\"do\": name} or null (keymap version %d)"
                     % (meaning, VERSION))


def is_gesture(name: Any) -> bool:
    """Is this one of the names in `GESTURES` ("tap1", "hold3", ...)? Never raises: for a caller
    that routes other names through the same code as gestures."""
    return isinstance(name, str) and name in GESTURES


def resolve(gesture: str, prompt: Optional[str] = None, keymap: Mapping[str, Any] = KEYMAP,
            context: Optional[str] = None) -> Resolution:
    """What `gesture` means while a prompt of kind `prompt` is showing (None: no prompt), in device
    context `context` (None, or one of `CONTEXTS`). See the module docstring for the rule. Raises
    ValueError for a name that is not a gesture, a context that is not one, and a keymap that is
    not version 2."""
    if context is not None and context not in CONTEXTS:
        raise ValueError("%r is not a keymap context (one of %s)" % (context, ", ".join(CONTEXTS)))
    if not is_gesture(gesture):
        raise ValueError("%r is not a gesture name (one of %s)" % (gesture, ", ".join(GESTURES)))
    if keymap.get("v") != VERSION:
        raise ValueError("this is keymap version %r; bollardeck reads version %d" % (keymap.get("v"), VERSION))
    always = keymap.get("always") or {}
    if gesture in always:
        return Resolution("always", "do", always[gesture])
    if prompt is not None:
        by_kind = (keymap.get("prompt") or {}).get(gesture)
        if isinstance(by_kind, Mapping) and prompt in by_kind:
            return _meaning("prompt", by_kind[prompt])
        return Resolution(None, None, None)
    if context is not None:
        by_context = keymap.get(context) or {}
        if gesture in by_context:
            return Resolution(context, "do", by_context[gesture])
    idle = keymap.get("idle") or {}
    if gesture in idle:
        return Resolution("idle", "do", idle[gesture])
    return Resolution(None, None, None)


def wants_raw(prompt: str, keymap: Mapping[str, Any] = KEYMAP) -> bool:
    """Does this kind of prompt take press and release times instead of gestures? True when any
    gesture's meaning for it is the verb "raw"."""
    return any(isinstance(by_kind, Mapping) and by_kind.get(prompt) == {"do": RAW}
               for by_kind in (keymap.get("prompt") or {}).values())


def problems(keymap: Any) -> List[str]:
    """Every reason a document is not a keymap ([] = fine): the `keymap` schema's verdict, and any
    gesture that `always` names and another map names too (the other entry could never apply)."""
    out = ["%s: %s" % (p.pointer or "(document)", p.message) for p in _schema.validate("keymap", keymap)]
    if isinstance(keymap, dict) and isinstance(keymap.get("always"), dict):
        for section in ("prompt", "idle") + CONTEXTS:
            block = keymap.get(section)
            for name in (block if isinstance(block, dict) else {}):
                if name in keymap["always"]:
                    out.append("/%s/%s: always names this gesture too, so this entry never applies" % (section, name))
    return out


def dumps(keymap: Mapping[str, Any] = KEYMAP) -> str:
    """A keymap as the text of a JSON file, for a program that still wants one on disk."""
    return json.dumps(keymap, indent=2) + "\n"
