// SPDX-License-Identifier: Apache-2.0
// bollardeck.gestures and bollardeck.keymap: every timeline and every resolver case under
// conformance/gestures/, which the Python engine and resolver are held to as well.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { CONFORMANCE, readJson, bollardeck } = require("./support.js");

const G = bollardeck.gestures, K = bollardeck.keymap, C = bollardeck.constants;
const timelines = readJson(CONFORMANCE, "gestures", "timelines.json");
const resolve = readJson(CONFORMANCE, "gestures", "resolve.json");
const engineFor = (config) => G.engine({ holdMs: config.hold_ms, tapFollowMs: config.tap_follow_ms, combos: config.combos });
const names = (found) => found.map((g) => g.name + "@" + g.tMs);

test("every gesture timeline: each call returns exactly what the vector says", () => {
  assert.ok(timelines.vectors.length >= 59);
  for (const v of timelines.vectors) {
    const engine = engineFor(v.config);
    for (const [i, event] of v.events.entries()) {
      const where = v.name + " event " + i;
      if (event.raises) { assert.throws(() => engine.feed(event), RangeError, where); break; }
      const got = engine.feed(event), want = event.emits || [];
      assert.deepEqual(got.map((g) => ({ gesture: g.name, t_ms: g.tMs })), want.map((w) => ({ gesture: w.gesture, t_ms: w.t_ms })), where);
      got.forEach((g, n) => {
        assert.ok(Number.isInteger(g.holdMs), where + ": every gesture says how long");
        if ("hold_ms" in want[n]) assert.equal(g.holdMs, want[n].hold_ms, where);
      });
    }
    const whole = v.events.filter((e) => !e.raises);
    if (whole.length === v.events.length) {
      assert.deepEqual(names(engineFor(v.config).run(v.events)), [].concat(...v.events.map((e) => (e.emits || []).map((g) => g.gesture + "@" + g.t_ms))), v.name);
    }
  }
});

test("a gesture says what it is, and every name it can have is in GESTURES", () => {
  const engine = G.engine();
  assert.deepEqual([engine.holdMs, engine.tapFollowMs, engine.combos], [C.HOLD_MS, C.TAP_FOLLOW_MS, G.combosFromKeymap(C.KEYMAP)]);
  assert.deepEqual(engine.press(2, 0, 50), [{ name: "tap2", button: 2, kind: "tap", count: 1, tMs: 50, holdMs: 50 }]);
  engine.press(1, 100, 150); engine.press(1, 200, 250);
  assert.deepEqual(engine.press(1, 300, 350), [{ name: "tap1x3", button: 1, kind: "tap", count: 3, tMs: 350, holdMs: 50 }]);
  engine.down(3, 1000);
  assert.deepEqual(engine.tick(1000 + C.HOLD_MS), [{ name: "hold3", button: 3, kind: "hold", count: 1, tMs: 1000 + C.HOLD_MS, holdMs: C.HOLD_MS }]);
  for (const name of C.GESTURES) {
    const p = G.parseGesture(name);
    assert.equal(G.gestureName(p.kind, p.button, p.count), name);
  }
  for (const bad of ["tap4", "tap1x4", "hold_outer", "", null, 7]) assert.throws(() => G.parseGesture(bad), RangeError, String(bad));
  assert.deepEqual(G.combosFromKeymap({ prompt: { tap2x2: {}, tap2x3: {}, tap1: {} }, idle: { tap3x2: "x" }, always: { tap2x2: "y" } }), { 2: [2, 3], 3: [2] });
});

test("nextDeadlineMs is the first moment a tick has something to say", () => {
  const engine = G.engine({ holdMs: 800, tapFollowMs: 500, combos: { 1: [3] } });
  assert.equal(engine.nextDeadlineMs(), null);
  engine.down(1, 100);
  assert.equal(engine.nextDeadlineMs(), 900);
  engine.up(1, 200);
  assert.deepEqual([engine.nextDeadlineMs(), engine.pending(), engine.isDown(1)], [701, 1, false]);
  assert.deepEqual(engine.tick(700), []);
  assert.deepEqual(names(engine.tick(701)), ["tap1@700"]);
  assert.equal(engine.nextDeadlineMs(), null);
});

