// SPDX-License-Identifier: Apache-2.0
// bollardeck.help: packs, topics, the detectors, the engine's rules, and the director.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { CONFORMANCE, readJson, bollardeck } = require("./support.js");

const H = bollardeck.help;
const K = bollardeck.constants;
const FULL = readJson(CONFORMANCE, "help-pack", "valid", "full.json");

function clockAt(t0) {
  const c = { t: t0 };
  c.now = () => c.t;
  return c;
}

function pagePack(scenarios, topics) {
  return H.pack({
    schema: "help-pack/1", pack: "t.p", lang: "en", rev: 1,
    pages: { device: {
      intro: { owner: { title: "hi", body: [["hello"]] } },
      topics: Object.assign({
        "device.make-busy": { title: "busy", body: [["wait"]], targets: ["device.make"] },
        "device.power": { title: "power", body: [["hold 3"]], targets: ["device.button3"], rev: 2 },
        "device.guest-only": { title: "g", body: [["g"]], when: { roles: ["guest"] } }
      }, topics || {}),
      scenarios: scenarios
    } }
  });
}

test("a pack is validated, frozen, and its problems name places", () => {
  const p = H.pack(FULL);
  assert.ok(Object.isFrozen(p.pages.player.topics));
  const bad = JSON.parse(JSON.stringify(FULL));
  bad.pages.player.scenarios["player.play-blocked"].topic = "player.nothing";
  bad.pages.player.topics["player.play"].see = ["player.gone"];
  bad.pages.player.scenarios["player.offline"].detector = "telepathy";
  const at = H.problems(bad).map((p) => [p.pointer, p.keyword]);
  assert.deepEqual(at, [
    ["/pages/player/topics/player.play/see/0", "see"],
    ["/pages/player/scenarios/player.play-blocked/topic", "topic"],
    ["/pages/player/scenarios/player.offline/detector", "detector"]
  ]);
  assert.throws(() => H.pack(bad), (e) => e instanceof TypeError && e.problems.length === 3);
});

test("topics and intros come out as this person should read them", () => {
  const p = H.pack(FULL);
  assert.equal(H.intro(p, "player", { role: "owner", tier: "free" }).body[0][0], "it plays your music.");
  assert.equal(H.intro(p, "player", { role: "owner", tier: "paid" }).body[0][0], "it plays everything.");
  assert.equal(H.intro(p, "player", { role: "visitor" }), null);
  const t = H.topic(p, "player", "player.play", { role: "owner" });
  assert.deepEqual([t.rev, t.tour, t.targets], [2, "tour.player.play", ["player.play"]]);
  assert.equal(H.topic(p, "player", "player.play", { role: "visitor" }), null);
  assert.equal(H.topic(p, "player", "player.queue", { role: "visitor" }).rev, 1);
  assert.deepEqual(H.scenarios(p, "player", { role: "owner", site: "other" }).map((s) => s.id), ["player.offline", "player.play-blocked"]);
  assert.deepEqual(H.scenarios(p, "player", { role: "owner", site: "example" }).map((s) => s.id),
    ["player.offline", "player.play-blocked", "x.myskin.knob-spin"]);
});

test("merge keeps the first pack's ids and lets later packs add only x.* topics", () => {
  const a = pagePack({}), b = JSON.parse(JSON.stringify(a));
  b.pack = "x.skin";
  b.pages.device.topics["device.make-busy"].title = "hijacked";
  b.pages.device.topics["x.skin.dial"] = { title: "dial", body: [["turn it"]] };
  b.pages.device.intro.owner.title = "other intro";
  const m = H.merge([a, b]);
  assert.equal(m.pages.device.topics["device.make-busy"].title, "busy");
  assert.equal(m.pages.device.topics["x.skin.dial"].title, "dial");
  assert.equal(m.pages.device.intro.owner.title, "hi");
});

