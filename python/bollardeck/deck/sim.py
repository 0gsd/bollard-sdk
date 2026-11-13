# SPDX-License-Identifier: Apache-2.0
"""bollardeck.deck.sim: a made-up dock and a made-up player, for tests and examples.

    from bollardeck import deck
    from bollardeck.deck.sim import SimDock, SimPlayer

    player = SimPlayer()
    d = player.deck()                         # a Deck with transport and volume wired to the player
    session, client = deck.pair(d)
    dock = SimDock(client)                    # says hello and keeps what it reads
    dock.hello()
    player.play()                             # publishes nowplaying to every subscribed session
    dock.client.request("transport", cmd="next")
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import Client, Deck, DeckError

SIM_DOCK = {"vendor": "Example Labs", "product": "Sim Dock", "vid": 4617, "pid": 49152,
            "profile": "usb-c", "fw": "0.1", "url": "https://example.org/sim-dock"}

SONGS = ({"song_id": "sim:1", "title": "First made-up song", "duration_ms": 180000},
         {"song_id": "sim:2", "title": "Second made-up song", "duration_ms": 200000},
         {"song_id": "sim:3", "title": "Third made-up song", "duration_ms": 160000})


class SimPlayer:
    """A player with three made-up songs, a transport, a volume, and a deck to publish on."""

    def __init__(self, songs=SONGS):
        self.songs = [dict(s) for s in songs]
        self.index = 0
        self.playing = False
        self.position_ms = 0
        self.volume = 0.5
        self._deck: Optional[Deck] = None

    def deck(self, **kw: Any) -> Deck:
        d = Deck({"model": "Sim Player", "fw": "0", "serial": None}, **kw)
        d.register("transport", handler=lambda s, m: self.transport(m["cmd"]))
        d.register("volume", handler=lambda s, m: self.set_volume(m))
        self._deck = d
        return d

    def now_playing(self) -> Dict[str, Any]:
        song = self.songs[self.index]
        return dict(song, origin="sim", player="sim", position_ms=self.position_ms, playing=self.playing)

    def _changed(self) -> None:
        if self._deck is not None:
            self._deck.publish("nowplaying", self.now_playing())

    def play(self) -> None:
        self.playing = True
        self._changed()

    def transport(self, cmd: str) -> None:
        if cmd == "play":
            self.playing = True
        elif cmd == "pause":
            self.playing = False
        elif cmd == "stop":
            self.playing, self.position_ms = False, 0
        elif cmd in ("next", "prev"):
            self.index = (self.index + (1 if cmd == "next" else -1)) % len(self.songs)
            self.position_ms = 0
        self._changed()

    def set_volume(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        if "set" in msg:
            self.volume = float(msg["set"])
        else:
            if self.volume >= 1 and msg["step"] > 0:
                raise DeckError("bad_request", "the volume is already full")
            self.volume = min(1.0, max(0.0, round(self.volume + msg["step"] / 16, 6)))
        return {"t": "ok", "volume": self.volume}


class SimDock:
    """A dock that says hello, subscribes to state and nowplaying, may send transport and volume,
    and keeps every nowplaying it reads."""

    def __init__(self, client: Client, dock: Optional[Dict[str, Any]] = None):
        self.client = client
        self.dock = dict(dock or SIM_DOCK)
        self.nowplaying: List[Dict[str, Any]] = []
        client.on("nowplaying", self.nowplaying.append)

    def hello(self, want=("state", "nowplaying"), can=("transport", "volume")) -> Dict[str, Any]:
        return self.client.hello(self.dock, want=list(want), can=list(can))
