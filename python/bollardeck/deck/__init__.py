# SPDX-License-Identifier: Apache-2.0
"""bollardeck.deck: a minimal deck service and its client, on the bollardeck/1 messages.

A **deck** is the service a device runs so that docks, watches and apps can read what it is doing
and control it (spec/bollardeck.md, Part A). This package is the minimal service: the handshake
(`hello`, `welcome`), the grants and the user's consent, subscriptions to read topics, and the
writes a capability's handler answers, over any transport that carries JSON lines. It is a DRAFT,
like Part A itself: the messages follow bollardeck/1 as drafted, and Bollard v2 will rewrite the
transports and the dock's own fields; the handshake and the grants are expected to stay.

The service:

    from bollardeck import deck

    d = deck.Deck({"model": "Pop Boll Rev B", "fw": "0.3.0", "serial": None})
    d.register("transport", handler=lambda session, msg: player.do(msg["cmd"]))
    d.register("volume", handler=lambda session, msg: player.set_volume(msg))
    server = deck.serve_unix(d, "/run/pb-deckd.sock")          # or deck.pair(d) in one process
    ...
    d.publish("nowplaying", player.now_playing())               # every session that may and asked
    d.approve(session.key, ["stems"])                            # the user said yes on the device

A dock or an app:

    client = deck.connect_unix("/run/pb-deckd.sock")
    welcome = client.hello({"vendor": "Example Labs", "product": "Bass Lean", "vid": 4617, "pid": 49152},
                           want=["state", "nowplaying"], can=["transport"])
    client.on("nowplaying", print)
    client.request("transport", cmd="next")                      # -> {"v": 1, "t": "ok", "re": ...}

Grants. Every capability has a default (CAPABILITIES, from the spec's table 5.4): "granted" ones
are given to any dock that asks; "consent" ones wait until the host calls `approve(key, flags)`,
which the user does on the device. A dock is known by its key (`dock_key`: its vid, pid and the
identity its transport proves, such as a USB serial, a BLE identity, or on a Unix socket the peer's
uid from the kernel, and on Linux its executable too); approvals are kept per key in
`Deck.approved`, a dict the host may persist. An approval is applied only to a session whose
transport gave an identity: the vid and pid a dock states in its hello prove nothing on their own,
so a session with no identity never gets a consent capability. On a Unix socket, an approval covers
every process of that uid (and, on Linux, that executable) that states the same vid and pid. `Deck(consent=fn)` is told of each session with
pending requests, to ask the user. A capability is offered only once it is registered: a device
that has no stems never grants them. Reads are topics (`publish`); writes are message types whose
handler answers them. `volume` and `transport` writes are checked against the `transport` schema
first, and `publish("nowplaying", ...)` against the `nowplaying` schema.

Errors are the spec's codes (ERROR_CODES), as {"t": "error", "re": id, "code", "msg"}; the session
stays open, except after `no_common_api`. A handler that fails is answered `busy` (`bad_request` for
a ValueError or TypeError) and logged. Requests past `rate` per second (the spec's 20 by default)
are answered `rate_limited`, and so are writes past `write_rate` a second from all sessions together. A line is at most `limits["max_line"]` bytes (never above MAX_LINE),
and a number that is not finite (NaN, Infinity) is a bad request. `info` goes to every peer in its
welcome: a host passes "serial": None unless the user chose to share it (spec 5.2).

Slow peers. On a Unix socket each session has a bounded outbox and its own writer, so one dock that
stops reading never holds up `publish` or anyone else: when its outbox is full, or a write takes
longer than SEND_TIMEOUT, it is disconnected. The state topics (COALESCED) keep only their latest
message in an outbox, so a burst of them never fills it. A server takes at most `max_sessions`
connections, and replaces only a stale socket at its path (never a file, never a live deck's).

Callbacks. A client's `on()` callbacks must be quick, and may not call `request()` (RuntimeError, on
every transport): in one process (`pair`) they run on the publisher's own thread.

Nothing here reads a clock or starts a thread except the Unix-socket server and client, which run
one reader thread per connection. Standard library only.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import queue
import select
import socket
import stat
import struct
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from .. import schema as _schema

API = "bollardeck/1"
ENVELOPE_VERSION = 1
MAX_LINE = 65536
RATE = 20.0                 # requests a second a dock may send (spec 4.2), with as many in a burst
WRITE_RATE = 40.0           # writes a second all of a deck's sessions together may send, with as many in a burst
OUTBOX = 256                # messages waiting for one Unix-socket peer before it is disconnected
SEND_TIMEOUT = 5.0          # seconds one write to a Unix-socket peer may take
MAX_SESSIONS = 16           # connections one Unix-socket server takes at once
INBOX = 256                 # messages a Client keeps for `inbox` (the oldest go first)
# Topics that are a state, not an event: a peer's outbox keeps only the latest of each, so a burst of
# them never fills it (spec 4.2: the deck MAY coalesce; it never drops button, remix_status or error).
COALESCED = ("state", "nowplaying", "corpus", "led", "led_ring", "matrix")

log = logging.getLogger("bollardeck.deck")

# The spec's table 5.4: flag -> (direction, default).
CAPABILITIES: Dict[str, Tuple[str, str]] = {
    "state": ("read", "granted"),
    "nowplaying": ("read", "granted"),
    "corpus": ("read", "granted"),
    "beat": ("read", "granted"),
    "led": ("read", "granted"),
    "led_ring": ("read", "granted"),
    "matrix": ("read", "granted"),
    "buttons": ("read", "granted"),
    "stems": ("read", "consent"),
    "volume": ("write", "granted"),
    "transport": ("write", "granted"),
    "light_sync": ("write", "granted"),
    "remix": ("write", "consent"),
    "stem_balance": ("write", "consent"),
    "audio_out": ("write", "granted"),
    "audio_in": ("write", "consent"),
}

# What a physical dock whose hello does not match its header is left with (spec 5.2).
MISMATCH_GRANTS = ("state", "nowplaying")

ERROR_CODES = ("unknown_type", "bad_request", "not_granted", "pending_consent", "rate_limited",
               "no_common_api", "identity_mismatch", "not_found", "corpus_rules", "busy")

# Writes checked against a schema before their handler sees them, and topics before they are sent.
_WRITE_SCHEMAS = {"volume": "transport", "transport": "transport"}
_TOPIC_SCHEMAS = {"nowplaying": "nowplaying"}
# Message types that are the deck's own.
_DECK_TYPES = ("hello", "subscribe", "unsubscribe", "welcome", "grants", "error", "ok")


class DeckError(Exception):
    """A request the deck refuses, with one of ERROR_CODES."""

    def __init__(self, code: str, msg: str = ""):
        if code not in ERROR_CODES:
            raise ValueError("%r is not a bollardeck error code" % (code,))
        super().__init__("%s: %s" % (code, msg) if msg else code)
        self.code = code
        self.msg = msg


# ── framing ──────────────────────────────────────────────────────────────────────────────────

def encode(message: Mapping[str, Any]) -> bytes:
    """One message as a JSON line (`v` added when missing). Raises ValueError past MAX_LINE."""
    body = dict(message)
    body.setdefault("v", ENVELOPE_VERSION)
    line = (json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(line) > MAX_LINE:
        raise ValueError("a bollardeck line is at most %d bytes, not %d" % (MAX_LINE, len(line)))
    return line


def _not_a_number(name: str) -> Any:
    raise DeckError("bad_request", "%s is not a number JSON can carry" % name)


def decode(line: Any, max_line: int = MAX_LINE) -> Dict[str, Any]:
    """One JSON line as a message. Raises DeckError("bad_request") for anything that is not one,
    including a line longer than `max_line` bytes and NaN or Infinity anywhere in it."""
    if isinstance(line, (bytes, bytearray)):
        if len(line) > max_line:
            raise DeckError("bad_request", "the line is longer than %d bytes" % max_line)
        try:
            line = bytes(line).decode("utf-8")
        except UnicodeDecodeError:
            raise DeckError("bad_request", "the line is not UTF-8") from None
    if isinstance(line, str) and len(line.encode("utf-8", "surrogatepass")) > max_line:
        raise DeckError("bad_request", "the line is longer than %d bytes" % max_line)
    try:
        msg = json.loads(line, parse_constant=_not_a_number)
    except DeckError:
        raise
    except (TypeError, ValueError, RecursionError):
        raise DeckError("bad_request", "the line is not JSON") from None
    if not isinstance(msg, dict):
        raise DeckError("bad_request", "a message is a JSON object")
    if msg.get("v") != ENVELOPE_VERSION or isinstance(msg.get("v"), bool):
        raise DeckError("bad_request", "the envelope version is 1")
    if not isinstance(msg.get("t"), str) or not msg["t"]:
        raise DeckError("bad_request", "a message has a type, t")
    if "id" in msg and (not isinstance(msg["id"], int) or isinstance(msg["id"], bool)):
        raise DeckError("bad_request", "id is an integer")
    return msg


def dock_key(dock: Mapping[str, Any], identity: str = "") -> str:
    """How the deck knows a dock across sessions: its vid and pid and the identity its transport
    gives (a USB serial number, a BLE address). A short hash, safe to store and to log."""
    raw = "%s|%s|%s" % (dock.get("vid"), dock.get("pid"), identity or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


# ── the service ──────────────────────────────────────────────────────────────────────────────

class Deck:
    """The deck side. One per device; one Session per connected dock or app."""

    def __init__(self, info: Optional[Mapping[str, Any]] = None, *,
                 consent: Optional[Callable[["Session", List[str]], None]] = None,
                 approved: Optional[Dict[str, List[str]]] = None,
                 limits: Optional[Mapping[str, Any]] = None,
                 rate: float = RATE, write_rate: float = WRITE_RATE, clock: Callable[[], float] = time.monotonic):
        self.info = dict(info or {})
        self.consent = consent
        self.approved: Dict[str, List[str]] = approved if approved is not None else {}
        self.limits = dict(limits or {})
        self.limits["max_line"] = min(int(self.limits.get("max_line") or MAX_LINE), MAX_LINE)
        self.rate = float(rate)
        self.write_rate = float(write_rate)
        self.clock = clock
        self._write_tokens = self.write_rate
        self._write_filled = clock()
        self._caps: Dict[str, Tuple[str, str]] = {}
        self._handlers: Dict[str, Tuple[str, Callable[..., Any]]] = {}    # message type -> (flag, handler)
        self._sessions: List[Session] = []
        self._lock = threading.RLock()
        for flag in ("state", "nowplaying"):         # every deck can say what it is doing
            self.register(flag)

    # ---- capabilities ------------------------------------------------------------------
    def register(self, flag: str, *, direction: Optional[str] = None, default: Optional[str] = None,
                 handler: Optional[Callable[["Session", Dict[str, Any]], Any]] = None,
                 types: Optional[Iterable[str]] = None) -> "Deck":
        """Offer a capability. A flag from CAPABILITIES takes its direction and default from the
        spec unless given; any other flag needs both. A write needs a `handler(session, msg)`,
        called for each message of `types` (default: the flag's own name). It returns None (the
        deck answers ok), a dict (the reply's payload), or raises DeckError."""
        spec = CAPABILITIES.get(flag)
        direction = direction or (spec[0] if spec else None)
        default = default or (spec[1] if spec else None)
        if direction not in ("read", "write") or default not in ("granted", "consent"):
            raise ValueError("%s: a capability is read or write, granted or consent" % flag)
        if direction == "write" and handler is None:
            raise ValueError("%s: a write capability needs a handler" % flag)
        with self._lock:
            names = tuple(types) if types else (flag,)
            if direction == "write":
                for t in names:
                    if t in _DECK_TYPES:
                        raise ValueError("%s: %r is the deck's own message type" % (flag, t))
            self._caps[flag] = (direction, default)
            if direction == "write":
                for t in names:
                    self._handlers[t] = (flag, handler)
        return self

    def _take_write(self) -> bool:
        """One write's worth of the deck-wide budget (`write_rate` a second, all sessions together)."""
        with self._lock:
            now = self.clock()
            self._write_tokens = min(self.write_rate, self._write_tokens + (now - self._write_filled) * self.write_rate)
            self._write_filled = now
            if self._write_tokens < 1:
                return False
            self._write_tokens -= 1
            return True

    def capabilities(self) -> Dict[str, Tuple[str, str]]:
        with self._lock:
            return dict(self._caps)

    # ---- sessions ----------------------------------------------------------------------
    def open(self, send: Callable[[Dict[str, Any]], None], *, identity: str = "",
             header: Optional[Mapping[str, Any]] = None) -> "Session":
        """A new session. `send(message)` delivers one message to the dock. `identity` is what the
        transport knows of the peer (a USB serial, a BLE address); `header` the vid and pid of a
        physical dock's Bollard header, when there is one."""
        s = Session(self, send, identity=identity, header=header)
        with self._lock:
            self._sessions.append(s)
        return s

    def sessions(self) -> List["Session"]:
        with self._lock:
            return [s for s in self._sessions if s.open]

    def _closed(self, s: "Session") -> None:
        with self._lock:
            if s in self._sessions:
                self._sessions.remove(s)

    def publish(self, topic: str, payload: Optional[Mapping[str, Any]] = None) -> int:
        """Send a read topic to every session that is granted it and subscribed. Returns how many.
        A `nowplaying` payload must fit the `nowplaying` schema (ValueError otherwise)."""
        if self._caps.get(topic, ("",))[0] != "read":
            raise ValueError("%s is not a registered read topic" % topic)
        body = dict(payload or {})
        body.pop("v", None)
        body["t"] = topic
        if topic in _TOPIC_SCHEMAS:
            problems = _schema.validate(_TOPIC_SCHEMAS[topic], dict(body, v=ENVELOPE_VERSION))
            if problems:
                raise ValueError("%s: %s" % (topic, "; ".join(str(p) for p in problems[:3])))
        n = 0
        for s in self.sessions():
            if topic in s.subscribed and topic in s.grants:
                s.send(body)
                n += 1
        return n

    # ---- consent -----------------------------------------------------------------------
    def approve(self, key: str, flags: Iterable[str]) -> None:
        """The user approved these consent capabilities for the dock `key`: kept in `approved`,
        and every live session of that dock is sent its new grants."""
        with self._lock:
            have = set(self.approved.get(key, []))
            have.update(f for f in flags if f in self._caps)
            self.approved[key] = sorted(have)
        for s in self.sessions():
            if s.key == key:
                s._regrant()

    def revoke(self, key: str, flags: Optional[Iterable[str]] = None) -> None:
        """Take approvals back (all of them when `flags` is None)."""
        with self._lock:
            have = set(self.approved.get(key, []))
            have = set() if flags is None else have - set(flags)
            if have:
                self.approved[key] = sorted(have)
            else:
                self.approved.pop(key, None)
        for s in self.sessions():
            if s.key == key:
                s._regrant()


class Session:
    """One dock or app talking to a Deck. Feed it with `receive`; it answers through `send`."""

    def __init__(self, deck: Deck, send: Callable[[Dict[str, Any]], None], *, identity: str = "",
                 header: Optional[Mapping[str, Any]] = None):
        self.deck = deck
        self._send = send
        self.identity = str(identity or "")
        self.header = dict(header) if header else None
        self.dock: Optional[Dict[str, Any]] = None
        self.key: Optional[str] = None
        self.asked: List[str] = []            # what the hello wanted and could do, known flags only
        self.grants: List[str] = []
        self.pending: List[str] = []
        self.subscribed: set = set()
        self.mismatch = False
        self.open = True
        self._lock = threading.Lock()
        self._tokens = deck.rate
        self._filled_at = deck.clock()

    @property
    def authenticated(self) -> bool:
        """Did the transport say who the peer is? Only then are the user's approvals applied."""
        return bool(self.identity)

    def send(self, message: Mapping[str, Any]) -> None:
        if not self.open:
            return
        body = dict(message)
        body.setdefault("v", ENVELOPE_VERSION)
        try:
            encode(body)
        except ValueError as exc:                       # an answer JSON cannot carry: say so instead
            log.warning("bollardeck.deck: a %s message could not be sent (%s)", body.get("t"), exc)
            body = {"v": ENVELOPE_VERSION, "t": "error", "code": "busy", "msg": "the answer could not be sent"}
            if "re" in message:
                body["re"] = message["re"]
        with self._lock:
            self._send(body)

    def _take_token(self) -> bool:
        now = self.deck.clock()
        self._tokens = min(self.deck.rate, self._tokens + (now - self._filled_at) * self.deck.rate)
        self._filled_at = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        return True

    def close(self) -> None:
        self.open = False
        self.deck._closed(self)

    def _error(self, re: Any, code: str, msg: str) -> None:
        out: Dict[str, Any] = {"t": "error", "code": code, "msg": msg}
        if re is not None:
            out["re"] = re
        self.send(out)

    def receive_line(self, line: Any) -> None:
        """One JSON line from the dock."""
        try:
            msg = decode(line, self.deck.limits["max_line"])
        except DeckError as exc:
            self._error(None, exc.code, exc.msg)
            return
        self.receive(msg)

    def receive(self, msg: Mapping[str, Any]) -> None:
        """One message from the dock (already decoded)."""
        if not self.open:
            return
        re = msg.get("id")
        t = msg.get("t")
        try:
            if self.dock is not None and not self._take_token():
                raise DeckError("rate_limited", "at most %g requests a second" % self.deck.rate)
            if t == "hello":
                self._hello(msg)
                return
            if self.dock is None:
                raise DeckError("bad_request", "a session opens with hello")
            if t in ("subscribe", "unsubscribe"):
                self._subscribe(msg, t == "subscribe")
                if re is not None:
                    self.send({"t": "ok", "re": re})
                return
            if t not in self.deck._handlers:
                raise DeckError("unknown_type", "the deck does not know %r" % t)
            flag, handler = self.deck._handlers[t]
            self._may(flag)
            if not self.deck._take_write():
                raise DeckError("rate_limited", "the device takes at most %g writes a second" % self.deck.write_rate)
            if t in _WRITE_SCHEMAS:
                problems = _schema.validate(_WRITE_SCHEMAS[t], dict(msg))
                if problems:
                    raise DeckError("bad_request", "; ".join(str(p) for p in problems[:3]))
            try:
                answer = handler(self, dict(msg))
            except DeckError:
                raise
            except Exception as exc:  # noqa: BLE001 - a handler that fails answers, and the session lives on
                log.warning("bollardeck.deck: the %s handler failed (%s: %s)", t, exc.__class__.__name__, exc)
                code = "bad_request" if isinstance(exc, (ValueError, TypeError)) else "busy"
                raise DeckError(code, "the device could not do that") from None
            reply = dict(answer) if isinstance(answer, Mapping) else {}
            reply.setdefault("t", "ok")
            if re is not None:
                reply["re"] = re
            self.send(reply)
        except DeckError as exc:
            self._error(re, exc.code, exc.msg)
            if exc.code == "no_common_api":
                self.close()

    def _may(self, flag: str) -> None:
        if flag in self.grants:
            return
        if flag in self.pending:
            raise DeckError("pending_consent", "%s waits for the user's consent" % flag)
        raise DeckError("not_granted", "%s has not been granted" % flag)

    def _hello(self, msg: Mapping[str, Any]) -> None:
        if self.dock is not None:
            raise DeckError("bad_request", "this session has already said hello")
        api = msg.get("api")
        if not isinstance(api, list) or API not in api:
            raise DeckError("no_common_api", "this deck speaks %s" % API)
        dock = msg.get("dock")
        if not isinstance(dock, dict):
            raise DeckError("bad_request", "hello names the dock")
        lists = []
        for name in ("want", "can"):
            got = msg.get(name, [])
            if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
                raise DeckError("bad_request", "%s is a list of capability flags" % name)
            lists.append(got)
        want, can = lists
        self.dock = dict(dock)
        self.key = dock_key(dock, self.identity)
        caps = self.deck.capabilities()
        self.asked = [f for f in dict.fromkeys(want + can) if f in caps]
        if self.header is not None and (dock.get("vid"), dock.get("pid")) != (self.header.get("vid"), self.header.get("pid")):
            self.mismatch = True              # a notice, with no "re": the hello is still answered by its welcome
            self._error(None, "identity_mismatch", "the hello does not match the dock's header")
        self._regrant(announce=False)
        self.subscribed = {f for f in want if f in self.grants and caps[f][0] == "read"}
        welcome = {"t": "welcome", "api": API, "boll": dict(self.deck.info), "grants": list(self.grants),
                   "pending": list(self.pending), "limits": dict(self.deck.limits)}
        if msg.get("id") is not None:
            welcome["re"] = msg["id"]
        self.send(welcome)
        if self.pending and self.deck.consent is not None:
            self.deck.consent(self, list(self.pending))

    def _regrant(self, announce: bool = True) -> None:
        caps = self.deck.capabilities()
        approved = set(self.deck.approved.get(self.key or "", [])) if self.authenticated else set()
        grants, pending = [], []
        for f in self.asked:
            if f not in caps:
                continue
            if self.mismatch and f not in MISMATCH_GRANTS:
                continue
            if caps[f][1] == "granted" or f in approved:
                grants.append(f)
            else:
                pending.append(f)
        changed = (grants, pending) != (self.grants, self.pending)
        self.grants, self.pending = grants, pending
        self.subscribed &= set(grants)
        if announce and changed:
            self.send({"t": "grants", "grants": list(grants), "pending": list(pending)})

    def _subscribe(self, msg: Mapping[str, Any], on: bool) -> None:
        topics = msg.get("topics")
        if not isinstance(topics, list) or not all(isinstance(x, str) for x in topics):
            raise DeckError("bad_request", "topics is a list of read topics")
        caps = self.deck.capabilities()
        for f in topics:
            if caps.get(f, ("",))[0] != "read":
                raise DeckError("bad_request", "%s is not a read topic of this deck" % f)
            if on:
                self._may(f)
        if on:
            self.subscribed |= set(topics)
        else:
            self.subscribed -= set(topics)


# ── transports ───────────────────────────────────────────────────────────────────────────────

class Client:
    """The dock's or app's side of a session, over any transport: the transport hands it each
    message from the deck with `deliver`, and it sends with the `write` it was given.

    `on(t, fn)` callbacks run on the transport's reader; an exception in one is logged and the
    reader carries on. A callback must not call `request()` (it would wait for an answer only the
    reader it is blocking can deliver): that raises RuntimeError. Messages no callback took and no
    request waited for go to `inbox`, which keeps the newest INBOX of them."""

    def __init__(self, write: Callable[[Dict[str, Any]], None], timeout: float = 5.0):
        self._write = write
        self.timeout = float(timeout)
        self._next = 1
        self._waiting: Dict[int, "queue.Queue[Dict[str, Any]]"] = {}
        self._handlers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self.inbox: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=INBOX)
        self.welcome: Optional[Dict[str, Any]] = None
        self.grants: List[str] = []
        self.pending: List[str] = []
        self._lock = threading.Lock()
        self._reader: Optional[int] = None          # the thread that delivers, when the transport has one
        self._delivering = threading.local()         # set while this thread runs an on() callback

    def deliver(self, msg: Dict[str, Any]) -> None:
        if msg.get("t") in ("welcome", "grants"):
            self.grants = list(msg.get("grants") or [])
            self.pending = list(msg.get("pending") or [])
        re = msg.get("re")
        with self._lock:
            waiter = self._waiting.pop(re, None) if isinstance(re, int) and not isinstance(re, bool) else None
        if waiter is not None:
            waiter.put(msg)
            return
        fns = list(self._handlers.get(msg.get("t"), []))
        for fn in fns:
            self._delivering.on = True
            try:
                fn(msg)
            except Exception as exc:  # noqa: BLE001 - one callback never silences the client
                log.warning("bollardeck.deck: an on(%r) callback failed (%s: %s)", msg.get("t"), exc.__class__.__name__, exc)
            finally:
                self._delivering.on = False
        if fns:
            return
        while True:
            try:
                self.inbox.put_nowait(msg)
                return
            except queue.Full:
                try:
                    self.inbox.get_nowait()             # the oldest goes
                except queue.Empty:
                    pass

    def on(self, t: str, fn: Callable[[Dict[str, Any]], None]) -> None:
        """Call fn(message) for every message of type t (a topic, "grants", "error")."""
        self._handlers.setdefault(t, []).append(fn)

    def request(self, t: str, **fields: Any) -> Dict[str, Any]:
        """Send a request with a fresh id and wait for its reply (ok, error, welcome, or a
        handler's own answer). Raises TimeoutError, or RuntimeError from an on() callback."""
        if getattr(self._delivering, "on", False) or (self._reader is not None and threading.get_ident() == self._reader):
            raise RuntimeError("request() from an on() callback would wait for an answer it is blocking")
        with self._lock:
            rid = self._next
            self._next += 1
            box: "queue.Queue[Dict[str, Any]]" = queue.Queue()
            self._waiting[rid] = box
        self._write(dict(fields, v=ENVELOPE_VERSION, t=t, id=rid))
        try:
            return box.get(timeout=self.timeout)
        except queue.Empty:
            with self._lock:
                self._waiting.pop(rid, None)
            raise TimeoutError("no answer to %s within %.1f s" % (t, self.timeout)) from None

    def hello(self, dock: Mapping[str, Any], want: Iterable[str] = (), can: Iterable[str] = (),
              api: Iterable[str] = (API,)) -> Dict[str, Any]:
        """Open the session. Returns the welcome, or the error that refused it."""
        answer = self.request("hello", api=list(api), dock=dict(dock), want=list(want), can=list(can))
        if answer.get("t") == "welcome":
            self.welcome = answer
        return answer

    def subscribe(self, *topics: str) -> Dict[str, Any]:
        return self.request("subscribe", topics=list(topics))

    def unsubscribe(self, *topics: str) -> Dict[str, Any]:
        return self.request("unsubscribe", topics=list(topics))

    def close(self) -> None:
        pass


