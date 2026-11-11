// SPDX-License-Identifier: Apache-2.0
// bollardeck.schema: the JavaScript validator gives every conformance vector the verdict the
// index records, which is the verdict the Python validator gives (tests/test_schemas.py).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { ROOT, CONFORMANCE, readJson, bollardeck } = require("./support.js");

const schema = bollardeck.schema;
const index = readJson(CONFORMANCE, "index.json");
const ID_BASE = "https://popboll.com/sdk/schema/";

test("the packaged schemas are the files under schema/", () => {
  const names = fs.readdirSync(path.join(ROOT, "schema")).filter((f) => f.endsWith(".schema.json")).map((f) => f.slice(0, -12)).sort();
  assert.deepEqual(schema.names(), names, "run tools/generate.py");
  for (const name of names) {
    assert.deepEqual(schema.load(name), readJson(ROOT, "schema", name + ".schema.json"), name + ": run tools/generate.py");
    assert.equal(index.schemas[name], "schema/" + name + ".schema.json");
  }
  assert.ok(Object.isFrozen(bollardeck.schemas) && Object.isFrozen(bollardeck.schemas.cue.$defs.cue.properties));
});

test("every vector in conformance/index.json gets the verdict the index records", () => {
  assert.ok(index.vectors.length >= 163);
  for (const v of index.vectors) {
    const doc = readJson(CONFORMANCE, v.file);
    const found = schema.validate(v.schema, doc);
    assert.equal(schema.isValid(v.schema, doc), v.valid, v.file + ": " + found.map(String).join("; "));
    if (v.valid) assert.deepEqual(found.map(String), [], v.file);
    else assert.ok(found.some((p) => p.pointer === v.at), v.file + ": no problem reported at " + JSON.stringify(v.at) + ": " + found.map(String).join("; "));
  }
});

test("the validator implements exactly the keywords the schemas use", () => {
  const used = new Set();
  const walk = (node) => {
    if (Array.isArray(node)) return node.forEach(walk);
    if (!node || typeof node !== "object") return;
    for (const [key, value] of Object.entries(node)) {
      used.add(key);
      if (["properties", "$defs"].includes(key)) Object.values(value).forEach(walk);
      else if (["additionalProperties", "items", "not", "if", "then", "allOf", "anyOf", "prefixItems"].includes(key)) walk(value);
    }
  };
  schema.names().forEach((name) => walk(schema.load(name)));
  schema.ANNOTATIONS.forEach((k) => used.delete(k));
  assert.deepEqual([...used].sort(), [...schema.KEYWORDS].sort());
});

test("a keyword the validator does not implement is refused", () => {
  const base = { $schema: schema.DIALECT, $id: ID_BASE + "x.schema.json" };
  const refused = [{ format: "date-time" }, { oneOf: [{}] }, { else: {} }, { uniqueItems: true },
    { properties: { a: { multipleOf: 2 } } }, { items: { allOf: [{ contains: {} }] } },
    { type: "date" }, { pattern: "(" }, { then: {} }];
  for (const extra of refused) {
    assert.throws(() => schema.check(Object.assign({}, base, extra)), schema.UnsupportedSchema, JSON.stringify(extra));
  }
  schema.check(Object.assign({}, base, { type: "object", properties: { a: true, b: false } }));
  assert.throws(() => schema.check({ type: "object" }), schema.UnsupportedSchema);       // no $id, no $schema
  assert.ok(new schema.UnsupportedSchema("x") instanceof Error);
});

test("unknown names and pointers are errors, not passes", () => {
  assert.throws(() => schema.validate("no-such-schema", {}), RangeError);
  assert.throws(() => schema.validate("constructor", {}), RangeError);
  assert.throws(() => schema.validate("cue#/$defs/nothing", {}), schema.UnsupportedSchema);
});