test("an engine refuses settings it cannot keep", () => {
  for (const opts of [{ holdMs: 0 }, { tapFollowMs: -1 }, { combos: { 4: [3] } }, { combos: { 1: [1] } }, { combos: { 1: [C.TAP_CHAIN_MAX + 1] } }, { combos: { 1: [2.5] } }]) {
    assert.throws(() => G.engine(opts), RangeError, JSON.stringify(opts));
  }
  const engine = G.engine();
  assert.throws(() => engine.down("1", 0), RangeError);
  assert.throws(() => engine.down(1, "0"), RangeError);
  assert.throws(() => engine.feed({ edge: "wiggle", t_ms: 0 }), RangeError);
});

test("key events: a source that reports the press beginning cannot have a chain broken by a tick", () => {
  // The timeline of finding 27: presses at 0-100, 550-650 and 700-750, and a poll at 620.
  const begin = G.engine({ combos: { 1: [3] } });
  let out = [];
  for (const [ev, now] of [[{ i: 1, down: 1, t_ms: 0 }], [{ i: 1, down: 0, t_ms: 100, hold_ms: 100 }], [{ i: 1, down: 1, t_ms: 550 }], [null, 620],
    [{ i: 1, down: 0, t_ms: 650, hold_ms: 100 }], [{ i: 1, down: 1, t_ms: 700 }], [{ i: 1, down: 0, t_ms: 750, hold_ms: 50 }]]) {
    out = out.concat(ev ? begin.key(ev) : begin.tick(now));
  }
  assert.deepEqual(names(out), ["tap1x3@750"]);
  // With only complete presses the poll has already reported the first tap: the limit the Python
  // engine documents, kept the same here.
  const whole = G.engine({ combos: { 1: [3] } });
  out = whole.key({ i: 1, down: 0, t_ms: 100, hold_ms: 100 }).concat(whole.tick(620), whole.key({ i: 1, down: 0, t_ms: 650, hold_ms: 100 }),
    whole.key({ i: 1, down: 0, t_ms: 750, hold_ms: 50 }), whole.tick(2000));
  assert.deepEqual(names(out), ["tap1@600", "tap1@1250", "tap1@1250"]);
  // A complete press that was long enough is a hold, stamped when it became one.
  assert.deepEqual(names(G.engine().key({ i: 3, down: 0, t_ms: 2000, hold_ms: 900 })), ["hold3@1900"]);
  assert.deepEqual(names(G.engine().key({ i: 2, down: 0, hold_ms: 40 }, 500)), ["tap2@500"]);
  assert.throws(() => G.engine().key({ i: 2, down: 0, hold_ms: 40 }), RangeError);
});

test("key events: a press beginning is only a hint", () => {
  const engine = G.engine();
  assert.deepEqual(engine.key({ i: 2, down: 1, t_ms: null }, 1000), []);
  assert.deepEqual([engine.isDown(2), engine.waiting(2), engine.waiting(), engine.waiting(1)], [false, true, true, false]);
  assert.deepEqual(engine.tick(1900).concat(engine.tick(3000)), []);
  assert.deepEqual(engine.key({ i: 2, down: 0, hold_ms: 120, t_ms: null }, 3100), [{ name: "tap2", button: 2, kind: "tap", count: 1, tMs: 1120, holdMs: 120 }]);
  assert.equal(engine.waiting(), false);
  const lost = G.engine();
  lost.key({ i: 1, down: 1, t_ms: 0 });
  assert.deepEqual([lost.tick(C.PRESS_LOST_MS), lost.waiting(1)], [[], true]);
  assert.deepEqual([lost.tick(C.PRESS_LOST_MS + 1), lost.waiting(1), lost.nextDeadlineMs()], [[], false, null]);
  const mixed = G.engine();
  mixed.down(2, 0);
  assert.deepEqual(names(mixed.key({ i: 2, down: 0, hold_ms: 5, t_ms: 60 })), ["tap2@60"]);
  const held = G.engine();
  held.key({ i: 1, down: 0, hold_ms: 100, t_ms: 100 });
  held.key({ i: 1, down: 1, t_ms: 300 });
  assert.equal(held.nextDeadlineMs(), 1100);
  assert.deepEqual([names(held.tick(1099)), names(held.tick(1100))], [[], ["tap1@600"]]);
});

