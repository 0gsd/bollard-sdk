// SPDX-License-Identifier: Apache-2.0
// bollardeck.js: the Bollawax Bollard SDK for browsers and Node. No build step: load it with a
// <script> tag (it defines globalThis.bollardeck), require() it, or import bollardeck.mjs.
//
// One tag is enough:   <script src="js/bollardeck.js"></script>
// The binding is this file and eight parts beside it, and this file loads the parts:
//   bollardeck.schemas.js   bollardeck.schemas   the JSON Schemas (generated)
//   bollardeck.schema.js    bollardeck.schema    validate(name, value)
//   bollardeck.cues.js      bollardeck.cues      what each button shows at a time
//   bollardeck.matrix.js    bollardeck.matrix    the LED matrix frame engine
//   bollardeck.gestures.js  bollardeck.gestures  button presses in, gestures out
//   bollardeck.keymap.js    bollardeck.keymap    what a gesture means
//   bollardeck.corpus.js    bollardeck.corpus    the corpus gate and a hub client
//   bollardeck.dom.js       cues.apply, cues.run, matrix.canvas, gestures.listen: the optional page helpers
// A plain tag in the page's HTML loads them in step, so the next <script> can use everything.
// A tag that is async, deferred or added by script loads them in order after itself: wait for
// bollardeck.ready, a promise of the bollardeck object (it rejects, naming the part, if one did
// not load). To load some of the parts, name them on the tag: data-parts="cues matrix" (spaces or
// commas) loads those and no others, the same way, and bollardeck.ready waits for them only; a
// name that is not a part rejects bollardeck.ready and loads nothing; an empty data-parts loads
// every part, as no data-parts does. To choose for yourself,
// write data-parts="none" on the tag (it then writes and adds nothing) and add a <script> for each
// part you want, in any order, before or after this file. In a worker, importScripts() them.
//
// The values below are checked against python/bollardeck/_version.py by the test suite, and
// bollardeck.constants is written by tools/generate.py from constants/constants.json.
(function (root) {
  "use strict";
  // A part loaded before this file has already made the object: fill it in, do not replace it.
  var bollardeck = (root.bollardeck && typeof root.bollardeck === "object") ? root.bollardeck : {};
  var core = {
    version: "0.2.0",
    speaks: {
      bollardeck: "bollardeck/1",
      routine_api: 1,
      licence: "popboll.licence/1",
      mrph5: "mrph5/1",
      wbol: "wbol/1",
    },
    minBollawax: "0.2.4",
  };
  Object.keys(core).forEach(function (k) { bollardeck[k] = core[k]; });
  // BEGIN GENERATED CONSTANTS (tools/generate.py writes this block from constants/constants.json)
  var deepFreeze = function (value) {
    // Freeze a constant all the way down, so no caller can change what the others read.
    var freeze = function (v) {
      if (v && typeof v === "object") { Object.keys(v).forEach(function (k) { freeze(v[k]); }); Object.freeze(v); }
      return v;
    };
    return freeze(value);
  };
  bollardeck.constants = deepFreeze({
    // A press this long or longer is a hold, not a tap.
    HOLD_MS: 800,
    // Taps on one button chain when the next press begins within this long of the last release.
    TAP_FOLLOW_MS: 500,
    // A release that states its own time belongs to an announced press when the press it describes
    // began within this long of the announcement.
    PRESS_MATCH_MS: 100,
    // A press a key source announced is forgotten when its release has not come after this long.
    PRESS_LOST_MS: 5000,
    // The longest chain of taps that is one gesture: a triple. A fourth tap starts a new chain.
    TAP_CHAIN_MAX: 3,
    // The states a button cue can be in.
    CUE_STATES: ["off", "on", "pulse", "chase"],
    // What a lit button can stand for. A cue may also carry no role (null).
    CUE_ROLES: ["a", "b", "c", "live", "go", "warn"],
    // One breath of a pulse cue: 2 Hz.
    PULSE_PERIOD_MS: 500,
    // One turn of a chase cue.
    CHASE_PERIOD_MS: 1000,
    // How bright a pulse cue is at its dimmest, where full is 1.
    PULSE_FLOOR: 0.35,
    // How bright the lamps behind a chase cue's head are, where the head is 1.
    CHASE_TAIL: 0.25,
    // The lamps in a button's arc: a chase cue's head visits each once per turn.
    CHASE_STEPS: 3,
    // The three buttons. A button is its number everywhere on the SDK's surface: cues, key events,
    // gesture names.
    BUTTON_NUMBERS: [1, 2, 3],
    // One row per button. "button" is the one vocabulary (1, 2, 3). "label" is a name for people
    // and describes the Boll's medallion only. "wire" is the word the bollardeck/1 wire uses for
    // the button under "btn" (spec/bollardeck.md, 6.2), and "id" is its wire id; both are for
    // translating at the wire, stay for as long as the wire is bollardeck/1, and are not a second
    // vocabulary.
    BUTTONS: [{"button": 1, "label": "inner", "wire": "inner", "id": "BTN_1_PLAY_PAUSE", "job": "play/pause"}, {"button": 2, "label": "middle", "wire": "middle", "id": "BTN_2_ONLINE_UPLOAD", "job": "online/upload"}, {"button": 3, "label": "outer", "wire": "outer", "id": "BTN_3_POWER", "job": "power"}],
    // Every gesture name: tap<button> for one tap, tap<button>x<count> for a chain of 2 or 3 taps,
    // hold<button> for a hold.
    GESTURES: ["tap1", "tap2", "tap3", "tap1x2", "tap2x2", "tap3x2", "tap1x3", "tap2x3", "tap3x3", "hold1", "hold2", "hold3"],
    // The kinds of prompt the keymap gives meanings for.
    PROMPT_KINDS: ["abc", "spectrum", "game"],
    // The engagement keymap, version 2: what each gesture means. "prompt" applies while a prompt is
    // showing and gives one meaning per kind of prompt: {"choice": x} answers the prompt with x,
    // {"do": name} is a verb ("raw": this kind wants press and release times, not gestures), null
    // takes the gesture and does nothing. "idle" (no prompt showing) and "always" (both, and first)
    // map a gesture to a verb. "pocket" (optional) maps a gesture to a player verb when no prompt
    // is showing and the device is in the pocket context (a cart with no dock), and is looked at
    // before "idle". It fits schema/keymap.schema.json.
    KEYMAP: {"v": 2, "prompt": {"tap1": {"abc": {"choice": "A"}, "spectrum": {"choice": -1}, "game": {"do": "raw"}}, "tap2": {"abc": {"choice": "B"}, "spectrum": {"choice": 0}, "game": {"do": "raw"}}, "tap3": {"abc": {"choice": "C"}, "spectrum": {"choice": 1}, "game": {"do": "raw"}}, "tap1x3": {"abc": {"choice": "A"}, "spectrum": {"choice": -2}, "game": {"do": "raw"}}, "tap3x3": {"abc": {"choice": "C"}, "spectrum": {"choice": 2}, "game": {"do": "raw"}}, "hold1": {"abc": {"do": "replay"}, "spectrum": {"do": "replay"}, "game": null}, "hold2": {"abc": {"do": "pass"}, "spectrum": {"do": "pass"}, "game": {"do": "forfeit"}}}, "idle": {"tap1": "skip_to_frontier", "tap1x3": "leave_us_alone"}, "always": {"hold3": "power"}, "pocket": {"tap1": "play_pause", "hold1": "stop", "tap1x2": "volume_down", "tap2": "whats_on", "tap2x2": "prev", "hold2": "share", "tap3": "next", "tap3x2": "volume_up"}},
    // The device contexts a keymap may give meanings for besides idle; a resolver is told the
    // context, and with none given only prompt, idle and always apply.
    KEYMAP_CONTEXTS: ["pocket"],
    // Where a cart's sound can go: the dock's audio, the headphone jack, a Bluetooth headset or
    // speaker, USB-C headphones on the side port, or nowhere. One route plays at a time.
    AUDIO_ROUTES: ["dock", "jack", "bt", "usb", "none"],
    // Where a device's power comes from now: a mains adapter, a dock's Bollport, a USB-C charger or
    // computer on a side port, its own battery pack, or a board that cannot tell.
    POWER_SOURCES: ["mains", "dock", "usb", "pack", "unknown"],
    // The role a cart picks from what is on its Bollport (spec v0.3 §5.3): host and brain of a
    // dock, a guest under another cart, a screen or hub with no dock descriptor, nothing at all
    // (pocket), or off. A computer on either port is an overlay, not a role.
    CART_ROLES: ["primary", "guest", "tv", "pocket", "off"],
    // The player verbs of the pocket context: what a player (Pompa on a cart) does for each.
    // whats_on shows the title, the audio route and the battery; share queues a share until the
    // device is online.
    POCKET_VERBS: ["play_pause", "stop", "next", "prev", "volume_up", "volume_down", "whats_on", "share"],
  });
  // END GENERATED CONSTANTS
  root.bollardeck = bollardeck;

  // ── the parts ──────────────────────────────────────────────────────────────────────────
  var PARTS = ["schemas", "schema", "cues", "matrix", "gestures", "keymap", "corpus", "dom"];
  bollardeck.parts = bollardeck.parts || {};
  var wanted = PARTS;               // narrowed by data-parts="cues matrix" on the tag
  var missing = function () { return wanted.filter(function (p) { return !bollardeck.parts[p]; }); };
  var settled = function () { return Promise.resolve(bollardeck); };

  if (typeof module === "object" && module.exports) {
    module.exports = bollardeck;          // set before the parts load: each of them requires this file
    if (typeof require === "function") PARTS.forEach(function (p) { require("./bollardeck." + p + ".js"); });
    bollardeck.ready = settled();
    return;
  }

  var doc = root.document;
  var script = doc && doc.currentScript;  // null when this file is imported as a module: bollardeck.mjs imports the parts
  // data-parts on the tag: absent loads every part; "none" loads nothing (and writes nothing);
  // a list of part names, separated by spaces or commas, loads those and no others.
  var asked = script && script.src ? script.getAttribute("data-parts") : null;
  // An empty data-parts says nothing, as it always has: every part.
  if (typeof asked === "string" && asked.trim() !== "" && asked.trim() !== "none") {
    var list = asked.split(/[\s,]+/).filter(function (p) { return p; });
    var unknown = list.filter(function (p) { return PARTS.indexOf(p) < 0; });
    if (unknown.length) {
      bollardeck.ready = Promise.reject(new Error("bollardeck: data-parts names no such part: " + unknown.join(", ") +
        " (the parts are " + PARTS.join(", ") + ', or "none")'));
      bollardeck.ready.catch(function () {});       // a page that never reads ready gets no unhandled rejection
      return;
    }
    wanted = PARTS.filter(function (p) { return list.indexOf(p) >= 0; });
  }
  if (!script || !script.src || (typeof asked === "string" && asked.trim() === "none") || !missing().length) {
    bollardeck.ready = settled();
    return;
  }
  var cut = script.src.search(/[?#]/);
  var path = cut < 0 ? script.src : script.src.slice(0, cut);
  var query = cut < 0 ? "" : script.src.slice(cut).replace(/#.*$/, "");       // keep a cache-busting ?v=
  var urls = missing().map(function (p) { return path.replace(/[^\/]*$/, "") + "bollardeck." + p + ".js" + query; });
  bollardeck.ready = new Promise(function (resolve, reject) {
    var settle = function () {
      var m = missing();
      if (m.length) reject(new Error("bollardeck: could not load " + m.map(function (p) { return "bollardeck." + p + ".js"; }).join(", ")));
      else resolve(bollardeck);
    };
    if (doc.readyState === "loading" && !script.async && !script.defer && script.type !== "module") {
      // The page is still being read: written tags run in order before the next tag in the page.
      urls.forEach(function (u) { doc.write('<script src="' + u.replace(/&/g, "&amp;").replace(/"/g, "&quot;") + '"><\/script>'); });
      doc.addEventListener("DOMContentLoaded", settle);
    } else {
      var left = urls.length;
      urls.forEach(function (u) {
        var s = doc.createElement("script");
        s.src = u;
        s.async = false;                  // run in the order added
        s.onload = s.onerror = function () { left -= 1; if (!left) settle(); };
        (doc.head || doc.documentElement).appendChild(s);
      });
    }
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
