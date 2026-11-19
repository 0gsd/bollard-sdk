// SPDX-License-Identifier: Apache-2.0
// bollardeck.popsnip.checkAccept and verify: every case in conformance/popsnip/accept.json and ed25519.json, the same
// answers as the Python twin (tests/test_popsnip_accept.py).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { CONFORMANCE, JS, readJson, bollardeck } = require("./support.js");

const P = bollardeck.popsnip;
const V = readJson(CONFORMANCE, "popsnip", "accept.json");
const SIG = readJson(CONFORMANCE, "popsnip", "ed25519.json");
const fromHex = (h) => new Uint8Array(Buffer.from(h, "hex"));
const dec = (t) => new Uint8Array(Buffer.from(t, "base64url"));
const ascii = (t) => new Uint8Array(Buffer.from(t, "ascii"));

function run(c) {
  const lst = c.list ? V.lists[c.list] : null;
  const held = c.held_list ? V.lists[c.held_list] : null;
  const fls = V.files[c.files];
  const files = fls === null ? null : Object.fromEntries(Object.entries(fls).map(([k, t]) => [k, ascii(t)]));
  return P.checkAccept(c.app, V.releases[c.release], files, V.logs[c.log], V.heads[c.head], V.certs, V.roots[c.roots],
    lst ? [lst.index, lst.pages] : null, V.pinned[c.pinned].map(dec), c.held_head ? V.heads[c.held_head] : null,
    held ? [held.index, held.pages] : null);
}

test("every Ed25519 case: the one equation (cofactorless, S < L, canonical points, no small order)", async () => {
  for (const c of SIG.cases) {
    assert.equal(await P.verify(fromHex(c.pub), fromHex(c.message), fromHex(c.signature)), c.valid, c.name);
  }
  assert.ok(SIG.cases.some((c) => /mixed-order key, h\*T not/.test(c.name) && c.valid === false));
  assert.ok(SIG.cases.some((c) => /mixed-order R/.test(c.name) && c.valid === false));
  assert.equal(await P.verify("not bytes", new Uint8Array(0), new Uint8Array(64)), false);
});

test("every accept case gives the Python twin's code", async () => {
  for (const c of V.cases) {
    const v = await run(c);
    assert.deepEqual([v.ok, v.code], [c.code === null, c.code], c.name + ": " + v.detail);
  }
  assert.ok(V.cases.length >= 25);
});

test("no pinned key accepts nothing, and an empty pinned list is no unsigned mode", async () => {
  assert.equal((await run(Object.assign({}, V.cases[0], { pinned: "other" }))).code, "cert");
  const v = await P.checkAccept("drumtoy", V.releases.r1, {}, V.logs.main, V.heads.main, V.certs, [], null, []);
  assert.equal(v.code, "cert");
});

test("nothing rejects: a malformed argument is a verdict", async () => {
  assert.equal((await P.checkAccept()).code, "malformed");
  assert.equal((await P.checkAccept(...Array(11).fill(null))).code, "malformed");
  const v = await P.checkAccept("x", {}, {}, [null], {}, [], [], [null, null], []);
  assert.deepEqual([v.ok, v.code], [false, "head"]);
  const c = V.cases[0], base = () => [c.app, V.releases.r1, { "index.html": ascii(V.files.r1["index.html"]),
    "app.js": ascii(V.files.r1["app.js"]) }, V.logs.main, V.heads.main, V.certs, [], null, V.pinned.release.map(dec)];
  const strings = base(); strings[2] = { "index.html": V.files.r1["index.html"], "app.js": V.files.r1["app.js"] };
  assert.equal((await P.checkAccept(...strings)).code, "malformed");          // files as strings, not bytes
  const notPair = base(); notPair[7] = [V.lists.app.index];
  assert.equal((await P.checkAccept(...notPair)).code, "malformed");
  assert.equal((await P.checkAccept(...base())).code, null);
});

test("it reads only its arguments: no environment, storage, network or pass", () => {
  const src = fs.readFileSync(path.join(JS, "bollardeck.popsnip.js"), "utf8");
  const start = src.indexOf("// ── accept:"), end = src.indexOf("  var api = {");
  assert.ok(start > 0 && end > start);
  const code = src.slice(start, end).replace(/\/\/[^\n]*/g, "");
  for (const word of ["process", "require(", "fetch(", "XMLHttpRequest", "localStorage", "indexedDB", "document.",
    "window.", "navigator.", "import(", "pass_active", "Date.now", "new Date"]) {
    assert.ok(!code.includes(word), word);
  }
});

test("a held record with a seq past the head and no head_hash is rollback, as in Python", async () => {
  const held = Object.assign({}, V.logs.main[4], { seq: 99 });       // a checked record kind with a seq, no head_hash
  const c = V.cases[0];
  const v = await P.checkAccept(c.app, V.releases.r1, { "index.html": ascii(V.files.r1["index.html"]),
    "app.js": ascii(V.files.r1["app.js"]) }, V.logs.main, V.heads.main, V.certs, [], null,
    V.pinned.release.map(dec), held, null);
  assert.equal(v.code, "rollback");
});

test("verify's memo changes no answer, and copies its inputs", async () => {
  for (let round = 0; round < 2; round++) {                       // the second round is all memo hits
    for (const c of SIG.cases) {
      assert.equal(await P.verify(fromHex(c.pub), fromHex(c.message), fromHex(c.signature)), c.valid, c.name);
    }
  }
  const good = SIG.cases.find((c) => c.valid);
  const sig = fromHex(good.signature), pending = P.verify(fromHex(good.pub), fromHex(good.message), sig);
  sig[40] ^= 1;                                                    // changed after the call: the answer is the call's
  assert.equal(await pending, true);
  assert.equal(await P.verify(fromHex(good.pub), fromHex(good.message), sig), false);
  const buf = Buffer.from(good.signature, "hex"), late = P.verify(fromHex(good.pub), fromHex(good.message), buf);
  buf[40] ^= 1;                                                    // a node Buffer too (its slice is a view)
  assert.equal(await late, true);
});
