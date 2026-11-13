# SPDX-License-Identifier: Apache-2.0
"""bollardeck.deck: the minimal deck service . A sample client and the sim
dock complete a handshake, grants are enforced, consent works, and the same over a Unix socket."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck import deck  # noqa: E402
from bollardeck.deck.sim import SIM_DOCK, SimDock, SimPlayer  # noqa: E402


def ok(reply, re=None):
    return reply.get("t") == "ok" and (re is None or reply.get("re") == re)


class Handshake(unittest.TestCase):
    def setUp(self):
        self.player = SimPlayer()
        self.deck = self.player.deck()
        self.session, self.client = deck.pair(self.deck)
        self.dock = SimDock(self.client)

    def test_the_sim_dock_and_a_player_complete_a_handshake(self):
        welcome = self.dock.hello()
        self.assertEqual(welcome["t"], "welcome")
        self.assertEqual((welcome["api"], welcome["re"]), (deck.API, 1))
        self.assertEqual(welcome["grants"], ["state", "nowplaying", "transport", "volume"])
        self.assertEqual(welcome["pending"], [])
        self.assertEqual(welcome["boll"]["model"], "Sim Player")
        self.assertEqual(welcome["limits"]["max_line"], deck.MAX_LINE)
        self.assertEqual(self.session.subscribed, {"state", "nowplaying"})
        self.assertEqual(self.session.key, deck.dock_key(SIM_DOCK))

    def test_granted_topics_named_in_want_are_sent_from_the_start(self):
        self.dock.hello()
        self.player.play()
        self.assertEqual(self.client.request("transport", cmd="next")["t"], "ok")
        self.assertEqual([m["song_id"] for m in self.dock.nowplaying], ["sim:1", "sim:2"])
        self.assertEqual(self.dock.nowplaying[0]["v"], 1)
        self.assertEqual(self.client.request("unsubscribe", topics=["nowplaying"])["t"], "ok")
        self.player.play()
        self.assertEqual(len(self.dock.nowplaying), 2)
        self.assertTrue(ok(self.client.subscribe("nowplaying")))
        self.player.play()
        self.assertEqual(len(self.dock.nowplaying), 3)

    def test_a_dock_that_did_not_want_a_topic_does_not_get_it(self):
        self.dock.hello(want=["state"], can=[])
        self.assertEqual(self.deck.publish("nowplaying", self.player.now_playing()), 0)
        self.assertEqual(self.dock.nowplaying, [])

    def test_writes_are_checked_and_answered_by_their_handler(self):
        self.dock.hello()
        reply = self.client.request("volume", set=0.25)
        self.assertEqual((reply["t"], reply["volume"]), ("ok", 0.25))
        for bad in (dict(cmd="seek"), dict(cmd="next", extra=1)):
            reply = self.client.request("transport", **bad)
            self.assertEqual((reply["t"], reply["code"]), ("error", "bad_request"), bad)
        reply = self.client.request("volume", set=0.5, step=1)
        self.assertEqual(reply["code"], "bad_request")
        self.player.volume = 1.0
        self.assertEqual(self.client.request("volume", step=1)["code"], "bad_request")    # the handler's own refusal

    def test_a_write_the_dock_did_not_ask_for_is_not_granted(self):
        self.dock.hello(can=[])
        reply = self.client.request("transport", cmd="next")
        self.assertEqual((reply["t"], reply["code"], reply["re"]), ("error", "not_granted", 2))
        self.assertEqual(self.player.index, 0)

    def test_a_capability_the_deck_does_not_offer_is_never_granted(self):
        welcome = self.dock.hello(want=["state", "stems", "made_up"], can=["remix", "transport"])
        self.assertEqual((welcome["grants"], welcome["pending"]), (["state", "transport"], []))
        self.assertEqual(self.client.request("remix", slot=1)["code"], "unknown_type")

    def test_nothing_before_hello_and_only_one_hello(self):
        self.assertEqual(self.client.request("transport", cmd="next")["code"], "bad_request")
        self.assertEqual(self.client.subscribe("state")["code"], "bad_request")
        self.dock.hello()
        self.assertEqual(self.dock.hello()["code"], "bad_request")

    def test_no_common_api_closes_the_session(self):
        reply = self.client.hello(SIM_DOCK, want=["state"], api=["bollardeck/2"])
        self.assertEqual((reply["t"], reply["code"]), ("error", "no_common_api"))
        self.assertFalse(self.session.open)
        self.assertNotIn(self.session, self.deck.sessions())

    def test_an_unknown_type_is_answered_and_the_session_stays_open(self):
        self.dock.hello()
        self.assertEqual(self.client.request("dance", style="waltz")["code"], "unknown_type")
        self.assertTrue(ok(self.client.request("transport", cmd="pause")))

    def test_a_malformed_line_is_a_bad_request(self):
        got = []
        session = self.deck.open(got.append)
        for line in (b"not json", b"[1]", b'{"t":"hello"}', b'{"v":2,"t":"hello"}', b'{"v":1,"t":""}',
                     b'{"v":1,"t":"hello","id":"one"}', b"\xff\xfe", b"{" + b" " * deck.MAX_LINE + b"}"):
            session.receive_line(line)
        self.assertEqual([m["code"] for m in got], ["bad_request"] * 8)
        self.assertTrue(session.open)

    def test_hello_needs_a_dock_and_lists(self):
        for bad in (dict(dock="x"), dict(dock={}, want="state"), dict(dock={}, can=[1])):
            session, client = deck.pair(self.deck)
            fields = dict(api=[deck.API], **bad)
            self.assertEqual(client.request("hello", **fields)["code"], "bad_request", bad)


class Consent(unittest.TestCase):
    def setUp(self):
        self.asked = []
        self.player = SimPlayer()
        self.deck = self.player.deck(consent=lambda session, flags: self.asked.append((session.key, flags)))
        self.deck.register("stems")                                         # read, by consent (the spec's table)
        self.remixed = []
        self.deck.register("remix", handler=lambda s, m: self.remixed.append(m["slot"]))

    def test_consent_capabilities_wait_for_the_user_and_are_kept_per_dock(self):
        session, client = deck.pair(self.deck, identity="usb:serial-1")
        grants = []
        client.on("grants", grants.append)
        welcome = SimDock(client).hello(want=["nowplaying", "stems"], can=["transport", "remix"])
        self.assertEqual(welcome["grants"], ["nowplaying", "transport"])
        self.assertEqual(welcome["pending"], ["stems", "remix"])
        self.assertEqual(self.asked, [(session.key, ["stems", "remix"])])
        self.assertEqual(client.request("remix", slot=1)["code"], "pending_consent")
        self.assertEqual(client.subscribe("stems")["code"], "pending_consent")
        self.assertEqual(self.deck.publish("stems", {"bundle": "x"}), 0)
        self.deck.approve(session.key, ["stems", "remix"])
        self.assertEqual(grants[-1]["grants"], ["nowplaying", "stems", "transport", "remix"])    # in the dock's order
        self.assertEqual(grants[-1]["pending"], [])
        self.assertTrue(ok(client.request("remix", slot=3)))
        self.assertEqual(self.remixed, [3])
        self.assertTrue(ok(client.subscribe("stems")))
        self.assertEqual(self.deck.publish("stems", {"bundle": "x"}), 1)
        # The same dock in a new session has them at once; another dock does not.
        _, again = deck.pair(self.deck, identity="usb:serial-1")
        self.assertEqual(SimDock(again).hello(want=["stems"], can=["remix"])["grants"], ["stems", "remix"])
        _, other = deck.pair(self.deck, identity="usb:serial-1")
        self.assertEqual(SimDock(other, dict(SIM_DOCK, pid=1)).hello(want=["stems"])["pending"], ["stems"])
        # Revoked: told at once, and a subscription to it ends.
        self.deck.revoke(session.key, ["stems"])
        self.assertEqual(grants[-1]["pending"], ["stems"])
        self.assertNotIn("stems", session.subscribed)
        self.assertEqual(self.deck.approved[session.key], ["remix"])
        self.deck.revoke(session.key)
        self.assertNotIn(session.key, self.deck.approved)

    def test_a_dock_whose_hello_does_not_match_its_header_gets_state_and_nowplaying_only(self):
        session, client = deck.pair(self.deck, header={"vid": 1, "pid": 2})
        errors = []
        client.on("error", errors.append)
        welcome = SimDock(client).hello(want=["state", "nowplaying", "stems"], can=["transport"])
        self.assertEqual([e["code"] for e in errors], ["identity_mismatch"])
        self.assertEqual((welcome["grants"], welcome["pending"]), (["state", "nowplaying"], []))
        self.assertEqual(client.request("transport", cmd="next")["code"], "not_granted")
        session, client = deck.pair(self.deck, header={"vid": 4617, "pid": 49152})
        self.assertIn("transport", SimDock(client).hello()["grants"])


class TrustAndLimits(unittest.TestCase):
    """Consent bound to a proven peer, non-finite numbers, failing handlers, slow peers, callbacks, limits."""

    def setUp(self):
        self.player = SimPlayer()
        self.deck = self.player.deck()
        self.deck.register("stems")

    def test_an_approval_needs_an_identity_the_transport_proved(self):
        a, ca = deck.pair(self.deck, identity="unix:uid=501")
        SimDock(ca).hello(want=["stems"])
        self.deck.approve(a.key, ["stems"])
        self.assertIn("stems", a.grants)
        # Another process claiming the same vid and pid: another uid is another dock ...
        b, cb = deck.pair(self.deck, identity="unix:uid=502")
        self.assertEqual(SimDock(cb).hello(want=["stems"])["pending"], ["stems"])
        self.assertNotEqual(a.key, b.key)
        # ... and a session whose transport proved nothing never gets a consent capability.
        c, cc = deck.pair(self.deck)
        self.assertFalse(c.authenticated)
        self.assertEqual(SimDock(cc).hello(want=["stems"])["pending"], ["stems"])
        self.deck.approve(c.key, ["stems"])
        self.assertNotIn("stems", c.grants)

    def test_a_unix_peer_is_known_by_its_uid(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = deck.serve_unix(self.deck, str(pathlib.Path(tmp) / "d.sock"))
            try:
                client = deck.connect_unix(server.path)
                SimDock(client).hello()
                (session,) = self.deck.sessions()
                self.assertTrue(session.identity.startswith("unix:uid=%d" % os.getuid()), session.identity)
                self.assertTrue(session.authenticated)
                client.close()
            finally:
                server.close()

    def test_nan_and_infinity_are_bad_requests(self):
        got = []
        session = self.deck.open(got.append, identity="t")
        session.receive_line(json.dumps({"v": 1, "t": "hello", "id": 1, "api": [deck.API], "dock": SIM_DOCK, "can": ["volume"]}))
        for word in ("NaN", "Infinity", "-Infinity"):
            session.receive_line('{"v":1,"t":"volume","id":2,"set":%s}' % word)
        self.assertEqual([m.get("code") for m in got[1:]], ["bad_request"] * 3)
        self.assertEqual(self.player.volume, 0.5)
        from bollardeck import schema
        for x in (float("nan"), float("inf"), float("-inf")):
            self.assertTrue(schema.validate("transport", {"t": "volume", "set": x}), x)   # built in code, not JSON
            self.assertTrue(schema.validate("nowplaying", {"song_id": "s", "title": "t", "position_ms": 0, "bpm": x}), x)

    def test_a_failing_handler_is_answered_and_the_session_lives_on(self):
        def boom(session, msg):
            if msg["cmd"] == "next":
                raise ZeroDivisionError("made up")
            if msg["cmd"] == "prev":
                raise ValueError("made up")
            return {"t": "ok", "odd": float("nan")}           # an answer JSON cannot carry
        d = deck.Deck()
        d.register("transport", handler=boom)
        _, client = deck.pair(d)
        SimDock(client).hello(can=["transport"])
        self.assertEqual(client.request("transport", cmd="next")["code"], "busy")
        self.assertEqual(client.request("transport", cmd="prev")["code"], "bad_request")
        self.assertEqual(client.request("transport", cmd="play")["code"], "busy")
        self.assertEqual(client.request("subscribe", topics=["state"])["t"], "ok")

    def test_a_peer_that_stops_reading_holds_up_nobody(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = deck.serve_unix(self.deck, str(pathlib.Path(tmp) / "d.sock"), outbox=32, send_timeout=2.0)
            try:
                import socket
                stuck = socket.socket(socket.AF_UNIX)
                stuck.connect(server.path)
                stuck.sendall(deck.encode({"t": "hello", "id": 1, "api": [deck.API], "dock": SIM_DOCK, "want": ["nowplaying"]}))
                good = deck.connect_unix(server.path)
                dock = SimDock(good, dict(SIM_DOCK, pid=9))
                dock.hello()
                big = dict(self.player.now_playing(), title="x" * 20000)
                t0 = time.monotonic()
                for i in range(30):
                    self.deck.publish("nowplaying", dict(big, position_ms=i))
                self.assertLess(time.monotonic() - t0, 3.0, "publish never waits on a peer")
                for _ in range(800):                      # the stuck write gives up after 2 s
                    if len(self.deck.sessions()) == 1 and dock.nowplaying and dock.nowplaying[-1]["position_ms"] == 29:
                        break
                    time.sleep(0.01)
                self.assertEqual(len(self.deck.sessions()), 1, "the peer that does not read is disconnected")
                self.assertEqual(dock.nowplaying[-1]["position_ms"], 29, "the reading peer has the latest state")
                stuck.close()
                good.close()
            finally:
                server.close()

    def test_a_failing_callback_does_not_silence_the_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = deck.serve_unix(self.deck, str(pathlib.Path(tmp) / "d.sock"))
            try:
                client = deck.connect_unix(server.path)
                seen, calls = [], []
                client.on("nowplaying", lambda m: (_ for _ in ()).throw(RuntimeError("made up")))
                client.on("nowplaying", seen.append)
                client.on("grants", lambda m: calls.append(self._try_request(client)))
                SimDock(client).hello()
                for want, step in ((1, self.player.play), (2, lambda: self.player.transport("next"))):
                    step()                               # one at a time: a burst of a state topic coalesces
                    for _ in range(200):
                        if len(seen) >= want:
                            break
                        time.sleep(0.01)
                self.assertEqual(len(seen), 2)
                self.assertEqual(client.inbox.qsize(), 0, "what a callback took is not kept again")
                self.assertEqual(client.request("transport", cmd="pause")["t"], "ok")
                client.close()
            finally:
                server.close()
        c = deck.Client(lambda m: None)
        for i in range(deck.INBOX + 50):
            c.deliver({"v": 1, "t": "state", "n": i})
        self.assertEqual(c.inbox.qsize(), deck.INBOX)
        self.assertEqual(c.inbox.get_nowait()["n"], 50, "the oldest went first")
        c._reader = threading.get_ident()
        with self.assertRaises(RuntimeError):
            c.request("transport", cmd="next")

    @staticmethod
    def _try_request(client):
        try:
            client.request("transport", cmd="next")
        except RuntimeError:
            return "refused"

    def test_limits_rate_and_a_session_cap(self):
        now = [0.0]
        d = deck.Deck(limits={"max_line": 10 ** 9}, rate=5, clock=lambda: now[0])
        self.assertEqual(d.limits["max_line"], deck.MAX_LINE, "never above the module's own")
        d = deck.Deck(limits={"max_line": 400}, rate=5, clock=lambda: now[0])
        d.register("transport", handler=lambda s, m: None)
        got = []
        session = d.open(got.append, identity="t")
        session.receive_line(deck.encode({"t": "hello", "id": 1, "api": [deck.API], "dock": SIM_DOCK, "can": ["transport"]}))
        self.assertEqual(got[0]["limits"]["max_line"], 400)
        session.receive_line(deck.encode({"t": "transport", "id": 2, "cmd": "next", "pad": "x" * 500}))
        self.assertEqual(got[-1]["code"], "bad_request")
        for i in range(8):
            session.receive_line(deck.encode({"t": "transport", "id": 10 + i, "cmd": "next"}))
        codes = [m["t"] if m["t"] == "ok" else m["code"] for m in got[-8:]]
        self.assertEqual(codes, ["ok"] * 5 + ["rate_limited"] * 3)   # a line refused at decode spends nothing
        now[0] += 1.0
        session.receive_line(deck.encode({"t": "transport", "id": 30, "cmd": "next"}))
        self.assertEqual(got[-1]["t"], "ok")
        with tempfile.TemporaryDirectory() as tmp:
            server = deck.serve_unix(self.deck, str(pathlib.Path(tmp) / "d.sock"), max_sessions=2)
            try:
                a, b = deck.connect_unix(server.path), deck.connect_unix(server.path)
                SimDock(a).hello()
                SimDock(b).hello()
                c = deck.connect_unix(server.path, timeout=1)
                for _ in range(100):
                    if not c.inbox.empty():
                        break
                    time.sleep(0.01)
                self.assertEqual(c.inbox.get_nowait()["code"], "busy")
                a.close()
                for _ in range(100):
                    if server.connections() == 1:
                        break
                    time.sleep(0.01)
                self.assertEqual(server.connections(), 1, "a closed connection is let go")
                b.close()
                c.close()
            finally:
                server.close()


class CallbacksSocketsAndBursts(unittest.TestCase):
    """Callbacks never request, only a stale socket is replaced, state topics coalesce, peer credentials."""

    def setUp(self):
        self.player = SimPlayer()
        self.deck = self.player.deck()

    def test_request_from_a_callback_is_refused_in_process_too(self):
        _, client = deck.pair(self.deck)
        outcomes = []

        def callback(m):
            try:
                client.request("transport", cmd="pause")
                outcomes.append("answered")
            except RuntimeError:
                outcomes.append("refused")
        client.on("nowplaying", callback)
        SimDock(client).hello()
        t = threading.Thread(target=self.player.play, daemon=True)
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), "publish returned: no deadlock")
        self.assertEqual(outcomes, ["refused"])
        self.assertEqual(client.request("transport", cmd="pause")["t"], "ok", "and outside a callback it works")

    def test_only_a_stale_socket_is_replaced(self):
        import errno
        import socket
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "d.sock"
            path.write_text("not a socket")
            with self.assertRaises(FileExistsError):
                deck.serve_unix(self.deck, str(path))
            self.assertEqual(path.read_text(), "not a socket")
            path.unlink()
            first = deck.serve_unix(self.deck, str(path))
            try:
                with self.assertRaises(OSError) as caught:
                    deck.serve_unix(self.deck, str(path))           # a live deck is never taken over
                self.assertEqual(caught.exception.errno, errno.EADDRINUSE)
                self.assertEqual(SimDock(deck.connect_unix(str(path))).hello()["t"], "welcome")
            finally:
                first.close()
            self.assertFalse(path.exists())
            stale = socket.socket(socket.AF_UNIX)                   # a socket left by a deck that stopped
            stale.bind(str(path))
            stale.close()
            second = deck.serve_unix(self.deck, str(path))
            path.unlink()                                           # someone else's file appears at the path ...
            path.write_text("theirs")
            second.close()
            self.assertEqual(path.read_text(), "theirs", "... and close() leaves it alone")

    def test_a_burst_of_a_state_topic_never_drops_a_reading_peer(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = deck.serve_unix(self.deck, str(pathlib.Path(tmp) / "d.sock"), outbox=8)
            try:
                dock = SimDock(deck.connect_unix(server.path))
                dock.hello()
                for i in range(400):
                    self.deck.publish("nowplaying", dict(self.player.now_playing(), position_ms=i))
                for _ in range(300):
                    if dock.nowplaying and dock.nowplaying[-1]["position_ms"] == 399:
                        break
                    time.sleep(0.01)
                self.assertEqual(len(self.deck.sessions()), 1, "still connected")
                self.assertEqual(dock.nowplaying[-1]["position_ms"], 399, "with the latest state")
                self.assertLess(len(dock.nowplaying), 400, "the burst was coalesced")
                self.assertEqual(dock.client.request("transport", cmd="next")["t"], "ok", "replies are never coalesced")
            finally:
                server.close()
        box = deck._Outbox(2)
        self.assertTrue(box.put({"t": "nowplaying", "n": 1}))
        self.assertTrue(box.put({"t": "beat", "n": 1}))
        self.assertTrue(box.put({"t": "nowplaying", "n": 2}))       # replaces the waiting one, in its place
        self.assertFalse(box.put({"t": "beat", "n": 2}))            # events are not coalesced: full
        self.assertEqual([json.loads(box.get())["n"] for _ in range(2)], [2, 1])

    def test_peer_credentials_on_both_kernels(self):
        import socket
        import struct
        from unittest import mock

        class Conn:
            def __init__(self, raw):
                self.raw = raw

            def getsockopt(self, *a):
                return self.raw
        # macOS and the BSDs: struct xucred, version 0 only (SO_PEERCRED hidden, as it is on a Mac).
        mac = {k: getattr(socket, k) for k in ("SO_PEERCRED",) if hasattr(socket, k)}
        with mock.patch.dict(socket.__dict__, {"LOCAL_PEERCRED": 1}):
            for k in mac:
                del socket.__dict__[k]
            try:
                self.assertEqual(deck.peer_identity(Conn(struct.pack("IIh", 0, 501, 1) + b"\0" * 64)), "unix:uid=501")
                self.assertEqual(deck.peer_identity(Conn(struct.pack("IIh", 1, 501, 1) + b"\0" * 64)), "", "an unknown layout fails closed")
                self.assertEqual(deck.peer_identity(Conn(b"\0\0")), "", "a short answer fails closed")
            finally:
                socket.__dict__.update(mac)
        # Linux: struct ucred {pid, uid, gid}, and the executable when /proc lets it be read.
        with mock.patch.dict(socket.__dict__, {"SO_PEERCRED": 17}):
            ucred = Conn(struct.pack("3i", 4321, 1000, 1000))
            with mock.patch.object(deck.os, "readlink", return_value="/usr/bin/sim-dock") as rl:
                self.assertEqual(deck.peer_identity(ucred), "unix:uid=1000;exe=/usr/bin/sim-dock")
                rl.assert_called_with("/proc/4321/exe")
            deck._SAID_NO_EXE = False
            with mock.patch.object(deck.os, "readlink", side_effect=PermissionError):
                with self.assertLogs("bollardeck.deck", "INFO") as said:
                    self.assertEqual(deck.peer_identity(ucred), "unix:uid=1000")
                    self.assertEqual(deck.peer_identity(ucred), "unix:uid=1000")
                self.assertEqual(len(said.output), 1, "said once")


class ClosingAndWriteRate(unittest.TestCase):
    """A closing session's last word is written; writes are limited across sessions."""

    def test_a_session_s_last_word_is_still_written(self):
        import socket
        d = SimPlayer().deck()
        with tempfile.TemporaryDirectory() as tmp:
            server = deck.serve_unix(d, str(pathlib.Path(tmp) / "d.sock"))
            try:
                for _ in range(4):
                    peer = socket.socket(socket.AF_UNIX)
                    peer.settimeout(5)
                    peer.connect(server.path)
                    peer.sendall(deck.encode({"t": "hello", "id": 1, "api": ["other/9"], "dock": SIM_DOCK}))
                    got = b""
                    while not got.endswith(b"\n"):
                        chunk = peer.recv(4096)
                        if not chunk:
                            break
                        got += chunk
                    peer.close()
                    self.assertEqual(deck.decode(got.strip())["code"], "no_common_api")
            finally:
                server.close()

    def test_writes_are_limited_across_sessions_too(self):
        now = [0.0]
        player = SimPlayer()
        d = player.deck(rate=100, write_rate=5, clock=lambda: now[0])
        clients = []
        for pid in (1, 2):
            _, c = deck.pair(d)
            SimDock(c, dict(SIM_DOCK, pid=pid)).hello(can=["transport"])
            clients.append(c)
        answers = [clients[i % 2].request("transport", cmd="pause") for i in range(8)]
        self.assertEqual([a["t"] if a["t"] == "ok" else a["code"] for a in answers], ["ok"] * 5 + ["rate_limited"] * 3)
        self.assertEqual(clients[0].subscribe("state")["t"], "ok", "only writes spend the deck's budget")
        now[0] += 1.0
        self.assertEqual(clients[1].request("transport", cmd="play")["t"], "ok")


