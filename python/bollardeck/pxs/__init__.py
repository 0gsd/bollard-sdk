# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.pxs: read, write and validate .pxs, the Pop Snip format (Pompas' extended song format).

A .pxs file is a complete, valid Impulse Tracker (IT) module followed by one PXS block: a 16-byte
header, typed chunks, and a 12-byte footer at the very end of the file ("PXSF", the block's offset,
a CRC-32). Every IT player reaches its data through the module's own offsets and never reads past
it, so the block is invisible to them; Pop Boll reads it for credits, licences, the song's MIDI and
more. The format's home document is the PXS specification (version 1).

    from bollardeck import pxs

    data = pxs.attach(module_bytes, [("HEAD", pxs.canonical_json(head)), ("DSCL", ...), ...])
    verdict = pxs.validate(data)          # Verdict(valid, kind "pxs"|"it"|"invalid", rule, reason, ...)
    for chunk in pxs.read_chunks(data):   # Chunk(id, flags, data): deflated chunks come back inflated
        ...
    layout = pxs.measure_it(module_bytes) # the IT structure check: regions, base end, unaccounted bytes

The validation rules are the specification's V1-V9 with the three amendments agreed with Amorphus:

    V1  the IT structure check (limits below; every structure inside the file; no overlaps)
    V2  base end = the largest end of any structure that check accounts for
    V3  the last 12 bytes are "PXSF", the block offset and the CRC; the offset equals base end
    V4  the CRC-32 matches
    V5  the header: magic "PXS" 0x1A, major 1, base 'i', flags 0, 1-64 chunks, the length, <= 256 KiB
    V6  the chunk walk ends exactly at the footer; ids printable; no uppercase id twice
    V7  HEAD first, flags 0, a UTF-8 JSON object <= 4 KiB with schema "pxs/1" and base "it"
    V8  at most 512 KiB of bytes inside the module that no structure accounts for
    V9  "PXS1" at 0x3C is a fingerprint, never required

Detection is by content: bytes that parse as IT and end in a "PXSF" footer are a .pxs, and the
block must then be valid. HEAD is checked for meaning, not for canonical bytes. Flags of chunks
other than HEAD are not checked (bit 0 means deflated; later bits are free). A signature, when
present, never affects validity. Standard library only.
"""
from __future__ import annotations

import json
import math
import re
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

SCHEMA = "pxs/1"
MAJOR, MINOR = 1, 0
MAGIC = b"PXS\x1a"
FOOTER_MAGIC = b"PXSF"
FINGERPRINT = b"PXS1"
HEADER_LEN, CHUNK_HEADER_LEN, FOOTER_LEN = 16, 12, 12
BASE_IT = ord("i")
MAX_BLOCK = 256 * 1024
MAX_CHUNKS = 64
MAX_HEAD = 4 * 1024
MAX_INFLATED = 1024 * 1024
MAX_UNACCOUNTED = 512 * 1024
MAX_FILE = 32 * 1024 * 1024
FLAG_DEFLATED = 1

# the IT limits a validator enforces (V1)
IT_HEADER_LEN = 0xC0
IT_INSTRUMENT_LEN = 554
IT_SAMPLE_HEADER_LEN = 80
IT_MAX_COUNT = 256                  # orders, instruments, samples, patterns
IT_MAX_ROWS = 1024
IT_MIDI_CONFIG_LEN = 4896

__all__ = [
    "SCHEMA", "MAX_BLOCK", "MAX_CHUNKS", "MAX_HEAD", "PxsError", "ItLayout", "Chunk", "Verdict",
    "canonical_json", "loads", "measure_it", "build_block", "attach", "read_chunks", "validate",
]


class PxsError(ValueError):
    """A broken module or block. `rule` names the rule it breaks ("V1".."V7")."""

    def __init__(self, rule: str, reason: str):
        super().__init__("%s: %s" % (rule, reason))
        self.rule = rule
        self.reason = reason


def canonical_json(obj: Any) -> bytes:
    """The JSON a writer emits: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


# ───────────────────────────────── the IT structure check (V1, V2, V8) ─────────────────────────────────