test("key events: a hint ends with an edge, a cancel, or when it is given up on", () => {
  const quick = G.engine({ pressLostMs: 200 });
  quick.key({ i: 1, down: 0, hold_ms: 100, t_ms: 100 });
  quick.key({ i: 1, down: 1, t_ms: 300 });
  assert.equal(quick.nextDeadlineMs(), 601);
  assert.deepEqual([names(quick.tick(600)), names(quick.tick(601))], [[], ["tap1@600"]]);
  const short = G.engine({ pressLostMs: 200, tapFollowMs: 50 });
  short.key({ i: 1, down: 0, hold_ms: 100, t_ms: 100 });
  short.key({ i: 1, down: 1, t_ms: 140 });
  assert.equal(short.nextDeadlineMs(), 341);
  assert.deepEqual([names(short.tick(340)), names(short.tick(341))], [[], ["tap1@150"]]);
  const engine = G.engine();
  engine.key({ i: 2, down: 1, t_ms: 0 });
  engine.down(2, 10); engine.up(2, 60);
  engine.key({ i: 3, down: 1, t_ms: 100 });
  engine.cancel(3, 120);
  assert.equal(engine.waiting(), false);
  engine.key({ i: 3, down: 1, t_ms: 200 });
  engine.up(3, 220);
  assert.equal(engine.waiting(3), true);
});

test("setCombos changes the combos of a running engine and drops nothing", () => {
  const engine = G.engine({ combos: {} });
  engine.down(1, 0);
  assert.equal(engine.setCombos({ 1: [3] }), engine);
  assert.deepEqual([engine.isDown(1), engine.up(1, 50), engine.pending(), engine.combos], [true, [], 1, { 1: [3] }]);
  assert.throws(() => engine.setCombos({ 4: [3] }), RangeError);
  assert.equal(engine.pending(), 1);
  engine.setCombos({});
  assert.equal(engine.nextDeadlineMs(), 50);
  assert.deepEqual(names(engine.tick(60)), ["tap1@60"]);
  assert.deepEqual(G.engine({ combos: {} }).setCombos(null).combos, G.combosFromKeymap(C.KEYMAP));
});

test("every resolver case: the keymap's answer is the vector's", () => {
  assert.equal(resolve.version, K.VERSION);
  assert.deepEqual(resolve.groups[0].keymap, JSON.parse(JSON.stringify(C.KEYMAP)), "the first group is the platform's keymap");
  let count = 0;
  for (const group of resolve.groups) {
    for (const c of group.cases) {
      count += 1;
      const r = K.resolve(c.gesture, c.prompt, group.keymap, c.context);
      const where = group.name + ": " + c.gesture + " during " + c.prompt + (c.context ? " in " + c.context : "");
      assert.deepEqual({ source: r.source, kind: r.kind, value: r.value }, c.expect, where);
      assert.equal(r.handled, c.expect.source !== null, where);
      assert.equal(r.action, c.expect.kind === "do" ? c.expect.value : null, where);
      assert.equal(r.choice, c.expect.kind === "choice" ? c.expect.value : null, where);
      if (group.name === "platform") assert.deepEqual(K.resolve(c.gesture, c.prompt), r, where + " (the default keymap)");
    }
  }
  assert.ok(count >= 77);
  for (const e of resolve.errors) assert.throws(() => K.resolve(e.gesture, null), RangeError, e.about);
  for (const e of resolve.bad_keymaps) assert.throws(() => K.resolve(e.gesture, e.prompt, e.keymap), RangeError, e.about);
  for (const e of resolve.bad_contexts) assert.throws(() => K.resolve(e.gesture, null, null, e.context), RangeError, e.about);
  assert.deepEqual(K.combos(null, ["pocket"]), { 1: [2, 3], 2: [2], 3: [2, 3] }, "a pocket engine gets the double taps");
  assert.deepEqual(K.combos(), { 1: [3], 3: [3] }, "no context: the combos are what they were");
  assert.deepEqual(K.resolve("tap1", undefined), K.resolve("tap1", null), "no prompt is no prompt, however it is said");
});

test("the keymap says which prompts take raw edges, and what is wrong with a keymap", () => {
  for (const kind of C.PROMPT_KINDS) assert.equal(K.wantsRaw(kind), kind === "game", kind);
  assert.equal(K.wantsRaw("constructor"), false);
  assert.deepEqual(K.combos(), G.combosFromKeymap(C.KEYMAP));
  assert.deepEqual(K.problems(C.KEYMAP), []);
  assert.ok(K.problems(resolve.bad_keymaps[0].keymap).length > 0);
  const twice = { v: 2, prompt: { tap1: { abc: null } }, idle: { tap2: "next" }, always: { tap1: "stop", tap2: "stop" } };
  assert.deepEqual(K.problems(twice), ["/prompt/tap1: always names this gesture too, so this entry never applies",
    "/idle/tap2: always names this gesture too, so this entry never applies"]);
  for (const name of ["constructor", "toString", "__proto__"]) assert.throws(() => K.resolve(name, "abc"), RangeError);
  assert.deepEqual(K.resolve("tap1", "toString").source, null);
});

