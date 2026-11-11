# SPDX-License-Identifier: Apache-2.0
"""mixolydian_bridge: force every Bridge onto the Mixolydian jam cell and log it.

The cell is I - bVII - IV - I (in C: C, Bb, F, C).
"""

MIXOLYDIAN_JAM_CELL = ["I", "bVII", "IV", "I"]


def on_plan(plan, ctx):
    for part in plan.parts:
        if part.category == "Bridge" and list(part.progression) != MIXOLYDIAN_JAM_CELL:
            ctx.log(f"part {part.part_index} {part.label}: {'-'.join(part.progression)} -> "
                    f"{'-'.join(MIXOLYDIAN_JAM_CELL)}")
            part.progression = list(MIXOLYDIAN_JAM_CELL)
    return plan