test("lint names every target a page does not have, for the roles that would see it", () => {
  const p = H.pack(FULL);
  const problems = H.lint(p, { player: { owner: ["player.play"], guest: ["player.play"] } });
  assert.deepEqual(problems.map((x) => x.pointer), [
    "/pages/player/topics/x.myskin.knob/targets/0", "/pages/player/topics/x.myskin.knob/targets/0",
    "/pages/player/scenarios/x.myskin.knob-spin/target", "/pages/player/scenarios/x.myskin.knob-spin/target"
  ]);
});

// ── the detectors, one by one ────────────────────────────────────────────────────────────

const view = { start: 0 };
function d(name, events, now, s) { return H.detectors[name](events, now, Object.assign({ params: {} }, s), view); }

test("blocked-repeat counts blocked uses of its target inside the window", () => {
  const s = { target: "device.make" };
  const two = [{ t: 1000, kind: "activate", target: "device.make", blocked: true }, { t: 5000, kind: "activate", target: "device.make", blocked: true }];
  assert.ok(d("blocked-repeat", two, 6000, s).fire);
  assert.equal(d("blocked-repeat", two, 9500, s), null);                      // the first left the 8 s window
  assert.equal(d("blocked-repeat", [two[0], { t: 2000, kind: "activate", target: "device.make", blocked: false }], 3000, s), null);
  assert.equal(d("blocked-repeat", two.map((e) => Object.assign({}, e, { target: "device.other" })), 6000, s), null);
});

test("rage wants three presses close together, close in time", () => {
  const near = [0, 300, 600].map((t, i) => ({ t, kind: "press", x: 100 + i * 5, y: 100 }));
  assert.ok(d("rage", near, 700, {}).fire);
  assert.equal(d("rage", near.map((e, i) => Object.assign({}, e, { x: e.x + i * 40 })), 700, {}), null);
  assert.equal(d("rage", near, 1400, {}), null);
});

test("error-code, signal-repeat, dwell, idle-after-landing, bounce and abandon", () => {
  assert.ok(d("error-code", [{ t: 10, kind: "error", code: "corpus_requires_paid" }], 20, { codes: ["corpus_requires_paid"] }).fire);
  assert.equal(d("error-code", [{ t: 10, kind: "error", code: "other" }], 20, { codes: ["corpus_requires_paid"] }), null);

  const sig = [{ t: 100, kind: "signal", name: "band.timeout" }, { t: 200, kind: "signal", name: "band.timeout" }];
  assert.ok(d("signal-repeat", sig, 300, { signal: "band.timeout", params: { n: 2 } }).fire);
  assert.equal(d("signal-repeat", sig.slice(0, 1), 300, { signal: "band.timeout", params: { n: 2 } }), null);

  const seen = [{ t: 0, kind: "visible", target: "device.codex", on: true }], w = { target: "device.codex", params: { ms: 15000, presses: 0 } };
  assert.ok(d("dwell", seen, 15000, w).fire);
  assert.equal(d("dwell", seen.concat([{ t: 9000, kind: "activate", target: "device.codex" }]), 15000, w), null);
  assert.equal(d("dwell", seen.concat([{ t: 9000, kind: "visible", target: "device.codex", on: false }]), 15000, w), null);

  assert.ok(d("idle-after-landing", [], 20000, {}).fire);
  assert.equal(d("idle-after-landing", [{ t: 500, kind: "input" }], 20000, {}), null);
  assert.equal(d("idle-after-landing", [{ t: 500, kind: "signal", name: "fm.tuned" }], 20000, { params: { unless: ["fm.tuned"] } }), null);
  assert.equal(d("idle-after-landing", [], 19999, {}), null);

  const closes = [1, 2].map((i) => ({ t: i * 1000, kind: "toggle", target: "device.mode", open: false }));
  assert.ok(d("bounce", closes, 3000, { target: "device.mode" }).fire);
  const nav = ["fm", "device", "fm"].map((page, i) => ({ t: i * 1000, kind: "nav", page }));
  assert.ok(d("bounce", nav, 3000, { params: { nav: true } }).fire);

  const flow = ["start", "cancel", "start", "cancel"].map((state, i) => ({ t: i * 10, kind: "flow", target: "device.go-public", state }));
  assert.ok(d("abandon", flow, 100, { target: "device.go-public" }).fire);
  flow.splice(2, 0, { t: 15, kind: "flow", target: "device.go-public", state: "submit" });
  assert.equal(d("abandon", flow, 100, { target: "device.go-public" }), null);
});

