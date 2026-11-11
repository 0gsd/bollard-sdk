# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.decode: audio files to PCM, for a board's FilePlayer (SDK 0.2.0). Standard library
only: the codecs are reached through ctypes (libsndfile, libopus) or as a separate program (faad),
and each says it is unavailable where its library or program is missing.

    from bollardeck.device import decode
    d = decode.for_path(path)                 # the first decoder that takes this file, or None
    with d.open(path, offset_ms=30000) as pcm:
        pcm.rate, pcm.channels                # e.g. 48000, 2
        block = pcm.read(4096)                # up to 4096 frames of signed 16-bit little-endian PCM

## The decoders, in the order they are asked

1. Registered ones, newest first: `decode.register(decoder)`. A program adds containers of its own
   this way (a wrapper format that holds one of the formats below), without this module knowing
   them.
2. `webm-opus`: a small Matroska (WebM) reader for Opus audio tracks, decoding with libopus.
3. `sndfile`: libsndfile (MP3, FLAC, Ogg Vorbis, Ogg Opus, WAV, AIFF, as the installed library allows).
4. `faad`: the faad program for AAC, in MP4/M4A (seeks with `-j`) or raw ADTS (decodes and discards
   up to the offset).

A decoder is any object with `name`, `sniff(head, path) -> bool` (`head` is the file's first 64
bytes), `available() -> bool` and `open(path, offset_ms) -> PCM stream` (with `rate`, `channels`,
`read(frames) -> bytes`, `close()`, and use as a context manager). `for_path` asks each available
decoder in order and returns the first whose sniff says yes. MIDI is not here: a board plays MIDI
through `AudioOut.play_midi`.

Libraries are found by `ctypes.util.find_library`, then by common file names, or named outright with
$BOLLARDECK_LIBSNDFILE and $BOLLARDECK_LIBOPUS; the program by $BOLLARDECK_FAAD or the PATH.

A file that cannot be decoded raises `DecodeError` (a `ValueError`), whichever decoder found it so and
whether it was found in `open` or in a later `read`; a decoder that is missing raises `RuntimeError`.
faad is given the file's absolute path (a name that starts with "-" is never an option) and has
FAAD_HEADER_S to begin its WAV; a raw ADTS file's offset is reached on the first read, not in `open`.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import io
import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any, BinaryIO, Iterator, List, Optional, Tuple

__all__ = ["Pcm", "register", "unregister", "decoders", "for_path", "sniff_kind", "WebmOpus", "Sndfile", "Faad",
           "webm_packets", "HEAD_BYTES", "DecodeError", "FAAD_HEADER_S"]

HEAD_BYTES = 64
FAAD_HEADER_S = 10.0          # how long faad may take to begin its WAV before it is stopped


class DecodeError(ValueError):
    """The file cannot be decoded: damaged, truncated, or not what it looked like."""


def _unpack(fmt: str, data: bytes) -> Tuple[Any, ...]:
    try:
        return struct.unpack(fmt, data)
    except struct.error as exc:
        raise DecodeError("a short or damaged field (%s)" % exc) from None
_REGISTERED: List[Any] = []


# ---------------------------------------------------------------- the stream shape

class Pcm:
    """A PCM stream: `rate`, `channels`, read(frames) -> s16le bytes ("" at the end), close()."""
    rate: int = 0
    channels: int = 0

    def read(self, frames: int) -> bytes:  # pragma: no cover - the base reads nothing
        return b""

    def close(self) -> None:
        return None

    def __enter__(self) -> "Pcm":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------- sniffing

def sniff_kind(head: bytes) -> Optional[str]:
    """What a file's first bytes say it is: "webm", "flac", "ogg", "wav", "aiff", "mp4", "adts",
    "mp3", or None."""
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xF0) == 0xF0 and (head[1] & 0x06) == 0:
        return "adts"                                   # MPEG-4 sync with layer 00
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0 and (head[1] & 0x06) != 0:
        return "mp3"                                    # MPEG audio frame sync, layer I-III
    return None


