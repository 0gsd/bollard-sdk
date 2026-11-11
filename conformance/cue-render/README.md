# conformance/cue-render

A cue list, a time, and what each of the three buttons shows then.

```json
{"version": 1,
 "constants": {"PULSE_PERIOD_MS": 500, "CHASE_PERIOD_MS": 1000, "PULSE_FLOOR": 0.35, "CHASE_TAIL": 0.25, "CHASE_STEPS": 3},
 "vectors": [
   {"name": "one-pulse-t125", "cues": [{"button": 3, "state": "pulse", "role": "go"}], "t_ms": 125,
    "buttons": [
      {"button": 1, "driven": false, "state": "off", "role": null, "level": 0, "arc": [0, 0, 0], "head": null, "pixel": 0},
      {"button": 2, "driven": false, "state": "off", "role": null, "level": 0, "arc": [0, 0, 0], "head": null, "pixel": 0},
      {"button": 3, "driven": true, "state": "pulse", "role": "go", "level": 0.675, "arc": [0.675, 0.675, 0.675], "head": null, "pixel": 172}]}
 ]}
```

- `cues` is a valid cue list: it fits the `cue` schema and names no button twice. Buttons are
  numbered 1, 2, 3. `constants` are the values of `constants/constants.json` the file was written with.
- `buttons` always has three entries, in button order.
- `driven` is false when the list has no cue for the button: the surface leaves that button alone.
- `level` is how bright one lamp for the button is, 0 to 1. `arc` is the same for a surface that
  draws a button as three lamps. `head` is the lamp that leads a chase (0, 1 or 2), else null.
  `pixel` is `level` as 0 to 255, rounded half to even.
- `calm: true` on a vector is reduced motion: `pulse` and `chase` are drawn as `on`.

`state`, `role`, `driven`, `head` and `pixel` must match exactly. `level` and `arc` come from a
cosine, so allow a difference of 1e-12.

The rules, for an implementation that has no vectors to hand:

- `off`: level 0. `on`: level 1.
- `pulse`: with `p = (t_ms mod PULSE_PERIOD_MS) / PULSE_PERIOD_MS`, level is
  `PULSE_FLOOR + (1 - PULSE_FLOOR) * (0.5 + 0.5 * cos(2π p))`. Full at `t_ms = 0`.
- `chase`: head is `floor((t_ms mod CHASE_PERIOD_MS) * 3 / CHASE_PERIOD_MS)`; the head's lamp is 1
  and the other two are `CHASE_TAIL`. A single lamp shows the middle of the arc.
- `t_ms` is counted in whole milliseconds.

`tools/pin_vectors.py` writes `buttons` from the Python renderer, `bollardeck.device.cues.at`;
`--check` fails when a value differs. The values were first pinned to the device's own cue layer
and did not change when the Python renderer took over. `tests/test_device.py` runs the vectors in
Python and `tests/js/cues.test.js` runs them against `js/bollardeck.cues.js`.
