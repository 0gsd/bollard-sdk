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

  var bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var cues = bollardeck.cues || (bollardeck.cues = {});
  cues.apply = applyCues;
  cues.run = function (elements, list, opts) { return runCues(bollardeck, elements, list, opts); };
  var matrix = bollardeck.matrix || (bollardeck.matrix = {});
  matrix.canvas = function (canvas, opts) { return matrixCanvas(bollardeck, canvas, opts); };
  var gestures = bollardeck.gestures || (bollardeck.gestures = {});
  gestures.listen = function (elements, onGesture, opts) { return listenGestures(bollardeck, elements, onGesture, opts); };
  (bollardeck.parts || (bollardeck.parts = {})).dom = true;
  if (typeof module === "object" && module.exports) module.exports = { cues: cues, matrix: matrix, gestures: gestures };
})(typeof globalThis !== "undefined" ? globalThis : this);
