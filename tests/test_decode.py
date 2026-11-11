# SPDX-License-Identifier: Apache-2.0
"""bollardeck.device.decode (SDK 0.2.0): sniffing, the registry, the WebM reader, and each codec where
its library or program is installed (skipped where it is not)."""
import ctypes
import io
import math
import os
import shutil
import sys
import time
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from bollardeck.device import decode  # noqa: E402


def vint_size(n):
    if n < 0x7F:
        return bytes([0x80 | n])
    if n < 0x3FFF:
        return struct.pack(">H", 0x4000 | n)
    return struct.pack(">I", 0x10000000 | n)


def el(eid, payload):
    return bytes.fromhex(eid) + vint_size(len(payload)) + payload


def uint(n, width=1):
    return n.to_bytes(width, "big")


def webm(packets, channels=1, private=b"OpusHead\x01\x01\x38\x01\x80\xbb\x00\x00\x00\x00\x00", scale=1000000):
    """A small WebM file: one Opus track, one cluster per packet list [(t_ms, bytes)]."""
    track = el("AE", el("D7", uint(1)) + el("83", uint(2)) + el("86", b"A_OPUS") + el("63A2", private)
               + el("E1", el("B5", struct.pack(">d", 48000.0)) + el("9F", uint(channels))))
    body = el("1549A966", el("2AD7B1", uint(scale, 3))) + el("1654AE6B", track)
    cluster = el("E7", uint(0))
    for t, frame in packets:
        cluster += el("A3", b"\x81" + struct.pack(">hB", t, 0x80) + frame)
    body += el("1F43B675", cluster)
    return el("1A45DFA3", el("4282", b"webm")) + el("18538067", body)


class Sniffing(unittest.TestCase):
    def test_magic_numbers(self):
        cases = {b"\x1a\x45\xdf\xa3....": "webm", b"fLaC....": "flac", b"OggS....": "ogg",
                 b"RIFF\x00\x00\x00\x00WAVE": "wav", b"\x00\x00\x00\x20ftypM4A ": "mp4", b"ID3\x04": "mp3",
                 b"\xff\xfb\x90\x00": "mp3", b"\xff\xf1\x50\x80": "adts", b"hello": None}
        for head, want in cases.items():
            self.assertEqual(decode.sniff_kind(head), want, head)


class Registry(unittest.TestCase):
    def test_a_registered_decoder_is_asked_first_and_can_go_again(self):
        class Wrapper:
            name = "wrapper"

            def available(self):
                return True

            def sniff(self, head, path):
                return head.startswith(b"WRAP")

            def open(self, path, offset_ms=0):
                raise NotImplementedError

        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "x.bin")
            p.write_bytes(b"WRAP" + bytes(60))
            decode.register(Wrapper())
            try:
                self.assertEqual(decode.for_path(p).name, "wrapper")
                self.assertEqual(decode.decoders()[0].name, "wrapper")
            finally:
                decode.unregister("wrapper")
            self.assertIsNone(decode.for_path(p))
        self.assertEqual([d.name for d in decode.decoders()], ["webm-opus", "sndfile", "faad"])


class WebmReader(unittest.TestCase):
    def test_tracks_and_packets_with_times(self):
        data = webm([(0, b"aa"), (20, b"bbb"), (40, b"c")], channels=2, scale=1000000)
        items = list(decode.webm_packets(io.BytesIO(data)))
        self.assertEqual(items[0][0], "track")
        self.assertEqual((items[0][1]["codec"], items[0][1]["channels"], items[0][1]["rate"]), ("A_OPUS", 2, 48000.0))
        self.assertEqual([v for k, v in items[1:]], [(1, 0, b"aa"), (1, 20, b"bbb"), (1, 40, b"c")])

    def test_a_laced_block_is_refused(self):
        data = webm([(0, b"aa")])
        data = data.replace(struct.pack(">hB", 0, 0x80), struct.pack(">hB", 0, 0x82))
        with self.assertRaises(ValueError):
            list(decode.webm_packets(io.BytesIO(data)))


def _wav(path, rate=8000, seconds=1.0):
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", (i % 1000)) for i in range(frames)))
    return frames


@unittest.skipUnless(decode.Sndfile().available(), "libsndfile is not installed")
class SndfileDecoding(unittest.TestCase):
    def test_a_wav_from_the_start_and_from_an_offset(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "ramp.wav")
            n = _wav(p)
            dec = decode.for_path(p)
            self.assertEqual(dec.name, "sndfile")
            with dec.open(p) as pcm:
                self.assertEqual((pcm.rate, pcm.channels), (8000, 1))
                whole = b""
                while True:
                    block = pcm.read(1000)
                    if not block:
                        break
                    whole += block
            self.assertEqual(len(whole), n * 2)
            with dec.open(p, offset_ms=250) as pcm:
                first = struct.unpack("<h", pcm.read(1))[0]
            self.assertEqual(first, 2000 % 1000)          # frame 2000 of the ramp


def _opus():
    try:
        return decode._lib("opus")
    except Exception:  # noqa: BLE001
        return None


