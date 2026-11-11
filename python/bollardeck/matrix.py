# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.matrix: the frame engine of the device's 13 x 8 LED matrix and its three RGB LEDs.

The Boll carries 104 blue LEDs, 13 wide and 8 high, and three RGB LEDs it may use: LED1, LED3 and
LED4. This module makes the frames for them. It is a pure engine: every frame is a function of
its arguments, with no clock, no socket and no hardware, and anything random is a hash of the
song or segment id. The device sends these frames to its matrix; `js/bollardeck.matrix.js` is the
same engine for a web page, and `conformance/matrix/` holds inputs with the frame both must make,
byte for byte.

    from bollardeck import matrix

    frame = matrix.glyph_frame("boot", 120)
    frame.to_bytes()              # the 113 bytes that go to the device
    print(matrix.to_ascii(frame)) # eight lines of 13 characters, for a terminal or a test

**A frame** is a `MatrixFrame`:

    frame.pixels      104 bytes, row-major (row 0 at the top, 13 columns), each 0 to 255
    frame.rgb         ((r, g, b) LED1, (r, g, b) LED3, (r, g, b) LED4), each 0 to 255
    frame.to_bytes()  the 113-byte wire form: the pixels, then the three RGB triples
    frame.hex()       the same as 226 hex digits, the form the vector files use
    frame.lit()       how many pixels are on;  frame.total()  the sum of all pixels
    frame.at(x, y)    one pixel;  frame.ascii()  the same as to_ascii(frame)

`MatrixFrame.from_bytes(raw)` and `from_hex(text)` read a wire frame back (ValueError when it is
not 113 bytes); `to_hex(frame)` is `frame.hex()`. Two frames are equal when their bytes are.

**The frame functions.** Each has a short name too, the name the vector files and the JavaScript
binding use: `film`, `playback`, `idle`, `corpus`, `glyph`, `dj`, `text`, `premiere`, `tone`.

    film_frame(song, t_ms, calm=False)
        The making-of film at film time t_ms. song is a mapping with "drama": {"shots": [...]},
        "song_id" (or "title") and "bpm". Each shot has "kind", "duration_ms" and, by kind,
        "actors", "data", "title" and "movement". A kind the engine does not know sparkles.
        A song with no shots gives the idle heart.
    playback_frame(song, pos_s, calm=False)
        Playback at pos_s seconds: 13 level bars from song["notes"], each
        [start s, length s, channel 1 to 16, pitch, velocity], kick and snare flashes from
        channel 10, and the progress of the current part (song["parts"]: "t0", "t1") or of
        song["duration"] on the bottom row. "bpm" times the pulse.
    idle_frame(t_ms, calm=False, temperament=None)
        The breathing heart. temperament is an optional mapping: "shape" ("breath", "pulse",
        "flicker", "tide" or "sparkle"), "period" in ms, "floor", "span" and "rgb" for LED1.
        None, an empty mapping or anything that is not a mapping is the plain four-second
        blue breath.
    corpus_frame(t_ms, level=0, bands=None, calm=False)
        A spinning record and a five-bar meter. level is 0 to 255; bands is an optional list of
        up to 16 values 0 to 255 that replaces the meter made from level.
    glyph_frame(name, t_ms, calm=False)
        One of GLYPHS: "boot", "low_battery", "update", "composing", "heart". Any other name
        gives the heart.
    dj_frame(seg, pos_s, t_ms=0, calm=False)
        DJ mode, pos_s seconds into the mix segment seg: two beat-matched platters, the
        crossfader, the key, the judges, the riser and the drop. seg is a mapping with "id",
        "tempo", "duration", "decks", "layers", "notes", "fx", "show" and "key"; the comment
        above dj_frame says what each row shows. t_ms is the scene clock, used for twinkles.
    text_frame(text, t_ms, loop=True, priority="pairing", ttl_ms=None, calm=False)
        Text in a 5 x 7 font, t_ms after it appeared: centred when it fits, scrolled otherwise
        (again and again when loop is true). priority picks the LED colour ("pairing", "jam",
        "premiere" or "notice"). With ttl_ms the bottom row drains as the time runs out.
    premiere_frame(number, t_ms, opened=False, calm=False, tier="")
        The box of series `number` waiting to be opened (a loop of PREMIERE_PERIOD_MS), or,
        with opened true, the lid flying off and a burst (one shot of PREMIERE_OPEN_MS). tier
        ("common", "uncommon", "rare", "epic", "legendary", "secret") colours LED3.
    tone_frame(frame, tone)
        A brightness curve and a tint on any frame. tone is a mapping: "lut" (256 values, the
        new value of each pixel level), "mix" (0 to 256) and "tint" ([r, g, b]). None, an
        empty mapping or anything that is not a mapping returns the frame unchanged.

`calm=True` on any of them is reduced motion: shots hold still, no flashes, no breathing.