// ── the optional page helper, against stand-in elements and a hand-turned clock ─────────────
function standIns() {
  const target = () => {
    const handlers = {};
    return { handlers, captured: [], addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
      removeEventListener(type, fn) { handlers[type] = (handlers[type] || []).filter((f) => f !== fn); },
      setPointerCapture(id) { this.captured.push(id); },
      fire(type, ev) { (handlers[type] || []).slice().forEach((fn) => fn(ev || {})); } };
  };
  return { els: [target(), target(), target()], keys: target() };
}

test("gestures.listen turns pointer and key events into gestures, with one timer", async () => {
  const { els, keys } = standIns();
  let now = 0;
  const seen = [], edges = [];
  let raw = false;
  const heard = G.listen(els, (g) => seen.push(g.name + "@" + g.tMs), { keyTarget: keys, now: () => now, holdMs: 60, tapFollowMs: 40,
    combos: { 1: [3] }, raw: (b) => raw && b !== 3, onEdge: (b, kind, t) => edges.push(b + kind + "@" + t) });
  els[1].fire("pointerdown", { pointerId: 7 }); now = 10; els[1].fire("pointerup");
  assert.deepEqual(seen, ["tap2@10"]);
  assert.deepEqual(els[1].captured, [7]);
  els[1].fire("pointerdown", { button: 2 });                    // not the main button
  assert.equal(heard.engine.isDown(2), false);
  now = 100; els[2].fire("pointerdown");
  now = 170;                                                     // the timer, not an event, reports the hold
  for (let i = 0; i < 200 && seen.length < 2; i++) await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(seen, ["tap2@10", "hold3@160"]);
  now = 200; els[2].fire("pointerup");
  now = 300; keys.fire("keydown", { key: "1" }); keys.fire("keydown", { key: "1", repeat: true }); now = 310; keys.fire("keyup", { key: "1" });
  now = 320; keys.fire("keydown", { key: "1" }); now = 330; keys.fire("keyup", { key: "1" });
  now = 340; keys.fire("keydown", { key: "1" }); now = 350; keys.fire("keyup", { key: "1" });
  keys.fire("keydown", { key: "q" }); keys.fire("keydown", { key: "2", ctrlKey: true });
  assert.deepEqual(seen.slice(2), ["tap1x3@350"]);
  now = 400; els[0].fire("pointerdown"); now = 410; els[0].fire("pointercancel");
  assert.equal(heard.engine.isDown(1), false);
  assert.equal(heard.engine.pending(), 0, "a cancelled press is not a tap");
  raw = true; now = 500; els[1].fire("pointerdown"); now = 590; els[1].fire("pointerup");
  assert.deepEqual(edges, ["2down@500", "2up@590"]);
  assert.equal(seen.length, 3, "raw edges do not go through the engine");
  now = 600; els[2].fire("pointerdown"); now = 610; els[2].fire("pointerup");
  assert.deepEqual([seen.length, seen[3], edges.length], [4, "tap3@610", 2], "raw is asked per button: 3 still makes gestures");
  now = 620; els[1].fire("pointerdown"); raw = false; now = 630; els[1].fire("pointerup");
  assert.deepEqual(edges.slice(2), ["2down@620", "2up@630"], "a press that began raw ends raw");
  let prevented = 0;
  const ev = (key) => ({ key, preventDefault() { prevented += 1; } });
  now = 640; els[1].fire("keydown", ev(" ")); now = 650; els[1].fire("keyup", ev(" "));
  now = 660; els[1].fire("keydown", ev("Enter")); els[1].fire("blur");
  els[1].fire("contextmenu", ev());
  assert.deepEqual([seen.slice(4), prevented, heard.engine.isDown(2)], [["tap2@650"], 4, false], "Space presses a focused button; losing focus cancels");
  now = 670; heard.edge("down", 2); now = 680; heard.edge("up", 2);
  assert.equal(seen[5], "tap2@680", "an edge can be fed by hand");
  heard.stop();
  now = 700; els[1].fire("pointerdown"); els[1].fire("pointerup");
  assert.equal(seen.length, 6, "stopped means stopped");
  assert.ok(Object.values(els[1].handlers).every((h) => h.length === 0), "and every listener is removed");
});

