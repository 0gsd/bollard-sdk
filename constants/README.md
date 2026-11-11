# constants

`constants.json` is the single source for values that Python and JavaScript must agree on. Nothing
else in this repository writes these values by hand.

| Constant | Value | What it is |
| :--- | :--- | :--- |
| `HOLD_MS` | 800 | a press this long or longer is a hold, not a tap |
| `TAP_FOLLOW_MS` | 500 | taps chain when the next press begins within this long of the last release |
| `TAP_CHAIN_MAX` | 3 | the longest chain of taps that is one gesture |
| `CUE_STATES` | off, on, pulse, chase | the states of a button cue |
| `CUE_ROLES` | a, b, c, live, go, warn | what a lit button can stand for (or null) |
| `PULSE_PERIOD_MS` | 500 | one breath of a pulse cue (2 Hz) |
| `CHASE_PERIOD_MS` | 1000 | one turn of a chase cue |
| `PULSE_FLOOR` | 0.35 | how bright a pulse cue is at its dimmest |
| `CHASE_TAIL` | 0.25 | how bright the lamps behind a chase cue's head are |
| `CHASE_STEPS` | 3 | the lamps in a button's arc |
| `BUTTON_NUMBERS` | 1, 2, 3 | the three buttons: a button is its number |
| `BUTTONS` | three rows | per button: `button` 1/2/3, `label` inner/middle/outer, and for the wire `wire` and `id` |
| `GESTURES` | twelve names | `tap1..3`, `tap1x2..tap3x3`, `hold1..3` |
| `PROMPT_KINDS` | abc, spectrum, game | the kinds of prompt the keymap gives meanings for |
| `KEYMAP` | an object | the engagement keymap: what each gesture means (format: `schema/keymap.schema.json`) |

`tools/generate.py` writes, from this file:

- `python/bollardeck/constants.py` (`from bollardeck import constants`);
- `js/bollardeck.constants.js` (the constants alone: `globalThis.bollardeckConstants`, or `require()`);
- the constants block inside `js/bollardeck.js`, so one `<script>` tag gives `bollardeck.constants`
  with no build step and no second file;
- `python/bollardeck/device/_makers.py`, from `makers.json`;
- `python/bollardeck/_schemas.py` and `js/bollardeck.schemas.js`, from `schema/`.

`tools/generate.py --check` writes nothing and fails when any of those is stale. CI runs it, and so
does the test suite.

## Adding a constant

Add an entry to `constants.json` with a `value` (any JSON) and an `about` (one or two sentences),
run `python3 tools/generate.py`, and commit the source and the generated files together. Names are
`UPPER_CASE`. A constant belongs here only when both bindings need it and must agree.

## Buttons: one vocabulary

A button is its number, 1, 2 or 3, everywhere on the SDK's surface. `label`
(inner, middle, outer) is a name for people and describes the Boll's medallion only. `wire` and
`id` are what the `bollardeck/1` wire calls a button (`spec/bollardeck.md` §6.2), so that
`bollardeck.device.cues.to_wire` and `from_wire` can translate at that boundary. The wire keeps
those words for as long as it is `bollardeck/1`; a wire that carries button numbers is proposed
for a later protocol version (§22 of that page).

## The keymap

`KEYMAP` is published here, under Apache-2.0, and Bollawax reads it from here. It is the only
copy: the Python binding reads `bollardeck.constants.KEYMAP`, the browser binding reads
`bollardeck.constants.KEYMAP`, and nothing keeps a second file.

It is keymap version 2. In version 1 a prompt meaning was a bare value
(`"A"`, `-1`, `"replay"`) and a reader had to know which strings were verbs. In version 2 the
keymap says so itself:

```json
"tap1":  {"abc": {"choice": "A"}, "spectrum": {"choice": -1}, "game": {"do": "raw"}},
"hold1": {"abc": {"do": "replay"}, "spectrum": {"do": "replay"}, "game": null}
```

`{"choice": x}` answers the prompt with x; `{"do": name}` is a verb; `null` takes the gesture and
does nothing. `idle` and `always` map a gesture to a verb, written as a bare name.
`bollardeck.device.keymap.resolve` is the rule for reading it, with vectors in
`conformance/gestures/resolve.json`.

## The maker registry

`makers.json` in this folder is the maker registry (`popboll.makers/1`): the maker codes that
appear in device serials. `tools/generate.py` packages it as `bollardeck.device._makers`, and
`bollardeck.device.identity` reads it. Add a maker by adding a row here and regenerating.