test("a page's own detector is named x-<name>", () => {
  assert.throws(() => H.detector("spin", () => null), RangeError);
  H.detector("x-always", () => ({ fire: true, evidence: {} }));
  assert.equal(typeof H.detectors["x-always"], "function");
});

// ── the engine's rules ───────────────────────────────────────────────────────────────────

function busyEngine(clock, store, more) {
  const p = pagePack({
    "device.make-busy": { topic: "device.make-busy", detector: "blocked-repeat", target: "device.make" },
    "device.power-off": { topic: "device.power", detector: "signal-repeat", signal: "ball.press-while-off" }
  });
  return H.engine(Object.assign({ pack: p, page: "device", ctx: { role: "owner" }, clock: clock.now, store: store, viewStart: 0 }, more || {}));
}
function block(e, t) { return e.feed({ t, kind: "activate", target: "device.make", blocked: true }); }

test("nothing in the first seconds of a view; then one offer, once a view", () => {
  const c = clockAt(0), e = busyEngine(c);
  assert.deepEqual(block(e, 1000).concat(block(e, 2000)), []);              // landing quiet
  c.t = 12000;
  assert.deepEqual(block(e, 11000), []);                                    // one is not a struggle
  const got = block(e, 12000);
  assert.deepEqual(got.map((o) => [o.scenario, o.topic, o.target]), [["device.make-busy", "device.make-busy", "device.make"]]);
  assert.equal(e.open().length, 1);
  e.settle("device.make-busy", "opened");
  assert.deepEqual(block(e, 13000), []);                                    // the scenario is spent for this view
});

test("one offer at a time; a struggle that waits for its turn is not lost", () => {
  const c = clockAt(20000), e = busyEngine(c, undefined, { policy: { HELP_OFFERS_PER_VIEW: 3 } });
  block(e, 20000);
  assert.equal(block(e, 20500).length, 1);
  assert.deepEqual(e.feed({ t: 21000, kind: "signal", name: "ball.press-while-off" }), []);   // busy: waits
  e.settle("device.make-busy", "opened");
  // a signal names no control: the offer points at the topic's first target
  assert.deepEqual(e.tick(21500).map((o) => [o.topic, o.target]), [["device.power", "device.button3"]]);
});

test("cooldown, snooze after ignores, NOT NOW, STOP OFFERING HELP, quiet zones", () => {
  const store = H.memoryStore(), c = clockAt(20000), apart = { policy: { HELP_BACKOFF_IGNORES: 99 } };
  let e = busyEngine(c, store, apart);
  block(e, 20000); assert.equal(block(e, 20100).length, 1);
  e.settle("device.make-busy", "ignored");
  e = busyEngine(c, store, Object.assign({ viewStart: 30000 }, apart));      // a new view, same day
  block(e, 50000); assert.equal(block(e, 50100).length, 0);                  // the topic's day-long cooldown
  for (let i = 1; i <= 2; i++) {                                             // two more ignored days: snoozed
    c.t = i * K.HELP_TOPIC_COOLDOWN_MS + 100000;
    e = busyEngine(c, store, Object.assign({ viewStart: c.t - 20000 }, apart));
    block(e, c.t); assert.equal(block(e, c.t + 1).length, 1);
    e.settle("device.make-busy", "ignored");
  }
  c.t = 3 * K.HELP_TOPIC_COOLDOWN_MS + 100000;
  e = busyEngine(c, store, Object.assign({ viewStart: c.t - 20000 }, apart));
  block(e, c.t); assert.equal(block(e, c.t + 1).length, 0);
  assert.ok(store.get().topics["device.make-busy"].snooze_until > c.t);

  const c2 = clockAt(20000), e2 = busyEngine(c2);
  e2.offersOff(true);
  block(e2, 20000); assert.equal(block(e2, 20100).length, 0);
  e2.offersOff(false);
  e2.quiet("dialog", true);
  assert.equal(block(e2, 20200).length, 0);
  e2.quiet("dialog", false);
  assert.equal(block(e2, 20300).length, 1);
  e2.snooze("device.make-busy");
  assert.equal(e2.open().length, 0);
  assert.ok(e2.state().topics["device.make-busy"].snooze_until >= 20000 + K.HELP_SNOOZE_MS);
});

