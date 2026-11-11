# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.routines.sim: a toy song factory, for trying a routine with no device.

It is not the Bollawax engine and makes no music worth hearing. It builds a small plan, invents
notes and judges' verdicts from a seed, and calls the six hooks in the order and with the shapes
a device does, so a routine author can see their hook run, see what was kept, and see what was
refused and why.

    from bollardeck.routines import load_routines, sim

    routines = load_routines(["examples/routines"], factory=sim.FACTORY)
    song = sim.run_song(routines, seed=7)
    song["plan"].parts[2].progression      # what on_plan left behind
    song["meta"]["routines_applied"]       # each routine's hooks_called and log
    song["meta"]["routines_failed"]        # any routine that was switched off, and why

The shapes here (`Plan`, `Part`, `NoteEvent`, `Verdict`, `Bus`) carry the fields the routine API
reads and checks. A real factory's objects have more fields; a routine should touch only these.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .runner import Factory, RoutineSet

__all__ = ["CHORDS", "TICKS_PER_BAR", "JUDGES", "NoteEvent", "Part", "Plan", "Verdict", "Bus", "FACTORY",
           "demo_plan", "demo_notes", "demo_verdicts", "demo_film", "run_song"]

# Roman-numeral chord names a sim plan may use.
CHORDS = frozenset({"I", "ii", "iii", "IV", "V", "vi", "bIII", "bVI", "bVII", "V7", "IVmaj7", "ii7"})
TICKS_PER_BAR = 1920                      # 480 ticks to the quarter note, four to the bar
JUDGES: Tuple[Tuple[str, str], ...] = (
    ("J1_groove", "groove"), ("J2_hook", "melody"), ("J3_harmony", "harmony"), ("J4_form", "form"),
    ("J5_texture", "texture"), ("J6_dynamics", "dynamics"), ("J7_surprise", "surprise"))


@dataclass(frozen=True)
class NoteEvent:
    channel_1based: int
    pitch: int
    velocity: int
    start_tick: int
    duration_ticks: int
    origin_tag: str = ""


@dataclass
class Part:
    part_index: int
    label: str
    category: str
    bars: int
    progression: List[str]
    energy: float
    movement_index: int = 0
    assigned_team_ids: List[int] = field(default_factory=list)
    study_break_channel: Optional[int] = None
    leitmotif_role: str = ""


@dataclass
class Plan:
    title: str
    form: str                             # "single" or "suite"
    key: str
    bpm: int
    parts: List[Part]
    total_bars: int
    movements: List[str] = field(default_factory=list)
    taste_dna: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Verdict:
    judge_id: str
    judge_number: int
    domain: str
    score: float
    threshold: float
    lock_vote: bool
    metrics: Dict[str, float]
    directives: List[str]


@dataclass
class Bus:
    """The locked takes: {part_index: [NoteEvent, ...]}."""
    locked_parts: Dict[int, List[NoteEvent]] = field(default_factory=dict)


FACTORY = Factory(chords=CHORDS, note_type=NoteEvent, ticks_per_bar=TICKS_PER_BAR)


def demo_plan(seed: Any = 0) -> Plan:
    """Verse, Chorus, Bridge, Chorus, with progressions picked from the seed."""
    rng = random.Random("plan|%s" % (seed,))
    cells = (["I", "V", "vi", "IV"], ["vi", "IV", "I", "V"], ["I", "IV", "V", "IV"], ["ii", "V", "I", "vi"])
    shape = (("Verse 1", "Verse", 8, 0.45), ("Chorus 1", "Chorus", 8, 0.8),
             ("Bridge", "Bridge", 4, 0.6), ("Chorus 2", "Chorus", 8, 0.9))
    parts = [Part(part_index=i, label=label, category=category, bars=bars, progression=list(rng.choice(cells)),
                  energy=energy, assigned_team_ids=[1 + (i % 3)])
             for i, (label, category, bars, energy) in enumerate(shape, start=1)]
    return Plan(title="Sim song %s" % (seed,), form="single", key="C", bpm=rng.choice((96, 108, 120)),
                parts=parts, total_bars=sum(p.bars for p in parts))


