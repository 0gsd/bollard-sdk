# SPDX-License-Identifier: Apache-2.0
"""judge_heckler: shout MORE_HOOK whenever J2's score is below 0.6. Scores stay untouched.

Verdicts arrive as frozen views, so a routine cannot forge a score even by accident; the
only things on_verdict can hand back are directives, a veto and a reason.
"""

THRESHOLD = 0.6


def on_verdict(part, verdicts, ctx):
    j2 = next((v for v in verdicts if v.judge_id.startswith("J2")), None)
    if j2 is None or j2.score >= THRESHOLD:
        return None
    ctx.log(f"part {part.part_index} take {ctx.take}: J2 {j2.score:.3f} < {THRESHOLD} -> MORE_HOOK")
    return {"directives": ["MORE_HOOK"], "reason": f"J2 scored {j2.score:.3f}"}