test("a read topic comes back only when its struggle recurs on enough later days, or its rev rises", () => {
  const store = H.memoryStore(), c = clockAt(20000);
  let e = busyEngine(c, store);
  block(e, 20000); block(e, 20100);
  e.settle("device.make-busy", "opened"); e.read("device.make-busy");
  let day = 1, offers = 0;
  for (; day <= 4; day++) {
    c.t = day * 86400000 + 20000;
    e = busyEngine(c, store, { viewStart: c.t - 20000 });
    block(e, c.t); offers += block(e, c.t + 1).length;
    if (offers) break;
  }
  assert.equal(day, K.HELP_RECUR_DAYS);           // fired on days 1, 2 and 3: offered on the third
});

test("the same events give the same offers", () => {
  function run() {
    const c = clockAt(0), e = busyEngine(c), out = [];
    e.on("offer", (o) => out.push(o));
    [11000, 11500, 30000].forEach((t) => block(e, t));
    e.feed({ t: 31000, kind: "signal", name: "ball.press-while-off" });
    e.settle("device.make-busy", "opened");
    e.tick(32000);
    return JSON.stringify(out);
  }
  assert.equal(run(), run());
});

test("the engine backs off after offers are left alone, longer each time, until one is opened", () => {
  const store = H.memoryStore(), c = clockAt(0);
  let day = 0;
  function view() { c.t = day * 86400000 + 20000; return busyEngine(c, store, { viewStart: c.t - 20000 }); }
  function offerAndIgnore(topicSignal) {
    const e = view();
    const got = topicSignal ? e.feed({ t: c.t, kind: "signal", name: "ball.press-while-off" }) : (block(e, c.t), block(e, c.t + 1));
    if (got.length) e.settle(got[0].topic, "ignored");
    return got.length;
  }
  assert.equal(offerAndIgnore(false), 1); day = 2;
  assert.equal(offerAndIgnore(true), 1);                        // two left alone in a row, two topics
  const s1 = store.get();
  assert.equal(s1.backoff, 1);
  assert.equal(s1.quiet_until, c.t + K.HELP_BACKOFF_MS);
  day = 2.5; assert.equal(offerAndIgnore(true) + offerAndIgnore(false), 0);   // backing off: nothing at all
  day = 5; offerAndIgnore(false); day = 7; offerAndIgnore(true);
  assert.equal(store.get().backoff, 2);
  assert.equal(store.get().quiet_until, c.t + 2 * K.HELP_BACKOFF_MS);          // doubled
  day = 12;
  const e = view(); block(e, c.t); const got = block(e, c.t + 1);
  assert.equal(got.length, 1);
  e.settle(got[0].topic, "opened");
  assert.deepEqual([store.get().backoff, store.get().quiet_until, store.get().ignored_run], [0, 0, 0]);
});

