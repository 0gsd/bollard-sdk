# conformance

Test vectors any implementation of the platform's formats must agree with, Pop Boll's own included.
They are plain JSON, so an implementation in any language can run them.

```
conformance/
  index.json                      every vector: its schema, its file, valid or not, and why
  <schema>/valid/<name>.json      a document that fits the schema
  <schema>/invalid/<name>.json    a document that does not
```

`<schema>` is a name from `schema/` without `.schema.json` (`licence`, `corpus-manifest`, ...).
Each file is the document itself, with nothing wrapped around it.

## index.json

```json
{"version": 1,
 "schemas": {"licence": "schema/licence.schema.json", "...": "..."},
 "vectors": [
   {"schema": "licence", "file": "licence/valid/scope-alone.json", "valid": true,
    "reason": "Only a scope: every capability takes the scope's default."},
   {"schema": "licence", "file": "licence/invalid/unknown-scope.json", "valid": false,
    "reason": "A scope this version does not define.", "at": "/scope"}
 ]}
```

- `schemas` maps each name to its schema file, relative to the repository root.
- `file` is relative to this folder.
- `at`, on invalid vectors only, is a JSON pointer (RFC 6901) into the document. `""` is the
  document itself, which is where a missing member is reported.

## Running them against your implementation

For every vector: load the schema, load the document, validate.

1. Your verdict must equal `valid`. This is the requirement.
2. If your validator reports where a problem is, one of the places it reports for an invalid
   vector should be `at`. Validators differ in how they report a failed `anyOf` or a missing
   member, so treat a different place as something to look at, not as a failure.

The SDK's own run is `tests/test_schemas.py`: it puts every vector through `bollardeck.schema`,
and through the `jsonschema` package as an independent second opinion.

## Every document is made up

No id, name, address, hash or text here comes from a real corpus, artist or device. Keep it that
way: write new vectors by hand, never by trimming a real file.

## What is here

203 schema vectors over the eleven schemas, listed in `index.json`. For each schema, the valid ones
show the smallest document, a typical one and the tolerated oddities; the invalid ones each break
one rule.

## Behaviour vectors

Some things are behaviour, not document shape, and a schema cannot hold them. Their vectors are
plain JSON too, are not listed in `index.json`, and say in their own `about` (or the folder's
README) how to run them:

| Files | For | What a vector is | Run by |
| :--- | :--- | :--- | :--- |
| `gestures/timelines.json` (59) | the gesture engine | a configuration, button events with times, and the gestures each event must produce | Python |
| `gestures/resolve.json` (77) | the keymap resolver, keymap version 2 | a keymap, a gesture, the kind of prompt showing, and the expected answer | Python |
| `cues/normalise.json` (19 and 5) | what a valid cue list is, and the cue normaliser | an input, whether it is valid, the normalised list, the repairs reported, the text line and the wire form | Python and JS |
| `cue-render/` (150) | what a button shows at a time | a cue list, a time, and each button's level, arc, head and pixel | Python and JS |
| `matrix/` (1,135) | the LED matrix engine | inputs and the frame the engine makes for them | Python and JS |
| `yaml/subset.json` (84) | the reader for `routine.yaml` | a text and its value, or a text that must be refused and the line to name | Python |
| `corpus-gate/` | the corpus gate | see below | Python |
| `pxs/blocks.json` (35) | the .pxs validator, rules V1-V9 | a whole file (base64 of its zlib bytes, made by `tools/pxs_vectors.py`) and the verdict: valid, kind (`pxs`, `it`, `invalid`) and the first rule broken | Python (`tests/test_pxs.py`); Amorphus runs the same file |

`tools/pin_vectors.py` writes the expected values of `cue-render/` from this repository's Python
renderer, and those of `matrix/` from its Python engine, `bollardeck.matrix`. The other files are written by hand. The SDK's own runs are
`tests/test_device.py`, `tests/test_routines.py`, `tests/test_corpus_gate.py` and `tests/js/`.

## Behaviour vectors: the corpus gate

`corpus-gate/*.json` are not schema vectors and are not in `index.json`. They say what the corpus
gate must answer: given a manifest, who is asking, the time, and how fresh the manifest is, is a
capability allowed, and if not, why. 117 cases in six files (`scopes`, `licence-state`, `time`,
`visibility`, `offline`, `capabilities`).

```json
{"version": 1,
 "about": "...",
 "manifests": {"revoked": { ...a corpus manifest... }},
 "cases": [
   {"name": "the instant of revocation", "manifest": "revoked", "capability": "musicians_may_study",
    "clock": "2031-06-01T12:00:00Z",
    "identity": {"email": "ada@example.org"},
    "standing": {"source": "hub", "revalidated_at": "2031-05-20T00:00:00Z", "reachable": false},
    "expect": {"allowed": false, "reason": "revoked"},
    "why": "Closed from the instant itself."}
 ]}
```

- `manifest` names a member of `manifests`. Some are deliberately invalid: refusing them is the test.
- `capability` is one of the eight licence capabilities, `study` (short for `musicians_may_study`)
  or `see`. A few cases pass something that is not a capability, or not a string.
- `clock` is "now", UTC. `identity` (optional) has `email`, `service`, `player`, `device`; absent
  means nobody in particular. `standing` (optional) says where the manifest came from: absent or
  `{"source": "local"}` is a folder on disk; `{"source": "hub", ...}` is a cached copy, with when
  its licence block was last revalidated, whether the hub answered the last time it was asked,
  and `withdrawn` when the hub has stopped serving the corpus.
- `expect.allowed` and `expect.reason` are the requirement. `expect.pending`,
  `expect.unverified_since` and `expect.capability_answered`, where present, must match too.
- The reasons, in the order the gate checks them: `bad_clock`, `unknown_capability`,
  `manifest_invalid`, `licence_ambiguous`, `unknown_scope`, `newer_version`, `withdrawn`,
  `not_visible`, (`see` is answered here), `licence_missing`, `licence_invalid`, `revoked`,
  `expired`, `not_granted`, `allowed`.

The SDK's own run is `tests/test_corpus_gate.py`.

## Also in this folder

`DECISIONS.md`: where a schema or a specification page left room, what the SDK does and why. Read
it before writing another implementation.
