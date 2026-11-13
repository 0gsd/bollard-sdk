# Bollawax Bollard SDK

The SDK for building on the Pop Boll platform: docks, routines, apps and tools that talk to a
Bollawax device or to its web twin, and that read corpora the way the platform does, respecting
each corpus's licence and settings.

**Status: 0.3.0, shipped with Bollawax 0.3.0 (0.2.0 shipped with 0.2.5, and 0.1.0, the first version,
with 0.2.4). Its interfaces may still change between 0.x versions.** The corpus client, the device layer, routines,
the matrix engine and the browser binding are built, and so are a cart's additions (a pocket
context for the keymap, power sources, file playback and its decoders, audio routes, Bluetooth, the
cart and dock descriptors), tested against the simulated board. 0.3.0 adds help content and tours, the
`.pxs` format, a minimal deck service and client (a draft, as the dock protocol is), and the now-playing
and transport schemas. The Glass Snipler types are placeholders. Of the specifications under `spec/`, the software
pages are current with this version and the hardware pages are speculative drafts: `bollard.md` is
version 1, the interface under the Boll's foot, and the specification for the cart and its docks is
not written (`spec/bollardeck.md` §20 records what is decided).

Pop Boll builds its own device images and web apps on this SDK. What you install is what we run.

## Layout