@dataclass
class ItLayout:
    """Where an IT module's structures lie. `base_end` is the end of the furthest one (V2)."""
    regions: List[Tuple[int, int, str]] = field(default_factory=list)   # (start, end, what), sorted
    base_end: int = 0
    unaccounted: int = 0                # bytes inside [0, base_end) that no structure covers (V8)
    orders: int = 0
    instruments: int = 0
    samples: int = 0
    patterns: int = 0
    stereo_samples: int = 0


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _compressed_end(data: bytes, start: int, frames: int, wide: bool, stereo: bool) -> int:
    """IT 2.14/2.15 compressed sample data: blocks of a u16 length and that many bytes, one run of
    blocks per channel; a block covers at most 0x8000 frames (8-bit) or 0x4000 (16-bit)."""
    per_block = 0x4000 if wide else 0x8000
    pos = start
    for _channel in range(2 if stereo else 1):
        left = frames
        while left > 0:
            if pos + 2 > len(data):
                raise PxsError("V1", "a compressed sample runs past the end of the file")
            pos += 2 + _u16(data, pos)
            left -= per_block
    return pos


def measure_it(data: bytes, limit: Optional[int] = None) -> ItLayout:
    """The IT structure check (V1). `limit`: the end of the module inside `data` (a .pxs's block
    offset); structures must lie before it. Returns the regions and base end (V2); raises PxsError."""
    end_limit = len(data) if limit is None else limit
    if len(data) > MAX_FILE:
        raise PxsError("V1", "larger than %d bytes" % MAX_FILE)
    if end_limit < IT_HEADER_LEN or data[:4] != b"IMPM":
        raise PxsError("V1", "not an IT module (no IMPM header)")
    lay = ItLayout()
    lay.orders, lay.instruments, lay.samples, lay.patterns = struct.unpack_from("<HHHH", data, 0x20)
    for name, n in (("orders", lay.orders), ("instruments", lay.instruments), ("samples", lay.samples),
                    ("patterns", lay.patterns)):
        if n > IT_MAX_COUNT:
            raise PxsError("V1", "%d %s (at most %d)" % (n, name, IT_MAX_COUNT))
    special = _u16(data, 0x2E)
    table = IT_HEADER_LEN + lay.orders
    pointers_end = table + 4 * (lay.instruments + lay.samples + lay.patterns)
    regions: List[Tuple[int, int, str]] = [(0, pointers_end, "header")]
    pos = pointers_end
    if special & 2:                                   # edit history: u16 count, 8 bytes each
        if pos + 2 > end_limit:
            raise PxsError("V1", "the edit history runs past the module")
        n = _u16(data, pos)
        regions.append((pos, pos + 2 + 8 * n, "edit history"))
        pos += 2 + 8 * n
    if special & 8:                                   # embedded MIDI configuration
        regions.append((pos, pos + IT_MIDI_CONFIG_LEN, "midi configuration"))
    msg_len, msg_off = _u16(data, 0x36), _u32(data, 0x38)
    if special & 1 and msg_len:
        regions.append((msg_off, msg_off + msg_len, "message"))

    def ptr(i: int) -> int:
        return _u32(data, table + 4 * i)

    for i in range(lay.instruments):
        p = ptr(i)
        regions.append((p, p + IT_INSTRUMENT_LEN, "instrument %d" % (i + 1)))
        if p + 4 <= end_limit and data[p:p + 4] != b"IMPI":
            raise PxsError("V1", "instrument %d has no IMPI header" % (i + 1))
    for i in range(lay.samples):
        p = ptr(lay.instruments + i)
        regions.append((p, p + IT_SAMPLE_HEADER_LEN, "sample header %d" % (i + 1)))
        if p + IT_SAMPLE_HEADER_LEN > end_limit:
            raise PxsError("V1", "sample header %d lies outside the module" % (i + 1))
        if data[p:p + 4] != b"IMPS":
            raise PxsError("V1", "sample %d has no IMPS header" % (i + 1))
        flags = data[p + 0x12]
        frames, sptr = _u32(data, p + 0x30), _u32(data, p + 0x48)
        if flags & 1 and frames:
            wide, stereo = bool(flags & 2), bool(flags & 4)
            lay.stereo_samples += int(stereo)
            if flags & 8:
                send = _compressed_end(data, sptr, frames, wide, stereo)
            else:
                send = sptr + frames * (2 if wide else 1) * (2 if stereo else 1)
            regions.append((sptr, send, "sample data %d" % (i + 1)))
    for i in range(lay.patterns):
        p = ptr(lay.instruments + lay.samples + i)
        if p == 0:
            continue                                  # an empty 64-row pattern stored as no data
        if p + 8 > end_limit:
            raise PxsError("V1", "pattern %d lies outside the module" % i)
        length, rows = _u16(data, p), _u16(data, p + 2)
        if not 1 <= rows <= IT_MAX_ROWS:
            raise PxsError("V1", "pattern %d has %d rows (1 to %d)" % (i, rows, IT_MAX_ROWS))
        regions.append((p, p + 8 + length, "pattern %d" % i))

    regions = sorted(set(regions))
    covered, last_end = 0, 0
    for start, stop, what in regions:
        if stop > end_limit or start > stop:
            raise PxsError("V1", "%s lies outside the module" % what)
        if start < last_end:
            raise PxsError("V1", "%s overlaps another structure" % what)
        covered += stop - start
        last_end = stop
    lay.regions = regions
    lay.base_end = last_end
    lay.unaccounted = lay.base_end - covered
    if lay.unaccounted > MAX_UNACCOUNTED:
        raise PxsError("V1", "%d bytes inside the module belong to no structure (at most %d)"
                       % (lay.unaccounted, MAX_UNACCOUNTED))
    return lay


