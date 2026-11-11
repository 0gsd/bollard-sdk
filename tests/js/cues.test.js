// SPDX-License-Identifier: Apache-2.0
// bollardeck.cues: what each button shows at a time matches every vector under
// conformance/cue-render/, which tools/pin_vectors.py writes from the Python renderer, and what a
// valid cue list is and how a bad one is repaired match conformance/cues/normalise.json, which
// the Python binding runs too.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { CONFORMANCE, readJson, jsonFiles, bollardeck } = require("./support.js");

const cues = bollardeck.cues;
const K = bollardeck.constants;
const close = (a, b) => Math.abs(a - b) <= 1e-12;       // cos() may differ in its last bit between languages

test("the constants the vectors were pinned with are the binding's", () => {
  for (const file of jsonFiles(path.join(CONFORMANCE, "cue-render"))) {
    const doc = readJson(file);
    assert.equal(doc.version, 1);
    assert.deepEqual(doc.constants, { PULSE_PERIOD_MS: K.PULSE_PERIOD_MS, CHASE_PERIOD_MS: K.CHASE_PERIOD_MS,
      PULSE_FLOOR: K.PULSE_FLOOR, CHASE_TAIL: K.CHASE_TAIL, CHASE_STEPS: K.CHASE_STEPS }, file);
  }
  // the three values are constants now, and still reachable where they always were
  assert.deepEqual([cues.PULSE_FLOOR, cues.CHASE_TAIL, cues.CHASE_STEPS], [K.PULSE_FLOOR, K.CHASE_TAIL, K.CHASE_STEPS]);
  assert.deepEqual([K.PULSE_FLOOR, K.CHASE_TAIL, K.CHASE_STEPS], [0.35, 0.25, 3]);
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "js", "bollardeck.cues.js"), "utf8");
  assert.ok(!/0\.35|0\.25/.test(source), "bollardeck.cues.js carries no copy of the constants");
  assert.deepEqual(cues.BUTTONS, K.BUTTON_NUMBERS);
  assert.deepEqual(cues.BUTTONS, [1, 2, 3]);
  assert.deepEqual(bollardeck.schema.load("cue").$defs.cue.properties.button.enum, cues.BUTTONS);
  assert.deepEqual(bollardeck.schema.load("cue").$defs.cue.properties.state.enum, K.CUE_STATES);
});

test("every cue-render vector: each button shows what the device shows", () => {
  let count = 0;
  for (const file of jsonFiles(path.join(CONFORMANCE, "cue-render"))) {
    const doc = readJson(file);
    const names = doc.vectors.map((v) => v.name);
    assert.equal(new Set(names).size, names.length, "a vector name is used twice");
    for (const v of doc.vectors) {
      count += 1;
      assert.deepEqual(bollardeck.schema.validate("cue", v.cues).map(String), [], v.name + ": vectors hold valid cue lists");
      const got = cues.at(v.cues, v.t_ms, { calm: !!v.calm });
      assert.equal(got.length, 3, v.name);
      got.forEach((g, i) => {
        const want = v.buttons[i], where = v.name + " button " + (i + 1);
        assert.deepEqual(Object.keys(g).sort(), Object.keys(want).sort(), where);
        for (const key of ["button", "driven", "state", "role", "head", "pixel"]) assert.equal(g[key], want[key], where + " " + key);
        assert.ok(close(g.level, want.level), where + " level " + g.level + " != " + want.level);
        g.arc.forEach((x, j) => assert.ok(close(x, want.arc[j]), where + " arc " + j));
        assert.equal(g.arc.length, 3, where);
      });
    }
  }
  assert.ok(count >= 100, "only " + count + " cue-render vectors");
});

test("pulse and chase follow their periods", () => {
  assert.equal(cues.pulseLevel(0), 1);
  assert.ok(close(cues.pulseLevel(K.PULSE_PERIOD_MS / 2), cues.PULSE_FLOOR));
  assert.ok(close(cues.pulseLevel(K.PULSE_PERIOD_MS * 7 + 100), cues.pulseLevel(100)));
  assert.ok(close(cues.pulseLevel(-100), cues.pulseLevel(K.PULSE_PERIOD_MS - 100)));
  assert.deepEqual([0, 333, 334, 666, 667, 999, 1000].map((t) => cues.chaseHead(t)), [0, 0, 1, 1, 2, 2, 0]);
  assert.equal(cues.pulseLevel(100.9), cues.pulseLevel(100), "time is counted in whole milliseconds");
  assert.ok(close(cues.pulseLevel(1000, { pulsePeriodMs: 2000 }), cues.PULSE_FLOOR), "a period can be passed in");
  assert.equal(cues.chaseHead(1500, { chasePeriodMs: 3000 }), 1);
  assert.throws(() => cues.pulseLevel("soon"), TypeError);
  assert.throws(() => cues.at([], NaN), TypeError);
});