**Helpers.** `to_ascii(frame, rgb=False)` draws a frame as text ('.' is off, then `: - + * #`
brighter; with rgb a ninth line gives the three LEDs as #rrggbb). `str_seed(text)` is the 32-bit
hash everything random comes from, and `song_seed(song)` is that hash of a song's id or title.
`film_reel(song)` returns (the shots, each shot's start in ms, the total in ms).
`dj_beat(seg, pos_s)` is the beats since a segment began, `dj_crossfader(seg, pos_s)` is where
its crossfader stands (0 is deck A, 1 is deck B) and `dj_camelot(key)` reads a key such as "8A"
as (8, "A"), or (0, "") for anything else. `text_pass_ms(text)` is how long one pass of
`text_frame` takes.

**Loose input.** Songs and segments come from files and from other programs, so the engine
reads them loosely and does not raise for a malformed one: a number may be written as a string
("12", " 3.5 ", "1_000", as Python's float() reads it), and a member of the wrong type is read as
absent. Where the vectors say `tolerant` they pin exactly that. The song, segment, temperament
or tone itself should be a mapping.

The arithmetic is kept to what IEEE doubles do the same way in every language: + - * / floor
sqrt and 32-bit integer hashing. There is no round(), no library sine (a fixed polynomial
instead) and no float modulo. An implementation in another language can match every byte.

The hardware shows fewer grey levels than the 0 to 255 a frame carries (about six: off, four
dims, full). The device's firmware lifts every value of 8 or more into the visible range, so
faint pixels stay faint and do not vanish; a browser draws the full range.

This module holds no state a caller can see and starts nothing. Showing text over whatever the
matrix is doing, with priorities and time limits, is the device process's business and is not
here. Standard library only.
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "W", "H", "N", "FRAME_BYTES", "TICK_MS", "PALETTE", "COLS", "GLYPHS", "PRIORITIES",
    "PREMIERE_PERIOD_MS", "PREMIERE_OPEN_MS",
    "MatrixFrame", "to_ascii", "to_hex", "from_hex",
    "str_seed", "song_seed", "film_reel", "dj_beat", "dj_crossfader", "dj_camelot", "text_pass_ms",
    "film_frame", "playback_frame", "idle_frame", "corpus_frame", "glyph_frame", "dj_frame", "text_frame",
    "premiere_frame", "tone_frame",
    "film", "playback", "idle", "corpus", "glyph", "dj", "text", "premiere", "tone",
]

W, H = 13, 8
N = W * H
TICK_MS = 90                       # the animation tick: twinkles and blinks step once per tick
FRAME_BYTES = N + 9
M32 = 0xFFFFFFFF
PI = 3.141592653589793
TAU = 6.283185307179586

# The colour of each of the 16 channels, as RGB.
PALETTE: Dict[int, Tuple[int, int, int]] = {
    1: (0xFF, 0x2A, 0x85), 2: (0xFF, 0x77, 0xFF), 3: (0x00, 0x55, 0xFF), 4: (0x00, 0xE5, 0xFF),
    5: (0xFF, 0xE6, 0x00), 6: (0xFF, 0x55, 0x00), 7: (0xB3, 0x66, 0xFF), 8: (0xFF, 0xCC, 0x00),
    9: (0x33, 0xFF, 0xCC), 10: (0xFF, 0xFF, 0xFF), 11: (0xFF, 0x88, 0x44), 12: (0x44, 0xFF, 0x66),
    13: (0x77, 0x88, 0xFF), 14: (0xFF, 0xAA, 0x33), 15: (0x00, 0xFF, 0xAA), 16: (0xFF, 0x00, 0x44),
}

# The 13 columns of the level display, left to right, from the 16 channels: bass, drums, keys,
# organ, clean and fuzz guitar, the lead in the middle, harmony, then strings+pads,
# brass+woodwinds, mallets+plucks, the arp and foley.
COLS: Tuple[Tuple[int, ...], ...] = ((3,), (10,), (4,), (11,), (5,), (6,), (1,), (2,), (7, 13), (8, 12),
                                     (9, 14), (15,), (16,))
CH_COL: Dict[int, int] = {ch: c for c, group in enumerate(COLS) for ch in group}
KICK = (35, 36)
SNARE = (37, 38, 39, 40)
JUDGE_THRESHOLDS = (0.78, 0.72, 0.74, 0.75, 0.72, 0.70, 0.78)   # the score each of the seven judges asks for

KIND_RGB: Dict[str, Tuple[int, int, int]] = {
    "JAM": (0, 120, 255), "VOTE": (255, 190, 0), "LOCK": (0, 255, 90), "DUEL": (255, 42, 133),
    "TRIBUNAL": (255, 120, 0), "CROSS": (255, 30, 40), "LIBRARY": (255, 160, 60),
    "MUTATION": (179, 102, 255), "LEITMOTIF": (255, 42, 133), "TITLE_CARD": (200, 200, 255),
    "MOVEMENT_CARD": (255, 210, 63), "PAN": (0, 229, 255), "CREDITS": (220, 220, 255),
    "INTERMISSION": (200, 0, 30), "OVERDUB": (180, 100, 255),
}
DEFAULT_RGB = (120, 120, 255)

# 3x5 font: each entry is the character and five rows, bit 4 = left column.
FONT_SRC = ("A25755B65656C34443D65556E74647F74644G34553H55755I72227J11152K55655L44447M57755"
            "N65555O25552P65644Q25563R65655S34216T72222U55557V55552W55775X55255Y55222Z71247"
            "075557126227261247361216455711574616634757771122875757975716"
            ".00002,00024:02020!22202?61202-00700'22000/11244&25253+02720#57575(12221)42224*05250")
FONT: Dict[str, Tuple[int, ...]] = {FONT_SRC[i]: tuple(int(c) for c in FONT_SRC[i + 1:i + 6])
                                    for i in range(0, len(FONT_SRC), 6)}

HEART = ((3, 1), (4, 1), (8, 1), (9, 1),
         (2, 2), (3, 2), (4, 2), (5, 2), (7, 2), (8, 2), (9, 2), (10, 2),
         (2, 3), (3, 3), (4, 3), (5, 3), (6, 3), (7, 3), (8, 3), (9, 3), (10, 3),
         (3, 4), (4, 4), (5, 4), (6, 4), (7, 4), (8, 4), (9, 4),
         (4, 5), (5, 5), (6, 5), (7, 5), (8, 5),
         (5, 6), (6, 6), (7, 6),
         (6, 7))
CHECK = ((2, 4), (3, 5), (4, 6), (5, 5), (6, 4), (7, 3), (8, 2), (9, 1), (10, 0))
FIGURE = ((1, 0), (0, 1), (1, 1), (2, 1), (1, 2), (0, 3), (2, 3), (0, 4), (2, 4))
NOTE_GLYPH = ((2, 0), (2, 1), (2, 2), (2, 3), (0, 3), (1, 3), (0, 4), (1, 4))
DEFAULT_TEAMS = ((1, 3, 5, 10), (2, 4, 8, 12), (6, 7, 11, 15), (9, 13, 14, 16))
GLYPHS = ("boot", "low_battery", "update", "composing", "heart")


# ── frames ───────────────────────────────────────────────────────────────────────────────

class MatrixFrame:
    """104 greyscale pixels (row-major, 13 wide) and the three usable RGB LEDs."""

    __slots__ = ("pixels", "rgb")

    def __init__(self, pixels: Sequence[int], rgb: Sequence[Sequence[int]] = ((0, 0, 0),) * 3):
        self.pixels = bytes(pixels)
        if len(self.pixels) != N:
            raise ValueError(f"a matrix frame has {N} pixels, not {len(self.pixels)}")
        self.rgb: Tuple[Tuple[int, int, int], ...] = tuple(
            (int(t[0]) & 255, int(t[1]) & 255, int(t[2]) & 255) for t in list(rgb)[:3])
        if len(self.rgb) != 3:
            raise ValueError("a matrix frame carries three RGB LEDs (LED1, LED3, LED4)")

    def to_bytes(self) -> bytes:
        return self.pixels + bytes(c for t in self.rgb for c in t)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "MatrixFrame":
        if len(raw) != FRAME_BYTES:
            raise ValueError(f"a wire frame is {FRAME_BYTES} bytes")
        r = raw[N:]
        return cls(raw[:N], ((r[0], r[1], r[2]), (r[3], r[4], r[5]), (r[6], r[7], r[8])))

    def hex(self) -> str:
        return self.to_bytes().hex()

    def lit(self) -> int:
        return sum(1 for v in self.pixels if v)

    def total(self) -> int:
        return sum(self.pixels)

    def at(self, x: int, y: int) -> int:
        return self.pixels[y * W + x]

    def ascii(self) -> str:
        return to_ascii(self)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MatrixFrame) and self.to_bytes() == other.to_bytes()

    def __hash__(self) -> int:
        return hash(self.to_bytes())

    def __repr__(self) -> str:
        return f"MatrixFrame(lit={self.lit()}, rgb={self.rgb})"


RAMP = ".:-+*#"


def to_ascii(frame: MatrixFrame, rgb: bool = False) -> str:
    """Eight lines of 13 characters: '.' off, then : - + * # brighter. For tests and docs."""
    rows = []
    for y in range(H):
        row = ""
        for x in range(W):
            v = frame.pixels[y * W + x]
            row += RAMP[0] if v == 0 else RAMP[1 + math.floor((v - 1) * 5 / 255)]
        rows.append(row)
    if rgb:
        rows.append(" ".join("#%02x%02x%02x" % t for t in frame.rgb))
    return "\n".join(rows)


# ── deterministic helpers (mirrored one for one in js/bollardeck.matrix.js) ──────────────

def _mix(x: int) -> int:
    x &= M32
    x ^= x >> 16
    x = (x * 0x7FEB352D) & M32
    x ^= x >> 15
    x = (x * 0x846CA68B) & M32
    x ^= x >> 16
    return x


def _h(*vals: int) -> int:
    h = 0x811C9DC5
    for v in vals:
        h = ((h ^ (int(v) & M32)) * 0x01000193) & M32
    return _mix(h)


def str_seed(s: str) -> int:
    """The 32-bit hash of a string's UTF-8 bytes: the seed of everything random in a frame."""
    h = 0x811C9DC5
    for b in str(s).encode("utf-8", "replace"):
        h = ((h ^ b) * 0x01000193) & M32
    return _mix(h)


def song_seed(song: Dict[str, Any]) -> int:
    """str_seed of the song's "song_id", or of its "title" when it has no id."""
    return str_seed(song.get("song_id") or song.get("title") or "")


def _num(v: Any, d: float = 0) -> float:
    if v is None or v == "" or isinstance(v, (list, dict)):
        return d
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    if x != x or x in (float("inf"), float("-inf")):
        return d
    return v if isinstance(v, int) and not isinstance(v, bool) else x


def _int(v: Any) -> int:
    return math.floor(_num(v, 0))


def _obj(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _mod(a: float, n: float) -> float:
    return a - n * math.floor(a / n)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _clamp01(x: float) -> float:
    return 0 if x < 0 else (1 if x > 1 else x)


def _smooth(x: float) -> float:
    x = _clamp01(x)
    return x * x * (3 - 2 * x)


def _sin(x: float) -> float:
    x = x - TAU * math.floor(x / TAU + 0.5)
    if x > PI / 2:
        x = PI - x
    elif x < -PI / 2:
        x = -PI - x
    x2 = x * x
    return x * (1 + x2 * (-1 / 6 + x2 * (1 / 120 + x2 * (-1 / 5040 + x2 * (1 / 362880)))))


def _cos(x: float) -> float:
    return _sin(x + PI / 2)


def _breath(t: float, period: float) -> float:
    p = _mod(t, period)
    half = period / 2
    return _smooth(p / half if p < half else (period - p) / half)


def _scale(rgb: Sequence[int], v: float) -> Tuple[int, int, int]:
    v = _clamp(v, 0, 255)
    return (math.floor(rgb[0] * v / 255), math.floor(rgb[1] * v / 255), math.floor(rgb[2] * v / 255))


def _px(buf: List[int], x: float, y: float, v: float) -> None:
    x = math.floor(x)
    y = math.floor(y)
    if v <= 0 or x < 0 or x >= W or y < 0 or y >= H:
        return
    v = math.floor(v)
    if v > 255:
        v = 255
    i = y * W + x
    if v > buf[i]:
        buf[i] = v


def _asc(s: Any) -> str:
    out = []
    for ch in str(s or ""):
        o = ord(ch)
        if 97 <= o <= 122:
            ch = chr(o - 32)
        if ch in FONT:
            out.append(ch)
        elif ch == "…":
            out.append("...")
        elif ch in ("·", "–", "—"):
            out.append("-")
        else:
            out.append(" ")
    return "".join(out).strip(" ")


def _text(buf: List[int], s: str, x0: float, y0: float, v: float) -> None:
    for i, ch in enumerate(s):
        g = FONT.get(ch)
        if not g:
            continue
        for r in range(5):
            bits = g[r]
            for c in range(3):
                if bits & (4 >> c):
                    _px(buf, x0 + i * 4 + c, y0 + r, v)


def _scroll(buf: List[int], s: str, lt: float, dur: float, y0: float, v: float,
            min_pps: float = 12, max_pps: float = 36) -> None:
    """Scroll s right to left within the shot: whole if it fits at max_pps, looped if short."""
    if not s:
        return
    dur = max(1, dur)
    travel = W + len(s) * 4 - 1
    if travel * 1000 / dur > max_pps:
        max_len = math.floor((math.floor(dur * max_pps / 1000) - W + 1) / 4)
        s = s[:max(1, max_len)]
        travel = W + len(s) * 4 - 1
    if travel * 1000 / dur < min_pps:
        off = _mod(math.floor(lt * min_pps / 1000), travel)
    else:
        off = math.floor(lt * travel / dur)
    _text(buf, s, W - off, y0, v)


def _sprite(buf: List[int], pts: Sequence[Tuple[int, int]], x0: float, y0: float, v: float) -> None:
    for p in pts:
        _px(buf, x0 + p[0], y0 + p[1], v)


def _first_char(s: str) -> str:
    for ch in s:
        if ch != " ":
            return ch
    return "?"


def _notes2(v: Any) -> List[List[int]]:
    out = []
    for n in _list(v):
        if isinstance(n, list) and len(n) >= 2:
            out.append([_int(n[0]), _int(n[1])])
    return out


def _pal(ch: int) -> Tuple[int, int, int]:
    return PALETTE.get(ch, DEFAULT_RGB)


# ── the film: one renderer per shot kind ───────────────────────────────────────────────────
# Each draws into buf at local time lt of a shot lasting dur ms and returns (LED3, LED4) and
# optionally an LED1 override. cx carries the seed, the bpm, the film tick and the beat.

def _r_jam(buf, shot, lt, dur, cx):
    a = _obj(shot.get("actors"))
    chans = [_int(c) for c in _list(a.get("channels"))]
    if not chans:
        chans = list(range(1, 17))
    study = _int(a.get("study"))
    benched = [_int(c) for c in _list(a.get("benched"))]
    bi = cx["beat_i"]
    ph = cx["beat_ph"]
    for c in range(W):
        group = COLS[c]
        on = [ch for ch in group if ch in chans]
        if on:
            target = 3 + _h(cx["seed"], 11, on[0], bi) % 5
            if bi % 4 == 0:
                target += 1
            hgt = _clamp(target - math.floor(ph * 3), 1, 8)
            for k in range(hgt):
                _px(buf, c, 7 - k, 255 if k == hgt - 1 else 150)
        elif study in group:
            if math.floor(cx["tick"] / 6) % 2 == 0:
                _px(buf, c, 0, 90)
        elif [ch for ch in group if ch in benched]:
            _px(buf, c, 7, 40)
    c3 = chans[0]
    c4 = chans[1] if len(chans) > 1 else chans[0]
    return _scale(_pal(c3), 200), _scale(_pal(c4), 120 + math.floor(135 * (1 - ph)))


def _r_vote(buf, shot, lt, dur, cx):
    d = _obj(shot.get("data"))
    scores = [_num(x, 0) for x in _list(d.get("scores"))][:7]
    while len(scores) < 7:
        scores.append(0)
    lamps = [_int(x) for x in _list(d.get("lamps"))][:7]
    while len(lamps) < 7:
        lamps.append(0)
    if not [s for s in scores if s > 0]:
        scores = [JUDGE_THRESHOLDS[j] + 0.08 if lamps[j] else JUDGE_THRESHOLDS[j] - 0.22 for j in range(7)]
    rise = _smooth(lt / max(1, dur * 0.45))
    verdict = lt >= dur * 0.55
    yes = 0
    for j in range(7):
        x = 2 * j
        ty = 8 - math.floor(JUDGE_THRESHOLDS[j] * 8 + 0.5)
        _px(buf, x, ty, 70)
        if j < 6:
            _px(buf, x + 1, ty, 45)
        hgt = math.floor(_clamp01(scores[j]) * 8 * rise + 0.5)
        val = 160
        if lamps[j]:
            yes += 1
        if verdict:
            val = 255 if lamps[j] else (90 if (cx["calm"] or cx["tick"] % 4 < 2) else 40)
        for k in range(hgt):
            _px(buf, x, 7 - k, val if k == hgt - 1 else val * 0.7)
    return _scale((0, 255, 90), yes * 36), _scale((255, 30, 40), (7 - yes) * 36)


def _r_lock(buf, shot, lt, dur, cx):
    if lt < 400:
        r = lt / 400 * 8
        fade = 255 - lt / 400 * 120
        for y in range(H):
            for x in range(W):
                dx2 = 2 * x - 12
                dy2 = 2 * y - 7
                dist = math.sqrt(dx2 * dx2 + dy2 * dy2) / 2
                if abs(dist - r) < 0.75:
                    _px(buf, x, y, fade)
    if lt >= 250:
        n = math.floor((lt - 250) / 45) + 1
        for k in range(len(CHECK)):
            if k < n:
                _px(buf, CHECK[k][0], CHECK[k][1], 255)
                _px(buf, CHECK[k][0], CHECK[k][1] + 1, 70)
        if n > len(CHECK) and not cx["calm"]:
            for j in range(4):
                hh = _h(cx["seed"], 31, j, math.floor(cx["tick"] / 2))
                if hh % 3 == 0:
                    _px(buf, (hh >> 4) % W, (hh >> 8) % H, 140)
    return _scale((0, 255, 90), 255), _scale((0, 255, 90), 140)


def _r_duel(buf, shot, lt, dur, cx):
    a = _obj(shot.get("actors"))
    d = _obj(shot.get("data"))
    lead = _int(a.get("lead")) or 1
    rival = _int(a.get("rival")) or 2
    ln = _notes2(d.get("lead_notes"))
    rn = _notes2(d.get("rival_notes"))
    winner = _int(d.get("winner"))
    q = dur / 4
    end = lt >= dur * 0.82
    k = min(3, math.floor(lt / q))
    pt = lt - k * q
    lead_playing = k % 2 == 0
    hop_l = 0
    hop_r = 0
    if not end:
        now = ln if lead_playing else rn
        if now:
            lo = min(n[1] for n in now)
            hi = max(n[1] for n in now)
            for n in now:
                nt = n[0] / 32 * q * 0.7
                age = pt - nt
                if age < 0 or age >= 700:
                    continue
                y = 6 - math.floor((n[1] - lo) * 5 / max(1, hi - lo))
                step = math.floor(age / 100)
                x = 3 + step if lead_playing else 9 - step
                _px(buf, x, y, 255)
                if step > 0:
                    _px(buf, x - 1 if lead_playing else x + 1, y, 90)
                if age < 120:
                    if lead_playing:
                        hop_l = 1
                    else:
                        hop_r = 1
    val_l = 220 if lead_playing else 140
    val_r = 140 if lead_playing else 220
    if end:
        win_l = winner == lead
        blink = cx["calm"] or cx["tick"] % 4 < 2
        val_l = (255 if blink else 160) if win_l else 50
        val_r = 50 if win_l else (255 if blink else 160)
    _sprite(buf, FIGURE, 0, 3 - hop_l, val_l)
    _sprite(buf, FIGURE, 10, 3 - hop_r, val_r)
    return _scale(_pal(lead), val_l), _scale(_pal(rival), val_r)


def _r_tribunal(buf, shot, lt, dur, cx):
    d = _obj(shot.get("data"))
    ang = 0.6
    hit = -1
    last = 0
    for f in (0.25, 0.47, 0.69):
        ts = dur * f
        last = ts
        if ts - 160 <= lt < ts:
            ang = 0.6 * (ts - lt) / 160
        elif ts <= lt < ts + 140:
            ang = 0
        elif ts + 140 <= lt < ts + 400:
            ang = 0.6 * (lt - ts - 140) / 260
        if 0 <= lt - ts < 250:
            hit = lt - ts
    ca = _cos(ang)
    sa = _sin(ang)
    for y in range(H):
        for x in range(W):
            vx = x - 1
            vy = y - 4
            s = vx * ca - vy * sa
            perp = vx * sa + vy * ca
            if 7 - 1 <= s <= 7 + 1 and -2 <= perp <= 2:
                _px(buf, x, y, 240)
            elif 0 <= s <= 6 and -0.5 <= perp <= 0.5:
                _px(buf, x, y, 170)
    for x in range(6, 11):
        _px(buf, x, 7, 255 if hit >= 0 else 110)
    if hit >= 0 and not cx["calm"]:
        for k in range(1, 4):
            if hit >= (k - 1) * 60:
                _px(buf, 6 - k, 7, 200 - k * 50)
                _px(buf, 10 + k, 7, 200 - k * 50)
    lock = str(d.get("majority") or "") == "LOCK"
    if lt >= last + 300 and (cx["calm"] or cx["tick"] % 4 < 3):
        pts = ((0, 1), (1, 2), (2, 1), (3, 0)) if lock else ((0, 0), (2, 0), (1, 1), (0, 2), (2, 2))
        _sprite(buf, pts, 0, 0, 255)
    return _scale((255, 210, 63), 220 if hit >= 0 else 90), _scale((0, 255, 90) if lock else (255, 30, 40), 150)


def _r_cross(buf, shot, lt, dur, cx):
    a = _obj(shot.get("actors"))
    d = _obj(shot.get("data"))
    musician = _int(a.get("musician")) or 1
    benched = str(d.get("verdict") or "") == "BENCHED"
    qd = dur * 0.78 / 3
    for x in range(4):
        _px(buf, x, 5, 90)
    _sprite(buf, FIGURE, 0, 0, 200)
    mv = 200
    my = 3
    if lt < dur * 0.78:
        i = min(2, math.floor(lt / qd))
        u = (lt - i * qd) / qd
        if u < 0.75:
            _text(buf, "?", 3 + math.floor(u * 5), 1, 220)
        if 0.7 <= u < 0.85:
            mv = 255
    else:
        e = (lt - dur * 0.78) / max(1, dur * 0.22)
        if benched:
            my = 3 + math.floor(_clamp01(e) * 5)
            mv = 200 - _clamp01(e) * 140
        elif cx["calm"] or cx["tick"] % 4 < 2:
            _text(buf, "!", 6, 1, 255)
    _sprite(buf, FIGURE, 10, my, mv)
    return _scale((255, 210, 63), 200), _scale(_pal(musician), mv)


def _r_library(buf, shot, lt, dur, cx):
    a = _obj(shot.get("actors"))
    d = _obj(shot.get("data"))
    w = math.floor(_smooth(lt / max(1, dur * 0.25)) * 5 + 0.5)
    for y in range(2, 7):
        _px(buf, 6, y, 200)
    if w == 0:
        for y in range(2, 7):
            for x in range(4, 9):
                if y in (2, 6) or x in (4, 8):
                    _px(buf, x, y, 150)
    else:
        for y in range(2, 7):
            for x in range(6 - w, 7 + w):
                if x == 6:
                    continue
                if y in (2, 6) or x == 6 - w or x == 6 + w:
                    _px(buf, x, y, 150)
                elif y in (3, 5) and (x + y) % 2 == 0:
                    _px(buf, x, y, 50)
        if w == 5 and lt >= dur * 0.35:
            fp = _mod(lt - dur * 0.35, 1100)
            if fp < 450:
                fx = 11 - math.floor(fp / 450 * 11)
                for y in range(2, 7):
                    _px(buf, fx, y, 230)
    cur16 = _mod(math.floor(cx["t"] * cx["bpm"] / 15000), 16)
    for st in [_int(s) for s in _list(d.get("steps"))][:8]:
        _px(buf, math.floor(_mod(st, 16) * 13 / 16), 7, 255 if _mod(st, 16) == cur16 else 110)
    musician = _int(a.get("musician")) or 1
    return _scale(_pal(musician), 200), _scale((255, 160, 60), 120)


def _r_mutation(buf, shot, lt, dur, cx):
    a = _obj(shot.get("actors"))
    judge = str(a.get("who") or "") == "judge"
    ch = 17 + _int(a.get("judge")) if judge else (_int(a.get("channel")) or 1)
    oc = _first_char(_asc(a.get("old")))
    nc = _first_char(_asc(a.get("new")))
    p = lt / max(1, dur)
    tick = cx["tick"]
    dens = _clamp01(1 - abs(p - 0.5) * 2.5)
    if cx["calm"]:
        dens = 0
    letter = oc if p < 0.5 else nc
    drop = dens * 160
    g = FONT.get(letter)
    if g:
        for r in range(5):
            shift = 1 if (dens > 0.2 and _h(cx["seed"], 43, ch, tick, r) % 7 == 0) else 0
            for c in range(3):
                if g[r] & (4 >> c):
                    if drop == 0 or _h(cx["seed"], 41, ch, tick, r * 3 + c) % 256 >= drop:
                        _px(buf, 5 + c + shift, 1 + r, 255 if p >= 0.8 else 200)
    if dens > 0:
        for i in range(N):
            hh = _h(cx["seed"], 47, ch, tick, i)
            if hh % 256 < dens * 90:
                _px(buf, i % W, math.floor(i / W), 40 + (hh >> 8) % 160)
    col = (255, 210, 63) if judge else _pal(ch)
    out3 = _scale(col, 220)
    out4 = _scale(col, 60 + math.floor(dens * 195))
    if cx["calm"]:
        return out3, out4
    return out3, out4, _scale(_pal(1 + _h(cx["seed"], 53, tick) % 16), 200)


def _r_leitmotif(buf, shot, lt, dur, cx):
    d = _obj(shot.get("data"))
    steps = [_int(s) for s in _list(d.get("steps"))][:8]
    rels = [_int(r) for r in _list(d.get("rels"))][:8]
    n = min(len(steps), len(rels))
    if n < 2:
        steps = [0, 2, 4, 6, 8, 10, 12, 14]
        rels = [0, 4, 7, 9, 7, 4, 2, 0]
        n = 8
    xs = [_clamp(math.floor(_mod(steps[i], 16) * 12 / 15), 0, 12) for i in range(n)]
    lo = min(rels[:n])
    hi = max(rels[:n])
    ys = [6 - math.floor((rels[i] - lo) * 5 / max(1, hi - lo)) for i in range(n)]
    cycle = max(1, dur / 2)
    hx = math.floor(_mod(lt, cycle) / cycle * 13)
    for i in range(n):
        _px(buf, xs[i], ys[i], 60)
    for i in range(n - 1):
        x0 = xs[i]
        x1 = xs[i + 1]
        if x0 == x1:
            continue
        for x in range(min(x0, x1), max(x0, x1) + 1):
            if x <= hx:
                y = ys[i] + math.floor((ys[i + 1] - ys[i]) * (x - x0) / (x1 - x0) + 0.5)
                _px(buf, x, y, 110)
    for i in range(n):
        if xs[i] <= hx:
            _px(buf, xs[i], ys[i], 255)
    _px(buf, hx, 0, 60)
    _px(buf, hx, 7, 60)
    return _scale(_pal(1), 220), _scale(_pal(2), 90)


def _stars(buf, cx, count):
    for j in range(count):
        hh = _h(cx["seed"], 61, j)
        tw = (cx["tick"] + j * 3) % 8
        _px(buf, hh % W, 0 if j % 2 == 0 else 7, 200 if tw < 2 else 60)


def _r_title(buf, shot, lt, dur, cx):
    _scroll(buf, _asc(shot.get("title")), lt, dur, 1, 255)
    _stars(buf, cx, 5)
    return _scale(_pal(1), 140), _scale(_pal(2), 140)


def _r_movement(buf, shot, lt, dur, cx):
    d = _obj(shot.get("data"))
    s = _asc(d.get("numeral")) or str(_int(shot.get("movement")))
    tw = len(s) * 4 - 1
    if tw <= W:
        _text(buf, s, math.floor((W - tw) / 2), 1, 255 * min(1, lt / 300))
    else:
        _scroll(buf, s, lt, dur, 1, 255)
    bpm = _num(d.get("bpm"), 0) or cx["bpm"]
    b = lt * bpm / 60000
    bi = math.floor(b)
    m = _mod(bi, 24)
    _px(buf, m if m <= 12 else 24 - m, 7, 220 if b - bi < 0.3 else 90)
    mv = _int(shot.get("movement"))
    return _scale(_pal(1 + _mod(mv, 16)), 180), _scale((255, 210, 63), 120)


def _r_pan(buf, shot, lt, dur, cx):
    a = _obj(shot.get("actors"))
    d = _obj(shot.get("data"))
    teams = [[_int(m) for m in _list(t.get("members"))][:4] for t in _list(a.get("teams")) if isinstance(t, dict)][:4]
    if not teams:
        teams = [list(t) for t in DEFAULT_TEAMS]
    fr = _clamp(_int(d.get("from")), 0, 3)
    to = _clamp(_int(d.get("to")), 0, 3)
    u = _smooth((lt / max(1, dur) - 0.15) / 0.7)
    vx = math.floor((fr * 8 - 3) + (to * 8 - fr * 8) * u + 0.5)
    offs = (1, 2, 4, 5)
    for s in range(len(teams)):
        base = s * 8 - vx
        for y in range(3, 8):
            _px(buf, base, y, 70)
            _px(buf, base + 6, y, 70)
        for x in range(7):
            _px(buf, base + x, 7, 70)
        for m in range(len(teams[s])):
            ch = teams[s][m]
            hop = 1 if (_h(cx["seed"], 71, ch, cx["beat_i"]) % 3 == 0 and cx["beat_ph"] < 0.5) else 0
            x = base + offs[m]
            _px(buf, x, 4 - hop, 255)
            _px(buf, x, 5 - hop, 170)
            _px(buf, x, 6 - hop, 120)
    return _scale((0, 229, 255), 160), _scale((0, 85, 255), 160)


def _r_intermission(buf, shot, lt, dur, cx):
    p = lt / max(1, dur)
    if p < 0.2:
        c = _smooth(p / 0.2)
    elif p > 0.85:
        c = 1 - _smooth((p - 0.85) / 0.15)
    else:
        c = 1
    w = math.floor(c * 7 + 0.5)
    sway = math.floor(lt / 500)
    for x in range(w):
        v = 150 if (x + sway) % 2 == 0 else 85
        for y in range(1, 8):
            _px(buf, x, y, v)
            _px(buf, 12 - x, y, v)
    for x in range(W):
        _px(buf, x, 0, 220)
    return _scale((200, 0, 30), 200), _scale((255, 210, 63), 80)


def _r_credits(buf, shot, lt, dur, cx):
    d = _obj(shot.get("data"))
    parts = []
    for ln in _list(d.get("lines")):
        if isinstance(ln, list) and len(ln) >= 2 and str(ln[0]) in ("h", "g", "t"):
            s = _asc(ln[1])
            if s:
                parts.append(s)
    text = "   ".join(parts) or _asc(shot.get("title")) or "THE END"
    _scroll(buf, text, lt, dur, 1, 255, 12, 40)
    tick = cx["tick"]
    for x in range(W):
        if _mod(x + tick, 4) == 0:
            _px(buf, x, 7, 60)
        if _mod(x - tick, 4) == 0:
            _px(buf, x, 0, 60)
    return _scale((220, 220, 255), 120), _scale((255, 210, 63), 120)


def _r_overdub(buf, shot, lt, dur, cx):
    d = _obj(shot.get("data"))
    props = [p for p in _list(d.get("proposals")) if isinstance(p, dict)][:6]
    if not props:
        props = [{"m_yes": 8, "m_total": 16, "j_yes": 4, "j_total": 7, "passed": True}]
    n = len(props)
    slot = max(1, dur / n)
    i = min(n - 1, math.floor(lt / slot))
    u = (lt - i * slot) / slot
    pr = props[i]
    my = _num(pr.get("m_yes"), 0)
    mt = max(1, _num(pr.get("m_total"), 16))
    jy = _num(pr.get("j_yes"), 0)
    jt = max(1, _num(pr.get("j_total"), 7))
    grow = _smooth(u / 0.5)
    mw = math.floor(my * 13 / mt * grow + 0.5)
    jw = math.floor(jy * 13 / jt * grow + 0.5)
    passed = bool(pr.get("passed"))
    val = 200
    if u >= 0.6:
        val = (255 if (cx["calm"] or cx["tick"] % 3 != 0) else 120) if passed else 60
    for x in range(W):
        if x % 2 == 0:
            _px(buf, x, 2, 40)
        if x < mw:
            _px(buf, x, 0, val)
            _px(buf, x, 1, val)
        if x < jw:
            _px(buf, x, 4, val)
            _px(buf, x, 5, val)
    for k in range(n):
        _px(buf, k * 2, 7, 255 if k == i else 60)
    return _scale((0, 255, 90) if passed else (255, 30, 40), 60 + math.floor(u * 195)), _scale((180, 100, 255), 120)


def _r_default(buf, shot, lt, dur, cx):
    for j in range(6):
        hh = _h(cx["seed"], 91, j, math.floor(cx["tick"] / 3))
        _px(buf, hh % W, (hh >> 8) % H, 120)
    return None


RENDERERS = {
    "JAM": _r_jam, "VOTE": _r_vote, "LOCK": _r_lock, "DUEL": _r_duel, "TRIBUNAL": _r_tribunal,
    "CROSS": _r_cross, "LIBRARY": _r_library, "MUTATION": _r_mutation, "LEITMOTIF": _r_leitmotif,
    "TITLE_CARD": _r_title, "MOVEMENT_CARD": _r_movement, "PAN": _r_pan, "INTERMISSION": _r_intermission,
    "CREDITS": _r_credits, "OVERDUB": _r_overdub,
}


def _shot_at(starts: Sequence[float], t: float) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if starts[mid] <= t:
            lo = mid
        else:
            hi = mid - 1
    return lo


def film_reel(song: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[float], float]:
    """(shots, each shot's start in ms, total ms) of song["drama"]["shots"]. A shot that is not a
    mapping is left out; a duration below zero counts as zero; the total is at least 1."""
    shots = [s for s in _list(_obj(_obj(song).get("drama")).get("shots")) if isinstance(s, dict)]
    starts: List[float] = []
    acc: float = 0
    for s in shots:
        starts.append(acc)
        acc += max(0, _num(s.get("duration_ms"), 0))
    return shots, starts, max(1, acc)


def film_frame(song: Dict[str, Any], t_ms: float, calm: bool = False) -> MatrixFrame:
    """The making-of film at film time t_ms: the shot playing then, drawn by its kind. t_ms is held
    inside the film. Calm: each shot stands still at six tenths of its length."""
    song = _obj(song)
    shots, starts, total = film_reel(song)
    if not shots:
        return idle_frame(t_ms, calm)
    t = math.floor(_num(t_ms, 0))
    t = max(0, min(t, total - 1))
    i = _shot_at(starts, t)
    shot = shots[i]
    dur = max(1, _num(shot.get("duration_ms"), 0))
    lt = t - starts[i]
    if calm:
        lt = math.floor(dur * 0.6)
    tt = starts[i] + lt
    bpm = _num(song.get("bpm"), 0) or 120
    b = tt * bpm / 60000
    bi = math.floor(b)
    cx = {"seed": song_seed(song), "bpm": bpm, "t": tt, "tick": math.floor(tt / TICK_MS),
          "beat_i": bi, "beat_ph": b - bi, "calm": bool(calm), "index": i}
    buf = [0] * N
    kind = str(shot.get("kind") or "")
    leds = RENDERERS.get(kind, _r_default)(buf, shot, lt, dur, cx)
    col = KIND_RGB.get(kind, DEFAULT_RGB)
    led1 = _scale(col, 180 if calm else 90 + math.floor(165 * (1 - cx["beat_ph"])))
    if not leds:
        leds = (_scale(col, 60), _scale(col, 60))
    if len(leds) > 2:
        led1 = leds[2]
    return MatrixFrame(buf, (led1, leds[0], leds[1]))


# ── playback ─────────────────────────────────────────────────────────────────────────────

_NOTE_CACHE: Dict[str, Any] = {"src": None, "notes": [], "times": []}


def _notes(song: Dict[str, Any]) -> Tuple[List[List[float]], List[float]]:
    raw = _list(song.get("notes"))
    if raw is _NOTE_CACHE["src"]:
        return _NOTE_CACHE["notes"], _NOTE_CACHE["times"]
    clean = []
    for n in raw:
        if isinstance(n, list) and len(n) >= 5:
            clean.append([_num(n[0], 0), _num(n[1], 0), _int(n[2]), _int(n[3]), _int(n[4])])
    clean = sorted(clean, key=lambda n: n[0])
    times = [n[0] for n in clean]
    _NOTE_CACHE.update(src=raw, notes=clean, times=times)
    return clean, times


def playback_frame(song: Dict[str, Any], pos_s: float, calm: bool = False) -> MatrixFrame:
    """Kick/snare flashes, 13 bands from the 16 channels, the part's progress on the bottom row."""
    song = _obj(song)
    notes, times = _notes(song)
    pos = max(0, _num(pos_s, 0))
    seed = song_seed(song)
    bpm = _num(song.get("bpm"), 0) or 120
    lv = [0.0] * W
    kick = 0.0
    snare = 0.0
    snare_t = 0.0
    i = bisect.bisect_right(times, pos) - 1
    scanned = 0
    while i >= 0 and scanned < 600:
        n = notes[i]
        dt = pos - n[0]
        if dt > 4.0:
            break
        scanned += 1
        i -= 1
        c = CH_COL.get(n[2], -1)
        if c < 0:
            continue
        vel = n[4] / 127
        e = 0.0
        if dt < 0.45:
            e = vel * (1 - dt / 0.45)
        if dt < n[1] and vel * 0.45 > e:
            e = vel * 0.45
        if e > lv[c]:
            lv[c] = e
        if n[2] == 10:
            if n[3] in KICK and dt < 0.16 and 1 - dt / 0.16 > kick:
                kick = 1 - dt / 0.16
            if n[3] in SNARE and dt < 0.2 and 1 - dt / 0.2 > snare:
                snare = 1 - dt / 0.2
                snare_t = n[0]
    buf = [0] * N
    loud = 0
    for c in range(W):
        if lv[c] > lv[loud]:
            loud = c
        hgt = math.floor(min(1, lv[c]) * 7 + 0.5)
        for k in range(hgt):
            _px(buf, c, 6 - k, 255 if k == hgt - 1 else 150)
    if not calm and kick > 0:
        for y in range(7):
            for x in range(W):
                _px(buf, x, y, 70 * kick)
    if not calm and snare > 0:
        st = math.floor(snare_t * 1000 + 0.5)
        for j in range(8):
            hh = _h(seed, 77, st, j)
            _px(buf, hh % W, (hh >> 8) % 7, 220 * snare)
    t0: float = 0
    t1: float = _num(song.get("duration"), 0)
    for p in _list(song.get("parts")):
        if isinstance(p, dict):
            a = _num(p.get("t0"), 0)
            b = _num(p.get("t1"), 0)
            if b > a and a <= pos < b:
                t0, t1 = a, b
                break
    if t1 <= t0:
        t1 = t0 + 1
    frac = _clamp01((pos - t0) / (t1 - t0))
    head = min(12, math.floor(frac * 13))
    beat = pos * bpm / 60
    ph = beat - math.floor(beat)
    for x in range(W):
        if x < head:
            _px(buf, x, 7, 110)
        elif x == head:
            _px(buf, x, 7, 255)
        elif not calm:
            _px(buf, x, 7, 60 * (1 - ph))
    led1 = _scale(_pal(1), 180 if calm else math.floor(60 + 195 * (1 - ph)))
    led3 = _scale(_pal(COLS[loud][0]), math.floor(255 * min(1, lv[loud])))
    led4 = (0, 0, 0) if calm else _scale((255, 255, 255), math.floor(255 * max(kick, snare)))
    return MatrixFrame(buf, (led1, led3, led4))


# ── idle, CORPUS mode and glyphs ─────────────────────────────────────────────────────────

def idle_frame(t_ms: float, calm: bool = False, temperament: Optional[Dict[str, Any]] = None) -> MatrixFrame:
    """The breathing heart. `temperament` shapes it: "shape" is "breath", "pulse", "flicker",
    "tide" or "sparkle", with its "period", "floor", "span" and LED1's "rgb". None, an empty
    mapping or anything that is not a mapping is the plain 4 s blue breath."""
    t = math.floor(_num(t_ms, 0))
    if temperament and isinstance(temperament, dict):
        return _idle_tempered(t, calm, temperament)
    s = 1 if calm else _breath(t, 4000)
    level = 200 if calm else 50 + math.floor(205 * s)
    buf = [0] * N
    _sprite(buf, HEART, 0, 0, level)
    return MatrixFrame(buf, ((0, 0, math.floor(48 * s)), (0, 0, 0), (0, 0, 0)))


# ── palettes: the idle temperament and the tone curve ───────────────────────────────────

def _temper_s(shape: str, t: float, period: float, x: float) -> float:
    if shape == "pulse":                       # lub-dub: two bumps early in the period
        u = _mod(t, period) / period
        a = _clamp01(1 - abs(u - 0.06) / 0.06)
        b = _clamp01(1 - abs(u - 0.24) / 0.06)
        return _smooth(max(a, b * 0.7))
    if shape == "flicker":                     # a candle: a new flame height every tick
        n = (_h(math.floor(t / TICK_MS), 0x51CE) & 255) / 255
        return 0.55 + 0.45 * n
    if shape == "tide":                        # a wave rolling across the columns
        return _breath(t + x * period / 26, period)
    if shape == "sparkle":                     # half a breath, plus sparkles (see below)
        return 0.5 + 0.5 * _breath(t, period)
    return _breath(t, period)


def _idle_tempered(t: float, calm: bool, temper: Dict[str, Any]) -> MatrixFrame:
    shape = str(temper.get("shape") or "breath")
    period = max(1000, _int(temper.get("period", 4000)))
    floor = _clamp(_int(temper.get("floor", 50)), 0, 255)
    span = _clamp(_int(temper.get("span", 205)), 0, 255 - floor)
    rgb = [_clamp(_int(v), 0, 255) for v in (_list(temper.get("rgb")) + [0, 0, 0])[:3]]
    buf = [0] * N
    s0 = 1 if calm else _temper_s(shape, t, period, 6)
    for p in HEART:
        s = s0 if (calm or shape != "tide") else _temper_s(shape, t, period, p[0])
        _px(buf, p[0], p[1], 200 if calm else floor + math.floor(span * s))
    if shape == "sparkle" and not calm:
        slot = math.floor(t / (period / 8))
        for i in range(2):
            hh = _h(slot, i, 0x5BA2)
            _px(buf, hh % W, (hh >> 8) % H, 255)
    led = (math.floor(rgb[0] * s0), math.floor(rgb[1] * s0), math.floor(rgb[2] * s0))
    return MatrixFrame(buf, (led, (0, 0, 0), (0, 0, 0)))


def tone_frame(frame: MatrixFrame, tone: Optional[Dict[str, Any]]) -> MatrixFrame:
    """A palette's tone on any frame: every pixel through its 256-entry curve "lut", every lit
    RGB LED mixed "mix"/256 toward the palette's "tint" at the LED's own brightness. None, an
    empty mapping or anything that is not a mapping returns the frame unchanged."""
    if not tone or not isinstance(tone, dict):
        return frame
    lut = tone.get("lut")
    pixels = list(frame.pixels)
    if isinstance(lut, list) and len(lut) == 256:
        pixels = [_clamp(_int(lut[v]), 0, 255) for v in pixels]
    k = _clamp(_int(tone.get("mix", 0)), 0, 256)
    tint = [_clamp(_int(v), 0, 255) for v in (_list(tone.get("tint")) + [0, 0, 0])[:3]]
    rgb = []
    for led in frame.rgb:
        m = max(led[0], led[1], led[2])
        if k and m:
            tr = [math.floor(c * m / 255) for c in tint]
            rgb.append(tuple(led[i] + math.floor((tr[i] - led[i]) * k / 256) for i in range(3)))
        else:
            rgb.append(tuple(led))
    return MatrixFrame(pixels, rgb)


def corpus_frame(t_ms: float, level: float = 0, bands: Optional[Sequence[int]] = None,
                 calm: bool = False) -> MatrixFrame:
    """A record turning at 33 1/3 rpm and a five-bar meter: from `bands` (up to 16 values, 0 to
    255) when given, else from `level` (0 to 255). Calm: the record stands still."""
    t = math.floor(_num(t_ms, 0))
    lvl = _clamp(math.floor(_num(level, 0)), 0, 255)
    buf = [0] * N
    ang = 0 if calm else t * TAU / 1800                     # 33 1/3 rpm
    ca = _cos(ang)
    sa = _sin(ang)
    for y in range(H):
        for x in range(7):
            dx = x - 3
            dy = y - 3.5
            d2 = dx * dx + dy * dy
            if d2 > 12.96:
                continue
            v = 70
            if d2 < 0.8:
                v = 160
            elif dx * ca + dy * sa > 0.5 and abs(dy * ca - dx * sa) < 0.6:
                v = 230
            _px(buf, x, y, v)
    groups = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11), (12, 13, 14, 15))
    bl = [_clamp(math.floor(_num(b, 0)), 0, 255) for b in (list(bands) if isinstance(bands, (list, tuple)) else [])]
    for k in range(5):
        if bl:
            v = 0
            for j in groups[k]:
                if j < len(bl) and bl[j] > v:
                    v = bl[j]
        else:
            v = lvl * (160 + _h(91, k, 0 if calm else math.floor(t / 120)) % 96) / 255
        hgt = _clamp(math.floor(v * 8 / 255 + 0.5), 0, 8)
        for j in range(hgt):
            _px(buf, 8 + k, 7 - j, 255 if j == hgt - 1 else 150)
    return MatrixFrame(buf, ((0, math.floor(lvl * 0.3), lvl), _scale((0, 229, 255), lvl), (0, 0, 0)))