# ───────────────────────────────── the block ─────────────────────────────────

@dataclass(frozen=True)
class Chunk:
    id: str
    flags: int
    data: bytes                 # inflated when flag bit 0 was set and inflation was asked for


ChunkInput = Union[Tuple[str, bytes], Tuple[str, bytes, int]]


def _check_id(cid: str) -> bytes:
    raw = cid.encode("ascii")
    if len(raw) != 4 or not all(0x21 <= c <= 0x7E for c in raw):
        raise PxsError("V6", "chunk id %r is not four printable ASCII bytes" % cid)
    return raw


def build_block(chunks: Sequence[ChunkInput], block_offset: int, deflate: bool = False) -> bytes:
    """The block for a module whose base ends at `block_offset`. Chunks are (id, data) or
    (id, data, flags); with `deflate`, every chunk but HEAD is deflated (flag bit 0). HEAD must come
    first. The writer does not reorder or drop anything: budgets are the caller's."""
    body = bytearray()
    seen = set()
    norm: List[Tuple[str, bytes, int]] = []
    for ch in chunks:
        cid, data = ch[0], bytes(ch[1])
        flags = ch[2] if len(ch) > 2 else 0
        if deflate and cid != "HEAD" and not flags & FLAG_DEFLATED:
            data, flags = zlib.compress(data, 9), flags | FLAG_DEFLATED
        norm.append((cid, data, flags))
    if not norm or norm[0][0] != "HEAD":
        raise PxsError("V7", "HEAD must be the first chunk")
    if norm[0][2] != 0:
        raise PxsError("V7", "HEAD's flags must be 0")
    if len(norm) > MAX_CHUNKS:
        raise PxsError("V5", "%d chunks (at most %d)" % (len(norm), MAX_CHUNKS))
    for cid, data, flags in norm:
        raw = _check_id(cid)
        if raw[:1].isupper():
            if cid in seen:
                raise PxsError("V6", "chunk %s appears twice" % cid)
            seen.add(cid)
        body += raw + struct.pack("<II", len(data), flags) + data + b"\0" * (-len(data) % 4)
    total = HEADER_LEN + len(body) + FOOTER_LEN
    if total > MAX_BLOCK:
        raise PxsError("V5", "the block is %d bytes (at most %d)" % (total, MAX_BLOCK))
    block = MAGIC + struct.pack("<HHBBHI", MAJOR, MINOR, BASE_IT, 0, len(norm), total) + bytes(body)
    return block + FOOTER_MAGIC + struct.pack("<II", block_offset, zlib.crc32(block) & 0xFFFFFFFF)


def attach(module: bytes, chunks: Sequence[ChunkInput], deflate: bool = True,
           fingerprint: bool = True) -> bytes:
    """A .pxs: the module (which must pass the IT check and end at its last structure) plus a block.
    With `fingerprint`, "PXS1" is written into the IT header's reserved field at 0x3C."""
    lay = measure_it(module)
    if lay.base_end != len(module):
        raise PxsError("V3", "the module has %d bytes after its last structure" % (len(module) - lay.base_end))
    base = bytearray(module)
    if fingerprint:
        base[0x3C:0x40] = FINGERPRINT
    return bytes(base) + build_block(chunks, len(base), deflate=deflate)


