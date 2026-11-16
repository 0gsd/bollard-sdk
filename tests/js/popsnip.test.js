// SPDX-License-Identifier: Apache-2.0
// bollardeck.popsnip: every vector in conformance/popsnip/records.json, byte for byte with the Python twin.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { CONFORMANCE, readJson, bollardeck } = require("./support.js");

const P = bollardeck.popsnip;
const V = readJson(CONFORMANCE, "popsnip", "records.json");

function code(fn) {
  try { fn(); return null; } catch (e) { if (!(e instanceof P.RecordError)) throw e; return e.code; }
}

test("the constants are the vectors'", () => {
  assert.equal(P.CONTEXT, V.context);
  assert.equal(P.GENESIS, V.genesis);
});

test("every record vector: the verdict, and for an accepted one its canonical bytes, id and signed message", async () => {
  let accepted = 0;
  for (const v of V.records) {
    assert.equal(code(() => P.check(v.record, v.signed)), v.error, v.name);
    if (v.canonical === undefined) continue;
    assert.equal(P.canonicalText(v.record), v.canonical, v.name);
    assert.deepEqual(Array.from(P.canonical(v.record)), Array.from(Buffer.from(v.canonical, "ascii")), v.name);
    assert.equal(Buffer.from(P.signedMessage(v.record)).toString("latin1"), V.context + v.canonical, v.name);
    assert.equal(await P.recordId(v.record), v.id, v.name);
    accepted += 1;
  }
  assert.ok(accepted >= 15);
  assert.deepEqual([...new Set(V.records.filter((v) => v.canonical).map((v) => v.record.kind))].sort(), P.KINDS.slice().sort());
});

test("every text vector, read from a string and from UTF-8 bytes", () => {
  for (const t of V.texts) {
    for (const data of [t.text, new TextEncoder().encode(t.text)]) {
      let value;
      assert.equal(code(() => { value = P.parse(data); }), t.parse_error, JSON.stringify(t.text).slice(0, 60));
      if (t.parse_error !== null) continue;
      let canon = null;
      const err = code(() => { canon = P.canonicalText(value); });
      assert.deepEqual([err, canon], [t.canonical_error, t.canonical], JSON.stringify(t.text).slice(0, 60));
    }
  }
  assert.equal(code(() => P.parse(new Uint8Array([0x7b, 0x22, 0xff, 0x22, 0x3a, 0x31, 0x7d]))), "bad_json");
  assert.equal(code(() => P.parse(42)), "bad_json");
});

test("the rekey requests", () => {
  for (const r of V.rekey_requests) {
    const entry = V.records.find((x) => x.canonical && x.record.kind === "popsnip.rekey" && x.record.seq === r.entry_seq).record;
    assert.deepEqual(P.rekeyRequest(entry), r.request);
    assert.equal(P.canonicalText(r.request), r.canonical);
    assert.equal(P.check(r.request), r.request);
  }
  assert.equal(code(() => P.rekeyRequest({})), "missing_field:app");
});

test("canonical never changes the record, and a __proto__ key stays a key", () => {
  const rec = JSON.parse(JSON.stringify(V.records.find((v) => v.canonical).record));
  const before = JSON.stringify(rec);
  P.canonical(rec);
  P.check(rec);
  assert.equal(JSON.stringify(rec), before);
  const odd = P.parse('{"__proto__":{"a":1}}');
  assert.equal(Object.getPrototypeOf(odd), Object.prototype);
  assert.equal(P.canonicalText(odd), '{"__proto__":{"a":1}}');
});

test("in-memory values outside the form", () => {
  for (const [value, want] of [[1.5, "bad_number"], [NaN, "bad_number"], [2 ** 53, "bad_number"], [undefined, "bad_number"],
    ["café", "not_ascii"], ["a\x7fb", "not_ascii"], ["a\nb", "not_ascii"]]) {
    assert.equal(code(() => P.canonical({ a: value })), want, String(value));
  }
  assert.equal(P.canonicalText({ a: true, b: null, c: [2 ** 53 - 1, -(2 ** 53 - 1), -0] }), '{"a":true,"b":null,"c":[9007199254740991,-9007199254740991,0]}');
  for (const odd of [new Date(0), new Map(), new Uint8Array(2), new (class X {})()]) {
    assert.equal(code(() => P.canonical({ a: odd })), "bad_number", String(odd));
  }
  let deep = {};
  for (let k = 0; k < 40 + 5000; k++) deep = { a: deep };
  assert.equal(code(() => P.canonical(deep)), "bad_json");
  for (const d of [100, 1000, 100000]) {
    assert.equal(code(() => P.parse('{"a":' + "[".repeat(d) + "]".repeat(d) + "}")), "bad_json");
  }
});

test("the small-order keys are the curve's, and no key of them passes", () => {
  assert.deepEqual(P.SMALL_ORDER.slice().sort(), V.small_order.slice().sort());
  for (const h of V.small_order) {
    const b64u = Buffer.from(h, "hex").toString("base64url");
    assert.equal(P.isPublicKey(b64u), false, h);
  }
  for (const k of Object.values(V.keys)) assert.equal(P.isPublicKey(k.pub), true);
});
