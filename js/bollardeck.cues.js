// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.cues: what each of the three buttons shows at a moment, from a cue list.
 *
 * The buttons have no lamps of their own, so "lit" is a cue each surface renders its own way: a
 * ring arc and a matrix pixel on the device, an outline on a web page. A valid cue list is the
 * `cue` schema's document with at most one {button, state, role} per button, in any order;
 * buttons are numbered 1, 2, 3. problems(list) says what is wrong with a list ([] when valid).
 *
 * at() and compile() want a valid list and throw otherwise. Checking needs only this part:
 * with bollardeck.schema.js loaded the `cue` schema is asked, and without it this file checks the
 * same rules itself, so a page that loads only the parts it uses can still call at(). A loop that must not stop for one
 * bad cue passes normalise(list) instead: it never throws, drops a cue it cannot use, reads a
 * role it cannot use as none, and keeps the last of two cues for one button. repairs(list) says
 * what normalise dropped or changed. Python's bollardeck.device.cues has the same four functions
 * with the same answers; conformance/cues/normalise.json holds both to them.
 *
 *   var show = bollardeck.cues.compile([{button: 1, state: "pulse", role: "go"}]);   // validates once
 *   show.at(performance.now());            // -> three entries, buttons 1, 2, 3 in order
 *   bollardeck.cues.at(list, tMs);         // the same, compiling (and remembering) the list
 *
 * Each entry is {button, driven, state, role, level, arc, head, pixel}:
 *   driven   false when the list has no cue for this button (the surface leaves it alone)
 *   state    "off" | "on" | "pulse" | "chase"        role   "a" | "b" | "c" | "live" | "go" | "warn" | null
 *   level    0..1, how bright a single lamp for this button is now
 *   arc      three levels 0..1, for a surface that shows a button as three lamps in a row
 *   head     which of the three leads a chase (0, 1, 2), else null
 *   pixel    level as 0..255, the value the device writes to the button's matrix pixel
 *
 * off is dark and on is full. pulse breathes once per PULSE_PERIOD_MS between 1 and PULSE_FLOOR,
 * full at t = 0. chase steps a full lamp through the arc once per CHASE_PERIOD_MS with the other
 * two at CHASE_TAIL; a single lamp shows the middle of the arc. With {calm: true} (reduced
 * motion) pulse and chase are drawn exactly as on.
 *
 * These are pure functions of the list and the time: call them from your own render loop.
 * bollardeck.dom.js adds the optional cues.apply(elements, entries) and cues.run(...).
 * conformance/cue-render/ holds lists and times with the entries expected for them.
 *
 * PULSE_FLOOR, CHASE_TAIL, CHASE_STEPS and the two periods are bollardeck.constants (generated
 * from constants/constants.json), so this file needs bollardeck.js loaded by the time it is used.
 */