test("a quiet zone withdraws the offer that is up, and it does not count against anything", () => {
  const c = clockAt(20000), e = busyEngine(c), settled = [];
  e.on("settle", (x) => settled.push(x.outcome));
  block(e, 20000); assert.equal(block(e, 20100).length, 1);
  e.quiet("prompt", true);
  assert.deepEqual([e.open().length, settled], [0, ["withdrawn"]]);
  const r = e.state().topics["device.make-busy"];
  assert.equal(r.last_offer, undefined);
  assert.equal(r.ignores, undefined);
  assert.equal(block(e, 20200).length, 0);                      // still quiet
  e.quiet("prompt", false);
  assert.equal(block(e, 20300).length, 1);                      // the same view may offer it again
});

test("a struggle that stays true between the band's questions comes back once a view, then counts as left alone", () => {
  const p = pagePack({ "device.band-asks": { topic: "device.make-busy", detector: "signal-repeat", signal: "band.timeout",
    params: { n: 2, window_ms: 600000 } } });
  let t = 20000;
  const store = H.memoryStore(), e = H.engine({ pack: p, page: "device", ctx: { role: "owner" }, clock: () => t, store, viewStart: 0 });
  const outcomes = [];
  let offers = 0;
  e.on("offer", () => offers++);
  e.on("settle", (x) => outcomes.push(x.outcome));
  e.feed({ t, kind: "signal", name: "band.timeout" }); e.feed({ t: t + 1, kind: "signal", name: "band.timeout" });
  for (let k = 0; k < 20; k++) {                     // ten minutes: the band asks for 20 s of every 30
    t += 6000; e.quiet("prompt", true);
    t += 20000; e.quiet("prompt", false); e.tick(t);
    t += 4000; e.tick(t);
  }
  assert.equal(offers, 2);
  assert.deepEqual(outcomes, ["withdrawn", "ignored"]);
  assert.equal(store.get().topics["device.make-busy"].ignores, 1);
  assert.equal(store.get().ignored_run, 1);
});

test("dwell wants the person busy elsewhere, not just watching", () => {
  const s = { target: "device.codex", params: { ms: 15000 } }, seen = [{ t: 0, kind: "visible", target: "device.codex", on: true }];
  assert.equal(d("dwell", seen, 60000, s), null);
  const busy = seen.concat([{ t: 3000, kind: "press", x: 1, y: 1, target: "device.make" }, { t: 4000, kind: "input" }]);
  assert.ok(d("dwell", busy, 15000, s).fire);
  assert.equal(d("dwell", seen.concat([{ t: 3000, kind: "press", x: 1, y: 1, target: "device.codex" }]), 15000, s), null);
  assert.ok(d("dwell", seen, 15000, { target: "device.codex", params: { ms: 15000, presses: 0 } }).fire);
});

test("an engine's events stay bounded on a page left open for hours, and nav bounce still works", () => {
  const c = clockAt(0), e = busyEngine(c, undefined, { viewStart: 0, policy: { HELP_OFFERS_PER_VIEW: 0 } });
  e.feed({ t: 0, kind: "nav", page: "fm" }); e.feed({ t: 1, kind: "nav", page: "device" });
  for (let i = 0; i < 20000; i++) e.feed({ t: 2 + i * 360, kind: "input" });   // two hours, one input every 0.36 s
  const size = e.size();
  assert.ok(size.events <= Math.min(K.HELP_EVENTS_MAX, 600000 / 360 + 1), JSON.stringify(size));
  assert.equal(size.navs, 2);
  for (let i = 0; i < 5; i++) e.feed({ t: 7200000 + i, kind: "nav", page: i % 2 ? "fm" : "device" });
  assert.equal(e.size().navs, 3);
  assert.ok(H.detectors.bounce([], 7200010, { params: { nav: true } }, { start: 0, navs: [{ t: 7200002, kind: "nav", page: "device" }, { t: 7200003, kind: "nav", page: "fm" }, { t: 7200004, kind: "nav", page: "device" }] }).fire);
  const late = H.engine({ pack: pagePack({}), page: "device", clock: c.now, viewStart: 0 });
  [5, 1, 3].forEach((t) => late.feed({ t, kind: "input" }));
  assert.equal(late.size().events, 3);
});