def _head(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(HEAD_BYTES)


# ---------------------------------------------------------------- libraries

def _load(env: str, names: Tuple[str, ...], stem: str) -> Optional[ctypes.CDLL]:
    candidates: List[str] = []
    if os.environ.get(env):
        candidates.append(os.environ[env])
    found = ctypes.util.find_library(stem)
    if found:
        candidates.append(found)
    candidates.extend(names)
    for c in candidates:
        try:
            return ctypes.CDLL(c)
        except OSError:
            continue
    return None


_LIBS: dict = {}


def _lib(key: str) -> Optional[ctypes.CDLL]:
    if key not in _LIBS:
        if key == "sndfile":
            _LIBS[key] = _load("BOLLARDECK_LIBSNDFILE", ("libsndfile.so.1", "libsndfile.1.dylib",
                               "/opt/homebrew/lib/libsndfile.dylib", "/usr/local/lib/libsndfile.dylib"), "sndfile")
        else:
            _LIBS[key] = _load("BOLLARDECK_LIBOPUS", ("libopus.so.0", "libopus.0.dylib",
                               "/opt/homebrew/lib/libopus.dylib", "/usr/local/lib/libopus.dylib"), "opus")
    return _LIBS[key]


# ---------------------------------------------------------------- libsndfile

class _SfInfo(ctypes.Structure):
    _fields_ = [("frames", ctypes.c_int64), ("samplerate", ctypes.c_int), ("channels", ctypes.c_int),
                ("format", ctypes.c_int), ("sections", ctypes.c_int), ("seekable", ctypes.c_int)]


class _SndfilePcm(Pcm):
    def __init__(self, lib: ctypes.CDLL, path: Path, offset_ms: int):
        self._lib = lib
        info = _SfInfo()
        lib.sf_open.restype = ctypes.c_void_p
        lib.sf_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(_SfInfo)]
        self._sf = lib.sf_open(os.fsencode(str(path)), 0x10, ctypes.byref(info))
        if not self._sf:
            raise DecodeError("libsndfile cannot open %s" % path)
        self.rate, self.channels = int(info.samplerate), int(info.channels)
        lib.sf_readf_short.restype = ctypes.c_int64
        lib.sf_readf_short.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
        lib.sf_seek.restype = ctypes.c_int64
        lib.sf_seek.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_int]
        lib.sf_close.argtypes = [ctypes.c_void_p]
        skip = int(offset_ms) * self.rate // 1000
        if skip and lib.sf_seek(self._sf, skip, 0) < 0:      # not seekable: read and drop
            while skip > 0:
                n = len(self.read(min(skip, 4096))) // (2 * self.channels)
                if n == 0:
                    break
                skip -= n

    def read(self, frames: int) -> bytes:
        if not self._sf or frames <= 0:
            return b""
        buf = (ctypes.c_short * (int(frames) * self.channels))()
        got = self._lib.sf_readf_short(self._sf, buf, int(frames))
        return bytes(buf)[: max(0, int(got)) * self.channels * 2]

    def close(self) -> None:
        if self._sf:
            self._lib.sf_close(self._sf)
            self._sf = None


class Sndfile:
    name = "sndfile"
    kinds = ("flac", "ogg", "wav", "aiff", "mp3")

    def available(self) -> bool:
        return _lib("sndfile") is not None

    def sniff(self, head: bytes, path: Path) -> bool:
        return sniff_kind(head) in self.kinds

    def open(self, path: Path, offset_ms: int = 0) -> Pcm:
        lib = _lib("sndfile")
        if lib is None:
            raise RuntimeError("libsndfile is not installed")
        return _SndfilePcm(lib, Path(path), int(offset_ms))


# ---------------------------------------------------------------- WebM (Matroska) with Opus

_SEGMENT, _CLUSTER, _TRACKS, _TRACK, _INFO = 0x18538067, 0x1F43B675, 0x1654AE6B, 0xAE, 0x1549A966
_MASTERS = {_SEGMENT, _CLUSTER, _TRACKS, _TRACK, _INFO, 0xE1, 0xA0}      # elements we step into
_TIMECODE_SCALE, _CLUSTER_TIME, _SIMPLE, _BLOCK = 0x2AD7B1, 0xE7, 0xA3, 0xA1
_TRACK_NUMBER, _CODEC_ID, _CODEC_PRIVATE, _RATE, _CHANNELS, _TRACK_TYPE = 0xD7, 0x86, 0x63A2, 0xB5, 0x9F, 0x83


