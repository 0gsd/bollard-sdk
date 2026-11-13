// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.dom.js: the optional helpers that touch a page. Everything else in the binding is
 * pure and runs anywhere; this file is the only one that uses elements, a canvas or animation
 * frames. Nothing here runs until you call it, so loading it under Node is harmless.
 *
 *   bollardeck.cues.apply(elements, entries, opts)
 *       Put what bollardeck.cues.at() returned on elements. `elements` is {1: el, 2: el, 3: el} or
 *       [el1, el2, el3]; a missing one is skipped. A driven button's element gets
 *       data-cue="off|on|pulse|chase", data-cue-role="a|b|c|live|go|warn" (removed for no role) and
 *       the custom properties --cue-level (0..1) and --cue-head (0, 1, 2; removed unless chasing).
 *       An undriven button's element has all four removed. Your stylesheet decides how that looks.
 *       opts.properties: false writes no custom property, so the element never gains a style
 *       attribute (for a page whose rules forbid inline style); the stylesheet then animates
 *       from data-cue alone. opts.undriven: "off" writes data-cue="off" on an undriven button
 *       instead of removing the attribute (its role is still removed).
 *
 *   bollardeck.cues.run(elements, cues, opts) -> {stop()}
 *       Call apply() every animation frame. `cues` is a cue list or a function returning the
 *       current one. opts.calm: true, false or a function; by default the reader's
 *       prefers-reduced-motion setting. opts.now: a clock in ms, by default performance.now.
 *       opts.properties and opts.undriven are passed to apply().
 *
 *   bollardeck.gestures.listen(elements, onGesture, opts) -> {engine, edge(kind, button), setCombos(combos), stop()}
 *       Feed a gesture engine from three elements and call onGesture(gesture) for each gesture.
 *       `elements` is {1: el, 2: el, 3: el} or [el1, el2, el3]. A pointer going down or up on an
 *       element is that button's edge, and so is Space or Enter on a focused one; a pointer that
 *       is cancelled, an element or the window losing focus, cancel the press. Keys work too:
 *       opts.keys maps a key to a button (default "1", "2", "3"), listened for on opts.keyTarget
 *       (default the document; null for no keys). The result's edge(kind, button) feeds an edge
 *       from an event of your own. One timer is
 *       kept, set to the engine's next deadline. Other opts: engine (one you made) or holdMs,
 *       tapFollowMs, combos for a new one; now (a clock in ms, default performance.now);
 *       raw (a function asked as each press begins: raw(button) true sends that press's two
 *       edges to onEdge(button, "down" | "up", tMs) and not through the engine, for a prompt
 *       that takes press and release times itself);
 *       onChange (a function told of every press beginning and ending, raw or not:
 *       onChange(button, isDown, {tMs, raw, kind}) with kind "down", "up" or "cancel", called
 *       before any gesture that edge completes. It is for drawing a pressed button; an edge the
 *       engine ignores, such as a second down, is not reported. The engine is fed even when
 *       onChange throws, and stop() ends a press in flight with kind "cancel").
 *       The result's setCombos(combos) changes which chain lengths are gestures while it
 *       listens (null: the keymap's). A press in flight and pending taps are kept; taps that
 *       can no longer become a combo are reported at once.
 *
 *   bollardeck.help.listen(root, engine, opts) -> {rescan(), stop()}
 *       Feed a help engine from a page: activate (a click on a [data-help] element; blocked when it is
 *       disabled, aria-disabled="true" or carries data-help-blocked), press (pointer down, with x and y),
 *       input (keys), visible (the engine's dwell targets, by IntersectionObserver) and a tick every
 *       opts.tickMs (1000).
 *   bollardeck.help.cta(engine, opts) -> {stop()}
 *       Show each offer as a small button (opts.label, default "HELP?") beside its target, announced
 *       in a polite live region, named in a few words (aria-label, aria-labelledby, its first heading, or the
 *       start of its text, at most 60 characters); pressed: settle("opened") and opts.onOpen(offer); left alone for
 *       HELP_OFFER_MS (or opts.offerMs): settle("ignored").
 *   bollardeck.help.modal(content, opts) -> {dialog, body, closed, close(value)} | null
 *       One help box in a <dialog>: content {title, body}, opts {actions: [{label, value, primary}],
 *       extra (a node above the body), canOpen(), onOpen(dialog), onClose(value)}. Focus goes back
 *       where it was. help.renderBody(doc, body) builds a body with DOM calls (never HTML).
 *   bollardeck.help.spot(element, opts) -> {pop, setText(t), place(), remove()}
 *       Ring an element (data-help-spot="on") and lay a note beside it (opts.pop, opts.place).
 *   bollardeck.help.ui(opts)
 *       A ui for bollardeck.help.play: spots, a lower-third caption, button cues through cues.run with
 *       {properties: false}, and the host's own module / open / close / press callbacks.
 *   bollardeck.help.sheet(doc, css), help.CSS, help.place(doc, node, anchor, where)
 *       The help look is one constructable stylesheet (help.CSS by default; sheet() replaces it), and
 *       every position is a rule in a second one keyed by data-help-n: no element ever gets a style
 *       attribute, so a page with a strict CSP or a no-inline-style rule can use all of this.
 *
 *   bollardeck.matrix.canvas(canvas, opts) -> {draw(frame), run(frameFn), stop()}
 *       Draw matrix frames as round lamps on a <canvas>. draw(frame) paints one frame (null
 *       paints the matrix dark). run(frameFn) calls frameFn(nowMs) every animation frame and
 *       draws what it returns. opts: lamp [r, g, b] (default blue), background (a CSS colour,
 *       default none), leds (draw the three RGB LEDs under the matrix, default true), fps (30).
 */
(function (root) {
  "use strict";

  function raf(fn) {
    return typeof root.requestAnimationFrame === "function" ? root.requestAnimationFrame(fn) : root.setTimeout(function () { fn(nowMs()); }, 33);
  }
  function cancel(id) {
    if (typeof root.cancelAnimationFrame === "function") root.cancelAnimationFrame(id); else root.clearTimeout(id);
  }
  function nowMs() {
    return root.performance && typeof root.performance.now === "function" ? root.performance.now() : Date.now();
  }
  function reducedMotion() {
    try { return !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (e) { return false; }
  }

  function attr(el, name, value) {
    if (value === null) { if (el.hasAttribute(name)) el.removeAttribute(name); }
    else if (el.getAttribute(name) !== value) el.setAttribute(name, value);
  }
  function prop(el, name, value) {
    if (!el.style) return;
    if (value === null) el.style.removeProperty(name);
    else if (el.style.getPropertyValue(name) !== value) el.style.setProperty(name, value);
  }

  function applyCues(elements, entries, opts) {
    var properties = !opts || opts.properties !== false;
    var undriven = opts && opts.undriven !== undefined && opts.undriven !== null ? opts.undriven : null;
    if (undriven !== null && undriven !== "off") throw new RangeError('cues.apply: undriven is "off" or absent, not ' + JSON.stringify(undriven));
    entries.forEach(function (e) {
      var el = Array.isArray(elements) ? elements[e.button - 1] : elements && elements[e.button];
      if (!el) return;
      attr(el, "data-cue", e.driven ? e.state : undriven);
      attr(el, "data-cue-role", e.driven && e.role ? e.role : null);
      if (!properties) return;                                    // el.style is never touched
      prop(el, "--cue-level", e.driven ? e.level.toFixed(3) : null);
      prop(el, "--cue-head", e.driven && e.head !== null ? String(e.head) : null);
    });
  }

  function runCues(bollardeck, elements, cues, opts) {
    opts = opts || {};
    var id = null, stopped = false;
    var clock = opts.now || nowMs;
    function calm() {
      if (typeof opts.calm === "function") return !!opts.calm();
      return opts.calm === undefined ? reducedMotion() : !!opts.calm;
    }
    function tick() {
      if (stopped) return;
      id = raf(tick);
      var list = typeof cues === "function" ? cues() : cues;
      applyCues(elements, bollardeck.cues.at(list || [], clock(), { calm: calm() }), opts);
    }
    tick();
    return { stop: function () { stopped = true; if (id !== null) cancel(id); id = null; } };
  }

  function matrixCanvas(bollardeck, canvas, opts) {
    opts = opts || {};
    var M = bollardeck.matrix;
    var lamp = opts.lamp || [64, 140, 255];
    var showLeds = opts.leds !== false;
    var gap = 1000 / (opts.fps || 30);
    var ctx = canvas.getContext("2d");
    var id = null, stopped = true, last = -Infinity;
    var rows = M.H + (showLeds ? 1.5 : 0);

    function fit() {
      var r = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { width: canvas.width, height: canvas.height };
      var dpr = Math.min(3, (typeof root.devicePixelRatio === "number" && root.devicePixelRatio) || 1);
      var w = Math.max(1, Math.round((r.width || canvas.width) * dpr)), h = Math.max(1, Math.round((r.height || canvas.height) * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      var pitch = Math.min(w / M.W, h / rows);
      return { pitch: pitch, x0: (w - pitch * M.W) / 2 + pitch / 2, y0: (h - pitch * rows) / 2 + pitch / 2 };
    }
    function dot(x, y, r) { ctx.beginPath(); ctx.arc(x, y, r, 0, 6.283185307179586); ctx.fill(); }
    function rgba(c, a) { return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + a.toFixed(3) + ")"; }

    function draw(frame) {
      var g = fit(), i, x, y;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (opts.background) { ctx.fillStyle = opts.background; ctx.fillRect(0, 0, canvas.width, canvas.height); }
      for (i = 0; i < M.N; i++) {
        x = g.x0 + (i % M.W) * g.pitch;
        y = g.y0 + Math.floor(i / M.W) * g.pitch;
        var v = frame ? frame.pixels[i] / 255 : 0;
        ctx.fillStyle = rgba(lamp, 0.14);
        dot(x, y, g.pitch * 0.3);
        if (v > 0) {
          ctx.globalCompositeOperation = "lighter";
          ctx.fillStyle = rgba(lamp, 0.25 * v);
          dot(x, y, g.pitch * 0.7);
          ctx.fillStyle = rgba(lamp, 0.35 + 0.65 * v);
          dot(x, y, g.pitch * 0.32);
          ctx.globalCompositeOperation = "source-over";
        }
      }
      if (showLeds) {
        y = g.y0 + (M.H + 0.5) * g.pitch;
        [1, 6, 11].forEach(function (col, k) {
          var c = frame ? frame.rgb[k] : [0, 0, 0];
          var amp = Math.max(c[0], c[1], c[2]) / 255;
          x = g.x0 + col * g.pitch;
          ctx.fillStyle = "rgba(128,128,128,0.25)";
          dot(x, y, g.pitch * 0.3);
          if (amp > 0.02) {
            ctx.globalCompositeOperation = "lighter";
            ctx.fillStyle = rgba(c, 0.3 * amp);
            dot(x, y, g.pitch * 0.8);
            ctx.fillStyle = rgba(c, 0.5 + 0.5 * amp);
            dot(x, y, g.pitch * 0.32);
            ctx.globalCompositeOperation = "source-over";
          }
        });
      }
    }

    function stop() { stopped = true; if (id !== null) cancel(id); id = null; }
    function run(frameFn) {
      stop();
      stopped = false;
      (function tick(now) {
        if (stopped) return;
        id = raf(tick);
        if (now === undefined) now = nowMs();
        if (now - last < gap - 2) return;
        last = now;
        var frame = null;
        try { frame = frameFn(now); } catch (e) { frame = null; }
        draw(frame);
      })();
    }

    return { canvas: canvas, draw: draw, run: run, stop: stop };
  }

  function listenGestures(bollardeck, elements, onGesture, opts) {
    opts = opts || {};
    var engine = opts.engine || bollardeck.gestures.engine({ holdMs: opts.holdMs, tapFollowMs: opts.tapFollowMs, combos: opts.combos });
    var clock = opts.now || nowMs;
    var keys = opts.keys || { "1": 1, "2": 2, "3": 3 };
    var keyTarget = opts.keyTarget === undefined ? root.document : opts.keyTarget;
    var timer = null, stopped = false, last = 0, undo = [], rawDown = {};

    function time() { last = Math.max(last, Math.floor(clock())); return last; }       // never backwards
    function report(found) { found.forEach(function (g) { onGesture(g); }); }
    function arm() {
      if (timer !== null) { root.clearTimeout(timer); timer = null; }
      var due = engine.nextDeadlineMs();
      if (stopped || due === null) return;
      timer = root.setTimeout(function () { timer = null; report(engine.tick(time())); arm(); }, Math.max(1, due - time()));
    }
    function change(button, isDown, t, raw, kind) {
      if (typeof opts.onChange === "function") opts.onChange(button, isDown, { tMs: t, raw: raw, kind: kind });
    }
    function edge(kind, button) {
      if (stopped) return;
      var t = time();
      // A press is raw or not from its beginning to its end, whatever changes while it is down.
      if (kind === "down" && !rawDown[button] && !engine.isDown(button) && typeof opts.raw === "function" && opts.raw(button)) {
        rawDown[button] = true;
        change(button, true, t, true, "down");
        if (opts.onEdge) opts.onEdge(button, "down", t);
        return;
      }
      if (rawDown[button]) {
        if (kind === "down") return;
        rawDown[button] = false;
        try { change(button, false, t, true, kind); }
        finally { if (opts.onEdge) opts.onEdge(button, "up", t); }   // a cancelled raw press ends like any other
        return;
      }
      // The engine is fed whatever onChange does: a handler that throws must not leave a
      // button down in the engine. Its error still reaches the caller.
      var found;
      try {
        if ((kind === "down") !== engine.isDown(button)) change(button, kind === "down", t, false, kind);
      } finally {
        found = engine[kind](button, t);
        arm();
      }
      report(found);
    }
    function on(target, type, fn) {
      if (!target || typeof target.addEventListener !== "function") return;
      target.addEventListener(type, fn);
      undo.push(function () { target.removeEventListener(type, fn); });
    }

    [1, 2, 3].forEach(function (button) {
      var el = Array.isArray(elements) ? elements[button - 1] : elements && elements[button];
      if (!el) return;
      on(el, "pointerdown", function (ev) {
        if (ev && ev.button) return;                               // the main button, a finger or a pen only
        if (ev && ev.pointerId !== undefined && typeof el.setPointerCapture === "function") {
          try { el.setPointerCapture(ev.pointerId); } catch (e) { /* a pointer that is already gone */ }
        }
        edge("down", button);
      });
      on(el, "pointerup", function () { edge("up", button); });
      on(el, "pointercancel", function () { edge("cancel", button); });
      on(el, "contextmenu", function (ev) { if (ev && ev.preventDefault) ev.preventDefault(); });   // a long press is a hold, not a menu
      on(el, "keydown", function (ev) {                          // Space or Enter on a focused button presses it
        if ((ev.key === " " || ev.key === "Enter") && !ev.repeat) { if (ev.preventDefault) ev.preventDefault(); edge("down", button); }
      });
      on(el, "keyup", function (ev) {
        if (ev.key === " " || ev.key === "Enter") { if (ev.preventDefault) ev.preventDefault(); edge("up", button); }
      });
      on(el, "blur", function () { if (engine.isDown(button) || rawDown[button]) edge("cancel", button); });
    });
    on(keyTarget, "keydown", function (ev) {
      var button = Object.prototype.hasOwnProperty.call(keys, ev.key) ? keys[ev.key] : null;
      if (button && !ev.repeat && !ev.ctrlKey && !ev.metaKey && !ev.altKey) edge("down", button);
    });
    on(keyTarget, "keyup", function (ev) {
      var button = Object.prototype.hasOwnProperty.call(keys, ev.key) ? keys[ev.key] : null;
      if (button) edge("up", button);
    });
    on(root, "blur", function () { [1, 2, 3].forEach(function (button) { if (engine.isDown(button) || rawDown[button]) edge("cancel", button); }); });

    return {
      engine: engine,
      edge: edge,                   // edge("down" | "up" | "cancel", button): feed it from an event of your own
      setCombos: function (combos) {
        engine.setCombos(combos);
        if (!stopped) { report(engine.tick(time())); arm(); }
        return this;
      },
      // Stop listening. A press in flight is cancelled: it is not a gesture, and onChange is
      // told the button is up (kind "cancel"), so nothing stays drawn as pressed.
      stop: function () {
        if (stopped) return;
        var t = time();
        [1, 2, 3].forEach(function (button) {
          var raw = !!rawDown[button];
          if (!raw && !engine.isDown(button)) return;
          rawDown[button] = false;
          if (!raw) engine.cancel(button, t);
          try { change(button, false, t, raw, "cancel"); } catch (e) { /* stopping goes on */ }
          if (raw && opts.onEdge) { try { opts.onEdge(button, "up", t); } catch (e) { /* stopping goes on */ } }
        });
        stopped = true;
        if (timer !== null) root.clearTimeout(timer);
        timer = null;
        undo.forEach(function (fn) { fn(); });
        undo = [];
      }
    };
  }

  // ── help: the page helpers for bollardeck.help ─────────────────────────────────────────
  // Nothing here writes a style attribute: the look is one constructable stylesheet (HELP_CSS, or the
  // page's own), and every position is a rule in a second constructed sheet keyed by data-help-n.

  var HELP_CSS = [
    '[data-help-spot="on"]{outline:3px solid var(--bdh-accent,#ffd23f);outline-offset:3px}',
    '.bdh-pill{position:absolute;z-index:2147483000;font:inherit;font-size:.8rem;padding:.15rem .5rem;cursor:pointer;',
    'border:2px solid var(--bdh-accent,#ffd23f);background:var(--bdh-bg,#111);color:var(--bdh-fg,#fff)}',
    '.bdh-pop{position:absolute;z-index:2147483001;max-width:22rem;padding:.5rem .75rem;',
    'border:2px solid var(--bdh-accent,#ffd23f);background:var(--bdh-bg,#111);color:var(--bdh-fg,#fff)}',
    '.bdh-pop:empty{display:none}',
    '.bdh-caption{position:fixed;z-index:2147483001;left:50%;bottom:6%;transform:translateX(-50%);max-width:44ch;',
    'white-space:pre-line;text-align:center;padding:.4rem .8rem;background:var(--bdh-bg,#111);color:var(--bdh-fg,#fff)}',
    '.bdh-caption:empty{display:none}',
    '.bdh-live{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}',
    '.bdh-modal-actions{display:flex;flex-wrap:wrap;gap:.5rem}'
  ].join("");

  var helpDocs = [];                // [{doc, base, pos, rules, n}] one per document
  function helpDoc(doc) {
    for (var i = 0; i < helpDocs.length; i++) if (helpDocs[i].doc === doc) return helpDocs[i];
    var d = { doc: doc, base: null, pos: null, rules: {}, n: 0 };
    var W = doc.defaultView || root;
    if (W && typeof W.CSSStyleSheet === "function" && "adoptedStyleSheets" in doc) {
      try {
        d.base = new W.CSSStyleSheet();
        d.pos = new W.CSSStyleSheet();
        doc.adoptedStyleSheets = doc.adoptedStyleSheets.concat([d.base, d.pos]);
        d.base.replaceSync(HELP_CSS);
      } catch (e) { d.base = d.pos = null; }
    }
    helpDocs.push(d);
    return d;
  }
  function helpSheet(doc, css) {           // replace the default look with the page's own
    var d = helpDoc(doc || root.document);
    if (d.base) d.base.replaceSync(String(css));
    return !!d.base;
  }
  function writeRules(d) {
    if (!d.pos) return;
    d.pos.replaceSync(Object.keys(d.rules).map(function (k) { return d.rules[k]; }).join("\n"));
  }
  // Put `node` beside `anchor` (or at the anchor's window corner when anchor is null).
  function placeBeside(doc, node, anchor, where) {
    var d = helpDoc(doc), W = doc.defaultView || root;
    var k = node.getAttribute("data-help-n");
    if (!k) { k = String(++d.n); node.setAttribute("data-help-n", k); }
    var sx = W.pageXOffset || 0, sy = W.pageYOffset || 0, vw = W.innerWidth || 1024;
    var a = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : { top: 8, left: vw - 8, right: vw - 8, bottom: 8, width: 0, height: 0 };
    var b = node.getBoundingClientRect ? node.getBoundingClientRect() : { width: 0, height: 0 };
    var gap = 8, top, left;
    var w = where || "auto";
    if (w === "auto") w = a.right + gap + b.width <= vw ? "right" : (a.top - gap - b.height >= 0 ? "above" : "below");
    if (w === "right") { top = a.top; left = a.right + gap; }
    else if (w === "left") { top = a.top; left = a.left - gap - b.width; }
    else if (w === "above") { top = a.top - gap - b.height; left = a.left; }
    else { top = a.bottom + gap; left = a.left; }
    left = Math.max(4, Math.min(left, vw - b.width - 4));
    d.rules[k] = '[data-help-n="' + k + '"]{top:' + Math.round(top + sy) + "px;left:" + Math.round(left + sx) + "px}";
    writeRules(d);
  }
  function forget(doc, node) {
    var d = helpDoc(doc), k = node && node.getAttribute && node.getAttribute("data-help-n");
    if (k && d.rules[k]) { delete d.rules[k]; writeRules(d); }
  }
  function targetEl(doc, id, nth) {
    var all = doc.querySelectorAll('[data-help="' + String(id).replace(/["\\]/g, "") + '"]');
    return all[(nth || 1) - 1] || null;
  }
  // What to call a target in a few words: its aria-label, the text of what labels it, its first heading,
  // or the start of its own text. Never a whole panel read aloud.
  function shortName(doc, el) {
    var t = el.getAttribute("aria-label");
    if (!t && el.getAttribute("aria-labelledby")) {
      t = el.getAttribute("aria-labelledby").split(/\s+/).map(function (id) { var n = doc.getElementById(id); return n ? n.textContent : ""; }).join(" ");
    }
    if (!t && el.querySelector) { var h = el.querySelector("h1, h2, h3, h4, h5, h6"); if (h) t = h.textContent; }
    t = String(t || el.textContent || "").replace(/\s+/g, " ").trim();
    return t.length > 60 ? t.slice(0, 59).replace(/\s+\S*$/, "") + "\u2026" : t;
  }
  function blockedEl(el) {
    return !!(el.disabled || el.getAttribute("aria-disabled") === "true" || el.hasAttribute("data-help-blocked"));
  }

  // Feed an engine from a page: activate, press, input, visible (for the dwell targets), and a tick.
  function helpListen(rootEl, engine, opts) {
    opts = opts || {};
    var doc = rootEl.ownerDocument || rootEl, W = doc.defaultView || root, undo = [], io = null, seen = [];
    function on(t, type, fn) { t.addEventListener(type, fn, true); undo.push(function () { t.removeEventListener(type, fn, true); }); }
    function near(e) { return e.target && e.target.closest ? e.target.closest("[data-help]") : null; }
    on(rootEl, "click", function (e) {
      var el = near(e);
      if (el) engine.feed({ kind: "activate", target: el.getAttribute("data-help"), blocked: blockedEl(el) });
    });
    on(rootEl, "pointerdown", function (e) {
      var el = near(e);
      engine.feed({ kind: "press", x: e.clientX, y: e.clientY, target: el ? el.getAttribute("data-help") : null });
      if (el && el.disabled) engine.feed({ kind: "activate", target: el.getAttribute("data-help"), blocked: true });
    });
    on(rootEl, "keydown", function () { engine.feed({ kind: "input" }); });
    function rescan() {
      if (!W.IntersectionObserver) return;
      if (!io) {
        io = new W.IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            engine.feed({ kind: "visible", target: en.target.getAttribute("data-help"), on: en.isIntersecting });
          });
        }, { threshold: 0.5 });
      }
      engine.watched("dwell").forEach(function (id) {
        var el = targetEl(doc, id);
        if (el && seen.indexOf(el) < 0) { seen.push(el); io.observe(el); }
      });
    }
    rescan();
    var timer = W.setInterval(function () { engine.tick(); }, opts.tickMs || 1000);
    return {
      rescan: rescan,
      stop: function () { undo.forEach(function (f) { f(); }); undo = []; if (io) io.disconnect(); W.clearInterval(timer); }
    };
  }

  // The HELP? offer: a small button beside the target, gone after HELP_OFFER_MS unless pressed.
  function helpCta(bollardeck, engine, opts) {
    opts = opts || {};
    var doc = opts.doc || root.document, W = doc.defaultView || root, shown = {};
    helpDoc(doc);
    var live = doc.createElement("div");
    live.className = "bdh-live";
    live.setAttribute("aria-live", "polite");
    doc.body.appendChild(live);
    function drop(topic) {
      var s = shown[topic];
      if (!s) return;
      W.clearTimeout(s.timer);
      forget(doc, s.pill);
      if (s.pill.parentNode) s.pill.parentNode.removeChild(s.pill);
      delete shown[topic];
    }
    function replace() { Object.keys(shown).forEach(function (t) { placeBeside(doc, shown[t].pill, shown[t].anchor, opts.place); }); }
    W.addEventListener("resize", replace);
    W.addEventListener("scroll", replace, { passive: true });
    var offUnsub = engine.on("offer", function (o) {
      var anchor = o.target ? targetEl(doc, o.target) : null;
      if (anchor && anchor.getClientRects && !anchor.getClientRects().length) anchor = null;   // hidden: the corner
      var pill = doc.createElement("button");
      pill.type = "button";
      pill.className = "bdh-pill";
      pill.setAttribute("data-help-pill", o.topic);
      pill.textContent = opts.label || "HELP?";
      var named = anchor ? shortName(doc, anchor) : "";
      pill.setAttribute("aria-label", (opts.label || "HELP?") + (named ? " " + named : ""));
      pill.addEventListener("click", function () {
        drop(o.topic);
        engine.settle(o.topic, "opened");
        if (opts.onOpen) opts.onOpen(o);
      });
      doc.body.appendChild(pill);
      placeBeside(doc, pill, anchor, opts.place);
      shown[o.topic] = { pill: pill, anchor: anchor, timer: W.setTimeout(function () {
        drop(o.topic);
        engine.settle(o.topic, "ignored");
      }, opts.offerMs || bollardeck.constants.HELP_OFFER_MS) };
      live.textContent = "";
      live.textContent = (opts.announce || "Help is available") + (named ? " for " + named : "") + ".";
    });
    var settleUnsub = engine.on("settle", function (x) { drop(x.topic); });
    return {
      stop: function () {
        offUnsub(); settleUnsub();
        Object.keys(shown).forEach(drop);
        W.removeEventListener("resize", replace);
        W.removeEventListener("scroll", replace);
        if (live.parentNode) live.parentNode.removeChild(live);
      }
    };
  }

  // A help body (paragraphs of strings, {b}, {code} and same-origin {a, href}) as DOM, never as HTML.
  function renderBody(doc, body) {
    var frag = doc.createDocumentFragment();
    (body || []).forEach(function (para) {
      var p = doc.createElement("p");
      para.forEach(function (bit) {
        if (typeof bit === "string") { p.appendChild(doc.createTextNode(bit)); return; }
        var n;
        if (bit.b !== undefined) { n = doc.createElement("b"); n.textContent = bit.b; }
        else if (bit.code !== undefined) { n = doc.createElement("code"); n.textContent = bit.code; }
        else if (bit.a !== undefined) {
          if (/^\/(?![\/\\])/.test(String(bit.href)) && !/[\u0000-\u0020\u007f\\]/.test(String(bit.href))) { n = doc.createElement("a"); n.setAttribute("href", bit.href); }
          else n = doc.createElement("span");
          n.textContent = bit.a;
        }
        if (n) p.appendChild(n);
      });
      frag.appendChild(p);
    });
    return frag;
  }

  // One help box. content {title, body}; opts {doc, actions: [{label, value, primary}], extra: Node,
  // canOpen(), onOpen(dialog), onClose(value), closeLabel}. Returns null when canOpen() says no.
  function helpModal(content, opts) {
    opts = opts || {};
    var doc = opts.doc || root.document;
    if (opts.canOpen && !opts.canOpen()) return null;
    helpDoc(doc);
    var dlg = doc.createElement("dialog");
    dlg.className = "bdh-modal" + (opts.className ? " " + opts.className : "");
    var h = doc.createElement("h2");
    h.id = "bdh-h-" + (++helpDoc(doc).n);
    h.textContent = content.title;
    dlg.setAttribute("aria-labelledby", h.id);
    var x = doc.createElement("button");
    x.type = "button";
    x.className = "bdh-modal-x";
    x.setAttribute("aria-label", opts.closeLabel || "Close");
    x.textContent = "\u00D7";
    var bodyBox = doc.createElement("div");
    bodyBox.className = "bdh-modal-body";
    bodyBox.id = "bdh-b-" + helpDoc(doc).n;
    dlg.setAttribute("aria-describedby", bodyBox.id);
    bodyBox.appendChild(renderBody(doc, content.body));
    dlg.appendChild(x);
    dlg.appendChild(h);
    if (opts.extra) dlg.appendChild(opts.extra);
    dlg.appendChild(bodyBox);
    var row = doc.createElement("div");
    row.className = "bdh-modal-actions";
    var result = null, done;
    var closed = new Promise(function (r) { done = r; });
    (opts.actions || []).forEach(function (a) {
      var b = doc.createElement("button");
      b.type = "button";
      b.className = "bdh-modal-act" + (a.primary ? " is-primary" : "");
      b.textContent = a.label;
      b.addEventListener("click", function () { result = a.value; dlg.close(); });
      row.appendChild(b);
    });
    dlg.appendChild(row);
    x.addEventListener("click", function () { dlg.close(); });
    var back = doc.activeElement;
    dlg.addEventListener("close", function () {
      if (dlg.parentNode) dlg.parentNode.removeChild(dlg);
      if (back && back.focus && back.isConnected) { try { back.focus(); } catch (e) { /* gone */ } }
      if (opts.onClose) opts.onClose(result);
      done(result);
    });
    doc.body.appendChild(dlg);
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
    if (opts.onOpen) opts.onOpen(dlg);
    return { dialog: dlg, body: bodyBox, closed: closed, close: function (v) { result = v === undefined ? result : v; if (dlg.open) dlg.close(); } };
  }

  // Ring a target and, if pop is given, lay a note beside it. Returns {pop, setText(t), place(), remove()}.
  function helpSpot(el, opts) {
    opts = opts || {};
    var doc = el.ownerDocument, W = doc.defaultView || root;
    helpDoc(doc);
    el.setAttribute("data-help-spot", "on");
    if (opts.scroll !== false && el.scrollIntoView) {
      try { el.scrollIntoView({ block: "center", behavior: opts.calm || reducedMotion() ? "auto" : "smooth" }); } catch (e) { el.scrollIntoView(); }
    }
    var pop = doc.createElement("div");
    pop.className = "bdh-pop";
    pop.setAttribute("role", "note");
    pop.textContent = opts.pop || "";
    doc.body.appendChild(pop);
    function place() { placeBeside(doc, pop, el, opts.place); }
    place();
    W.addEventListener("resize", place);
    return {
      el: el, pop: pop,
      setText: function (t) { pop.textContent = t || ""; place(); },
      place: place,
      remove: function () {
        W.removeEventListener("resize", place);
        if (el.getAttribute("data-help-spot") === "on") el.removeAttribute("data-help-spot");
        forget(doc, pop);
        if (pop.parentNode) pop.parentNode.removeChild(pop);
      }
    };
  }

  // A ui for bollardeck.help.play: say, spot, cue, unspot, hide, module, open, close, act, chapter.
  // opts {doc, find(target, nth) -> element, buttons() -> {1, 2, 3} elements, module(name, open),
  // open(topic), close(), press(button, hold), chapter(title), calm}.
  function helpUi(bollardeck, opts) {
    opts = opts || {};
    var doc = opts.doc || root.document, spots = [], pending = null, list = [], run = null, caption = null;
    function find(target, nth) { return opts.find ? opts.find(target, nth) : targetEl(doc, target, nth); }
    function cap() {
      if (!caption) {
        helpDoc(doc);
        caption = doc.createElement("div");
        caption.className = "bdh-caption";
        caption.setAttribute("aria-live", "polite");
        doc.body.appendChild(caption);
      }
      return caption;
    }
    function clearSpots() { spots.forEach(function (s) { s.remove(); }); spots = []; pending = null; }
    function clearCues() {
      list = [];
      if (run) { run.stop(); run = null; }
      var b = opts.buttons ? opts.buttons() : null;
      if (b) bollardeck.cues.apply(b, bollardeck.cues.at([], 0), { properties: false });
    }
    var ui = {
      chapter: function (s) { if (opts.chapter) opts.chapter(s.title); },
      say: function (s, cues) {
        if (pending) { pending.setText(s.text); if (caption) caption.textContent = ""; }
        else cap().textContent = (cues || [s.text]).join("\n");
      },
      spot: function (s) {
        if (!s.keep) clearSpots();
        var el = find(s.target, s.nth);
        if (!el) return;
        var h = helpSpot(el, { pop: s.pop && s.pop !== "@say" ? s.pop : "", place: s.place, calm: opts.calm });
        spots.push(h);
        pending = h;
        if (caption) caption.textContent = "";
      },
      cue: function (s) {
        list = list.filter(function (c) { return c.button !== s.button; }).concat([{ button: s.button, state: s.state, role: s.role === undefined ? null : s.role }]);
        var b = opts.buttons ? opts.buttons() : null;
        if (b && !run) run = bollardeck.cues.run(b, function () { return list; }, { properties: false, undriven: "off", calm: opts.calm });
        if (s.pop) { cap().textContent = s.pop; }
      },
      unspot: function () { clearSpots(); clearCues(); },
      hide: function () { clearSpots(); clearCues(); if (caption) caption.textContent = ""; },
      module: function (s) { if (opts.module) return opts.module(s.module, s.open); },
      open: function (s) { if (opts.open) return opts.open(s.topic); },
      close: function () { if (opts.close) return opts.close(); },
      act: function (s) {
        var m = /button([123])$/.exec(s.target);
        if (m && opts.press && (s.action === "press" || s.action === "hold")) return opts.press(Number(m[1]), s.action === "hold");
        var el = find(s.target, s.nth);
        if (!el) throw new Error("bollardeck.help ui: no element for " + s.target);
        if (s.action === "select") { el.value = s.value; el.dispatchEvent(new (doc.defaultView || root).Event("change", { bubbles: true })); }
        else el.click();
      },
      stop: function () { ui.hide(); if (caption && caption.parentNode) caption.parentNode.removeChild(caption); caption = null; }
    };
    return ui;
  }

  var bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var cues = bollardeck.cues || (bollardeck.cues = {});
  cues.apply = applyCues;
  cues.run = function (elements, list, opts) { return runCues(bollardeck, elements, list, opts); };
  var matrix = bollardeck.matrix || (bollardeck.matrix = {});
  matrix.canvas = function (canvas, opts) { return matrixCanvas(bollardeck, canvas, opts); };
  var gestures = bollardeck.gestures || (bollardeck.gestures = {});
  gestures.listen = function (elements, onGesture, opts) { return listenGestures(bollardeck, elements, onGesture, opts); };
  var help = bollardeck.help || (bollardeck.help = {});
  help.CSS = HELP_CSS;
  help.sheet = helpSheet;
  help.listen = helpListen;
  help.cta = function (engine, opts) { return helpCta(bollardeck, engine, opts); };
  help.renderBody = renderBody;
  help.shortName = shortName;
  help.modal = helpModal;
  help.spot = helpSpot;
  help.place = placeBeside;
  help.ui = function (opts) { return helpUi(bollardeck, opts); };
  (bollardeck.parts || (bollardeck.parts = {})).dom = true;
  if (typeof module === "object" && module.exports) module.exports = { cues: cues, matrix: matrix, gestures: gestures, help: help };
})(typeof globalThis !== "undefined" ? globalThis : this);
