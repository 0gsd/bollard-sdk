# examples

Small working examples. Each runs from the repository root with nothing installed.

| Path | What it shows |
| :--- | :--- |
| `device_on_sim.py` | a whole small device on the simulator: the hal, a song with routines in the toy factory, a prompt answered with button presses through the gesture engine and the keymap, and the cues that were lit |
| `routines/` | three example routines, one or more for each of the six hooks |
| `corpus_from_a_fake_hub.py` | Finding corpora on a hub, asking the gate what a visitor may do with each, reading what it allows, showing the notices. It starts its own stand-in hub on a loopback port and three made-up corpora; it never talks to a real service. |
| `deck_client.py` | a third-party client for a deck: hello, what was granted, now playing, a transport write. It starts its own made-up player (`bollardeck.deck.sim`) on a Unix socket in a temporary folder, or takes the socket of a deck already running |
| `browser/index.html` | the browser binding in a page, opened straight from disk with no server and no build step: a cue list on three buttons, three buttons to tap and hold with the gesture and the keymap's answer, the LED matrix on a canvas, and what the validator says about a bad cue list |

```bash
python3 examples/device_on_sim.py
python3 examples/corpus_from_a_fake_hub.py
python3 examples/deck_client.py
python3 -m bollardeck.routines examples/routines      # needs the package installed, or PYTHONPATH=python
```
