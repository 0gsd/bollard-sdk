# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device: the device layer. Buttons, lights, identity, and the boards under them.

    bollardeck.device.hal        the hardware abstraction (interface version `hal.HAL_API`): protocols,
                                 board detection, a registry for board families, and the simulator
    bollardeck.device.cues       what should be lit for each button; the normaliser; the wire form
    bollardeck.device.gestures   button presses in, gestures out (`tap1`, `tap3x3`, `hold2`), on a clock you supply
    bollardeck.device.keymap     gesture + what is showing -> the action the keymap gives it
    bollardeck.device.identity   device serials, maker codes, a device's own identity file
    bollardeck.device.dock       reserved for the Dock protocol; empty until its specification exists

A button is its number, 1, 2 or 3, everywhere here. "inner", "middle" and "outer" are labels for
people, and the names the bollardeck wire still uses; `cues.to_wire` and `cues.from_wire` are the
only places they are translated.

## A device loop in fifteen lines

    import io
    from bollardeck.device import cues, hal, keymap
    from bollardeck.device.gestures import GestureEngine

    board = hal.current()                                   # the simulator, on a dev machine
    lights = board.cues()
    engine = GestureEngine()
    prompt = "abc"                                          # the kind of prompt showing, or None
    lights.set([cues.cue(1, "on", "a"), cues.cue(2, "on", "b"), cues.cue(3, "on", "c")])

    keys = board.keys(io.StringIO("1 120 1000\\n3 900 4000\\n"))    # two presses, as a GPIO bridge writes them
    for event in keys.events():
        for gesture in engine.key(event) + engine.tick(event["t_ms"] + engine.tap_follow_ms + 1):
            answer = keymap.resolve(gesture.name, prompt)
            print(gesture.name, answer.source, answer.kind, answer.value)   # tap1 prompt choice A / hold3 always do power

`examples/device_on_sim.py` is this loop as a runnable script, with a routine running beside it.

## What each part promises

- **hal**: a program asks the board for keys, cues, power, storage, a matrix, audio and a
  display, and never touches a device file. A wrong or missing board is never fatal; the simulator
  stands in, and `hal.describe()` says so. Real boards register themselves (`hal.register`).
- **cues**: `cues.normalise` returns a list that always fits the `cue` schema. A bad cue is left
  out and reported, never raised from a light loop; `strict=True` raises for authors.
- **gestures** and **keymap**: pure functions of their input. The browser binding implements the
  same two against the same vectors (`conformance/gestures/`), so a web page and a device agree
  on what a press means.
- **identity**: reads and checks. It never invents a serial, assigns a number or touches a secure
  element.

Standard library only.
"""

__all__ = ["cues", "dock", "gestures", "hal", "identity", "keymap"]