def pair(deck: Deck, *, identity: str = "", header: Optional[Mapping[str, Any]] = None,
         timeout: float = 5.0) -> Tuple[Session, Client]:
    """A session and its client in one process, joined directly (the in-process transport).
    Every message still goes through encode() and decode(), as it would on a wire. `identity` is
    what the host knows of the peer; with none, approvals are not applied to it."""
    holder: Dict[str, Session] = {}
    client = Client(lambda m: holder["s"].receive_line(encode(m)), timeout=timeout)
    session = deck.open(lambda m: client.deliver(decode(encode(m))), identity=identity, header=header)
    holder["s"] = session
    return session, client


def _lines(sock: socket.socket, max_line: int = MAX_LINE):
    buf = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                yield line
        if len(buf) > max_line:
            return                                   # a line that never ends: drop the peer


XUCRED_VERSION = 0          # struct xucred's cr_version on macOS and the BSDs
_SAID_NO_EXE = False


def peer_identity(conn: socket.socket) -> str:
    """Who is at the other end of a Unix-domain socket, as the kernel says: "unix:uid=<uid>", and on
    Linux ";exe=<path>" when it can be read (when it cannot, the uid alone: still an identity the
    kernel proved, logged once). "" when the platform does not say, or says it in a layout this code
    does not know (no approvals then)."""
    try:
        if hasattr(socket, "SO_PEERCRED"):                       # Linux: struct ucred {pid, uid, gid}
            pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            who = "unix:uid=%d" % uid
            try:
                who += ";exe=" + os.readlink("/proc/%d/exe" % pid)
            except OSError:                                      # another uid's process, or /proc with hidepid
                global _SAID_NO_EXE
                if not _SAID_NO_EXE:
                    _SAID_NO_EXE = True
                    log.info("bollardeck.deck: a peer's executable cannot be read; it is known by its uid alone")
            return who
        if hasattr(socket, "LOCAL_PEERCRED"):                    # macOS and the BSDs: struct xucred
            raw = conn.getsockopt(0, socket.LOCAL_PEERCRED, 256)
            version, uid = struct.unpack_from("II", raw)
            if version != XUCRED_VERSION:                         # a layout this code does not know: fail closed
                return ""
            return "unix:uid=%d" % uid
    except (OSError, struct.error):
        pass
    return ""


