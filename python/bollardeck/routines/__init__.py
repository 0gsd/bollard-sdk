# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.routines: the routine API (bollardeck Part B, `api: 1`).

A routine is custom logic that runs inside a device's song factory. It is a folder, or a .zip of
one, holding `routine.yaml` (the manifest) and `routine.py` (the code). The factory calls the
routine's hook functions at six fixed points of a song; every hook is optional.

    routine.yaml                          routine.py
    ------------                          ----------
    name: mixolydian_bridge               def on_plan(plan, ctx):
    version: 0.1.0                            for part in plan.parts: ...
    author: Example Hacker                    return plan
    api: 1
    hooks: [on_plan]
    limits: {max_ms_per_call: 50}

## Writing a routine

| Hook | When | You get | You may hand back |
| :--- | :--- | :--- | :--- |
| `on_plan(plan, ctx)` | after the song is planned | a copy of the plan | the plan with parts re-ordered (not in a suite) and each part's `progression`, `energy`, `bars`, `label` changed |
| `on_part_candidate(part, notes, ctx)` | after a take is played, before it is judged | the part and a copy of the take's notes | a list of notes (or edit the copy and return None) |
| `on_verdict(part, verdicts, ctx)` | after the judges | frozen verdicts | `{"directives": [...], "veto": bool, "reason": str}` or None |
| `on_overdub(plan, bus, ctx)` | after overdubs are voted | the plan and a frozen view of the locked takes | `{part_index: [notes to add]}` |
| `on_export(meta, ctx)` | before the song's metadata is written | the frozen metadata | a small JSON-able mapping, stored under your routine's name |
| `on_drama(shots, ctx)` | when a film of the song is directed | a copy of the shots | the shots re-ordered, with new ones added |

`ctx` gives every hook: `ctx.rng` (a seeded random.Random: use it, so the song stays
reproducible), `ctx.log(text)`, `ctx.folder` (the one place you may write), `ctx.corpus`
(read-only ids, labels, summaries, DNA), `ctx.roster`, `ctx.taste_dna`, `ctx.device`, `ctx.part`,
`ctx.take`, `ctx.song_id`, `ctx.api`.

The rules:

- You work on copies. The factory checks what comes back and keeps only what the hook may change.
- Scores cannot be changed, and there is no API that creates or alters a corpus.
- While a hook runs, network sockets, subprocesses, ctypes and file writes outside your folder
  are refused. That is a guard rail for honest code on your own device, not a sandbox.
- An exception, a broken limit or an invalid result switches your routine off for the rest of the
  song. It is recorded in the song's metadata under `routines_failed`; routines that ran cleanly
  are under `routines_applied`.
- The manifest's `limits` can only tighten the hard caps (`HARD_LIMITS`).

Try one without a device:

    from bollardeck.routines import load_routines, sim
    song = sim.run_song(load_routines(["path/to/my_routine"], factory=sim.FACTORY), seed=7)
    print(song["meta"]["routines_applied"], song["meta"]["routines_failed"])

or list what would load: `python3 -m bollardeck.routines path/to/routines`.

## The manifest

`routine.yaml` is read by a small YAML reader of the SDK's own (`routines.yamlsubset`: what a
manifest needs, and a refusal with a line number for anything else) and then checked against the
`routine-manifest` schema. Nothing is coerced: quote a version that would read as a number.

## Calling routines from a factory

    from bollardeck.routines import Factory, load_routines

    routines = load_routines(data_dir=my_data_dir,
                             factory=Factory(chords=MY_CHORDS, note_type=MyNote, ticks_per_bar=1920))
    routines.begin_song(song_id=..., rng_seed=..., state=checkpoint_dict, corpus_set=..., device_serial=...)
    if routines:
        plan = routines.plan(plan)
        notes = routines.part_candidate(part, notes, take)
        directives, vetoes = routines.verdict(part, verdicts, take)
        added = routines.overdub(plan, bus)
        meta.update(routines.export(meta))
        film = routines.drama(film)

Routines are found in `<data dir>/routines/` and then in every path of `$POPBOLLARD_ROUTINES`;
the first routine with a name wins, and they run in (manifest `order`, discovery) order.
`$POPBOLLARD_NO_ROUTINES=1` turns them all off, and nothing is ever loaded on a hosted service
(`K_SERVICE` or `$POPBOLLARD_CLOUD_RUN` set). A set with nothing in it is falsy and costs nothing.

`Factory` tells the routine API what a chord, a note and a bar are in your program; it carries
no music theory of its own. A hook that needs it and finds none raises `RoutineSetupError`.

A routine may not import the modules in `BANNED_IMPORTS` (the network, other processes, foreign
code). Your program has modules of its own that a routine must not reach, the ones that write
corpora or own the song's state: name them with `load_routines(..., banned_imports=["my_engine",
"my_corpus_writer"])`. The SDK does not know their names and does not list anyone's.
"""
from . import manifest, sim, yamlsubset
from .errors import RoutineError, RoutineSetupError
from .manifest import (API_VERSION, DEFAULT_ORDER, ENTRY_NAME, HARD_LIMITS, HOOKS, MANIFEST_NAME, NAME_RE,
                       ManifestError, parse_manifest)
from .runner import (BANNED_IMPORTS, DIRECTIVE_RE, ENV_DATA_DIR, ENV_OFF, ENV_PATHS, CorpusView, Factory, Routine,
                     RoutineContext, RoutineSet, VerdictView, check_source, default_routine_dirs, discover, freeze,
                     is_hosted_service, is_package, load_routine, load_routines, main, thaw)

__all__ = ["API_VERSION", "HOOKS", "HARD_LIMITS", "MANIFEST_NAME", "ENTRY_NAME", "NAME_RE", "DEFAULT_ORDER",
           "DIRECTIVE_RE", "BANNED_IMPORTS", "ENV_PATHS", "ENV_OFF", "ENV_DATA_DIR",
           "RoutineError", "RoutineSetupError", "ManifestError", "Factory", "Routine", "RoutineSet",
           "RoutineContext", "CorpusView", "VerdictView", "freeze", "thaw", "parse_manifest", "check_source",
           "is_package", "discover", "default_routine_dirs", "load_routine", "load_routines",
           "is_hosted_service", "main", "manifest", "sim", "yamlsubset"]