def glyph_frame(name: str, t_ms: float, calm: bool = False) -> MatrixFrame:
    """One of GLYPHS at t_ms. "heart", and any name that is not a glyph, is the idle heart."""
    t = math.floor(_num(t_ms, 0))
    name = str(name or "")
    if name == "heart":
        return idle_frame(t, calm)
    buf = [0] * N
    led1 = (0, 0, 0)
    led3 = (0, 0, 0)
    if name == "boot":
        p = 2399 if calm else _mod(t, 2400)
        if p < 700:
            c = math.floor(p / 50)
            for x in range(W):
                age = c - x
                if 0 <= age < 4:
                    for y in range(H):
                        _px(buf, x, y, 255 - age * 60)
        else:
            _text(buf, "PB", 3, 1, 255)
            for k in range(min(W, math.floor((p - 700) / 130))):
                _px(buf, k, 7, 120)
        led1 = (0, 0, 200)
        led3 = (0, 80, 200)
    elif name == "low_battery":
        on = calm or _mod(math.floor(t / 500), 2) == 0
        for x in range(1, 11):
            _px(buf, x, 2, 200)
            _px(buf, x, 5, 200)
        for y in range(2, 6):
            _px(buf, 1, y, 200)
            _px(buf, 10, y, 200)
        _px(buf, 11, 3, 200)
        _px(buf, 11, 4, 200)
        if on:
            for x in (2, 3):
                _px(buf, x, 3, 255)
                _px(buf, x, 4, 255)
        led1 = (200 if on else 40, 0, 0)
    elif name == "update":
        off = 0 if calm else _mod(math.floor(t / 150), 3)
        for y in range(3):
            _px(buf, 6, y + off, 255)
        for x in range(4, 9):
            _px(buf, x, 3 + off, 255)
        for x in range(5, 8):
            _px(buf, x, 4 + off, 255)
        for x in range(2, 11):
            _px(buf, x, 7, 150)
        _px(buf, 2, 6, 150)
        _px(buf, 10, 6, 150)
        led1 = _scale((0, 160, 255), 120 + off * 60)
    elif name == "composing":
        k = -1 if calm else _mod(math.floor(t / 300), 3)
        for j in range(3):
            _sprite(buf, NOTE_GLYPH, j * 5, 2 - (1 if j == k else 0), 255 if j == k else (200 if calm else 120))
        led1 = _scale((0, 120, 255), 200 if calm else 90 + math.floor(165 * _breath(t, 1800)))
    else:
        return idle_frame(t, calm)
    return MatrixFrame(buf, (led1, led3, (0, 0, 0)))