(function (root) {
  "use strict";

  var BUTTONS = [1, 2, 3];
  var TAU = 6.283185307179586;

  var bollardeck;                   // set at the bottom of this file

  // A value from bollardeck.constants, read when it is needed: this file may load before bollardeck.js.
  function K(name) {
    var v = bollardeck.constants && bollardeck.constants[name];
    if (v === undefined) throw new Error("bollardeck.cues: no " + name + " (load bollardeck.js)");
    return v;
  }

  function period(opts, key, name) {
    var v = opts && opts[key];
    if (v === undefined || v === null) v = bollardeck.constants && bollardeck.constants[name];
    if (typeof v !== "number" || !(v > 0)) throw new Error("bollardeck.cues: no " + name + " (load bollardeck.js, or pass " + key + ")");
    return v;
  }

  function clock(tMs) {
    if (typeof tMs !== "number" || !isFinite(tMs)) throw new TypeError("bollardeck.cues: a time is a finite number of milliseconds");
    return tMs < 0 ? Math.ceil(tMs) : Math.floor(tMs);        // whole milliseconds, as the device counts
  }

  function mod(a, n) { return a - n * Math.floor(a / n); }

  // The breathe of a pulse cue: 1 at t = 0 (and every period), PULSE_FLOOR half a period later.
  function pulseLevel(tMs, opts) {
    var p = period(opts, "pulsePeriodMs", "PULSE_PERIOD_MS");
    var phase = mod(clock(tMs), p) / p;
    var floor = K("PULSE_FLOOR");
    return floor + (1 - floor) * (0.5 + 0.5 * Math.cos(TAU * phase));
  }

  // Which lamp of a three-lamp arc leads a chase: 0, 1, 2 in turn, one turn per period.
  function chaseHead(tMs, opts) {
    var p = period(opts, "chasePeriodMs", "CHASE_PERIOD_MS");
    return Math.floor(mod(clock(tMs), p) * K("CHASE_STEPS") / p);
  }

  // 0..1 as 0..255, rounding a half to the even neighbour as the device's round() does.
  function toPixel(level) {
    var x = 255 * level, f = Math.floor(x), d = x - f;
    if (d > 0.5 || (d === 0.5 && f % 2 === 1)) f += 1;
    return f;
  }

  // A problem found without the validator: the members bollardeck.schema.Problem has, and its text.
  function Problem(pointer, message, keyword) { this.pointer = pointer; this.message = message; this.keyword = keyword; }
  Problem.prototype.toString = function () { return "#" + this.pointer + ": " + this.message; };

  function problem(pointer, message, keyword) {
    var P = bollardeck.schema && bollardeck.schema.Problem;
    return P ? new P(pointer, message, keyword) : new Problem(pointer, message, keyword);
  }

  // The `cue` schema checked by hand, for a page that loads this part without bollardeck.schema.js
  // (54 KB with the schemas). The schema is small and fixed by cue model 1; with the validator
  // loaded, problems() asks it instead, and the tests hold the two to the same verdicts.
  function shapeProblems(list) {
    if (!Array.isArray(list)) return [problem("", "is not an array", "type")];
    var found = [];
    if (list.length > 3) found.push(problem("", "has more than 3 items", "maxItems"));
    var states = K("CUE_STATES"), roles = K("CUE_ROLES");
    list.forEach(function (c, i) {
      var at = "/" + i;
      if (c === null || typeof c !== "object" || Array.isArray(c)) { found.push(problem(at, "is not an object", "type")); return; }
      ["button", "state", "role"].forEach(function (k) {
        if (!Object.prototype.hasOwnProperty.call(c, k)) found.push(problem(at, "lacks \"" + k + "\"", "required"));
      });
      Object.keys(c).forEach(function (k) {
        if (k !== "button" && k !== "state" && k !== "role") found.push(problem(at + "/" + k, "is not allowed here", "additionalProperties"));
      });
      if ("button" in c && BUTTONS.indexOf(c.button) < 0) found.push(problem(at + "/button", "is not one of 1, 2, 3", "enum"));
      if ("state" in c && states.indexOf(c.state) < 0) found.push(problem(at + "/state", "is not one of " + states.join(", "), "enum"));
      if ("role" in c && c.role !== null && roles.indexOf(c.role) < 0) found.push(problem(at + "/role", "is not one of " + roles.join(", ") + " or null", "enum"));
      if (c.state === "off" && "role" in c && c.role !== null) found.push(problem(at + "/role", "must be null for an off cue", "const"));
    });
    return found;
  }

  // What is wrong with `list` as a cue list ([] when it is fine): the `cue` schema's problems,
  // and a second cue for a button the list already has one for. Uses bollardeck.schema when it
  // is loaded, and its own check of the same schema when it is not.
  function problems(list) {
    var found = bollardeck.schema ? bollardeck.schema.validate("cue", list) : shapeProblems(list);
    if (found.length) return found;
    var seen = {};
    list.forEach(function (cue, i) {
      if (seen[cue.button]) {
        found.push(problem("/" + i + "/button", "is a second cue for button " + cue.button, "one-per-button"));
      }
      seen[cue.button] = true;
    });
    return found;
  }

  function lamps(fn) {
    var out = [], n = K("CHASE_STEPS");
    for (var i = 0; i < n; i++) out.push(fn(i));
    return out;
  }

  function entry(button, cue, t, opts) {
    var e = { button: button, driven: !!cue, state: cue ? cue.state : "off", role: cue ? cue.role : null,
              level: 0, arc: lamps(function () { return 0; }), head: null, pixel: 0 };
    if (!cue || cue.state === "off") return e;
    var k = 1;
    if (opts && opts.calm) k = 1;
    else if (cue.state === "pulse") k = pulseLevel(t, opts);
    else if (cue.state === "chase") {
      var tail = K("CHASE_TAIL");
      e.head = chaseHead(t, opts);
      e.arc = lamps(function (i) { return i === e.head ? 1 : tail; });
      e.level = e.arc[Math.floor(e.arc.length / 2)];
      e.pixel = toPixel(e.level);
      return e;
    }
    e.level = k;
    e.arc = lamps(function () { return k; });
    e.pixel = toPixel(k);
    return e;
  }

  // What normalise() does with `list`: {cues, repairs}. Never throws.
  function scan(list) {
    var repairsFound = [], by = {};
    function note(index, kind, message, dropped) { repairsFound.push({ index: index, kind: kind, message: message, dropped: dropped }); }
    if (!Array.isArray(list)) {
      note(null, "list", "not a list", true);
      return { cues: [], repairs: repairsFound };
    }
    var states = K("CUE_STATES"), roles = K("CUE_ROLES");
    list.forEach(function (c, i) {
      if (c === null || typeof c !== "object" || Array.isArray(c)) { note(i, "cue", "not an object", true); return; }
      var b = c.button;
      if (typeof b !== "number" || BUTTONS.indexOf(b) < 0) {
        note(i, "button", "button must be 1, 2 or 3" + (("btn" in c) && !("button" in c) ? " (\"btn\" is the wire form)" : ""), true);
        return;
      }
      if (typeof c.state !== "string" || states.indexOf(c.state) < 0) { note(i, "state", "state must be one of " + states.join("/"), true); return; }
      var role = c.role === undefined ? null : c.role;
      if (role !== null && (typeof role !== "string" || roles.indexOf(role) < 0)) {
        note(i, "role", "role is not one of " + roles.join("/") + "; read as none", false);
        role = null;
      } else if (role !== null && c.state === "off") {
        note(i, "role", "an off cue carries no role; read as none", false);
        role = null;
      }
      if (by[b]) note(i, "duplicate", "button " + b + " has two cues; this one replaces the earlier", false);
      by[b] = { button: b, state: c.state, role: role };
    });
    return { cues: BUTTONS.filter(function (b) { return by[b]; }).map(function (b) { return by[b]; }), repairs: repairsFound };
  }

  // The cue list every renderer wants, from anything: one {button, state, role} per button, in
  // button order, always valid. Never throws: a cue it cannot use is dropped, a role it cannot
  // use is read as none, and of two cues for one button the last is kept. A cue with no role
  // member has none, and members the cue model lacks are left out.
  function normalise(list) { return scan(list).cues; }

  // What normalise(list) drops or changes: [{index, kind, message, dropped}], [] for nothing.
  // kind is "list", "cue", "button", "state", "role" or "duplicate".
  function repairs(list) { return scan(list).repairs; }

  // Check a cue list once and get something to ask at each frame. Throws a TypeError carrying
  // .problems when the list is not a valid cue list. The list is copied: changing it afterwards
  // changes nothing here.
  function compile(list) {
    var found = problems(list);
    if (found.length) {
      var err = new TypeError("bollardeck.cues: not a cue list: " + found.map(String).join("; "));
      err.problems = found;
      throw err;
    }
    var by = {};
    list.forEach(function (cue) { by[cue.button] = Object.freeze({ button: cue.button, state: cue.state, role: cue.role }); });
    var cues = Object.freeze(BUTTONS.filter(function (b) { return by[b]; }).map(function (b) { return by[b]; }));
    return Object.freeze({
      cues: cues,
      at: function (tMs, opts) {
        var t = clock(tMs);
        return BUTTONS.map(function (b) { return entry(b, by[b], t, opts); });
      }
    });
  }

  var compiled = typeof WeakMap !== "undefined" ? new WeakMap() : null;

  // What the three buttons show at tMs for this cue list. The list is checked the first time it
  // is seen and remembered, so treat a list as immutable and pass a new one to change the cues.
  function at(list, tMs, opts) {
    var show = compiled && list && typeof list === "object" ? compiled.get(list) : null;
    if (!show) {
      show = compile(list);
      if (compiled) compiled.set(list, show);
    }
    return show.at(tMs, opts);
  }

  var api = {
    BUTTONS: BUTTONS, problems: problems, normalise: normalise, repairs: repairs,
    compile: compile, at: at, pulseLevel: pulseLevel, chaseHead: chaseHead
  };

  bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var cues = bollardeck.cues || (bollardeck.cues = {});
  Object.keys(api).forEach(function (k) { cues[k] = api[k]; });
  // The three rendering constants, as they have always been reachable here; the values are bollardeck.constants'.
  ["PULSE_FLOOR", "CHASE_TAIL", "CHASE_STEPS"].forEach(function (name) {
    Object.defineProperty(cues, name, { get: function () { return K(name); }, enumerable: true, configurable: true });
  });
  (bollardeck.parts || (bollardeck.parts = {})).cues = true;
  if (typeof module === "object" && module.exports) module.exports = cues;
})(typeof globalThis !== "undefined" ? globalThis : this);