| Path | What | Licence |
| :--- | :--- | :--- |
| `python/bollardeck/` | The Python package (`import bollardeck`), standard library only: `corpus` (read corpora through one gate that respects their licence and settings), `device` (hardware abstraction with a simulator and a registry for boards, button cues, gestures, the keymap, device identity), `routines` (the routine API), `matrix` (the LED matrix frame engine: film shots, playback, DJ mode, text, the premiere box), `schema` (validate a document against a format), `constants`. `deck` and `snipler` are placeholders | Apache-2.0 |
| `js/` | The browser and Node binding, no build step: `bollardeck.js` and its parts (constants, the same validator and schemas, button cues, the LED matrix frame engine, optional page helpers). `js/README.md` is the reference | Apache-2.0 |
| `c/` | A header for dock firmware | Apache-2.0 |
| `schema/` | JSON Schemas (draft 2020-12) for eleven formats: corpus manifest, licence block, corpus origin file, routine manifest, button cues, keymap, device identity, maker registry, image release record, Glass Snipler events and frame | Apache-2.0 |
| `constants/` | `constants.json`, the single source for values Python and JS share (tap timings, cue states, roles, periods and levels, buttons, gesture names, the keymap), and `makers.json`, the maker registry | Apache-2.0 |
| `conformance/` | Test vectors any implementation must pass, as plain JSON: 203 schema vectors with an index, and behaviour vectors for the corpus gate, gestures, the keymap, cues, the matrix engine and the routine manifest reader | Apache-2.0 |
| `tools/` | `generate.py` (writes everything derived from `constants/` and `schema/`, for Python and JS; `--check` fails when any is stale), `pin_vectors.py` (writes the expected values of the cue and matrix vectors from the SDK's own Python), `sync_spec.py`, `release.sh` | Apache-2.0 |
| `examples/` | A device on the simulator with routines, three example routines, a corpus read from a fake hub, a page that runs from disk | Apache-2.0 |
| `tests/` | The Python suite (`python3 -m unittest discover -s tests`) and the Node tests under `tests/js/` | Apache-2.0 |
| `spec/` | The public specification pages, unchanged copies of those published at popboll.com/spec (`spec/SOURCES.json` has the checksums) | CC BY 4.0 |

## Install (from a checkout)

```bash
pip install .
```

```python
import bollardeck
print(bollardeck.__version__, bollardeck.SPEAKS)

import bollardeck.schema as schema
print(schema.validate("licence", {"scope": "morpus_only", "store_audio": True}))
# [Problem(pointer='/store_audio', message='must be false, not true', keyword='const')]
```

## Corpora

```python
from bollardeck.corpus import HubClient, discover

found = discover(roots=["/media/sd/corpora"], hub=HubClient("https://hub.example", token=TOKEN))
for corpus in found.corpora:
    verdict = corpus.may("study")                 # the gate: never raises, always says why
    if verdict:
        pairs = corpus.study_pairs(verdict)       # content takes the verdict; there is no other way in
    else:
        print(corpus.id, verdict.reason, verdict.detail)
```

`help(bollardeck.corpus)` is the usage guide; `examples/corpus_from_a_fake_hub.py` runs without a
network. The gate's behaviour is pinned by `conformance/corpus-gate/`.

A hub's read token alone is study only for a corpus that is not public. To reach such a corpus's
tracks, audio, art and bundles, say who the client acts for: `HubClient(..., acting_for="ada@example.org")`
or `hub.corpus(id, acting_for=...)`. The name goes in the `X-Pop-For` header, never in a URL, and
is self-declared until sign-in arrives. Also there: `CorpusUnavailable` and `NotAvailable` carry a
`reason` and the hub's `status`; `corpus.open_audio_ranged(file, verdict, range_header=...)` gives
a relay the source's status and headers, and `corpus.open_art_ranged(name, verdict, ...)` does the same
for cover art; `hub.listing().from_cache`; `corpus.manifest_view()` (read-only,
no copy); `hub.corpus_gate()` (the hub's rollout switch, `enforce` or `report`). A clock that is set
back does not reopen an expired licence held in a cache.

## The device layer and routines

`bollardeck.device` is the hardware abstraction (with a registry so a board family registers
itself from outside), button cues, the gesture engine, the keymap resolver and device identity;
`bollardeck.routines` is the routine API. Each module's docstring is its usage guide. To see them
work together on the simulator:

```bash
python3 examples/device_on_sim.py
```

A key source may say when a press begins (`"<button> down [t_ms]"`, `hal.base.key_line(1, down=True)`).
That is a hint and never a gesture: a press is a tap or a hold by the `hold_ms` its release
states, and every `Gesture` carries that `hold_ms`. A `routine.yaml` may also be one JSON object.

`bollardeck.matrix` makes the frames of the 13 x 8 LED matrix and its three RGB LEDs, byte for
byte what `js/bollardeck.matrix.js` makes (`conformance/matrix/`, 1,135 vectors):

```python
from bollardeck import matrix
frame = matrix.glyph("boot", 0)            # also film, playback, idle, corpus, dj, text, premiere, tone
frame.to_bytes(), frame.hex(), matrix.to_ascii(frame)
```

The keymap (`bollardeck.constants.KEYMAP`, `schema/keymap.schema.json`) says what each button
gesture means, and `conformance/gestures/`, `conformance/cues/` and `conformance/cue-render/` pin
the behaviour for every binding. `conformance/DECISIONS.md` says what the SDK does where the
schemas and the pages left room.

## Working on it

```bash
python3 -m unittest discover -s tests     # also runs the Node tests when node is installed
node --test tests/js/*.test.js            # the browser binding alone
python3 tools/generate.py                 # after changing constants/ or schema/
python3 tools/pin_vectors.py              # after changing how a cue or a matrix frame is drawn
```

`jsonschema` and PyYAML, when installed, cross-check the SDK's own validator and its reader for
`routine.yaml`. Neither is needed to use the SDK; CI installs both for the tests.

**popbollard** is Pop Boll's own repository for Bollawax, and it is closed. Where a tool or a test
here names it (`tools/sync_spec.py --from`, the `BOLLARD_SDK_POPBOLLARD` environment variable of
`tests/test_reality.py` and `tests/test_corpus_reality.py`), that is a check for its maintainers:
it reads a checkout of that repository and is skipped without one. Nothing in the SDK needs it.

## In a page

```html
<script src="js/bollardeck.js"></script>
<script>
  bollardeck.schema.validate("licence", {scope: "morpus_only", store_audio: true});
  bollardeck.cues.at([{button: 1, state: "pulse", role: "go"}], performance.now());
  bollardeck.matrix.glyph("boot", 0);
</script>
```

One tag loads the whole binding: the validator (the twin of `bollardeck.schema` in Python), the
button cue helpers, the LED matrix frame engine, the gesture engine and keymap resolver, and the
corpus gate with a hub client on `fetch`, with optional helpers for elements and a canvas. `js/README.md` is the reference, `examples/browser/index.html` runs from disk, and
`node --test tests/js/*.test.js` runs its tests. `conformance/matrix/` and
`conformance/cue-render/` hold the behaviour vectors it must pass (`tools/pin_vectors.py` writes
their expected values), and `tools/generate.py` writes `js/bollardeck.schemas.js`.

`CHANGELOG.md` lists what each version added and changed.

## Versions

The SDK has its own version, and its tags are the version number (`0.1.0`, `0.2.0`, `0.3.0`). It is not the Bollawax
image version.
`bollardeck.SPEAKS` lists the wire and format versions this SDK speaks, and
`bollardeck.MIN_BOLLAWAX` is the oldest Bollawax release it is tested against.

## Contributing

Pull requests are closed for now; see [CONTRIBUTING.md](CONTRIBUTING.md). Issues are welcome.

## Licence

Code: Apache-2.0 (`LICENSE`). Specification text in `spec/`: CC BY 4.0, "Pop Boll, by Graham
Smith" (`LICENSES/CC-BY-4.0.txt`). See `NOTICE` for names and trademarks.