def _parse_block(data: bytes, block_offset: int) -> Tuple[List[Tuple[str, int, bytes]], int]:
    """(chunks as (id, flags, stored data), minor) for the block at `block_offset`: V4-V6."""
    end = len(data) - FOOTER_LEN
    blk = data[block_offset:end]
    if zlib.crc32(blk) & 0xFFFFFFFF != _u32(data, len(data) - 4):
        raise PxsError("V4", "the CRC-32 does not match")
    if len(blk) < HEADER_LEN or blk[:4] != MAGIC:
        raise PxsError("V5", "no PXS block header at the block offset")
    major, minor, base, flags, count, total = struct.unpack_from("<HHBBHI", blk, 4)
    if major != MAJOR:
        raise PxsError("V5", "major version %d (this reader knows %d)" % (major, MAJOR))
    if base != BASE_IT:
        raise PxsError("V5", "base %r is not 'i'" % chr(base))
    if flags:
        raise PxsError("V5", "header flags %d (must be 0)" % flags)
    if not 1 <= count <= MAX_CHUNKS:
        raise PxsError("V5", "%d chunks (1 to %d)" % (count, MAX_CHUNKS))
    if total != len(blk) + FOOTER_LEN:
        raise PxsError("V5", "the header's length does not match the block")
    if total > MAX_BLOCK:
        raise PxsError("V5", "the block is %d bytes (at most %d)" % (total, MAX_BLOCK))
    out: List[Tuple[str, int, bytes]] = []
    seen = set()
    pos = HEADER_LEN
    for _ in range(count):
        if pos + CHUNK_HEADER_LEN > len(blk):
            raise PxsError("V6", "a chunk header runs past the footer")
        raw = blk[pos:pos + 4]
        length, cflags = struct.unpack_from("<II", blk, pos + 4)
        if not all(0x21 <= c <= 0x7E for c in raw):
            raise PxsError("V6", "chunk id %r is not printable" % raw)
        stop = pos + CHUNK_HEADER_LEN + length
        if stop > len(blk):
            raise PxsError("V6", "chunk %s runs past the footer" % raw.decode("ascii"))
        cid = raw.decode("ascii")
        if raw[:1].isupper():
            if cid in seen:
                raise PxsError("V6", "chunk %s appears twice" % cid)
            seen.add(cid)
        out.append((cid, cflags, blk[pos + CHUNK_HEADER_LEN:stop]))
        pos = stop + (-length % 4)
    if pos != len(blk):
        raise PxsError("V6", "the chunks do not end exactly at the footer")
    return out, minor


MAX_JSON_DEPTH = 32                                    # lists and objects one inside another (the PXS specification, §5)
_QUOTE_OR_BRACKET = re.compile(r'["\[\]{}]')           # what matters outside a string
_QUOTE_OR_ESCAPE = re.compile(r'["\\]')                # what matters inside one


def _refuse_constant(name: str):
    raise ValueError("%s is not JSON" % name)


def _finite(text: str) -> float:
    v = float(text)
    if not math.isfinite(v):
        raise ValueError("a number no 64-bit float holds")
    return v


def _int64(text: str) -> int:
    v = int(text)
    if not -(1 << 63) <= v < (1 << 63):
        raise ValueError("a whole number wider than 64 bits")
    return v


def _check_nesting(text: str) -> None:
    """Raises ValueError when lists and objects nest more than MAX_JSON_DEPTH deep. One pass over the text,
    which is either outside a string (a quote opens one, a bracket opens or closes a level) or inside one (a
    quote closes it, a backslash takes the next character with it). Every step moves on, so the time is the
    text's length whatever the text is. Text that is not JSON is json.loads's to refuse; this only counts."""
    depth, at = 0, 0
    while True:
        m = _QUOTE_OR_BRACKET.search(text, at)
        if m is None:
            return
        c, at = m.group(), m.end()
        if c == '"':
            while True:
                m = _QUOTE_OR_ESCAPE.search(text, at)
                if m is None:
                    return                      # the string never closes
                if m.group() == '"':
                    at = m.end()
                    break
                at = m.end() + 1                # the backslash and the character it escapes
        elif c in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("nested more than %d deep" % MAX_JSON_DEPTH)
        else:
            depth -= 1