test("a name can point inside a schema", () => {
  assert.deepEqual(schema.validate("cue#/$defs/cue", { button: 1, state: "on", role: null }), []);
  assert.ok(schema.isValid("device-identity#/$defs/device_serial", "PB0042-ACME-1A2B3C"));
  assert.ok(!schema.isValid("device-identity#/$defs/device_serial", "VPB0042-WEB-pb-example"));
});

test("problems carry JSON pointers", () => {
  const found = schema.validate("makers", { schema: "popboll.makers/1", makers: [{ "a/b": 1, "c~d": 2 }] });
  const pointers = found.map((p) => p.pointer);
  assert.ok(pointers.includes("/makers/0/a~1b"));      // RFC 6901: "/" in a key is written ~1
  assert.ok(pointers.includes("/makers/0/c~0d"));      // and "~" is written ~0
  assert.ok(pointers.includes("/makers/0"));
  for (const p of found) {
    assert.ok(String(p).startsWith("#" + p.pointer + ": "));
    assert.deepEqual(Object.keys(JSON.parse(JSON.stringify(p))).sort(), ["keyword", "message", "pointer"]);
  }
  assert.deepEqual(schema.validate("licence", 7).map((p) => p.pointer), [""]);
});

test("numbers and booleans are told apart as JSON Schema says", () => {
  const one = { button: 1.0, state: "on", role: null };
  assert.ok(schema.isValid("cue#/$defs/cue", one));
  assert.ok(!schema.isValid("cue#/$defs/cue", Object.assign({}, one, { button: true })));     // true is not 1
  assert.ok(!schema.isValid("cue#/$defs/cue", Object.assign({}, one, { button: 1.5 })));
  assert.ok(!schema.isValid("cue#/$defs/cue", Object.assign({}, one, { button: "1" })));
  assert.ok(!schema.isValid("licence", { scope: "full", store_art: 1 }));
});

test("a pattern ends at the end, and a length is counted in characters", () => {
  const manifest = readJson(CONFORMANCE, "corpus-manifest/valid/minimal.json");
  assert.ok(schema.isValid("corpus-manifest", manifest));
  assert.ok(!schema.isValid("corpus-manifest", Object.assign({}, manifest, { id: manifest.id + "\n" })));
  const kept = schema.names().map((n) => [n, schema.load(n)]);
  try {
    schema.use({ t: { $schema: schema.DIALECT, $id: ID_BASE + "t.schema.json", type: "string", minLength: 2 } });
    assert.deepEqual(schema.names(), ["t"]);
    assert.ok(!schema.isValid("t", "\u{1F600}"));       // one character, two UTF-16 units
    assert.ok(schema.isValid("t", "ab"));
    assert.throws(() => schema.use({ bad: { $schema: schema.DIALECT, $id: ID_BASE + "bad.schema.json", format: "uri" } }), schema.UnsupportedSchema);
    assert.deepEqual(schema.names(), ["t"], "a refused set of schemas replaces nothing");
  } finally {
    schema.use(Object.fromEntries(kept));
  }
  assert.equal(schema.names().length, kept.length);
});

test("no schema pattern uses a class JavaScript and Python read differently", () => {
  // \s, \S, \b and \B follow Unicode in one language and ASCII in the other.
  const walk = (node, name) => {
    if (Array.isArray(node)) return node.forEach((n) => walk(n, name));
    if (!node || typeof node !== "object") return;
    if (typeof node.pattern === "string") assert.ok(!/\\[sSbB]/.test(node.pattern), name + ": " + node.pattern);
    Object.values(node).forEach((n) => walk(n, name));
  };
  schema.names().forEach((name) => walk(schema.load(name), name));
});

test("validating changes neither the document nor the schema", () => {
  for (const v of index.vectors) {
    const doc = readJson(CONFORMANCE, v.file);
    const before = JSON.stringify(doc), kept = JSON.stringify(schema.load(v.schema));
    schema.validate(v.schema, doc);
    assert.equal(JSON.stringify(doc), before, v.file);
    assert.equal(JSON.stringify(schema.load(v.schema)), kept, v.file);
  }
});
