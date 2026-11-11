# SPDX-License-Identifier: Apache-2.0
"""tour_guide: one small, legal change in each of on_part_candidate, on_overdub, on_export, on_drama.

A routine never builds a note from nothing: it copies one it was given with dataclasses.replace,
so it works whatever note class the factory uses.
"""
from dataclasses import replace

SEEN = {"notes": 0, "takes": 0}


def on_part_candidate(part, notes, ctx):
    SEEN["notes"] += len(notes)
    SEEN["takes"] += 1
    if notes and notes[-1].pitch + 12 <= 127:
        notes.append(replace(notes[-1], pitch=notes[-1].pitch + 12))
    return notes


def on_overdub(plan, bus, ctx):
    first = min(bus["locked_parts"])
    locked = bus["locked_parts"][first]
    if not locked:
        return None
    ctx.log(f"one overdub note on part {first}")
    return {first: [replace(locked[0], velocity=min(127, locked[0].velocity + 10))]}


def on_export(meta, ctx):
    return {"notes_seen": SEEN["notes"], "takes_seen": SEEN["takes"], "song": meta["song_id"]}


def on_drama(shots, ctx):
    return [{"kind": "title_card", "duration_ms": 1200, "data": {"text": "a tour_guide film"}}] + shots