# ── the Series Premiere: the box, then the burst ────────────────────────────────────────
# A new series has begun and the band's premiere is waiting:
#   pending (a loop of PREMIERE_PERIOD_MS)  the box sits with a twinkle over it, shakes, then
#                                           "S<n>" (calm: box and number as two still pages)
#   opened (one shot of PREMIERE_OPEN_MS)   the lid flies off, a burst in the headliner's tier
#                                           colour (LED3), then "S<n>" (calm: no burst)
# LED1 pulses gold.
PREMIERE_PERIOD_MS = 3200
PREMIERE_OPEN_MS = 2600
PREMIERE_RGB = (255, 210, 63)
PREMIERE_TIER_RGB: Dict[str, Tuple[int, int, int]] = {
    "common": (154, 154, 184), "uncommon": (111, 232, 154), "rare": (125, 234, 242), "epic": (192, 140, 255),
    "legendary": (255, 228, 92), "secret": (255, 107, 154)}


def _premiere_box(buf: List[int], dx: float, lid: float, v: float) -> None:
    for x in range(3, 10):
        _px(buf, x + dx, 4, v)
        _px(buf, x + dx, 7, v)
    for y in range(5, 7):
        _px(buf, 3 + dx, y, v)
        _px(buf, 9 + dx, y, v)
    for y in range(4, 8):
        _px(buf, 6 + dx, y, 255)                 # the ribbon
    for x in range(2, 11):
        _px(buf, x + dx, 3 - lid, v)             # the lid
    _px(buf, 5 + dx, 2 - lid, 180)               # the bow
    _px(buf, 7 + dx, 2 - lid, 180)