class Registration(unittest.TestCase):
    def test_what_register_refuses(self):
        d = deck.Deck()
        self.assertEqual(sorted(d.capabilities()), ["nowplaying", "state"])
        with self.assertRaises(ValueError):
            d.register("transport")                                          # a write needs a handler
        with self.assertRaises(ValueError):
            d.register("made_up")                                            # not in the spec: say what it is
        with self.assertRaises(ValueError):
            d.register("mine", direction="write", default="granted", handler=print, types=["hello"])
        d.register("mine", direction="write", default="consent", handler=lambda s, m: {"t": "done"}, types=["mine.do"])
        self.assertEqual(d.capabilities()["mine"], ("write", "consent"))
        with self.assertRaises(ValueError):
            d.publish("mine")
        with self.assertRaises(ValueError):
            d.publish("nowplaying", {"title": "no song_id"})                 # checked against the schema

    def test_framing(self):
        self.assertEqual(deck.encode({"t": "ok", "re": 1}), b'{"t":"ok","re":1,"v":1}\n')
        self.assertEqual(deck.decode(b'{"v":1,"t":"ok"}'), {"v": 1, "t": "ok"})
        with self.assertRaises(ValueError):
            deck.encode({"t": "x", "pad": "y" * deck.MAX_LINE})
        with self.assertRaises(ValueError):
            deck.DeckError("made_up")
        self.assertEqual(len(deck.dock_key({"vid": 1, "pid": 2}, "serial")), 20)
        self.assertNotEqual(deck.dock_key({"vid": 1, "pid": 2}, "a"), deck.dock_key({"vid": 1, "pid": 2}, "b"))