def _clear_stale_socket(path: str) -> None:
    """Make room for a new socket at `path`: nothing there, or a socket nobody answers on (left by a
    deck that stopped), which is removed. Anything else is refused: a file that is not a socket
    (FileExistsError), or a socket a deck is serving on (OSError EADDRINUSE)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(st.st_mode):
        raise FileExistsError(errno.EEXIST, "not a socket; a deck will not replace it", path)
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        probe.connect(path)
        live = True
    except OSError:
        live = False
    finally:
        probe.close()
    if live:
        raise OSError(errno.EADDRINUSE, "a deck is already served on this socket", path)
    os.unlink(path)


class _Outbox:
    """One peer's messages waiting to be written: at most `size`, in order, except that a topic in
    COALESCED (a state, published without "re") keeps only its latest message, in the place its
    first waiting one took. So a burst of now-playing never fills it; replies and events still do."""

    def __init__(self, size: int):
        self.size = int(size)
        self._cond = threading.Condition()
        self._q: "deque[Tuple[str, Any]]" = deque()
        self._latest: Dict[str, bytes] = {}
        self._closed = False

    def put(self, message: Mapping[str, Any]) -> bool:
        """Queue a message (ValueError when JSON cannot carry it). False when the outbox is full."""
        data = encode(message)
        t = message.get("t")
        key = t if t in COALESCED and "re" not in message else None
        with self._cond:
            if self._closed:
                return True
            if key is not None and key in self._latest:
                self._latest[key] = data
                return True
            if len(self._q) >= self.size:
                return False
            if key is not None:
                self._latest[key] = data
                self._q.append(("topic", key))
            else:
                self._q.append(("data", data))
            self._cond.notify()
            return True

    def finish(self) -> None:
        """No more messages: the writer still writes what is queued (bounded by SEND_TIMEOUT per
        write), then stops. A session that ends (no_common_api, the peer's own EOF) says its last
        word this way; `close()` is for a peer that is dropped, and throws the queue away."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def get(self) -> Optional[bytes]:
        """The next bytes to write; None once closed and empty."""
        with self._cond:
            while not self._q and not self._closed:
                self._cond.wait()
            if not self._q:
                return None
            kind, value = self._q.popleft()
            return self._latest.pop(value) if kind == "topic" else value

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._q.clear()
            self._latest.clear()
            self._cond.notify_all()


class UnixServer:
    """A deck served on a Unix-domain socket, one session per connection, at most `max_sessions`
    at once. Each peer has a bounded outbox and a writer of its own. `close()` stops it."""

    def __init__(self, deck: Deck, path: str, mode: int = 0o660, *, max_sessions: int = MAX_SESSIONS,
                 outbox: int = OUTBOX, send_timeout: float = SEND_TIMEOUT):
        self.deck = deck
        self.path = str(path)
        self.max_sessions = int(max_sessions)
        self.outbox = int(outbox)
        self.send_timeout = float(send_timeout)
        _clear_stale_socket(self.path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        os.chmod(self.path, mode)
        self._ino = os.lstat(self.path).st_ino                  # close() removes only this socket
        self._sock.listen(8)
        self._closed = False
        self._lock = threading.Lock()
        self._conns: List[socket.socket] = []
        threading.Thread(target=self._accept, name="bollardeck-deck", daemon=True).start()

    def connections(self) -> int:
        with self._lock:
            return len(self._conns)

    def _accept(self) -> None:
        while not self._closed:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with self._lock:
                full = len(self._conns) >= self.max_sessions
                if not full:
                    self._conns.append(conn)
            if full:
                try:
                    conn.settimeout(1.0)
                    conn.sendall(encode({"t": "error", "code": "busy", "msg": "too many sessions"}))
                except OSError:
                    pass
                _shut(conn)
                continue
            threading.Thread(target=self._serve, args=(conn,), name="bollardeck-deck-session", daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        out = _Outbox(self.outbox)
        holder: Dict[str, Session] = {}

        def drop(why: str) -> None:
            s = holder.get("s")
            if s is not None and s.open:
                log.info("bollardeck.deck: a peer is disconnected (%s)", why)
                s.open = False
            out.close()
            _shut(conn)

        def send(m: Dict[str, Any]) -> None:
            try:
                if not out.put(m):
                    drop("it is not reading")
            except ValueError as exc:
                log.warning("bollardeck.deck: a message could not be encoded (%s)", exc)

        done = threading.Event()

        def writer() -> None:
            try:
                while True:
                    data = out.get()
                    if data is None:
                        return
                    if not _send_within(conn, data, self.send_timeout):
                        drop("a write did not finish in %.1f s" % self.send_timeout)
                        return
            finally:
                done.set()

        session = self.deck.open(send, identity=peer_identity(conn))
        holder["s"] = session
        threading.Thread(target=writer, name="bollardeck-deck-writer", daemon=True).start()
        try:
            for line in _lines(conn, self.deck.limits["max_line"]):
                session.receive_line(line)
                if not session.open:
                    break
        except Exception as exc:  # noqa: BLE001 - one session's failure never reaches the server
            log.warning("bollardeck.deck: a session ended (%s: %s)", exc.__class__.__name__, exc)
        finally:
            session.close()
            out.finish()                                         # what is queued is still written
            if not done.wait(self.send_timeout + 1.0):
                out.close()
            _shut(conn)
            with self._lock:
                if conn in self._conns:
                    self._conns.remove(conn)

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass
        with self._lock:
            conns, self._conns = list(self._conns), []
        for c in conns:
            _shut(c)
        try:
            if os.lstat(self.path).st_ino == self._ino:
                os.unlink(self.path)
        except OSError:
            pass


def _send_within(conn: socket.socket, data: bytes, timeout: float) -> bool:
    """Write all of `data` within `timeout` seconds, without a socket timeout (which would also end
    the session's reads): wait until the socket is writable, then write no more than its low-water
    mark, which never blocks. False when it could not."""
    deadline = time.monotonic() + timeout
    view = memoryview(data)
    try:                                   # select() promises room for this many bytes, so no send blocks
        chunk = max(512, min(conn.getsockopt(socket.SOL_SOCKET, socket.SO_SNDLOWAT), 65536))
    except OSError:
        chunk = 2048
    while view:
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        try:
            _, writable, _ = select.select([], [conn], [], left)
        except (OSError, ValueError):
            return False
        if not writable:
            return False
        try:
            n = conn.send(view[:chunk])
        except (BlockingIOError, InterruptedError):
            continue
        except OSError:
            return False
        view = view[n:]
    return True


def _shut(conn: socket.socket) -> None:
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        conn.close()
    except OSError:
        pass


def serve_unix(deck: Deck, path: str, mode: int = 0o660, **kw: Any) -> UnixServer:
    """Serve `deck` on the Unix-domain socket `path` (replaced if it exists)."""
    return UnixServer(deck, path, mode, **kw)


class UnixClient(Client):
    """A Client connected to a deck's Unix-domain socket."""

    def __init__(self, path: str, timeout: float = 5.0):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(str(path))
        self._wlock = threading.Lock()

        def write(m: Dict[str, Any]) -> None:
            with self._wlock:
                self._sock.sendall(encode(m))

        super().__init__(write, timeout=timeout)
        reader = threading.Thread(target=self._read, name="bollardeck-deck-client", daemon=True)
        reader.start()
        self._reader = reader.ident

    def _read(self) -> None:
        for line in _lines(self._sock):
            try:
                self.deliver(decode(line))
            except DeckError:
                continue
            except Exception as exc:  # noqa: BLE001 - the reader outlives anything a message does
                log.warning("bollardeck.deck: a message could not be delivered (%s: %s)", exc.__class__.__name__, exc)

    def close(self) -> None:
        _shut(self._sock)


def connect_unix(path: str, timeout: float = 5.0) -> UnixClient:
    """A client for the deck served on the Unix-domain socket `path`."""
    return UnixClient(path, timeout=timeout)


__all__ = ["API", "CAPABILITIES", "COALESCED", "ERROR_CODES", "INBOX", "MAX_LINE", "MAX_SESSIONS", "MISMATCH_GRANTS", "OUTBOX", "RATE",
           "SEND_TIMEOUT", "WRITE_RATE", "Client", "Deck", "DeckError", "Session", "UnixClient", "UnixServer", "connect_unix", "decode",
           "dock_key", "encode", "pair", "peer_identity", "serve_unix"]