test("a link may not hold a backslash, and the page helpers say what a target is in a few words", () => {
  const bad = JSON.parse(JSON.stringify(FULL));
  bad.pages.player.topics["player.queue"].body = [[{ a: "away", href: "/\\evil.example" }]];
  assert.deepEqual(H.problems(bad).map((p) => [p.pointer, p.keyword]), [["/pages/player/topics/player.queue/body/0/0/href", "href"]]);
  const els = {};
  function node(attrs, text, heading) {
    return { getAttribute: (k) => (k in attrs ? attrs[k] : null), textContent: text, querySelector: () => heading || null };
  }
  const doc = { getElementById: (id) => els[id] || null };
  els.h = { textContent: "  CODEX  " };
  assert.equal(H.shortName(doc, node({ "aria-labelledby": "h" }, "a very long panel ".repeat(40))), "CODEX");
  assert.equal(H.shortName(doc, node({ "aria-label": "Play" }, "x")), "Play");
  assert.equal(H.shortName(doc, node({}, "lots ".repeat(40), { textContent: "RIFF BOOK" })), "RIFF BOOK");
  const long = H.shortName(doc, node({}, "word ".repeat(40)));
  assert.ok(long.length <= 60 && long.endsWith("\u2026"), long);
  const made = [];
  const fake = {
    createDocumentFragment: () => ({ appendChild: (n) => made.push(n) }),
    createElement: (tag) => ({ tag, attrs: {}, kids: [], setAttribute(k, v) { this.attrs[k] = v; }, appendChild(n) { this.kids.push(n); } }),
    createTextNode: (t) => ({ text: t })
  };
  H.renderBody(fake, [[{ a: "ok", href: "/fm" }, { a: "no", href: "/\\evil.example" }, { a: "no", href: "//evil.example" },
    { a: "no", href: "/\t/evil.example" }, { a: "no", href: "/\n/evil.example" }, { a: "no", href: "/ x" }, { a: "no", href: "/fm\u0000" }]]);
  assert.deepEqual(made[0].kids.map((k) => [k.tag, k.attrs.href || null]),
    [["a", "/fm"], ["span", null], ["span", null], ["span", null], ["span", null], ["span", null], ["span", null]]);
  ["/\t/evil.example", "/\r\n/evil.example", "/a b", "/x\u007f"].forEach((href) => {
    const doc = JSON.parse(JSON.stringify(FULL));
    doc.pages.player.topics["player.queue"].body = [[{ a: "away", href }]];
    const kw = H.problems(doc).map((p) => p.keyword);            // refused: by the link check, or already by the schema
    assert.ok(kw.includes("href") || kw.includes("pattern"), JSON.stringify(href) + " " + JSON.stringify(kw));
  });
});

// ── the director ─────────────────────────────────────────────────────────────────────────

const CAPTURE = readJson(CONFORMANCE, "help-director", "valid", "capture.json");

test("reading time and caption cues", () => {
  assert.equal(H.sayMs("hi."), K.HELP_SAY_MIN_MS);
  assert.equal(H.sayMs(Array(20).fill("word").join(" ")), 20 * K.HELP_SAY_MS_PER_WORD);
  const cues = H.splitCaption("click MAKE A NEW SONG and the band will spin itself up, asking you to make quick decisions during composition to influence the outcome.");
  cues.forEach((c) => c.split("\n").forEach((l) => assert.ok(l.length <= K.HELP_CAPTION_LINE, l)));
  cues.forEach((c) => assert.ok(c.split("\n").length <= 2));
  assert.equal(cues.join(" ").replace(/\n/g, " "), "click MAKE A NEW SONG and the band will spin itself up, asking you to make quick decisions during composition to influence the outcome.");
});

