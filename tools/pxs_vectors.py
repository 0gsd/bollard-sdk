#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
pxs_vectors.py: write conformance/pxs/blocks.json, the .pxs validation vectors.

    tools/pxs_vectors.py           write the file
    tools/pxs_vectors.py --check   write nothing; exit 1 when the file differs from what this makes

Every case is a whole file built here from a tiny IT module made up on the spot (two channels, one
instrument, one 64-frame generated waveform, one short pattern): no sample, name or text comes from
a real song. Valid cases are written with bollardeck.pxs; invalid ones break exactly one rule, by
hand. A case stores the file as "file_z64": base64 of the zlib-compressed bytes, so a 300 KiB case
stays small. Standard library only.
"""
import base64
import json
import math
import pathlib
import struct
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
from bollardeck import pxs  # noqa: E402

OUT = ROOT / "conformance" / "pxs" / "blocks.json"


def tiny_it(stereo: bool = False, rows: int = 2, message: str = "made up for the PXS vectors") -> bytes:
    """A minimal IT 2.14 module: header, orders, parapointers, message, IMPI, IMPS, a pattern, data."""
    frames = 64
    wave = [int(round(12000 * math.sin(2 * math.pi * i / frames))) for i in range(frames)]
    pcm = b"".join(struct.pack("<h", v) for v in wave)
    if stereo:                                              # IT stereo: the left channel, then the right
        pcm += b"".join(struct.pack("<h", -v) for v in wave)
    pattern = bytearray()
    pattern += bytes([0x81, 0x03, 60, 1]) + b"\0"           # row 0: channel 1, note C-5, instrument 1
    pattern += bytes([0x81, 0x01, 255]) + b"\0"             # row 1: note off
    pattern += b"\0" * max(0, rows - 2)                      # empty rows
    msg = message.encode("ascii") + b"\0"
    orders = bytes([0, 255])
    hdr_len = 0xC0 + len(orders) + 4 * 3
    msg_off = hdr_len
    ins_off = msg_off + len(msg)
    smp_off = ins_off + 554
    pat_off = smp_off + 80
    dat_off = pat_off + 8 + len(pattern)
    b = bytearray(b"IMPM" + b"PXS vector".ljust(26, b"\0"))
    b += struct.pack("<BB", 4, 16) + struct.pack("<HHHH", len(orders), 1, 1, 1)
    b += struct.pack("<HHHH", 0x0214, 0x0214, 0x000D, 0x0001)
    b += struct.pack("<BBBBBB", 128, 48, 6, 125, 128, 0)
    b += struct.pack("<HII", len(msg), msg_off, 0)
    b += bytes([32, 32] + [32 | 128] * 62) + bytes([64] * 64)
    b += orders + struct.pack("<III", ins_off, smp_off, pat_off)
    b += msg
    ins = bytearray(b"IMPI" + b"\0" * 13)
    ins += struct.pack("<BBBHbBBBBB", 2, 0, 0, 64, 0, 60, 128, 32 | 128, 0, 0)
    ins += struct.pack("<HBB", 0x0214, 1, 0) + b"made-up wave".ljust(26, b"\0") + struct.pack("<BBBBH", 0, 0, 0, 0, 0)
    for n in range(120):
        ins += bytes([n, 1])
    ins += bytes(82 * 3) + bytes(4)
    b += ins
    b += b"IMPS" + b"\0" * 13 + struct.pack("<BBB", 64, 1 | 2 | 16 | (4 if stereo else 0), 64)
    b += b"made-up wave".ljust(26, b"\0") + struct.pack("<BB", 1, 32)
    b += struct.pack("<IIIIIII", frames, 0, frames, 8363 * 4, 0, 0, dat_off) + bytes(4)
    b += struct.pack("<HHI", len(pattern), rows, 0) + pattern
    b += pcm
    return bytes(b)


HEAD = {"schema": "pxs/1", "base": "it", "origin": "band", "truth": "midi", "ref": "vectorrefaaaaaaaaaaaaaaaaa",
        "title": "Made Up Vector Song", "generator": "pxs_vectors", "public": False}
DSCL = {"genai": False, "ml": False, "items": [{"name": "pxs_vectors", "version": "1", "licence": "Apache-2.0",
                                                 "role": "made this vector", "ml": False, "genai": False}]}


def good(**kw) -> bytes:
    chunks = kw.pop("chunks", None) or [("HEAD", pxs.canonical_json(HEAD)), ("DSCL", pxs.canonical_json(DSCL))]
    return pxs.attach(tiny_it(**kw.pop("it", {})), chunks, deflate=kw.pop("deflate", True),
                      fingerprint=kw.pop("fingerprint", True))


def raw_block(module: bytes, chunks, *, offset=None, major=1, base=ord("i"), flags=0, count=None,
              total=None, crc=None, tail_pad=b"") -> bytes:
    """A block written by hand, with any field wrong on purpose."""
    body = bytearray()
    for cid, data, cflags in chunks:
        body += cid + struct.pack("<II", len(data), cflags) + data + b"\0" * (-len(data) % 4)
    body += tail_pad
    n = len(chunks) if count is None else count
    size = 16 + len(body) + 12 if total is None else total
    block = pxs.MAGIC + struct.pack("<HHBBHI", major, 0, base, flags, n, size) + bytes(body)
    c = zlib.crc32(block) & 0xFFFFFFFF if crc is None else crc
    off = len(module) if offset is None else offset
    return module + block + b"PXSF" + struct.pack("<II", off, c)


def head_bytes(**over) -> bytes:
    h = dict(HEAD)
    h.update(over)
    return pxs.canonical_json(h)


def cases():
    m = tiny_it()
    hd = pxs.canonical_json(HEAD)
    ds = pxs.canonical_json(DSCL)
    yield "plain-it", m, True, "it", "", "A module with no PXS footer is a plain IT."
    yield "minimal", good(), True, "pxs", "", "HEAD and DSCL, deflated DSCL, the fingerprint."
    yield "not-deflated", good(deflate=False), True, "pxs", "", "Chunks stored as they are."
    yield "no-fingerprint", good(fingerprint=False), True, "pxs", "", "V9: the fingerprint is never required."
    yield "stereo-sample", good(it={"stereo": True}), True, "pxs", "", "A3: 16-bit stereo samples are valid."
    yield "unknown-lowercase-chunk", good(chunks=[("HEAD", hd), ("DSCL", ds), ("pxyz", b"private")]), True, "pxs", "", "Private chunks are skipped."
    yield "unknown-uppercase-chunk", good(chunks=[("HEAD", hd), ("DSCL", ds), ("ZZZZ", b"later")]), True, "pxs", "", "A chunk from a later minor is skipped."
    yield "empty-lyrc", good(chunks=[("HEAD", hd), ("LYRC", b"")]), True, "pxs", "", "A14: LYRC is reserved; an empty one is fine."
    yield "sign-unknown-kid", good(chunks=[("HEAD", hd), ("DSCL", ds), ("SIGN", pxs.canonical_json({"alg": "ES256", "kid": "dev:aaaaaaaaaaaaaaaaaaaaaaaaaa", "sig": "AAAA"}))]), True, "pxs", "", "A4: a signature never affects validity; an unknown kid is unverified."
    yield "head-not-canonical", raw_block(m, [(b"HEAD", b'{ "schema" : "pxs/1",\n "base": "it", "extra": [1, 2] }', 0)]), True, "pxs", "", "Amendment 2: HEAD is checked for meaning, not canonical bytes."
    yield "chunk-unknown-flags", raw_block(m, [(b"HEAD", hd, 0), (b"DSCL", ds, 2)]), True, "pxs", "", "Amendment 3: only HEAD's flags are checked."
    yield "minor-7", raw_block(m, [(b"HEAD", hd, 0)]).replace(b"PXS\x1a\x01\x00\x00\x00", b"PXS\x1a\x01\x00\x07\x00", 1), False, "invalid", "V4", "Changing the minor without the CRC breaks V4 (the CRC covers the header)."
    # invalid: one rule each
    yield "not-it", b"\0" * 300 + raw_block(b"", [(b"HEAD", hd, 0)], offset=300)[0:], False, "invalid", "V1", "No IMPM header: not an IT module."
    bad_rows = bytearray(m)
    bad_rows[m.index(b"\x81\x03") - 6] = 0                        # the pattern's row count low byte
    bad_rows[m.index(b"\x81\x03") - 5] = 0
    yield "pattern-zero-rows", bytes(raw_block(bytes(bad_rows), [(b"HEAD", hd, 0)])), False, "invalid", "V1", "A pattern with 0 rows."
    yield "gap-before-block", raw_block(m + b"\0\0\0\0", [(b"HEAD", hd, 0)]), False, "invalid", "V3", "Four bytes between the module and the block: the offset is not base end."
    yield "offset-out-of-range", raw_block(m, [(b"HEAD", hd, 0)], offset=10), False, "invalid", "V3", "The footer points inside the IT header."
    yield "bad-crc", raw_block(m, [(b"HEAD", hd, 0)], crc=0), False, "invalid", "V4", "The CRC-32 does not match."
    yield "major-2", raw_block(m, [(b"HEAD", hd, 0)], major=2), False, "invalid", "V5", "An unknown major version."
    yield "base-x", raw_block(m, [(b"HEAD", hd, 0)], base=ord("x")), False, "invalid", "V5", "Base 'x' is reserved."
    yield "header-flags", raw_block(m, [(b"HEAD", hd, 0)], flags=1), False, "invalid", "V5", "Header flags must be 0."
    yield "zero-chunks", raw_block(m, [], count=0), False, "invalid", "V5", "A block needs at least HEAD."
    yield "length-mismatch", raw_block(m, [(b"HEAD", hd, 0)], total=999), False, "invalid", "V5", "The header's length is not the block's."
    yield "too-big", raw_block(m, [(b"HEAD", hd, 0), (b"BIGG", b"\0" * (300 * 1024), 0)]), False, "invalid", "V5", "A block over 256 KiB."
    yield "chunk-overrun", raw_block(m, [(b"HEAD", hd, 0)], count=2, tail_pad=b"CRED" + struct.pack("<II", 4096, 0)), False, "invalid", "V6", "A chunk runs past the footer."
    yield "short-walk", raw_block(m, [(b"HEAD", hd, 0)], tail_pad=b"\0" * 8), False, "invalid", "V6", "Bytes left between the last chunk and the footer."
    yield "repeated-uppercase", raw_block(m, [(b"HEAD", hd, 0), (b"CRED", b"{}", 0), (b"CRED", b"{}", 0)]), False, "invalid", "V6", "An uppercase id twice."
    yield "unprintable-id", raw_block(m, [(b"HEAD", hd, 0), (b"C\x00ED", b"", 0)]), False, "invalid", "V6", "A chunk id with a NUL."
    yield "head-not-first", raw_block(m, [(b"DSCL", ds, 0), (b"HEAD", hd, 0)]), False, "invalid", "V7", "HEAD must be the first chunk."
    yield "head-deflated", raw_block(m, [(b"HEAD", zlib.compress(hd), 1)]), False, "invalid", "V7", "HEAD's flags must be 0."
    yield "head-wrong-schema", raw_block(m, [(b"HEAD", head_bytes(schema="pxs/2"), 0)]), False, "invalid", "V7", "HEAD's schema must be pxs/1."
    yield "head-wrong-base", raw_block(m, [(b"HEAD", head_bytes(base="xm"), 0)]), False, "invalid", "V7", "HEAD's base must be it."
    yield "head-too-big", raw_block(m, [(b"HEAD", head_bytes(title="x" * 5000), 0)]), False, "invalid", "V7", "HEAD over 4 KiB."
    yield "head-not-json", raw_block(m, [(b"HEAD", b"schema=pxs/1", 0)]), False, "invalid", "V7", "HEAD is not JSON."
    yield "head-array", raw_block(m, [(b"HEAD", b'["pxs/1"]', 0)]), False, "invalid", "V7", "HEAD is not an object."
    yield "it-with-broken-footer", m + b"trailing junk, not a block" + b"PXSF" + struct.pack("<II", len(m), 0), False, "invalid", "V4", "Detection is by content: a PXSF footer makes it a .pxs, and the block must hold."
    # HEAD is read as the PXS specification's JSON (§5) (bollardeck.pxs.loads): one more field written by hand before its closing brace.
    def head_plus(extra: bytes) -> bytes:
        return raw_block(m, [(b"HEAD", hd[:-1] + extra + b"}", 0)])
    yield "v7-head-nan", head_plus(b',"x":NaN'), False, "invalid", "V7", "NaN is not JSON."
    yield "v7-head-infinity", head_plus(b',"x":-Infinity'), False, "invalid", "V7", "-Infinity is not JSON."
    yield "v7-head-number-too-large", head_plus(b',"x":1e400'), False, "invalid", "V7", "A number no 64-bit float holds."
    yield "v7-head-wide-integer", head_plus(b',"x":9223372036854775808'), False, "invalid", "V7", "A whole number wider than 64 signed bits."
    yield "v7-head-nested-33", head_plus(b',"x":' + b"[" * 32 + b"]" * 32), False, "invalid", "V7", "33 lists and objects one inside another (HEAD is the first)."
    yield "v7-head-nested-1500", head_plus(b',"x":' + b"[" * 1500 + b"]" * 1500), False, "invalid", "V7", "Far too deep; counted before parsing, so no RecursionError on Python 3.11."
    yield "head-nested-32", head_plus(b',"x":' + b"[" * 31 + b"]" * 31), True, "pxs", "", "32 lists and objects one inside another, the most allowed."
    yield "head-widest-integers", head_plus(b',"x":[9223372036854775807,-9223372036854775808]'), True, "pxs", "", "The widest whole numbers 64 signed bits hold."


def document() -> dict:
    out = []
    for name, data, valid, kind, rule, why in cases():
        out.append({"name": name, "file_z64": base64.b64encode(zlib.compress(data, 9)).decode("ascii"),
                    "bytes": len(data), "expect": {"valid": valid, "kind": kind, "rule": rule}, "why": why})
    return {"version": 1,
            "about": ("Validation vectors for .pxs (PXS specification v1, rules V1-V9 with the agreed "
                      "amendments). Each file_z64 is base64 of the zlib-compressed file. Run validate(file) "
                      "and compare valid and kind; for an invalid file, the first rule broken must be "
                      "expect.rule. Every module here is made up by tools/pxs_vectors.py."),
            "generated_by": "tools/pxs_vectors.py",
            "cases": out}


def main(argv) -> int:
    text = json.dumps(document(), indent=1, sort_keys=False) + "\n"
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("conformance/pxs/blocks.json is stale: run tools/pxs_vectors.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print("wrote %s (%d cases)" % (OUT.relative_to(ROOT), len(document()["cases"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