@unittest.skipUnless(_opus() is not None, "libopus is not installed")
class WebmOpusDecoding(unittest.TestCase):
    def encode(self, seconds=1.0, hz=440):
        lib = _opus()
        err = ctypes.c_int(0)
        lib.opus_encoder_create.restype = ctypes.c_void_p
        lib.opus_encoder_create.argtypes = [ctypes.c_int32, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        lib.opus_encode.restype = ctypes.c_int32
        lib.opus_encode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int32]
        lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
        enc = lib.opus_encoder_create(48000, 1, 2049, ctypes.byref(err))   # OPUS_APPLICATION_AUDIO
        self.assertEqual(err.value, 0)
        packets = []
        frame = 960                                         # 20 ms
        for k in range(int(seconds * 50)):
            pcm = (ctypes.c_short * frame)(*[int(8000 * math.sin(2 * math.pi * hz * (k * frame + i) / 48000))
                                             for i in range(frame)])
            out = ctypes.create_string_buffer(4000)
            n = lib.opus_encode(enc, pcm, frame, out, 4000)
            self.assertGreater(n, 0)
            packets.append((k * 20, out.raw[:n]))
        lib.opus_encoder_destroy(enc)
        return packets

    def test_a_round_trip_and_an_offset(self):
        packets = self.encode()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "tone.webm")
            p.write_bytes(webm(packets, channels=1, private=b"OpusHead\x01\x01\x00\x00\x80\xbb\x00\x00\x00\x00\x00"))
            dec = decode.for_path(p)
            self.assertEqual(dec.name, "webm-opus")
            with dec.open(p) as pcm:
                self.assertEqual((pcm.rate, pcm.channels), (48000, 1))
                total = 0
                while True:
                    block = pcm.read(4800)
                    if not block:
                        break
                    total += len(block) // 2
            self.assertEqual(total, 48000)                  # 50 packets of 20 ms, no pre-skip
            with dec.open(p, offset_ms=500) as pcm:
                rest = 0
                while True:
                    block = pcm.read(4800)
                    if not block:
                        break
                    rest += len(block) // 2
            self.assertEqual(rest, 24000)                   # the second half


@unittest.skipUnless(decode.Faad().available(), "faad is not installed")
class FaadDecoding(unittest.TestCase):
    def test_faad_is_found(self):
        self.assertTrue(decode.Faad().program())


FAKE_FAAD = """import struct, sys, time
open(sys.argv[0] + ".argv", "w").write("\\n".join(sys.argv[1:]))
if "{mode}" == "hang":
    time.sleep(30)
data = struct.pack("<h", 7) * 8000
fmt = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
sys.stdout.buffer.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
                        + b"data" + struct.pack("<I", len(data)) + data)
"""


class FaadRobustness(unittest.TestCase):
    """An absolute path, the offset on the first read, a bounded wait."""

    def fake(self, d, mode="ok"):
        prog = Path(d, "faad")
        prog.write_text("#!" + sys.executable + "\n" + FAKE_FAAD.replace("{mode}", mode))
        prog.chmod(0o755)
        return prog

    def test_a_name_that_starts_with_a_dash_is_never_an_option(self):
        with tempfile.TemporaryDirectory() as d:
            prog = self.fake(d)
            f = Path(d, "-o.aac")
            f.write_bytes(b"\xff\xf1" + bytes(62))                       # ADTS
            with mock.patch.dict(os.environ, {"BOLLARDECK_FAAD": str(prog)}):
                with decode.Faad().open(f, 500) as pcm:                    # returns before the offset is reached
                    self.assertEqual((pcm.rate, pcm.channels), (8000, 1))
                    self.assertEqual(len(pcm.read(100)), 200)               # the first read drops 0.5 s first
            argv = Path(str(prog) + ".argv").read_text().splitlines()
            self.assertEqual(argv[-1], str(f.resolve()))
            self.assertTrue(argv[-1].startswith("/"))

    def test_a_faad_that_never_begins_is_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            prog = self.fake(d, "hang")
            f = Path(d, "x.aac")
            f.write_bytes(b"\xff\xf1" + bytes(62))
            with mock.patch.dict(os.environ, {"BOLLARDECK_FAAD": str(prog)}), \
                    mock.patch.object(decode, "FAAD_HEADER_S", 0.5):
                t0 = time.monotonic()
                with self.assertRaises(decode.DecodeError):
                    decode.Faad().open(f, 0)
                self.assertLess(time.monotonic() - t0, 10)


class OneErrorType(unittest.TestCase):
    """Every decoder's damaged-file error is one DecodeError, a ValueError."""

    def test_decode_error_is_a_value_error_and_struct_errors_become_it(self):
        self.assertTrue(issubclass(decode.DecodeError, ValueError))
        with self.assertRaises(decode.DecodeError):
            decode._unpack(">hB", b"\x00")
        data = webm([(0, b"aa")]).replace(struct.pack(">hB", 0, 0x80), struct.pack(">hB", 0, 0x82))
        with self.assertRaises(decode.DecodeError):
            list(decode.webm_packets(io.BytesIO(data)))

    @unittest.skipUnless(decode.Sndfile().available(), "libsndfile is not installed")
    def test_a_file_libsndfile_cannot_open(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "x.mp3")
            f.write_bytes(b"\xff\xfb" + b"not audio at all" * 4)
            with self.assertRaises(decode.DecodeError):
                decode.Sndfile().open(f, 0)


if __name__ == "__main__":
    unittest.main()