test("a tour drops act, cut and capture-only steps; holds come from the verbs", () => {
  const tl = H.timeline(CAPTURE, "tour");
  assert.ok(!tl.some((s) => s.do === "act" || s.do === "cut" || s.capture_only));
  assert.equal(tl.find((s) => s.do === "say").hold, 1200);
  assert.equal(tl.find((s) => s.do === "spot").hold, K.HELP_HOLD_MS.spot);
  assert.equal(H.timeline(CAPTURE, "capture").length, CAPTURE.steps.length);
});

test("director problems: say length, @say with no say, too long", () => {
  const long = { schema: "help-director/1", id: "tour.a.b", title: "t", page: "p", role: "r",
    steps: [{ do: "spot", target: "a.b", pop: "@say" }, { do: "hide" }, { do: "say", text: "x".repeat(K.HELP_SAY_MAX_CHARS + 1) }] };
  assert.deepEqual(H.directorProblems(long).map((p) => p.keyword), ["pop", "say-length"]);
  const forever = { schema: "help-director/1", id: "tour.a.b", title: "t", page: "p", role: "r", steps: [{ do: "wait", ms: K.HELP_SCRIPT_MAX_MS + 1 }] };
  assert.deepEqual(H.directorProblems(forever).map((p) => p.keyword), ["length"]);
  assert.deepEqual(H.directorProblems(CAPTURE), []);
});

test("play runs a script against a ui, logs every step and makes captions from the log", async () => {
  const script = H.director({ schema: "help-director/1", id: "tour.a.b", title: "t", page: "p", role: "r", steps: [
    { do: "chapter", title: "one" }, { do: "spot", target: "a.b", pop: "@say" },
    { do: "say", text: "first sentence here. and a second one." }, { do: "act", target: "a.b", action: "click" },
    { do: "cut", until: "signal:x.done", max_ms: 100 }, { do: "hide" }, { do: "chapter", title: "two" }, { do: "say", text: "bye.", ms: 1000 }] });
  let t = 0;
  const calls = [];
  const ui = new Proxy({}, { get: (_, verb) => (s, cues) => { calls.push([verb, cues ? cues.length : null]); } });
  const opts = { clock: () => t, sleep: (ms) => { t += ms; return Promise.resolve(); }, waitFor: () => Promise.resolve(true) };
  const tour = await H.play(script, ui, opts);
  assert.deepEqual(tour.map((e) => e.verb), ["chapter", "spot", "say", "hide", "chapter", "say"]);
  const cuts = [];
  const log = await H.play(script, ui, Object.assign({ mode: "capture", cut: (on) => cuts.push(on) }, opts));
  assert.deepEqual(log.map((e) => e.verb), script.steps.map((s) => s.do));
  assert.deepEqual(cuts, [true, false]);
  const vtt = H.vtt(log, script);
  assert.ok(vtt.startsWith("WEBVTT\n\n"));
  assert.match(vtt, /\d\d:\d\d:\d\d\.\d{3} --> \d\d:\d\d:\d\d\.\d{3}\nfirst sentence here\. and a second one\./);
  assert.match(H.chaptersVtt(log, script), /\none\n/);
  assert.deepEqual(H.readText(script), [{ chapter: "one", text: "first sentence here. and a second one." }, { chapter: "two", text: "bye." }]);
  await assert.rejects(H.play(script, ui, Object.assign({}, opts, { mode: "capture", waitFor: () => Promise.resolve(false) })), /step 4/);
});

test("lintDirector names unknown targets and signals", () => {
  const got = H.lintDirector(CAPTURE, { player: { owner: ["player.play"] } }, ["song.locked"]);
  assert.deepEqual(got.map((p) => p.pointer), ["/steps/2/target", "/steps/10/until"]);
});

test("the help part loads on its own, and dom adds the page helpers", () => {
  assert.equal(path.basename(require.resolve("../../js/bollardeck.help.js")), "bollardeck.help.js");
  ["listen", "cta", "modal", "spot", "ui", "sheet", "renderBody", "place"].forEach((k) => assert.equal(typeof H[k], "function", k));
  assert.equal(typeof H.CSS, "string");
});
