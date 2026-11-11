# conformance/matrix

Inputs to the LED matrix engine and the frame it makes for each. An implementation of the engine
in any language passes when it makes the same bytes. Two are held to these files: the Python
engine `bollardeck.matrix` (`tests/test_matrix.py`) and the JavaScript engine
`js/bollardeck.matrix.js` (`tests/js/matrix.test.js`).

Each file covers one call and is plain JSON:

```json
{"version": 1,
 "about": "...",
 "fixtures": {"suite": {"song_id": "...", "drama": {"shots": []}}},
 "vectors": [
   {"name": "jam-mid", "call": "film", "args": {"song": {"$fixture": "suite"}, "t_ms": 21160},
    "frame": "<226 hex digits>"},
   {"name": "beat-ramp-3", "call": "dj_beat", "args": {"seg": {"$fixture": "ramp"}, "pos_s": 12},
    "value": 20.0}
 ],
 "pinned_to": {"python": "bollardeck.matrix"}}
```

- An argument that is exactly `{"$fixture": "name"}` stands for `fixtures.name`.
- `frame` is the 113-byte wire form as hex: 104 pixels row-major (13 wide, row 0 at the top), then
  LED1, LED3 and LED4 as `r g b`. It must match exactly.
- `value` is a number, a string or a list, and must match exactly too. The engine's arithmetic is
  kept to what IEEE doubles do the same way in every language.
- An argument that is absent takes the call's default.

| File | Call and arguments |
| :--- | :--- |
| `film.json` | `film`: `song`, `t_ms`, `calm` |
| `playback.json` | `playback`: `song`, `pos_s`, `calm` |
| `idle.json` | `idle`: `t_ms`, `calm`, `temperament` |
| `corpus.json` | `corpus`: `t_ms`, `level` (0), `bands`, `calm` |
| `glyph.json` | `glyph`: `name`, `t_ms`, `calm` |
| `dj.json` | `dj`: `seg`, `pos_s`, `t_ms` (0), `calm` |
| `text.json` | `text`: `text`, `t_ms`, `loop` (true), `priority` ("pairing"), `ttl_ms`, `calm` |
| `premiere.json` | `premiere`: `number`, `t_ms`, `opened`, `calm`, `tier` ("") |
| `tone.json` | `tone`: `frame` (hex), `tone` |
| `helpers.json` | `dj_beat`, `dj_crossfader`: `seg`, `pos_s`. `dj_camelot`: `value`. `text_pass_ms`, `str_seed`: `text`. `ascii`: `frame` |

`calm` defaults to false everywhere.

Every song, segment, title and id here is made up. The vectors named `tolerant-…`, and the ones
whose names say what they show, hold malformed input on purpose: they fix how the engine reads a
number written as a string, an empty list where a value was expected, and a name that happens to
be a member of every JavaScript object (`__proto__`, `toString`, `constructor`, `hasOwnProperty`,
`valueOf`), as a name the engine looks up and as a member of a song, segment, temperament or tone.

## Where the expected values come from

From this repository's Python engine, `bollardeck.matrix`. `tools/pin_vectors.py` runs it over the
inputs and writes `frame`, `value` and `pinned_to`; `tools/pin_vectors.py --check` writes nothing
and reports any file that changed.

The device runs that same module, so there is one engine in Python and its twin in JavaScript.

Running the vectors needs none of that: they are plain JSON.

To add a vector, write its `name`, `call` and `args` by hand, then pin. Add only a vector the
Python engine and the JavaScript engine answer the same way. Where they do not
(text that is not a string, a number written in non-ASCII digits), there is no vector.
