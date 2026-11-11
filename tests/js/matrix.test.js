// SPDX-License-Identifier: Apache-2.0
// bollardeck.matrix: the engine makes, byte for byte, the frame of every vector under
// conformance/matrix/. tools/pin_vectors.py wrote the expected values from the Python engine,
// bollardeck.matrix, and cross-checked them against the device's; tests/test_matrix.py holds the
// Python engine to the same vectors.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { CONFORMANCE, readJson, jsonFiles, bollardeck } = require("./support.js");

const M = bollardeck.matrix;
const files = jsonFiles(path.join(CONFORMANCE, "matrix"));
const or = (v, d) => (v === undefined ? d : v);

// One vector's call, with the vector files' argument names.
function run(call, a) {
  switch (call) {
    case "film": return M.toHex(M.film(a.song, a.t_ms, !!a.calm));
    case "playback": return M.toHex(M.playback(a.song, a.pos_s, !!a.calm));
    case "idle": return M.toHex(M.idle(a.t_ms, !!a.calm, a.temperament));
    case "corpus": return M.toHex(M.corpus(a.t_ms, or(a.level, 0), a.bands, !!a.calm));
    case "glyph": return M.toHex(M.glyph(a.name, a.t_ms, !!a.calm));
    case "dj": return M.toHex(M.dj(a.seg, a.pos_s, or(a.t_ms, 0), !!a.calm));
    case "text": return M.toHex(M.text(a.text, a.t_ms, !!or(a.loop, true), or(a.priority, "pairing"), a.ttl_ms, !!a.calm));
    case "premiere": return M.toHex(M.premiere(a.number, a.t_ms, !!a.opened, !!a.calm, or(a.tier, "")));
    case "tone": return M.toHex(M.tone(M.fromHex(a.frame), a.tone));
    case "dj_beat": return M.djBeat(a.seg, a.pos_s);
    case "dj_crossfader": return M.djCrossfader(a.seg, a.pos_s);
    case "dj_camelot": return M.djCamelot(a.value);
    case "text_pass_ms": return M.textPassMs(a.text);
    case "str_seed": return M.strSeed(a.text);
    case "ascii": return M.ascii(M.fromHex(a.frame));
    default: throw new Error("no matrix call named " + call);
  }
}

function resolve(args, fixtures) {
  const out = {};
  for (const [key, value] of Object.entries(args)) {
    const isRef = value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).join() === "$fixture";
    out[key] = isRef ? fixtures[value.$fixture] : value;
  }
  return out;
}

test("there are vectors for every part of the engine", () => {
  const calls = new Set();
  let count = 0;
  for (const file of files) {
    const doc = readJson(file);
    assert.equal(doc.version, 1, file);
    assert.ok(doc.about && doc.pinned_to, file);
    assert.equal(doc.pinned_to.python, "bollardeck.matrix", file);
    const names = doc.vectors.map((v) => v.name);
    assert.equal(new Set(names).size, names.length, file + ": a vector name is used twice");
    for (const v of doc.vectors) {
      calls.add(v.call);
      count += 1;
      assert.ok(("frame" in v) !== ("value" in v), file + " " + v.name + ": a vector expects a frame or a value");
      if ("frame" in v) assert.match(v.frame, /^[0-9a-f]{226}$/, file + " " + v.name);
    }
  }
  assert.deepEqual([...calls].sort(), ["ascii", "corpus", "dj", "dj_beat", "dj_camelot", "dj_crossfader", "film", "glyph", "idle",
    "playback", "premiere", "str_seed", "text", "text_pass_ms", "tone"]);
  assert.ok(count >= 1100, "only " + count + " matrix vectors");
});

for (const file of files) {
  test("matrix vectors: " + path.basename(file), () => {
    const doc = readJson(file);
    const before = JSON.stringify(doc.fixtures || {});
    for (const v of doc.vectors) {
      const got = run(v.call, resolve(v.args, doc.fixtures || {}));
      if ("frame" in v) assert.equal(got, v.frame, v.name);
      else assert.deepStrictEqual(got, v.value, v.name);
    }
    assert.equal(JSON.stringify(doc.fixtures || {}), before, "the engine changed its input");
  });
}

test("a frame is 104 pixels and three RGB LEDs, and round-trips through hex and bytes", () => {
  const frame = M.glyph("boot", 120, false);
  assert.equal(frame.pixels.length, M.N);
  assert.equal(M.W * M.H, M.N);
  assert.deepEqual(frame.rgb.map((led) => led.length), [3, 3, 3]);
  const hex = M.toHex(frame);
  assert.equal(hex.length, M.FRAME_BYTES * 2);
  assert.deepEqual(M.fromHex(hex), { pixels: frame.pixels, rgb: frame.rgb });
  assert.equal(Buffer.from(M.toBytes(frame)).toString("hex"), hex);
  assert.throws(() => M.fromHex("00"), RangeError);
  assert.throws(() => M.fromHex("zz".repeat(M.FRAME_BYTES)), RangeError);
  assert.equal(M.ascii(M.idle(0, true)).split("\n").length, M.H);
});

test("the engine is pure: the same inputs give the same frame, whatever came between", () => {
  const song = { song_id: "purity", bpm: 111, drama: { shots: [{ kind: "JAM", duration_ms: 3000 }, { kind: "MUTATION", duration_ms: 3000, actors: { old: "a", new: "b" } }] },
    notes: [[0, 1, 1, 60, 100], [0.5, 0.2, 10, 36, 120]] };
  const first = [M.toHex(M.film(song, 4100, false)), M.toHex(M.playback(song, 0.6, false)), M.toHex(M.idle(900, false))];
  M.film({ song_id: "other", drama: { shots: [{ kind: "LOCK", duration_ms: 500 }] } }, 100, false);
  M.playback({ notes: [[0, 1, 2, 60, 100]] }, 0.1, false);
  assert.deepEqual([M.toHex(M.film(song, 4100, false)), M.toHex(M.playback(song, 0.6, false)), M.toHex(M.idle(900, false))], first);
  assert.equal(typeof M.canvas, "function", "the canvas renderer sits beside the engine");
});

test("a caller's string never reaches Object.prototype", () => {
  for (const name of ["constructor", "toString", "__proto__", "hasOwnProperty", "valueOf"]) {
    const song = { song_id: "p", drama: { shots: [{ kind: name, duration_ms: 1000 }] } };
    assert.equal(M.toHex(M.film(song, 300, false)), M.toHex(M.film({ song_id: "p", drama: { shots: [{ kind: "NOT_A_KIND", duration_ms: 1000 }] } }, 300, false)), name);
    assert.equal(M.toHex(M.text("OK", 0, true, name, 0, false)), M.toHex(M.text("OK", 0, true, "nothing", 0, false)), name);
    assert.equal(M.toHex(M.premiere(2, 900, true, false, name)), M.toHex(M.premiere(2, 900, true, false, "legendary")), name);
    assert.equal(M.toHex(M.glyph(name, 0, false)), M.toHex(M.idle(0, false)), name);
  }
});
