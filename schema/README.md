# schema

JSON Schemas (draft 2020-12) for the platform's formats, one file per format. They were written
fresh for the SDK from how each format behaves today; before them, the formats existed only as
prose and as validators in code.

| File | Format | Version it describes |
| :--- | :--- | :--- |
| `corpus-manifest.schema.json` | a corpus's `corpus.json`, with its settings and attestation | `schema_version` 1 |
| `licence.schema.json` | the licence block inside a corpus manifest | `popboll.licence/1` |
| `routine-manifest.schema.json` | a routine's `routine.yaml` (the document the YAML parses to) | `api: 1` |
| `cue.schema.json` | a button cue list, as the hardware abstraction takes it | cue model 1 |
| `device-identity.schema.json` | a device's `device_identity.json`, and the serial patterns | `schema_version` 1 |
| `makers.schema.json` | the maker registry, `makers.json` | `popboll.makers/1` |
| `origin.schema.json` | a self-hosted corpus's discovery file, `popboll-corpus.json` | `popboll.origin/1` |
| `image-release.schema.json` | the image release record, `latest.json` | record 1 (both shapes in use) |
| `snipler-events.schema.json` | a batch of Glass Snipler input events | PWHAMSS page 0.0.2-draft |
| `snipler-frame.schema.json` | a Glass Snipler frame | envelope `v` 1, PWHAMSS page 0.0.2-draft |
| `keymap.schema.json` | the engagement keymap: what each button gesture means | `v` 2 |

Not here yet, on purpose: bollardeck Part A messages and the dock descriptor. That specification
is being rewritten, and schemas written now would be wrong.

## Using them

From Python, with nothing to install beyond the SDK:

```python
import bollardeck.schema as schema

for problem in schema.validate("licence", block):
    print(problem.pointer, problem.message)      # a JSON pointer into your document, and why
```

`schema.names()` lists the names. A name may point inside a schema: `"cue#/$defs/cue"` checks one
cue, `"device-identity#/$defs/device_serial"` checks a physical device's serial.

From anything else, load the files with any draft 2020-12 validator. Each schema's `$id` is
`https://popboll.com/sdk/schema/<file>`; three schemas refer to another by a relative `$ref`
(`corpus-manifest` and `origin` to `licence`, `makers` to `device-identity`), so give your validator all the
files. The `$id`s are names, not addresses you can fetch yet.

## Rules for these files

- **Only the keywords the SDK's validator implements.** `bollardeck.schema` refuses a schema that
  uses any other keyword, and a test fails when the implemented set and the used set differ. To
  use a new keyword, implement it in `python/bollardeck/schema.py` first. `format` is not used:
  say it with `pattern`.
- **Patterns stay portable.** Anchored, ASCII classes written out (`[0-9]`, not `\d`), nothing
  that reads differently in ECMA 262 and Python.
- **Unknown members are allowed** unless the format itself refuses them (a maker row, a cue, a
  routine's `limits`). A reader ignores what it does not know; a writer keeps it.
- **A schema checks shape, not truth.** It cannot tell whether a licence has lapsed, whether a
  hash matches, whether a maker code is registered, or whether two rows repeat a code. Each
  schema's `description` says what it leaves to code.
- After changing a schema, run `python3 tools/generate.py` (it rewrites
  `python/bollardeck/_schemas.py`, the copy the package carries) and add or change vectors under
  `conformance/`.

`conformance/DECISIONS.md` lists the rules a reader applies that a schema cannot state.