def premiere_frame(number: Any, t_ms: float, opened: bool = False, calm: bool = False, tier: str = "") -> MatrixFrame:
    """Series `number`'s box at t_ms: waiting (a loop), or opening when `opened` (see above). A
    tier that is not one of the six is drawn in the legendary colour."""
    t = max(0, math.floor(_num(t_ms, 0)))
    n = max(1, _int(number))
    label = _asc("S" + str(n))
    tw = len(label) * 4 - 1
    buf = [0] * N
    tier_rgb = PREMIERE_TIER_RGB.get(str(tier or ""), PREMIERE_TIER_RGB["legendary"])
    led3 = (0, 0, 0)
    if not opened:
        if calm:
            show_box = _mod(math.floor(t / 1600), 2) == 0
            p = 0
        else:
            p = _mod(t, PREMIERE_PERIOD_MS)
            show_box = p < 2000
        if show_box:
            dx = 0
            if not calm and 1200 <= p:
                dx = 1 if _mod(math.floor(p / 100), 2) == 0 else -1
            _premiere_box(buf, dx, 0, 200)
            if not calm:
                k = _h(n, math.floor(p / 150)) % 5
                _px(buf, 4 + k, 0 + _mod(math.floor(p / 300), 2), 140)
        else:
            _text(buf, label, math.floor((W - tw) / 2), 1, 255)
        pulse = 200 if calm else 90 + math.floor(165 * _breath(t, 1600))
        led1 = _scale(PREMIERE_RGB, pulse)
    else:
        lt = t
        if calm:
            if lt < 1300:
                _premiere_box(buf, 0, 3, 200)
            else:
                _text(buf, label, math.floor((W - tw) / 2), 1, 255)
            led3 = _scale(tier_rgb, 160)
        elif lt < 600:
            _premiere_box(buf, 0, math.floor(lt / 150), 220)
        elif lt < 1800:
            u = (lt - 600) / 1200
            r = 1 + u * 6
            for i in range(12):
                a = i * TAU / 12
                _px(buf, 6 + _cos(a) * r, 3.5 + _sin(a) * r * 0.6, 255 - math.floor(180 * u))
            _premiere_box(buf, 0, 3, 120 - math.floor(80 * u))
            led3 = _scale(tier_rgb, 255 - math.floor(120 * u))
        else:
            _text(buf, label, math.floor((W - tw) / 2), 1, 255)
            led3 = _scale(tier_rgb, 120)
        led1 = _scale(PREMIERE_RGB, 255 if lt < 1800 and not calm else 200)
    return MatrixFrame(buf, (led1, led3, (0, 0, 0)))


