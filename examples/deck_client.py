#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
deck_client.py: a third-party client for a deck, and a made-up player to talk to.

    python3 examples/deck_client.py                      starts its own made-up player and talks to it
    python3 examples/deck_client.py /run/pb-deckd.sock   talks to a deck that is already running

It says hello as a dock that wants to read what is playing and to send transport, prints the
welcome (what it was granted, what waits for the user's consent), prints each now-playing message,
and skips to the next song. The made-up player is bollardeck.deck.sim on a Unix socket in a
temporary folder; nothing here needs hardware or a network.
"""
import pathlib
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))           # run from a checkout without installing

from bollardeck import deck  # noqa: E402
from bollardeck.deck.sim import SIM_DOCK, SimPlayer  # noqa: E402


def talk(path: str) -> None:
    client = deck.connect_unix(path)
    client.on("nowplaying", lambda m: print("now playing: %s (%s)" % (m["title"], "playing" if m.get("playing") else "paused")))
    welcome = client.hello(SIM_DOCK, want=["state", "nowplaying"], can=["transport"])
    print("welcome: granted %s; waiting for consent %s" % (", ".join(welcome.get("grants", [])) or "nothing",
                                                          ", ".join(welcome.get("pending", [])) or "nothing"))
    print("transport next: %s" % client.request("transport", cmd="next")["t"])
    time.sleep(0.2)                                      # let the now-playing message arrive
    client.close()


def main() -> int:
    if len(sys.argv) > 1:
        talk(sys.argv[1])
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        player = SimPlayer()
        server = deck.serve_unix(player.deck(), str(pathlib.Path(tmp) / "deck.sock"))
        try:
            talk(server.path)
        finally:
            server.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