class OverAUnixSocket(unittest.TestCase):
    def test_a_sample_client_and_the_sim_player_over_a_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            player = SimPlayer()
            server = deck.serve_unix(player.deck(), str(pathlib.Path(tmp) / "deck.sock"))
            try:
                a, b = deck.connect_unix(server.path), deck.connect_unix(server.path)
                dock_a, dock_b = SimDock(a), SimDock(b, dict(SIM_DOCK, pid=7))
                self.assertEqual(dock_a.hello()["t"], "welcome")
                self.assertEqual(dock_b.hello(want=["state"])["t"], "welcome")
                self.assertTrue(ok(a.request("transport", cmd="next")))
                for _ in range(100):
                    if dock_a.nowplaying:
                        break
                    time.sleep(0.01)
                self.assertEqual([m["song_id"] for m in dock_a.nowplaying], ["sim:2"])
                self.assertEqual(dock_b.nowplaying, [])
                self.assertEqual(len(player._deck.sessions()), 2)
                a.close()
                for _ in range(100):
                    if len(player._deck.sessions()) == 1:
                        break
                    time.sleep(0.01)
                self.assertEqual(len(player._deck.sessions()), 1)
                b.close()
            finally:
                server.close()
            self.assertFalse(pathlib.Path(server.path).exists())

    def test_the_example_runs(self):
        out = subprocess.run([sys.executable, str(ROOT / "examples" / "deck_client.py")], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("welcome: granted state, nowplaying, transport", out.stdout)
        self.assertIn("now playing: Second made-up song", out.stdout)
        self.assertIn("transport next: ok", out.stdout)


if __name__ == "__main__":
    unittest.main()