# ── DJ mode: a mix segment on the matrix ────────────────────────────────────────────────
# One frame of the segment `seg` (tempo, decks, layers, notes [[t, dur, ch, pitch, vel, layer_i]],
# fx, show) at pos_s seconds into it; t_ms is the scene clock (twinkles only).
#
#   row 0        the key: a tick at the Camelot position (x = 1..12 -> 0..11; B = major is
#                brighter), a ghost of the old key for a moment after a "key" show event;
#                a judge's score bar on "judge" events (revealed from the full row); a comet
#                when an influencer tugs a choice ("tug")
#   rows 1-6     deck A's platter (x 0-5) and deck B's (x 7-12), spinning one turn per bar on
#                the segment's beat clock (tempo ramps included), so the two decks are
#                visibly beat-matched; rim and stripe brightness follow what the deck sounds
#                like now (its notes, layer gains, the crossfader, deck/master filter and gain
#                fx); the labels pulse on the beat; a "stutter" makes the stripe jump back;
#                "pull" events (a sniplet leaves its shelf) sparkle over the pulling deck
#   column 6     the master meter between the platters; a "riser" fills it from the bottom
#   row 7        the crossfader: a knob under the deck you hear (from "crossfade" fx), its
#                track pulsing on the beat (harder on the downbeat)
#   a "drop"     (silence, then the drop) flashes the whole matrix when the drop lands
#   LEDs         LED1 the key's colour (Camelot wheel) on the beat, the judge's colour while
#                a judge reacts, white for the riser and the drop; LED3 deck A, LED4 deck B
#   calm         the platters stand still (stripe up), no beat pulse, sparkles, comets or
#                flashes; the meter, knob, key and judges' scores still show

DJ_DECK_RGB: Dict[str, Tuple[int, int, int]] = {"A": (255, 42, 133), "B": (0, 229, 255)}
DJ_JUDGE_RGB: Dict[str, Tuple[int, int, int]] = {"camelot": (255, 210, 63), "groove": (255, 42, 133),
                                                 "segue": (0, 229, 255), "weird": (179, 102, 255),
                                                 "floor": (0, 255, 90)}
# the Camelot wheel 1..12 as a colour wheel (B = major at full brightness, A = minor dimmer)
DJ_KEY_RGB: Tuple[Tuple[int, int, int], ...] = (
    (255, 0, 64), (255, 80, 0), (255, 170, 0), (230, 230, 0), (130, 255, 0), (0, 255, 60),
    (0, 255, 170), (0, 200, 255), (0, 110, 255), (60, 0, 255), (160, 0, 255), (255, 0, 200))
DJ_PLATTERS = (("A", 0, 2.5), ("B", 7, 9.5))     # deck, first column, centre x (centre y 3.5)
DJ_PULL_MS = 700
DJ_JUDGE_MS = 1400
DJ_REVEAL_MS = 300
DJ_DROP_MS = 350
DJ_KEY_GHOST_MS = 500
DJ_TUG_MS = 600

_DJ_CACHE: Dict[str, Any] = {"src": None, "notes": [], "times": []}


def dj_camelot(v: Any) -> Tuple[int, str]:
    """'8A' -> (8, 'A'); anything else -> (0, '')."""
    s = str(v if v is not None else "").strip()
    if len(s) < 2 or len(s) > 3:
        return 0, ""
    letter = s[len(s) - 1]
    if letter == "a" or letter == "b":
        letter = chr(ord(letter) - 32)
    if letter != "A" and letter != "B":
        return 0, ""
    digits = s[:len(s) - 1]
    for ch in digits:
        if ch not in "0123456789":
            return 0, ""
    n = int(digits)
    return (n, letter) if 1 <= n <= 12 else (0, "")


def _dj_tempo(seg: Dict[str, Any]) -> Tuple[float, float, float]:
    tp = _obj(seg.get("tempo"))
    b0 = _num(tp.get("bpm_start"), 0) or _num(tp.get("bpm_end"), 0) or 120
    b1 = _num(tp.get("bpm_end"), 0) or b0
    ln = _num(seg.get("duration"), 0)
    beats = _num(tp.get("beats"), 0)
    if ln <= 0 and beats > 0:
        ln = 120 * beats / (b0 + b1)
    return b0, b1, ln


def dj_beat(seg: Dict[str, Any], pos_s: float) -> float:
    """Beats since the segment start at pos_s, on the contract's linear-in-time tempo ramp."""
    b0, b1, ln = _dj_tempo(_obj(seg))
    t = _num(pos_s, 0)
    if ln <= 0 or t <= 0:
        return t * b0 / 60
    if t >= ln:
        return (b0 * ln + (b1 - b0) * ln / 2) / 60 + (t - ln) * b1 / 60
    return (b0 * t + (b1 - b0) * t * t / (2 * ln)) / 60


