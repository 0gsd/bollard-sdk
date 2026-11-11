# Example routines

Three small routines for the song factory of a Bollawax device. `bollardeck.routines` documents
the interface and implements the loading and the checks.

| Routine | Hooks | What it changes |
| :--- | :--- | :--- |
| `mixolydian_bridge/` | `on_plan` | every Bridge's progression becomes I - bVII - IV - I |
| `judge_heckler/` | `on_verdict` | adds a `MORE_HOOK` directive when judge J2 scores a take below 0.6; never touches a score |
| `tour_guide/` | `on_part_candidate`, `on_overdub`, `on_export`, `on_drama` | one small, legal change in each of the other four hooks |

List what would load, in order:

```sh
python3 -m bollardeck.routines examples/routines
```

Run them in the toy factory, with no device:

```sh
python3 examples/device_on_sim.py
```

To install a routine on a device, copy its folder (or a zip of it) into `routines/` in the
device's data directory. Routines only work with the corpora already on the device, and nothing
here creates or changes a corpus.

`MORE_HOOK` is a made-up directive code. A device records it in each take's `routine_directives`
and carries it into the next take; whether the band acts on a code is up to the device.