def demo_notes(part: Part, seed: Any = 0, take: int = 1) -> List[NoteEvent]:
    """One note on each beat of the part, on channel 1."""
    rng = random.Random("notes|%s|%s|%s" % (seed, part.part_index, take))
    beat = TICKS_PER_BAR // 4
    return [NoteEvent(channel_1based=1, pitch=rng.choice((60, 62, 64, 65, 67, 69, 71)), velocity=rng.randint(60, 110),
                      start_tick=i * beat, duration_ticks=beat // 2)
            for i in range(part.bars * 4)]


def demo_verdicts(part: Part, seed: Any = 0, take: int = 1) -> List[Verdict]:
    """Seven judges, each with a score between 0.3 and 1 drawn from the seed."""
    rng = random.Random("verdicts|%s|%s|%s" % (seed, part.part_index, take))
    out = []
    for number, (judge_id, domain) in enumerate(JUDGES, start=1):
        score = round(rng.uniform(0.3, 1.0), 3)
        out.append(Verdict(judge_id=judge_id, judge_number=number, domain=domain, score=score, threshold=0.6,
                           lock_vote=score >= 0.6, metrics={"confidence": round(rng.random(), 3)}, directives=[]))
    return out


def demo_film(plan: Plan) -> Dict[str, Any]:
    """One shot per part."""
    shots, t = [], 0
    for part in plan.parts:
        ms = part.bars * 500
        shots.append({"kind": "part", "duration_ms": ms, "t_ms": t, "data": {"label": part.label}})
        t += ms
    return {"shots": shots, "total_ms": t, "kinds": {"part": len(shots)}}


def run_song(routines: RoutineSet, seed: Any = 0, song_id: str = "sim-0001", device_serial: str = "",
             max_takes: int = 3) -> Dict[str, Any]:
    """One song through the toy factory, calling every hook the way a device does: on_plan once,
    then for each part a take (on_part_candidate, on_verdict; another take while a routine vetoes,
    up to `max_takes`), then on_overdub, on_export and on_drama. Returns {"plan", "bus", "takes",
    "overdubs", "meta", "film"}. Deterministic for a seed."""
    if routines.factory is None:
        routines.factory = FACTORY
    routines.begin_song(song_id=song_id, rng_seed=seed, device_serial=device_serial,
                        corpus_ids=["0000-SIM"], corpus_labels=["The simulator's empty corpus"])
    plan = demo_plan(seed)
    if routines:
        plan = routines.plan(plan)
    bus = Bus()
    takes: List[Dict[str, Any]] = []
    for part in plan.parts:
        directives: List[str] = []
        for take in range(1, max_takes + 1):
            notes = demo_notes(part, seed, take)
            if routines:
                notes = routines.part_candidate(part, notes, take)
            verdicts = demo_verdicts(part, seed, take)
            extra, vetoes = routines.verdict(part, verdicts, take) if routines else ([], [])
            directives = extra
            takes.append({"part_index": part.part_index, "take": take, "notes": len(notes),
                          "routine_directives": list(extra), "vetoed_by": list(vetoes)})
            if not vetoes:
                break
        bus.locked_parts[part.part_index] = list(notes)
    overdubs = routines.overdub(plan, bus) if routines else []
    meta: Dict[str, Any] = {"song_id": song_id, "seed": seed, "title": plan.title, "bpm": plan.bpm,
                            "total_bars": plan.total_bars,
                            "parts": [{"part_index": p.part_index, "label": p.label, "category": p.category,
                                       "bars": p.bars, "progression": list(p.progression)} for p in plan.parts]}
    if routines:
        meta.update(routines.export(meta))
    film = demo_film(plan)
    if routines:
        film = routines.drama(film)
    return {"plan": plan, "bus": bus, "takes": takes, "overdubs": overdubs, "meta": meta, "film": film}
