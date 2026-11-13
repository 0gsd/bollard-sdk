// SPDX-License-Identifier: Apache-2.0
// The binding is whole however it is loaded: require(), import, one <script> tag, the tags
// written out by hand in any order, or a tag added by script.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");
const { ROOT, JS, PARTS, bollardeck } = require("./support.js");

const WHOLE = "b.version && b.constants.HOLD_MS && b.schemas.cue && b.schema.validate && b.cues.at && b.cues.apply && b.matrix.film && b.matrix.canvas && b.gestures.engine && b.gestures.listen && b.keymap.resolve && b.corpus.judge && b.corpus.hub";
const source = (name) => fs.readFileSync(path.join(JS, name), "utf8");
const whole = (b) => !!(b.version && b.constants.HOLD_MS && b.schemas.cue && b.schema.validate && b.cues.at && b.cues.apply && b.matrix.film && b.matrix.canvas && b.gestures.engine && b.gestures.listen && b.keymap.resolve && b.corpus.judge && b.corpus.hub);

function node(script) {
  return execFileSync(process.execPath, ["-e", script], { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
}

test("the files of the binding are the ones bollardeck.js names", () => {
  const files = fs.readdirSync(JS).filter((f) => /\.m?js$/.test(f)).sort();
  assert.deepEqual(files, ["bollardeck.constants.js", "bollardeck.js", "bollardeck.mjs"].concat(PARTS.map((p) => "bollardeck." + p + ".js")).sort());
  const main = source("bollardeck.js");
  assert.ok(main.includes('var PARTS = ' + JSON.stringify(PARTS).replace(/,/g, ", ") + ";"));
  for (const p of PARTS) {
    assert.ok(main.includes("//   bollardeck." + p + ".js"), "bollardeck.js's header does not describe " + p);
    assert.ok(source("bollardeck.mjs").includes('import "./bollardeck.' + p + '.js";'), "bollardeck.mjs does not import " + p);
  }
  assert.ok(whole(bollardeck));
  assert.deepEqual(Object.keys(bollardeck.parts).sort(), PARTS.slice().sort());
});

test("require() of bollardeck.js, or of any part first, gives the same whole object and no warning", () => {
  for (const first of ["bollardeck.js"].concat(PARTS.map((p) => "bollardeck." + p + ".js"))) {
    const out = execFileSync(process.execPath, ["-e",
      "const x = require('./js/" + first + "'); const b = require('./js/bollardeck.js');" +
      "console.log(JSON.stringify([!!(" + WHOLE + "), b === globalThis.bollardeck, typeof x]));" +
      "b.ready.then((r) => { if (r !== b) process.exit(3); });"],
    { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], env: Object.assign({}, process.env, { NODE_OPTIONS: "--throw-deprecation --trace-warnings" }) });
    assert.deepEqual(JSON.parse(out).slice(0, 2), [true, true], first);
    assert.ok(["object", "function"].includes(JSON.parse(out)[2]), first);
  }
  const quiet = execFileSync(process.execPath, ["-e", "require('./js/bollardeck.cues.js'); require('./js/bollardeck.js').matrix.idle(0)"],
    { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  assert.equal(quiet, "");
});

test("a part required by itself is its own namespace", () => {
  const out = JSON.parse(node(
    "const m = require('./js/bollardeck.matrix.js'), s = require('./js/bollardeck.schema.js'), c = require('./js/bollardeck.cues.js'), d = require('./js/bollardeck.schemas.js');" +
    "const b = require('./js/bollardeck.js');" +
    "console.log(JSON.stringify([m === b.matrix, s === b.schema, c === b.cues, d === b.schemas, m.toHex(m.idle(0)).length]))"));
  assert.deepEqual(out, [true, true, true, true, 226]);
});

test("bollardeck.mjs has the whole binding as named exports", () => {
  const out = JSON.parse(node(
    "import('./js/bollardeck.mjs').then((m) => { const b = m.default;" +
    "console.log(JSON.stringify([Object.keys(m).sort(), m.schema === b.schema, m.cues === b.cues, m.matrix === b.matrix, m.schemas === b.schemas, m.constants === b.constants," +
    " !!(" + WHOLE + "), m.schema.isValid('cue', []), b === require('./js/bollardeck.js')])); })"));
  assert.deepEqual(out, [["constants", "corpus", "cues", "default", "gestures", "help", "keymap", "matrix", "minBollawax", "schema", "schemas", "speaks", "version"], true, true, true, true, true, true, true, true]);
});

// ── a page: a stand-in document, and the files run as classic scripts ─────────────────────
function page(opts) {
  opts = opts || {};
  const written = [], added = [], listeners = {};
  const document = {
    readyState: opts.readyState || "loading",
    currentScript: null,
    write: (html) => { written.push(html); },
    addEventListener: (name, fn) => { listeners[name] = fn; },
    createElement: () => ({}),
    head: { appendChild: (s) => { added.push(s); } },
  };
  const sandbox = { document, console, setTimeout, clearTimeout };
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  const run = (name, tag) => {
    document.currentScript = tag === undefined ? { src: "file:///site/js/" + name, async: false, defer: false, type: "", getAttribute: () => null } : tag;
    vm.runInContext(source(name), context, { filename: name });
    document.currentScript = null;
  };
  return { sandbox, document, written, added, listeners, run };
}

test("one plain <script> tag writes a tag for each part, and the page is whole before the next script", async () => {
  const p = page();
  p.run("bollardeck.js");
  assert.deepEqual(p.written, PARTS.map((name) => '<script src="file:///site/js/bollardeck.' + name + '.js"></script>'));
  for (const html of p.written) p.run(/bollardeck\.[a-z]+\.js/.exec(html)[0]);     // the browser runs them next, in order
  const b = p.sandbox.bollardeck;
  assert.ok(whole(b));
  assert.equal(b.schema.validate("cue", [{ button: 4, state: "on", role: null }]).map((x) => x.pointer).join(), "/0/button");
  assert.equal(b.matrix.toHex(b.matrix.idle(0, false)), bollardeck.matrix.toHex(bollardeck.matrix.idle(0, false)));
  p.listeners.DOMContentLoaded();
  assert.equal(await b.ready, b);
});

test("a query string on the tag is kept, so a cache-busting version reaches the parts", () => {
  const p = page();
  p.run("bollardeck.js", { src: "https://example.test/static/sdk/bollardeck.js?v=3&x=\"y\"#frag", async: false, defer: false, type: "", getAttribute: () => null });
  assert.equal(p.written[0], '<script src="https://example.test/static/sdk/bollardeck.schemas.js?v=3&amp;x=&quot;y&quot;"></script>');
});

test("an async, deferred or script-added tag loads the parts in order and bollardeck.ready waits for them", async () => {
  for (const tag of [{ async: true }, { defer: true }, { late: true }]) {
    const p = page({ readyState: tag.late ? "complete" : "loading" });
    p.run("bollardeck.js", { src: "file:///site/js/bollardeck.js", async: !!tag.async, defer: !!tag.defer, type: "", getAttribute: () => null });
    assert.deepEqual(p.written, []);
    assert.deepEqual(p.added.map((s) => [s.src, s.async]), PARTS.map((name) => ["file:///site/js/bollardeck." + name + ".js", false]));
    let done = false;
    p.sandbox.bollardeck.ready.then(() => { done = true; });
    for (const s of p.added) {
      await null;
      assert.equal(done, false);
      p.run(path.basename(s.src));
      s.onload();
    }
    assert.equal(await p.sandbox.bollardeck.ready, p.sandbox.bollardeck);
    assert.ok(whole(p.sandbox.bollardeck));
  }
});

test("a part that does not load rejects bollardeck.ready, naming it", async () => {
  const p = page({ readyState: "complete" });
  p.run("bollardeck.js");
  for (const s of p.added) {
    if (!s.src.endsWith("bollardeck.matrix.js")) { p.run(path.basename(s.src)); s.onload(); } else s.onerror();
  }
  await assert.rejects(p.sandbox.bollardeck.ready, /could not load bollardeck\.matrix\.js/);
  const q = page();
  q.run("bollardeck.js");
  q.listeners.DOMContentLoaded();                              // none of the written tags ran
  await assert.rejects(q.sandbox.bollardeck.ready, /could not load bollardeck\.schemas\.js, bollardeck\.schema\.js/);
});

test("data-parts=\"none\" loads nothing, and hand-written tags work in any order", async () => {
  const p = page();
  p.run("bollardeck.js", { src: "file:///site/js/bollardeck.js", async: false, defer: false, type: "", getAttribute: (n) => (n === "data-parts" ? "none" : null) });
  assert.deepEqual([p.written, p.added], [[], []]);
  assert.equal(await p.sandbox.bollardeck.ready, p.sandbox.bollardeck);
  assert.equal(p.sandbox.bollardeck.matrix, undefined);
  p.run("bollardeck.matrix.js");
  assert.equal(p.sandbox.bollardeck.matrix.N, 104);

  // Parts before bollardeck.js need nothing said; parts after it need data-parts="none" on its tag,
  // or it will have asked for them already.
  const none = { src: "file:///site/js/bollardeck.js", async: false, defer: false, type: "", getAttribute: (n) => (n === "data-parts" ? "none" : null) };
  const orders = [PARTS.slice().reverse().concat(["bollardeck"]), ["dom", "keymap", "help", "matrix", "corpus", "bollardeck", "cues", "gestures", "schema", "schemas"], ["bollardeck"].concat(PARTS)];
  for (const order of orders) {
    const q = page();
    const last = order[order.length - 1] === "bollardeck";
    for (const name of order) {
      if (name === "bollardeck") q.run("bollardeck.js", last ? undefined : none);
      else q.run("bollardeck." + name + ".js");
    }
    assert.deepEqual(q.written, [], order.join(" ") + ": nothing more is asked for");
    assert.ok(whole(q.sandbox.bollardeck), order.join(" "));
    assert.equal(await q.sandbox.bollardeck.ready, q.sandbox.bollardeck);
    const matrix = q.sandbox.bollardeck.matrix;
    q.run("bollardeck.matrix.js");                             // a part loaded twice changes nothing
    assert.equal(q.sandbox.bollardeck.matrix, matrix);
    assert.ok(whole(q.sandbox.bollardeck));
  }
  const alone = page();
  alone.run("bollardeck.matrix.js");
  assert.equal(alone.sandbox.bollardeck.matrix.toHex(alone.sandbox.bollardeck.matrix.glyph("boot", 0)).length, 226, "the matrix engine works with nothing else loaded");
});

test("data-parts with a list loads those parts and no others", async () => {
  const tag = (parts, more) => Object.assign({ src: "file:///site/js/bollardeck.js?v=7", async: false, defer: false, type: "",
    getAttribute: (n) => (n === "data-parts" ? parts : null) }, more || {});
  const p = page();
  p.run("bollardeck.js", tag("matrix  cues"));
  assert.deepEqual(p.written, ["cues", "matrix"].map((name) => '<script src="file:///site/js/bollardeck.' + name + '.js?v=7"></script>'), "in the binding's own order");
  p.run("bollardeck.cues.js"); p.run("bollardeck.matrix.js");
  p.listeners.DOMContentLoaded();
  const b = p.sandbox.bollardeck;
  assert.equal(await b.ready, b);
  assert.deepEqual([typeof b.cues.at, b.matrix.N, b.schema, b.corpus, b.gestures], ["function", 104, undefined, undefined, undefined]);

  const late = page({ readyState: "complete" });
  late.run("bollardeck.js", tag("gestures,keymap, dom"));
  assert.deepEqual(late.added.map((s) => path.basename(s.src)), ["bollardeck.gestures.js?v=7", "bollardeck.keymap.js?v=7", "bollardeck.dom.js?v=7"]);
  assert.deepEqual(late.written, []);
  for (const s of late.added) { late.run(path.basename(s.src).replace(/\?.*$/, "")); s.onload(); }
  assert.equal(await late.sandbox.bollardeck.ready, late.sandbox.bollardeck);
  assert.equal(typeof late.sandbox.bollardeck.gestures.listen, "function");

  const missing = page();                                      // a listed part that does not load is named
  missing.run("bollardeck.js", tag("cues matrix"));
  missing.run("bollardeck.cues.js");
  missing.listeners.DOMContentLoaded();
  await assert.rejects(missing.sandbox.bollardeck.ready, /could not load bollardeck\.matrix\.js$/);

  const had = page();                                          // a listed part that is already there is not asked for again
  had.run("bollardeck.cues.js");
  had.run("bollardeck.js", tag("cues"));
  assert.deepEqual([had.written, had.added], [[], []]);
  assert.equal(await had.sandbox.bollardeck.ready, had.sandbox.bollardeck);

  for (const bad of ["cues matrx", "none cues", "__proto__", ", ,x"]) {
    const q = page();
    q.run("bollardeck.js", tag(bad));
    assert.deepEqual([q.written, q.added], [[], []], JSON.stringify(bad));
    await assert.rejects(q.sandbox.bollardeck.ready, /data-parts names no such part/, JSON.stringify(bad));
  }
  for (const empty of ["", "  "]) {                            // an empty data-parts says nothing: every part, as before
    const q = page();
    q.run("bollardeck.js", tag(empty));
    assert.equal(q.written.length, PARTS.length, JSON.stringify(empty));
  }
  const none = page();                                         // "none" still writes nothing, with or without spaces
  none.run("bollardeck.js", tag(" none "));
  assert.deepEqual([none.written, none.added], [[], []]);
  assert.equal(await none.sandbox.bollardeck.ready, none.sandbox.bollardeck);
});

test("with no document at all (a worker, a shell) bollardeck.js still defines the core", () => {
  const sandbox = {};
  sandbox.globalThis = sandbox;
  vm.runInContext(source("bollardeck.js"), vm.createContext(sandbox));
  assert.equal(sandbox.bollardeck.version, bollardeck.version);
  assert.deepEqual(JSON.parse(JSON.stringify(sandbox.bollardeck.constants)), JSON.parse(JSON.stringify(bollardeck.constants)));
});

test("the browser example loads the binding from beside itself with one tag and nothing from a network", () => {
  const html = fs.readFileSync(path.join(ROOT, "examples", "browser", "index.html"), "utf8");
  assert.ok(html.includes('<script src="../../js/bollardeck.js"></script>'));
  assert.equal((html.match(/<script[^>]*\bsrc=/g) || []).length, 1, "one script tag with a src");
  assert.ok(!/https?:\/\//.test(html.replace(/<!--[\s\S]*?-->/g, "")), "the example fetches nothing");
  // Its inline script runs against stand-ins far enough to draw a frame and light a button.
  const inline = /<script>([\s\S]*?)<\/script>/.exec(html)[1];
  const drawn = [], made = {};
  const el = () => { const a = new Map(), s = new Map(); return { textContent: "", hasAttribute: (n) => a.has(n), getAttribute: (n) => (a.has(n) ? a.get(n) : null),
    setAttribute: (n, v) => a.set(n, v), removeAttribute: (n) => a.delete(n), addEventListener: () => {}, value: "0",
    style: { getPropertyValue: (n) => s.get(n) || "", setProperty: (n, v) => s.set(n, v), removeProperty: (n) => s.delete(n) }, a,
    width: 260, height: 190, getContext: () => new Proxy({}, { get: (t, k) => (k in t ? t[k] : (...args) => { if (k === "arc") drawn.push(args); }), set: (t, k, v) => { t[k] = v; return true; } }) }; };
  const p = page();
  p.run("bollardeck.js");
  PARTS.forEach((name) => p.run("bollardeck." + name + ".js"));
  Object.assign(p.sandbox, { performance: { now: () => 400 }, matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => 1, cancelAnimationFrame: () => {} });
  p.document.getElementById = (id) => (made[id] = made[id] || el());
  vm.runInContext(inline, p.sandbox, { filename: "examples/browser/index.html" });
  assert.ok(drawn.length > 104, "the example drew the matrix");
  assert.ok(["on", "pulse", "chase"].includes(made["btn-1"].getAttribute("data-cue")), "the example lit button 1");
});