def _vint(fh: BinaryIO, keep_marker: bool) -> Tuple[Optional[int], int]:
    first = fh.read(1)
    if not first:
        return None, 0
    b = first[0]
    length = 1
    mask = 0x80
    while length <= 8 and not (b & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise DecodeError("not an EBML number")
    rest = fh.read(length - 1)
    if len(rest) != length - 1:
        return None, 0
    value = b if keep_marker else (b & (mask - 1))
    for x in rest:
        value = (value << 8) | x
    if not keep_marker and value == (1 << (7 * length)) - 1:
        value = -1                                      # unknown size
    return value, length


def _uint(data: bytes) -> int:
    return int.from_bytes(data, "big") if data else 0


def webm_packets(fh: BinaryIO) -> Iterator[Tuple[str, Any]]:
    """Read a WebM stream: yields ("track", {number, codec, rate, channels, private}) for each audio
    track, then ("packet", (track number, time in ms, frame bytes)) in file order. Lacing other
    than none is refused (Opus in WebM is not laced)."""
    scale = 1_000_000
    cluster_ms = 0
    track: dict = {}
    ends: List[int] = []

    def pos() -> int:
        return fh.tell()

    while True:
        while ends and pos() >= ends[-1]:
            done = ends.pop()
            if track and done == track.get("_end"):
                if track.get("type", 2) == 2:
                    yield "track", {k: v for k, v in track.items() if not k.startswith("_")}
                track = {}
        eid, _ = _vint(fh, keep_marker=True)
        if eid is None:
            return
        size, _ = _vint(fh, keep_marker=False)
        if size is None:
            return
        start = pos()
        if eid in _MASTERS:
            if size >= 0:
                ends.append(start + size)
            if eid == _TRACK:
                track = {"_end": start + size if size >= 0 else None}
            continue
        if size < 0:
            raise DecodeError("an element of unknown size that is not a container")
        data = fh.read(size)
        if len(data) != size:
            return
        if eid == _TIMECODE_SCALE:
            scale = _uint(data) or scale
        elif eid == _CLUSTER_TIME:
            cluster_ms = _uint(data) * scale // 1_000_000
        elif eid in (_SIMPLE, _BLOCK):
            b = io.BytesIO(data)
            number, _ = _vint(b, keep_marker=False)
            rel, flags = _unpack(">hB", b.read(3))
            if flags & 0x06:
                raise DecodeError("laced blocks are not supported")
            yield "packet", (number, cluster_ms + rel * scale // 1_000_000, b.read())
        elif track is not None and "_end" in track:
            if eid == _TRACK_NUMBER:
                track["number"] = _uint(data)
            elif eid == _TRACK_TYPE:
                track["type"] = _uint(data)
            elif eid == _CODEC_ID:
                track["codec"] = data.decode("ascii", "replace").rstrip("\x00")
            elif eid == _CODEC_PRIVATE:
                track["private"] = data
            elif eid == _RATE:
                track["rate"] = _unpack(">d" if size == 8 else ">f", data)[0]
            elif eid == _CHANNELS:
                track["channels"] = _uint(data)


class _WebmOpusPcm(Pcm):
    PREROLL_MS = 80                                    # Opus needs this much to settle after a jump

    def __init__(self, lib: ctypes.CDLL, path: Path, offset_ms: int):
        self._fh = open(path, "rb")
        self._items = webm_packets(self._fh)
        self._track: Optional[dict] = None
        self._first: Optional[Tuple[int, int, bytes]] = None
        for kind, value in self._items:
            if kind == "track" and value.get("codec") == "A_OPUS" and self._track is None:
                self._track = value
            elif kind == "packet" and self._track is not None and value[0] == self._track.get("number"):
                self._first = value
                break
        if self._track is None:
            self.close()
            raise DecodeError("%s has no Opus audio track" % path)
        self.rate = 48000                               # Opus always decodes at 48 kHz here
        self.channels = int(self._track.get("channels") or 2)
        head = self._track.get("private") or b""
        self._skip = struct.unpack("<H", head[10:12])[0] if len(head) >= 12 and head[:8] == b"OpusHead" else 0
        self._lib = lib
        err = ctypes.c_int(0)
        lib.opus_decoder_create.restype = ctypes.c_void_p
        lib.opus_decoder_create.argtypes = [ctypes.c_int32, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        lib.opus_decode.restype = ctypes.c_int
        lib.opus_decode.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int]
        lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        self._dec = lib.opus_decoder_create(48000, self.channels, ctypes.byref(err))
        if not self._dec or err.value != 0:
            self.close()
            raise RuntimeError("libopus would not make a decoder (%d)" % err.value)
        self._buf = b""
        self._offset = int(offset_ms)
        self._drop = 0                                  # frames still to throw away before the offset

    def _packets(self) -> Iterator[Tuple[int, bytes]]:
        if self._first is not None:
            first, self._first = self._first, None
            yield first[1], first[2]
        for kind, value in self._items:
            if kind == "packet" and self._track is not None and value[0] == self._track.get("number"):
                yield value[1], value[2]

    def _fill(self) -> bool:
        if not hasattr(self, "_iter"):
            self._iter = self._packets()
            self._started = False
        out = (ctypes.c_short * (5760 * self.channels))()
        for t_ms, frame in self._iter:
            if not self._started:
                if t_ms + 120 < self._offset - self.PREROLL_MS:
                    continue                            # far before the offset: not even decoded
                self._started = True
                self._drop = max(0, (self._offset - t_ms) * 48) + (self._skip if t_ms <= 0 else 0)
            n = self._lib.opus_decode(self._dec, frame, len(frame), out, 5760, 0)
            if n < 0:
                continue                                # a damaged packet: skip it
            pcm = bytes(out)[: n * self.channels * 2]
            if self._drop:
                cut = min(self._drop, n)
                self._drop -= cut
                pcm = pcm[cut * self.channels * 2:]
            if pcm:
                self._buf += pcm
                return True
        return False

    def read(self, frames: int) -> bytes:
        want = int(frames) * self.channels * 2
        try:
            while len(self._buf) < want and self._fill():
                pass
        except struct.error as exc:
            raise DecodeError("a damaged block (%s)" % exc) from None
        out, self._buf = self._buf[:want], self._buf[want:]
        return out

    def close(self) -> None:
        if getattr(self, "_dec", None):
            self._lib.opus_decoder_destroy(self._dec)
            self._dec = None
        if getattr(self, "_fh", None):
            self._fh.close()
            self._fh = None


class WebmOpus:
    name = "webm-opus"

    def available(self) -> bool:
        return _lib("opus") is not None

    def sniff(self, head: bytes, path: Path) -> bool:
        return sniff_kind(head) == "webm"

    def open(self, path: Path, offset_ms: int = 0) -> Pcm:
        lib = _lib("opus")
        if lib is None:
            raise RuntimeError("libopus is not installed")
        return _WebmOpusPcm(lib, Path(path), int(offset_ms))


# ---------------------------------------------------------------- faad (AAC)

class _ProcessPcm(Pcm):
    """WAV on a program's standard output."""

    def __init__(self, argv: List[str], drop_ms: int = 0, header_s: Optional[float] = None):
        import threading
        self._proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out = self._proc.stdout
        assert out is not None
        self._out = out
        # a program that never begins its WAV is stopped, so open() cannot hang
        timer = threading.Timer(FAAD_HEADER_S if header_s is None else header_s, self._proc.kill)
        timer.daemon = True
        timer.start()
        try:
            riff = out.read(12)
            if riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
                self.close()
                raise DecodeError("the decoder wrote no WAV")
            while True:
                hdr = out.read(8)
                if len(hdr) < 8:
                    self.close()
                    raise DecodeError("the decoder's WAV has no data")
                cid, size = hdr[:4], _unpack("<I", hdr[4:])[0]
                if cid == b"fmt ":
                    fmt = out.read(size)
                    self.channels, self.rate = _unpack("<HI", fmt[2:8])
                elif cid == b"data":
                    break
                else:
                    out.read(size)
        finally:
            timer.cancel()
        self._drop = int(drop_ms) * self.rate // 1000 * self.channels * 2     # reached on the first read

    def read(self, frames: int) -> bytes:
        if not self._proc:
            return b""
        while self._drop > 0:
            got = self._out.read(min(self._drop, 65536))
            if not got:
                self._drop = 0
                return b""
            self._drop -= len(got)
        return self._out.read(int(frames) * self.channels * 2)

    def close(self) -> None:
        if getattr(self, "_proc", None):
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc.wait()
            self._proc = None


class Faad:
    name = "faad"

    def program(self) -> Optional[str]:
        return os.environ.get("BOLLARDECK_FAAD") or shutil.which("faad")

    def available(self) -> bool:
        return self.program() is not None

    def sniff(self, head: bytes, path: Path) -> bool:
        return sniff_kind(head) in ("mp4", "adts")

    def open(self, path: Path, offset_ms: int = 0) -> Pcm:
        prog = self.program()
        if prog is None:
            raise RuntimeError("faad is not installed")
        offset_ms = int(offset_ms)
        where = str(Path(path).resolve())               # absolute: a name that starts with "-" is not an option
        if sniff_kind(_head(Path(path))) == "mp4" and offset_ms >= 1000:
            whole = offset_ms // 1000                   # faad jumps whole seconds; the rest is dropped
            return _ProcessPcm([prog, "-w", "-j", str(whole), where], offset_ms - whole * 1000)
        return _ProcessPcm([prog, "-w", where], offset_ms)


# ---------------------------------------------------------------- the registry

BUILT_IN = (WebmOpus(), Sndfile(), Faad())


def register(decoder: Any) -> None:
    """Ask `decoder` before every other (and before those registered earlier)."""
    unregister(getattr(decoder, "name", ""))
    _REGISTERED.insert(0, decoder)


def unregister(name: str) -> None:
    _REGISTERED[:] = [d for d in _REGISTERED if getattr(d, "name", None) != name]


def decoders() -> List[Any]:
    """Every decoder in the order `for_path` asks them, available or not."""
    return list(_REGISTERED) + list(BUILT_IN)


def for_path(path: Path) -> Optional[Any]:
    """The first available decoder whose sniff takes this file, or None."""
    head = _head(Path(path))
    for d in decoders():
        try:
            if d.available() and d.sniff(head, Path(path)):
                return d
        except Exception:  # noqa: BLE001 - a broken plug-in never stops the built-ins
            continue
    return None