def _dj_u(ev: Dict[str, Any], pos: float) -> float:
    dur = _num(ev.get("dur"), 0)
    if dur <= 0:
        return 1
    return _clamp01((pos - _num(ev.get("t"), 0)) / dur)


def _dj_side(v: Any) -> int:
    s = str(v if v is not None else "")
    return 0 if s == "A" else (1 if s == "B" else -1)


def _dj_latest(evs: List[Any], kind: str, pos: float) -> List[Tuple[int, Dict[str, Any]]]:
    """(index, event) of every `kind` event that has started by pos, in list order."""
    out = []
    for k in range(len(evs)):
        ev = evs[k]
        if isinstance(ev, dict) and ev.get("type") == kind and _num(ev.get("t"), 0) <= pos:
            out.append((k, ev))
    return out


def _dj_last(found: List[Tuple[int, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The one that started last (ties: the later in the list)."""
    best = None
    for _, ev in found:
        if best is None or _num(ev.get("t"), 0) >= _num(best.get("t"), 0):
            best = ev
    return best


def dj_crossfader(seg: Dict[str, Any], pos_s: float, loaded: Optional[Dict[str, bool]] = None) -> float:
    """The crossfader at pos_s: 0 = deck A, 1 = deck B (from the segment's "crossfade" fx)."""
    seg = _obj(seg)
    pos = _num(pos_s, 0)
    fx = _list(seg.get("fx"))
    first = None
    for ev in fx:
        if isinstance(ev, dict) and ev.get("type") == "crossfade":
            if first is None or _num(ev.get("t"), 0) < _num(first.get("t"), 0):
                first = ev
    cur = _dj_last(_dj_latest(fx, "crossfade", pos))
    if cur is None and first is not None:
        a = _dj_side(first.get("from"))
        b = _dj_side(first.get("to"))
        return a if a >= 0 else (1 - b if b >= 0 else 0)
    if cur is None:
        ld = loaded or {}
        if ld.get("A") and not ld.get("B"):
            return 0
        if ld.get("B") and not ld.get("A"):
            return 1
        return 0.5
    a = _dj_side(cur.get("from"))
    b = _dj_side(cur.get("to"))
    if a < 0:
        a = 1 - b if b >= 0 else 0
    if b < 0:
        b = 1 - a
    u = 1 if str(cur.get("curve") or "") == "cut" else _dj_u(cur, pos)
    return a + (b - a) * u


def _dj_gain(pts: Any, pos: float) -> float:
    pts = [p for p in _list(pts) if isinstance(p, list) and len(p) >= 2]
    if not pts:
        return 1
    if pos <= _num(pts[0][0], 0):
        return _clamp01(_num(pts[0][1], 1))
    for i in range(1, len(pts)):
        t1 = _num(pts[i][0], 0)
        if pos < t1:
            t0 = _num(pts[i - 1][0], 0)
            g0 = _num(pts[i - 1][1], 1)
            g1 = _num(pts[i][1], 1)
            if t1 <= t0:
                return _clamp01(g1)
            return _clamp01(g0 + (g1 - g0) * (pos - t0) / (t1 - t0))
    return _clamp01(_num(pts[len(pts) - 1][1], 1))


def _dj_env(fx: List[Any], kind: str, target: str, pos: float) -> float:
    """The latest `kind` ("filter" | "gain") envelope on `target` at pos, 0..1; -1 if none."""
    found = [(k, ev) for k, ev in _dj_latest(fx, kind, pos) if str(ev.get("target") or "") == target]
    cur = _dj_last(found)
    if cur is None:
        return -1
    u = _dj_u(cur, pos)
    if str(cur.get("shape") or "") == "exp":
        u = u * u
    a = _num(cur.get("from"), 1)
    b = _num(cur.get("to"), 1)
    return _clamp01(a + (b - a) * u)


def _dj_notes(seg: Dict[str, Any]) -> Tuple[List[List[float]], List[float]]:
    raw = _list(seg.get("notes"))
    if raw is _DJ_CACHE["src"]:
        return _DJ_CACHE["notes"], _DJ_CACHE["times"]
    clean = []
    for n in raw:
        if isinstance(n, list) and len(n) >= 5:
            clean.append([_num(n[0], 0), _num(n[1], 0), _int(n[2]), _int(n[3]), _int(n[4]),
                          _int(n[5]) if len(n) > 5 else -1])
    clean = sorted(clean, key=lambda n: n[0])
    times = [n[0] for n in clean]
    _DJ_CACHE.update(src=raw, notes=clean, times=times)
    return clean, times


def _dj_deck_of(v: Any, lay: Dict[int, Tuple[str, float]]) -> str:
    """A target or event deck: "deck:B" / "B" -> "B", "layer:3" -> that layer's deck, else ""."""
    s = str(v if v is not None else "")
    if s == "A" or s == "deck:A":
        return "A"
    if s == "B" or s == "deck:B":
        return "B"
    if s == "master":
        return "*"
    if s[:6] == "layer:":
        ly = lay.get(_int(s[6:]))
        return ly[0] if ly else ""
    return ""


def dj_frame(seg: Dict[str, Any], pos_s: float, t_ms: float = 0, calm: bool = False) -> MatrixFrame:
    """DJ mode: two beat-matched platters, the crossfader, the key, the judges (see above)."""
    seg = _obj(seg)
    pos = _num(pos_s, 0)
    tick = math.floor(_num(t_ms, 0) / TICK_MS)
    seed = str_seed(seg.get("id") or "")
    fx = _list(seg.get("fx"))
    show = _list(seg.get("show"))
    layers = _list(seg.get("layers"))
    lay: Dict[int, Tuple[str, float]] = {}
    loaded = {"A": False, "B": False}
    for k in range(len(layers)):
        ly = layers[k]
        if not isinstance(ly, dict):
            continue
        li = _int(ly.get("i")) if ly.get("i") is not None else k
        d = "B" if str(ly.get("deck") or "") == "B" else "A"
        lay[li] = (d, _dj_gain(ly.get("gain"), pos))
        loaded[d] = True
    for dk in _list(seg.get("decks")):
        if isinstance(dk, dict):
            d = str(dk.get("deck") or "")
            if d == "A" or d == "B":
                loaded[d] = True
    # what each deck sounds like now (as playback_frame reads its notes)
    notes, times = _dj_notes(seg)
    act = {"A": 0.0, "B": 0.0}
    i = bisect.bisect_right(times, pos) - 1
    scanned = 0
    while i >= 0 and scanned < 600:
        n = notes[i]
        dt = pos - n[0]
        if dt > 4.0:
            break
        scanned += 1
        i -= 1
        vel = n[4] / 127
        e = 0.0
        if dt < 0.45:
            e = vel * (1 - dt / 0.45)
        if dt < n[1] and vel * 0.45 > e:
            e = vel * 0.45
        if e <= 0:
            continue
        ly = lay.get(n[5])
        d = ly[0] if ly else "A"
        g = ly[1] if ly else 1
        loaded[d] = True
        if e * g > act[d]:
            act[d] = e * g
    xf = _clamp01(dj_crossfader(seg, pos, loaded))
    xg = {"A": _clamp01(_cos(xf * PI / 2)), "B": _clamp01(_sin(xf * PI / 2))}
    mf = _dj_env(fx, "filter", "master", pos)
    mg = _dj_env(fx, "gain", "master", pos)
    aud = {}
    for d in ("A", "B"):
        f = _dj_env(fx, "filter", "deck:" + d, pos)
        g = _dj_env(fx, "gain", "deck:" + d, pos)
        a = min(1, act[d]) * xg[d]
        if f >= 0:
            a = a * (0.35 + 0.65 * f)
        if g >= 0:
            a = a * g
        if mf >= 0:
            a = a * (0.35 + 0.65 * mf)
        if mg >= 0:
            a = a * mg
        aud[d] = a
    beat = dj_beat(seg, pos)
    bi = math.floor(beat)
    ph = beat - bi
    # a stutter on a deck repeats the last 1/rate bar: its stripe jumps back
    stut: Dict[str, Optional[Dict[str, Any]]] = {"A": None, "B": None}
    for _, ev in _dj_latest(fx, "stutter", pos):
        if pos >= _num(ev.get("t"), 0) + _num(ev.get("dur"), 0):
            continue
        d = _dj_deck_of(ev.get("target"), lay)
        for name in ("A", "B"):
            if d == name or d == "*":
                if stut[name] is None or _num(ev.get("t"), 0) >= _num(stut[name].get("t"), 0):
                    stut[name] = ev
    buf = [0] * N
    for name, x0, cx in DJ_PLATTERS:
        a = aud[name]
        on = loaded[name]
        b = beat
        st = stut[name]
        if st is not None:
            bt = dj_beat(seg, _num(st.get("t"), 0))
            rep = 4 / _clamp(_num(st.get("rate"), 8), 2, 64)
            b = bt + _mod(beat - bt, rep)
        ang = -PI / 2 if calm else b * TAU / 4 - PI / 2
        ca = _cos(ang)
        sa = _sin(ang)
        if on:
            vinyl = 22 + math.floor(50 * a)
            rim = 40 + math.floor(120 * a)
            stripe = 120 + math.floor(135 * a)
            label = 150 if calm else (70 + math.floor(185 * (1 - ph)) if a > 0.05 else 70)
            if st is not None and not calm and _mod(tick, 2) == 0:
                rim = rim + 60
        else:
            vinyl, rim, stripe, label = 12, 22, 0, 30
        for y in range(1, 7):
            for x in range(x0, x0 + 6):
                dx = x - cx
                dy = y - 3.5
                d2 = dx * dx + dy * dy
                if d2 > 8.5:
                    continue
                if d2 < 1:
                    v = label
                elif on and dx * ca + dy * sa > 0.5 and abs(dy * ca - dx * sa) < 0.75:
                    v = stripe
                elif d2 > 6:
                    v = rim
                else:
                    v = vinyl
                _px(buf, x, y, v)
    # the master meter between the platters, and the riser filling it
    level = min(1, max(aud["A"], aud["B"]))
    hgt = math.floor(level * 6 + 0.5)
    for y in range(1, 7):
        _px(buf, 6, y, 10)
    for k in range(hgt):
        _px(buf, 6, 6 - k, 255 if k == hgt - 1 else 110)
    riser = -1.0
    for _, ev in _dj_latest(fx, "riser", pos):
        if pos < _num(ev.get("t"), 0) + _num(ev.get("dur"), 0):
            riser = _dj_u(ev, pos)
    if riser >= 0:
        rh = min(6, 1 + math.floor(riser * 6))
        for k in range(rh):
            top = k == rh - 1
            _px(buf, 6, 6 - k, (255 if (calm or _mod(tick, 2) == 0) else 160) if top else 200)
    # the crossfader on the bottom row
    down = _mod(bi, 4) == 0
    track = 16 if calm else 16 + math.floor((60 if down else 30) * (1 - ph))
    for x in range(W):
        _px(buf, x, 7, track)
    knob = 1 + math.floor(xf * 10 + 0.5)
    _px(buf, knob - 1, 7, 150)
    _px(buf, knob, 7, 255)
    _px(buf, knob + 1, 7, 150)
    # the key on the top row (a ghost of the old one just after a change)
    key = _obj(seg.get("key"))
    kn, kl = dj_camelot(key.get("from") or key.get("to"))
    kev = _dj_last(_dj_latest(show, "key", pos))
    if kev is not None:
        n2, l2 = dj_camelot(kev.get("to"))
        if n2:
            if not calm and pos - _num(kev.get("t"), 0) < DJ_KEY_GHOST_MS / 1000:
                n1, _ = dj_camelot(kev.get("from"))
                if n1:
                    _px(buf, n1 - 1, 0, 90)
            kn, kl = n2, l2
    if kn:
        _px(buf, kn - 1, 0, 255 if kl == "B" else 170)
    # a judge holds up a score: the whole row, shrinking to the score
    jud = None
    for _, ev in _dj_latest(show, "judge", pos):
        if pos - _num(ev.get("t"), 0) < DJ_JUDGE_MS / 1000:
            jud = ev
    if jud is not None:
        age = (pos - _num(jud.get("t"), 0)) * 1000
        w = math.floor(_clamp01(_num(jud.get("score"), 0)) * 13 + 0.5)
        if not calm and age < DJ_REVEAL_MS:
            w = 13 - math.floor((13 - w) * age / DJ_REVEAL_MS)
        for x in range(w):
            _px(buf, x, 0, 230)
    if not calm:
        # an influencer tugs a choice: a comet along the top row
        for k, ev in _dj_latest(show, "tug", pos):
            age = (pos - _num(ev.get("t"), 0)) * 1000
            if age >= DJ_TUG_MS:
                continue
            x = math.floor(age * 13 / DJ_TUG_MS)
            if _h(seed, 131, k) % 2 == 1:
                _px(buf, 12 - x, 0, 220)
                _px(buf, 13 - x, 0, 90)
            else:
                _px(buf, x, 0, 220)
                _px(buf, x - 1, 0, 90)
        # a sniplet leaves its shelf: sparkles over the deck that pulled it
        for k, ev in _dj_latest(show, "pull", pos):
            age = (pos - _num(ev.get("t"), 0)) * 1000
            if age >= DJ_PULL_MS:
                continue
            d = _dj_deck_of(ev.get("deck"), lay)
            if d == "" and ev.get("layer") is not None:
                d = _dj_deck_of("layer:" + str(_int(ev.get("layer"))), lay)
            x0 = 7 if d == "B" else 0
            for j in range(5):
                hh = _h(seed, 101, k, j, tick)
                _px(buf, x0 + hh % 6, 1 + (hh >> 8) % 6, (250 if (hh >> 16) % 3 else 130) * (1 - age / DJ_PULL_MS))
    # the drop lands: a flash
    flash = 0.0
    if not calm:
        for _, ev in _dj_latest(fx, "drop", pos):
            age = (pos - _num(ev.get("t"), 0) - _num(ev.get("dur"), 0)) * 1000
            if 0 <= age < DJ_DROP_MS:
                flash = 1 - age / DJ_DROP_MS
        if flash > 0:
            for p in range(N):
                _px(buf, p % W, math.floor(p / W), 255 * flash)
    # LEDs
    if kn:
        kc = DJ_KEY_RGB[kn - 1]
        m = 1 if kl == "B" else 0.6
        led1 = _scale(kc, (180 if calm else 60 + 195 * (1 - ph)) * m)
    else:
        led1 = _scale(DEFAULT_RGB, 60)
    if jud is not None:
        led1 = _scale(DJ_JUDGE_RGB.get(str(jud.get("judge") or ""), (255, 210, 63)), 220)
    if riser >= 0:
        led1 = _scale((255, 255, 255), 60 + 195 * riser)
    led3 = _scale(DJ_DECK_RGB["A"], 20 + 235 * aud["A"]) if loaded["A"] else (0, 0, 0)
    led4 = _scale(DJ_DECK_RGB["B"], 20 + 235 * aud["B"]) if loaded["B"] else (0, 0, 0)
    if flash > 0:
        white = _scale((255, 255, 255), 255 * flash)
        led1, led3, led4 = white, white, white
    return MatrixFrame(buf, (led1, led3, led4))


# ── text: pairing codes and jam words ───────────────────────────────────────────────────
# text_frame() draws text in a 5x7 font that keeps codes such as K7QX-3MPA legible (0 is
# slashed; row 7 is a bar that drains with the time limit). A device shows it over whatever the
# matrix is doing; which text wins when two are up is PRIORITIES, highest first. Keeping the list
# of what is up, and for how long, is the device process's business and is not in this module.

PRIORITIES: Dict[str, int] = {"pairing": 300, "jam": 200, "premiere": 150, "notice": 100}
TEXT_PPS = 10                      # scroll speed, pixels per second (about 1.7 characters/s)
TEXT_GAP = 7                       # pixels between loops of a ticker, with a dot in the middle
TEXT_HOLD_MS = 2500                # how long a one-shot word that fits (e.g. "BYE") stays up
TEXT_PAGE_MS = 1500                # reduced motion: two characters per page instead of scrolling

# 5x7 font: each entry is the character and seven rows as two hex digits, bit 16 = left column.
FONT57_SRC = (
    "00E11131519110E1040C040404040E20E11010204081F31F02040201110E402060A121F0202"
    "51F101E0101110E60608101E11110E71F01020408080880E11110E11110E90E11110F01020C"
    "A0E1111111F1111B1E11111E11111EC0E11101010110ED1C12111111121CE1F10101E10101F"
    "F1F10101E101010G0E11101711110FH1111111F111111I0E04040404040EJ0702020202120C"
    "K11121418141211L1010101010101FM111B1515111111N11111915131111O0E11111111110E"
    "P1E11111E101010Q0E11111115120DR1E11111E141211S0F10100E01011ET1F040404040404"
    "U1111111111110EV11111111110A04W1111111515150AX11110A040A1111Y1111110A040404"
    "Z1F01020408101F-0000001F000000?0E110102040004!04040404040004.00000000000C0C"
    ":000C0C000C0C00'0C040800000000/00010204081000+0004041F040400#0A0A1F0A1F0A0A"
    "*0004150E150400,000000000C0408&0C12140815120D(02040808080402)08040202020408")
FONT57: Dict[str, Tuple[int, ...]] = {FONT57_SRC[i]: tuple(int(FONT57_SRC[i + 1 + 2 * k:i + 3 + 2 * k], 16)
                                                         for k in range(7))
                                      for i in range(0, len(FONT57_SRC), 15)}
OVERLAY_RGB: Dict[str, Tuple[int, int, int]] = {"pairing": (0, 229, 255), "jam": (255, 42, 133),
                                                "premiere": (255, 210, 63), "notice": (255, 210, 63)}


def _text57(buf: List[int], s: str, x0: float, y0: float, v: float) -> None:
    for i, ch in enumerate(s):
        g = FONT57.get(ch)
        if not g:
            continue
        for r in range(7):
            for c in range(5):
                if g[r] & (16 >> c):
                    _px(buf, x0 + i * 6 + c, y0 + r, v)


def text_pass_ms(text: Any) -> int:
    """How long one pass of text_frame takes: a hold for a word that fits, else one scroll."""
    s = _asc(text)
    tw = len(s) * 6 - 1
    if not s or tw <= W:
        return TEXT_HOLD_MS
    return math.floor((W + tw) * 1000 / TEXT_PPS)


def text_frame(text: Any, t_ms: float, loop: bool = True, priority: str = "pairing",
               ttl_ms: Optional[float] = None, calm: bool = False) -> MatrixFrame:
    """Text in the 5x7 font at t_ms since it appeared: centred if it fits, else scrolled (a
    ticker when loop); row 7 drains with ttl_ms. Calm: two-character pages, no scrolling."""
    s = _asc(text)
    t = max(0, math.floor(_num(t_ms, 0)))
    buf = [0] * N
    tw = len(s) * 6 - 1
    if s and tw <= W:
        _text57(buf, s, math.floor((W - tw) / 2), 0, 255)
    elif s and calm:
        pages = math.floor((len(s) + 1) / 2)
        k = math.floor(t / TEXT_PAGE_MS)
        k = _mod(k, pages) if loop else min(pages - 1, k)
        chunk = s[k * 2:k * 2 + 2]
        _text57(buf, chunk, math.floor((W - (len(chunk) * 6 - 1)) / 2), 0, 255)
    elif s:
        base = W - math.floor(t * TEXT_PPS / 1000)
        if loop:
            period = tw + TEXT_GAP
            if base < 0:
                base = _mod(base, period) - period
            x = base
            while x < W:
                _text57(buf, s, x, 0, 255)
                _px(buf, x + tw + math.floor(TEXT_GAP / 2) + 1, 3, 120)
                x += period
        else:
            _text57(buf, s, base, 0, 255)
    ttl = _num(ttl_ms, 0)
    if ttl > 0:
        lit = math.ceil(_clamp01(1 - t / ttl) * W)
        for x in range(lit):
            _px(buf, x, 7, 70)
    col = OVERLAY_RGB.get(str(priority or ""), (220, 220, 255))
    pulse = 200 if calm else 90 + math.floor(165 * _breath(t, 1600))
    return MatrixFrame(buf, (_scale(col, pulse), _scale(col, 60), (0, 0, 0)))


# ── hex, and the short names ─────────────────────────────────────────────────────────────

def to_hex(frame: MatrixFrame) -> str:
    """The 113-byte wire form of a frame as 226 hex digits."""
    return frame.to_bytes().hex()


def from_hex(text: str) -> MatrixFrame:
    """The frame written as 226 hex digits. ValueError when it is not 113 bytes of hex."""
    return MatrixFrame.from_bytes(bytes.fromhex(text))


# The names the vector files and the JavaScript binding use for the nine frame functions.
film = film_frame
playback = playback_frame
idle = idle_frame
corpus = corpus_frame
glyph = glyph_frame
dj = dj_frame
text = text_frame
premiere = premiere_frame
tone = tone_frame