def loads(text: str) -> Any:
    """The JSON a .pxs reader takes (the PXS specification, §5): RFC 8259 and no more (no NaN or Infinity), every number one a
    64-bit float holds and every whole number one 64 signed bits hold, at most 32 lists and objects one inside
    another. Raises ValueError for anything else, and never RecursionError: the depth is counted before the
    text is parsed. A name that comes twice keeps its last value."""
    _check_nesting(text)
    return json.loads(text, parse_constant=_refuse_constant, parse_float=_finite, parse_int=_int64)


def _check_head(chunks: List[Tuple[str, int, bytes]]) -> Dict[str, Any]:
    cid, flags, data = chunks[0]
    if cid != "HEAD":
        raise PxsError("V7", "the first chunk is %s, not HEAD" % cid)
    if flags != 0:
        raise PxsError("V7", "HEAD's flags must be 0")
    if len(data) > MAX_HEAD:
        raise PxsError("V7", "HEAD is %d bytes (at most %d)" % (len(data), MAX_HEAD))
    try:
        head = loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise PxsError("V7", "HEAD is not UTF-8 JSON") from None
    if not isinstance(head, dict):
        raise PxsError("V7", "HEAD is not a JSON object")
    if head.get("schema") != SCHEMA or head.get("base") != "it":
        raise PxsError("V7", 'HEAD must say "schema": "pxs/1" and "base": "it"')
    return head


@dataclass
class Verdict:
    valid: bool
    kind: str                           # "pxs", "it" (a plain module) or "invalid"
    rule: str = ""                      # the first rule broken, when invalid
    reason: str = ""
    base_end: int = 0
    block_offset: int = 0
    minor: int = 0
    chunks: List[Tuple[str, int, int]] = field(default_factory=list)   # (id, flags, stored length)
    head: Dict[str, Any] = field(default_factory=dict)
    stereo_samples: int = 0


def validate(data: bytes) -> Verdict:
    """The strict validator: V1-V9 with the agreed amendments. Never raises on bad input."""
    data = bytes(data)
    has_footer = len(data) >= IT_HEADER_LEN + HEADER_LEN + FOOTER_LEN and \
        data[len(data) - FOOTER_LEN:len(data) - 8] == FOOTER_MAGIC
    try:
        if not has_footer:
            lay = measure_it(data)
            trailing = len(data) - lay.base_end
            if lay.unaccounted + trailing > MAX_UNACCOUNTED:
                raise PxsError("V1", "%d bytes belong to no structure (at most %d)"
                               % (lay.unaccounted + trailing, MAX_UNACCOUNTED))
            return Verdict(True, "it", base_end=lay.base_end, stereo_samples=lay.stereo_samples)
        block_offset = _u32(data, len(data) - 8)
        if not IT_HEADER_LEN <= block_offset <= len(data) - FOOTER_LEN - HEADER_LEN:
            raise PxsError("V3", "the footer's block offset is out of range")
        lay = measure_it(data, limit=block_offset)
        if lay.base_end != block_offset:
            raise PxsError("V3", "the block starts at %d but the module ends at %d" % (block_offset, lay.base_end))
        chunks, minor = _parse_block(data, block_offset)
        head = _check_head(chunks)
        return Verdict(True, "pxs", base_end=lay.base_end, block_offset=block_offset, minor=minor,
                       chunks=[(c, f, len(d)) for c, f, d in chunks], head=head,
                       stereo_samples=lay.stereo_samples)
    except PxsError as exc:
        return Verdict(False, "invalid", exc.rule, exc.reason)


def read_chunks(data: bytes, inflate: bool = True) -> List[Chunk]:
    """The chunks of a valid .pxs, in file order. With `inflate`, deflated chunks come back
    inflated (at most 1 MiB each; a chunk that fails to inflate is skipped, as unknown flags are)."""
    v = validate(data)
    if v.kind != "pxs":
        raise PxsError(v.rule or "V3", v.reason or "not a .pxs")
    out: List[Chunk] = []
    for cid, flags, stored in _parse_block(bytes(data), v.block_offset)[0]:
        if inflate and flags & FLAG_DEFLATED:
            if flags & ~FLAG_DEFLATED:
                continue
            d = zlib.decompressobj()
            try:
                body = d.decompress(stored, MAX_INFLATED)
            except zlib.error:
                continue
            if d.unconsumed_tail:
                continue
            out.append(Chunk(cid, 0, body))
        else:
            out.append(Chunk(cid, flags, stored))
    return out
