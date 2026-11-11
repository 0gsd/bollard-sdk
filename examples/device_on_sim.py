#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
device_on_sim.py: a whole small device on the simulator, with routines running in its factory.

    python3 examples/device_on_sim.py            (from a checkout: no install needed)

It does what a device does, in order, and prints each step:

1. asks the hal which board this is (the simulator, unless you are on a real one);
2. loads the routines in examples/routines and runs one song through the toy factory;
3. shows a prompt: lights three button cues and reads button presses through the gesture engine
   and the keymap;
4. prints the cue lines the simulator wrote, which is what a real board would have lit.

Nothing here needs hardware, a network or anything outside the standard library.
"""
import io
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))           # run from a checkout without installing

from bollardeck.device import cues, hal, keymap  # noqa: E402
from bollardeck.device.gestures import GestureEngine  # noqa: E402
from bollardeck.routines import load_routines, sim  # noqa: E402

# Button presses as a GPIO bridge writes them: "<button> <hold_ms> <release_ms>".
PRESSES = "\n".join([
    "1 120 1000",        # a tap on 1 while the prompt shows: answer A
    "3 90 2000",         # three quick taps on 3: a triple, answer C
    "3 80 2300",
    "3 85 2600",
    "2 1100 5000",       # a long press on 2: pass
    "1 100 7000",        # the prompt is gone by now: skip_to_frontier
    "3 950 9000",        # a long press on 3 means power, prompt or not
]) + "\n"


def main() -> int:
    board = hal.current()
    print("board: %s (maker code %s, hal interface %d)" % (hal.describe(), board.maker_code, hal.HAL_API))

    # -- a song, with routines -------------------------------------------------------------
    routines = load_routines([HERE / "routines"], factory=sim.FACTORY)
    song = sim.run_song(routines, seed=7)
    print("\nsong %r, %d bars:" % (song["plan"].title, song["plan"].total_bars))
    for part in song["plan"].parts:
        print("  part %d %-9s %s" % (part.part_index, part.label, "-".join(part.progression)))
    for applied in song["meta"]["routines_applied"]:
        print("  routine %-18s hooks %s" % (applied["name"], dict(applied["hooks_called"])))
        for line in applied["log"]:
            print("      " + line)
    for failed in song["meta"]["routines_failed"]:
        print("  routine %s was switched off at %s: %s" % (failed["name"], failed["where"], failed["error"]))
    print("  film: %d shots, the first a %r" % (len(song["film"]["shots"]), song["film"]["shots"][0]["kind"]))

    # -- a prompt, buttons and lights ------------------------------------------------------
    with tempfile.TemporaryDirectory() as folder:
        cue_file = pathlib.Path(folder) / "cues.txt"
        lights = hal.sim.FileCues(cue_file) if board.name == "sim" else board.cues()
        engine = GestureEngine()
        prompt = "abc"                                     # an A/B/C question is showing
        lights.set([cues.cue(1, "on", "a"), cues.cue(2, "on", "b"), cues.cue(3, "on", "c")])
        print("\nprompt %r is showing; buttons:" % prompt)

        def act(gesture):
            nonlocal prompt
            answer = keymap.resolve(gesture.name, prompt)
            if not answer.handled:
                what = "not the keymap's business"
            elif answer.kind == "choice":
                what = "%s: choose %r" % (answer.source, answer.value)
            elif answer.kind == "do":
                what = "%s: do %s" % (answer.source, answer.value)
            else:
                what = "%s: taken, nothing happens" % answer.source
            print("  %6d ms  %-7s %s" % (gesture.t_ms, gesture.name, what))
            if answer.source == "prompt" and answer.action == "pass":
                prompt = None                              # the prompt was passed: it goes away
                lights.set([cues.cue(1, "pulse", "live")])
                print("             (prompt gone; button 1 now pulses)")

        for event in board.keys(io.StringIO(PRESSES)).events():
            for gesture in engine.key(event):
                act(gesture)
        for gesture in engine.tick(event["t_ms"] + engine.tap_follow_ms + 1):
            act(gesture)
        lights.clear()

        if cue_file.is_file():
            print("\nwhat the simulator lit (one line per change, button:state:role):")
            for line in cue_file.read_text().splitlines():
                print("  " + line)
                assert cues.cue_line(cues.parse_cue_line(line)) == line
    return 0


if __name__ == "__main__":
    sys.exit(main())