test("compile checks the list once, copies it, and answers for buttons 1, 2, 3 in order", () => {
  const list = [{ button: 3, state: "pulse", role: "go" }, { button: 1, state: "on", role: null }];
  const show = cues.compile(list);
  assert.deepEqual(show.cues.map((c) => c.button), [1, 3]);
  list[0].state = "off";                                   // changing the list afterwards changes nothing
  const at = show.at(0);
  assert.deepEqual(at.map((e) => [e.button, e.driven, e.state, e.level]), [[1, true, "on", 1], [2, false, "off", 0], [3, true, "pulse", 1]]);
  assert.ok(Object.isFrozen(show) && Object.isFrozen(show.cues));
  at[0].arc[0] = 9;                                        // each answer is the caller's own
  assert.deepEqual(show.at(0)[0].arc, [1, 1, 1]);
});

test("reduced motion draws pulse and chase exactly as on", () => {
  const list = [{ button: 1, state: "pulse", role: "a" }, { button: 2, state: "chase", role: "warn" }, { button: 3, state: "off", role: null }];
  for (const t of [0, 130, 250, 700]) {
    const calm = cues.at(list, t, { calm: true });
    assert.deepEqual(calm.map((e) => [e.state, e.level, e.arc, e.head, e.pixel]),
      [["pulse", 1, [1, 1, 1], null, 255], ["chase", 1, [1, 1, 1], null, 255], ["off", 0, [0, 0, 0], null, 0]]);
  }
});

test("a list that is not a valid cue list is refused, with the problems", () => {
  const index = readJson(CONFORMANCE, "index.json");
  const invalid = index.vectors.filter((v) => v.schema === "cue" && !v.valid);
  assert.ok(invalid.length >= 5);
  for (const v of invalid) {
    const doc = readJson(CONFORMANCE, v.file);
    assert.throws(() => cues.compile(doc), (e) => e instanceof TypeError && e.problems.length > 0, v.file);
    assert.throws(() => cues.at(doc, 0), TypeError, v.file);
  }
  for (const v of index.vectors.filter((x) => x.schema === "cue" && x.valid)) {
    assert.equal(cues.at(readJson(CONFORMANCE, v.file), 123).length, 3, v.file);
  }
  const twice = [{ button: 2, state: "on", role: null }, { button: 2, state: "off", role: null }];
  assert.deepEqual(cues.problems(twice).map((p) => [p.pointer, p.keyword]), [["/1/button", "one-per-button"]]);
  assert.throws(() => cues.compile(twice), /second cue for button 2/);
  assert.deepEqual(cues.problems([]), []);
});

test("one rule for a valid cue list, shared with Python: conformance/cues/normalise.json", () => {
  const doc = readJson(CONFORMANCE, "cues", "normalise.json");
  assert.equal(doc.version, 2);
  const brief = (found) => found.map((r) => ({ index: r.index, kind: r.kind, dropped: r.dropped }));
  let twice = 0;
  for (const v of doc.normalise) {
    const before = JSON.stringify(v.input);
    // valid: fits the schema and names no button twice
    const found = cues.problems(v.input);
    assert.equal(found.length === 0, v.valid, v.name + ": valid");
    if (v.one_per_button) {
      twice += 1;
      assert.deepEqual(bollardeck.schema.validate("cue", v.input), [], v.name + ": the schema alone cannot see it");
      assert.deepEqual(found.map((p) => [p.pointer, p.keyword]), v.one_per_button.map((at) => [at, "one-per-button"]), v.name);
    }
    // a strict reader refuses what is not valid; normalise repairs it and never throws
    if (v.valid) assert.deepEqual(cues.compile(v.input).cues, v.output, v.name);
    else assert.throws(() => cues.compile(v.input), TypeError, v.name);
    const out = cues.normalise(v.input);
    assert.deepEqual(out, v.output, v.name + ": normalise");
    assert.deepEqual(brief(cues.repairs(v.input)), v.repairs, v.name + ": repairs");
    assert.deepEqual(cues.problems(out), [], v.name + ": normalise's output is always valid");
    assert.deepEqual(cues.normalise(out), out, v.name + ": normalising twice changes nothing");
    assert.equal(cues.at(out, 0).length, 3, v.name);
    assert.equal(JSON.stringify(v.input), before, v.name + ": the input is not changed");
  }
  assert.ok(twice >= 3 && doc.normalise.length >= 19);
  for (const junk of [undefined, null, 7, "x", {}, [[]], [{ button: NaN, state: "on" }], [{ button: 1e99, state: "on" }]]) {
    assert.deepEqual(cues.problems(cues.normalise(junk)), [], "normalise never throws: " + JSON.stringify(junk));
  }
});