test("gestures.listen reports every press beginning and ending, and its combos can change while it listens", () => {
  const { els, keys } = standIns();
  let now = 0, raw = false;
  const seen = [], changes = [], edges = [];
  const heard = G.listen(els, (g) => seen.push(g.name + "@" + g.tMs), { keyTarget: keys, now: () => now, holdMs: 60, tapFollowMs: 40, combos: {},
    raw: () => raw, onEdge: (b, kind, t) => edges.push(b + kind + "@" + t),
    onChange: (b, isDown, info) => changes.push([b, isDown, info.tMs, info.raw, info.kind, seen.length]) });
  els[0].fire("pointerdown"); els[0].fire("pointerdown");            // the second down is ignored: one change
  now = 10; els[0].fire("pointerup"); els[0].fire("pointerup");
  assert.deepEqual(changes, [[1, true, 0, false, "down", 0], [1, false, 10, false, "up", 0]], "told before the gesture the edge completes");
  assert.deepEqual(seen, ["tap1@10"]);
  now = 20; els[1].fire("pointerdown"); now = 25; els[1].fire("pointercancel");
  assert.deepEqual(changes.slice(2).map((c) => c.slice(0, 5)), [[2, true, 20, false, "down"], [2, false, 25, false, "cancel"]]);
  raw = true;
  now = 30; keys.fire("keydown", { key: "3" }); now = 40; keys.fire("keyup", { key: "3" });
  assert.deepEqual(changes.slice(4).map((c) => c.slice(0, 5)), [[3, true, 30, true, "down"], [3, false, 40, true, "up"]]);
  assert.deepEqual(edges, ["3down@30", "3up@40"], "onEdge is still for raw presses only");
  raw = false;

  // Button 1 gains a triple tap while it is down: the press in flight is kept and starts a chain.
  now = 100; els[0].fire("pointerdown");
  assert.equal(heard.setCombos({ 1: [3] }), heard);
  assert.deepEqual([heard.engine.isDown(1), heard.engine.combos], [true, { 1: [3] }]);
  now = 110; els[0].fire("pointerup");
  assert.deepEqual([seen.length, heard.engine.pending()], [1, 1]);
  // ...and loses it with that tap pending: the tap is reported at once, not dropped.
  now = 120; heard.setCombos({});
  assert.deepEqual(seen.slice(1), ["tap1@120"]);
  assert.equal(heard.engine.pending(), 0);
  assert.throws(() => heard.setCombos({ 9: [2] }), RangeError);
  heard.stop();
  heard.setCombos({ 1: [3] });                                      // after stop: the engine changes, nothing is reported
  assert.deepEqual(heard.engine.combos, { 1: [3] });
});

test("keymap.isGesture says whether a name is a gesture without throwing", () => {
  for (const name of C.GESTURES) assert.equal(K.isGesture(name), true, name);
  for (const name of ["screen", "tap4", "tap1x4", "", "constructor", "__proto__", null, undefined, 1, ["tap1"]]) assert.equal(K.isGesture(name), false, String(name));
});

test("gestures.listen: a throwing onChange leaves no button down, and stop() ends a press in flight", () => {
  const { els, keys } = standIns();
  let now = 0, raw = false, angry = false;
  const seen = [], changes = [], edges = [];
  const heard = G.listen(els, (g) => seen.push(g.name + "@" + g.tMs), { keyTarget: keys, now: () => now, combos: {},
    raw: () => raw, onEdge: (b, kind, t) => edges.push(b + kind + "@" + t),
    onChange: (b, isDown, info) => { changes.push([b, isDown, info.kind, info.raw]); if (angry) throw new Error("the page's own bug"); } });
  els[0].fire("pointerdown");
  angry = true; now = 20;
  assert.throws(() => els[0].fire("pointerup"), /the page's own bug/);
  assert.equal(heard.engine.isDown(1), false, "the engine was fed all the same");
  assert.throws(() => els[1].fire("pointerdown"), /the page's own bug/);
  assert.equal(heard.engine.isDown(2), true);
  angry = false; changes.length = 0;
  raw = true; now = 30; els[2].fire("pointerdown"); raw = false;
  now = 40;
  heard.stop();
  assert.deepEqual(changes.slice(1), [[2, false, "cancel", false], [3, false, "cancel", true]]);
  assert.deepEqual([heard.engine.isDown(2), edges, heard.engine.pending()], [false, ["3down@30", "3up@40"], 0]);
  heard.stop();                                                     // twice is once
  assert.equal(changes.length, 3);
});