// ── the optional page helper, against stand-in elements ──────────────────────────────────
function element() {
  const attrs = new Map(), style = new Map();
  let writes = 0;
  return {
    hasAttribute: (n) => attrs.has(n), getAttribute: (n) => (attrs.has(n) ? attrs.get(n) : null),
    setAttribute: (n, v) => { writes += 1; attrs.set(n, String(v)); }, removeAttribute: (n) => { writes += 1; attrs.delete(n); },
    style: { getPropertyValue: (n) => style.get(n) || "", setProperty: (n, v) => { writes += 1; style.set(n, v); }, removeProperty: (n) => { style.delete(n); } },
    attrs, styles: style, writes: () => writes,
  };
}

test("cues.apply puts the cue on elements and leaves undriven buttons bare", () => {
  const els = { 1: element(), 2: element(), 3: element() };
  const list = [{ button: 1, state: "on", role: "go" }, { button: 3, state: "chase", role: null }];
  cues.apply(els, cues.at(list, 400));
  assert.deepEqual([...els[1].attrs], [["data-cue", "on"], ["data-cue-role", "go"]]);
  assert.deepEqual([...els[1].styles], [["--cue-level", "1.000"]]);
  assert.deepEqual([...els[2].attrs], []);
  assert.deepEqual([...els[2].styles], []);
  assert.deepEqual([...els[3].attrs], [["data-cue", "chase"]]);
  assert.deepEqual([...els[3].styles], [["--cue-level", "1.000"], ["--cue-head", "1"]]);
  const before = els[1].writes();
  cues.apply(els, cues.at(list, 400));
  assert.equal(els[1].writes(), before, "nothing is written when nothing changed");
  cues.apply(els, cues.at([], 400));
  assert.deepEqual([...els[1].attrs, ...els[3].attrs, ...els[1].styles, ...els[3].styles], []);
  const row = [element(), null, element()];                  // a list of elements works too; a missing one is skipped
  cues.apply(row, cues.at(list, 0));
  assert.equal(row[0].getAttribute("data-cue"), "on");
  assert.equal(row[2].getAttribute("data-cue"), "chase");
});

test("cues.apply can leave style alone and say off for an undriven button", () => {
  const els = { 1: element(), 2: element(), 3: element() };
  const list = [{ button: 1, state: "pulse", role: "go" }, { button: 3, state: "chase", role: null }];
  const opts = { properties: false, undriven: "off" };
  cues.apply(els, cues.at(list, 400), opts);
  assert.deepEqual([...els[1].attrs], [["data-cue", "pulse"], ["data-cue-role", "go"]]);
  assert.deepEqual([...els[2].attrs], [["data-cue", "off"]]);
  assert.deepEqual([...els[3].attrs], [["data-cue", "chase"]]);
  assert.deepEqual([els[1].styles.size, els[2].styles.size, els[3].styles.size, els[1].writes(), els[2].writes(), els[3].writes()], [0, 0, 0, 2, 1, 1], "attributes only");
  cues.apply(els, cues.at([], 400), opts);
  assert.deepEqual([[...els[1].attrs], [...els[3].attrs]], [[["data-cue", "off"]], [["data-cue", "off"]]]);
  // An element with no style object at all is fine in this mode, and each option works alone.
  const bare = { hasAttribute: () => false, getAttribute: () => null, setAttribute(n, v) { this[n] = v; }, removeAttribute() {} };
  cues.apply([bare], cues.at(list, 0), { properties: false });
  assert.equal(bare["data-cue"], "pulse");
  const two = element();
  cues.apply({ 2: two }, cues.at(list, 0), { undriven: "off" });
  assert.deepEqual([[...two.attrs], [...two.styles]], [[["data-cue", "off"]], []]);
  assert.throws(() => cues.apply(els, cues.at(list, 0), { undriven: "dark" }), RangeError);
});

test("cues.run follows a changing list until it is stopped", async () => {
  const els = [element(), element(), element()];
  let list = [{ button: 2, state: "pulse", role: "live" }];
  const running = cues.run(els, () => list, { calm: false, now: () => 250 });
  assert.equal(els[1].getAttribute("data-cue"), "pulse");
  assert.equal(els[1].styles.get("--cue-level"), cues.PULSE_FLOOR.toFixed(3));
  list = [{ button: 1, state: "on", role: null }];
  for (let i = 0; i < 200 && els[1].getAttribute("data-cue") !== null; i++) await new Promise((r) => setTimeout(r, 10));
  assert.equal(els[1].getAttribute("data-cue"), null);
  assert.equal(els[0].getAttribute("data-cue"), "on");
  running.stop();
  list = [];
  await new Promise((r) => setTimeout(r, 80));
  assert.equal(els[0].getAttribute("data-cue"), "on", "stopped means stopped");
});

test("the cue helpers do not depend on the page helper or the matrix", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "js", "bollardeck.cues.js"), "utf8");
  assert.ok(!/document|window|requestAnimationFrame|canvas/.test(source.replace(/\/\*[\s\S]*?\*\//, "")));
});
