// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.keymap: what a gesture means, by keymap version 2.
 *
 * The twin of python/bollardeck/device/keymap.py, held to conformance/gestures/resolve.json.
 * The platform's keymap is bollardeck.constants.KEYMAP; any other may be passed in.
 *
 *   bollardeck.keymap.resolve("tap1", "abc")    // {source: "prompt", kind: "choice", value: "A", ...}
 *   bollardeck.keymap.resolve("hold1", "abc")   // {source: "prompt", kind: "do", value: "replay", ...}
 *   bollardeck.keymap.resolve("tap2")           // no prompt showing: the idle map, or no answer
 *   bollardeck.keymap.resolve("tap2", null, null, "pocket")   // {source: "pocket", kind: "do", value: "whats_on", ...}
 *
 * The rule:
 *  1. If `always` names the gesture, that verb is the answer, prompt or no prompt.
 *  2. Otherwise, while a prompt is showing: if `prompt` names the gesture and that entry has a
 *     member for this kind of prompt, that member is the answer: {choice: x} answers the prompt,
 *     {do: name} is a verb, null takes the gesture and does nothing. `idle` is never consulted
 *     while a prompt is showing.
 *  3. Otherwise, with no prompt showing and a context given ("pocket": a cart with no dock): if
 *     the keymap's map for that context names the gesture, that verb is the answer.
 *  4. Otherwise, with no prompt showing: if `idle` names the gesture, that verb is the answer.
 *  5. Otherwise there is no answer (source null): the gesture is not the keymap's business.
 *
 * An answer is {source, kind, value, handled, action, choice}. `source` is "always", "prompt",
 * "pocket", "idle" or null; `kind` is "choice", "do" or null; `handled` is true for rules 1 to 4; `action`
 * is the verb's name when kind is "do", else null; `choice` is the value when kind is "choice",
 * else null (check `kind`: a choice may be 0). A name that is not a gesture, a keymap that is
 * not version 2, a context that is not one of KEYMAP_CONTEXTS, and a prompt meaning that is a
 * bare value all throw a RangeError. With no context given the answer is what it was before
 * contexts existed.
 * isGesture(name) says whether a name is a gesture, for a caller that routes other names
 * through the same code and does not want to catch.
 */
(function (root) {
  "use strict";

  var RAW = "raw", VERSION = 2;
  var bollardeck;                   // set at the bottom of this file

  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function constant(name) {
    var k = bollardeck.constants;
    if (!k || k[name] === undefined) throw new Error("bollardeck.keymap: no " + name + " (load bollardeck.js, or pass a keymap)");
    return k[name];
  }
  function map(keymap, section) { return isObject(keymap[section]) ? keymap[section] : {}; }

  function answer(source, kind, value) {
    return { source: source, kind: kind, value: value, handled: source !== null,
             action: kind === "do" ? value : null, choice: kind === "choice" ? value : null };
  }

  function meaning(source, m) {
    if (m === null) return answer(source, null, null);
    if (isObject(m) && Object.keys(m).length === 1) {
      if (has(m, "choice")) return answer(source, "choice", m.choice);
      if (has(m, "do")) return answer(source, "do", m.do);
    }
    throw new RangeError(JSON.stringify(m) + " is not a keymap meaning: {\"choice\": x}, {\"do\": name} or null (keymap version " + VERSION + ")");
  }

  // Is this one of the names in GESTURES ("tap1", "hold3", ...)? Never throws.
  function isGesture(name) {
    return typeof name === "string" && constant("GESTURES").indexOf(name) >= 0;
  }

  // What `gesture` means while a prompt of kind `prompt` is showing (null or absent: no prompt).
  function resolve(gesture, prompt, keymap, context) {
    var names = constant("GESTURES");
    if (context !== undefined && context !== null && (typeof context !== "string" || constant("KEYMAP_CONTEXTS").indexOf(context) < 0)) {
      throw new RangeError(JSON.stringify(context) + " is not a keymap context (one of " + constant("KEYMAP_CONTEXTS").join(", ") + ")");
    }
    if (!isGesture(gesture)) {
      throw new RangeError(JSON.stringify(gesture) + " is not a gesture name (one of " + names.join(", ") + ")");
    }
    if (keymap === undefined || keymap === null) keymap = constant("KEYMAP");
    if (!isObject(keymap) || keymap.v !== VERSION) {
      throw new RangeError("this is keymap version " + JSON.stringify(isObject(keymap) ? keymap.v : keymap) + "; bollardeck reads version " + VERSION);
    }
    var always = map(keymap, "always");
    if (has(always, gesture)) return answer("always", "do", always[gesture]);
    if (prompt !== null && prompt !== undefined) {
      var byKind = map(keymap, "prompt")[gesture];
      if (has(map(keymap, "prompt"), gesture) && isObject(byKind) && typeof prompt === "string" && has(byKind, prompt)) {
        return meaning("prompt", byKind[prompt]);
      }
      return answer(null, null, null);
    }
    if (context !== undefined && context !== null) {
      var byContext = map(keymap, context);
      if (has(byContext, gesture)) return answer(context, "do", byContext[gesture]);
    }
    var idle = map(keymap, "idle");
    if (has(idle, gesture)) return answer("idle", "do", idle[gesture]);
    return answer(null, null, null);
  }

  // Does this kind of prompt take press and release times instead of gestures? True when any
  // gesture's meaning for it is the verb "raw".
  function wantsRaw(prompt, keymap) {
    if (keymap === undefined || keymap === null) keymap = constant("KEYMAP");
    var byGesture = map(keymap, "prompt");
    return Object.keys(byGesture).some(function (name) {
      var m = isObject(byGesture[name]) && has(byGesture[name], prompt) ? byGesture[name][prompt] : null;
      return isObject(m) && Object.keys(m).length === 1 && m.do === RAW;
    });
  }

  // Every reason a document is not a keymap ([] when it is fine), as text: the `keymap` schema's
  // verdict, and any gesture that `always` names and another map names too.
  function problems(keymap) {
    if (!bollardeck.schema) throw new Error("bollardeck.keymap: checking a keymap needs bollardeck.schema (load bollardeck.schema.js)");
    var out = bollardeck.schema.validate("keymap", keymap).map(function (p) { return (p.pointer || "(document)") + ": " + p.message; });
    if (isObject(keymap) && isObject(keymap.always)) {
      ["prompt", "idle"].concat(constant("KEYMAP_CONTEXTS")).forEach(function (section) {
        Object.keys(map(keymap, section)).forEach(function (name) {
          if (has(keymap.always, name)) out.push("/" + section + "/" + name + ": always names this gesture too, so this entry never applies");
        });
      });
    }
    return out;
  }

  // The combos an engine needs for this keymap (bollardeck.gestures.combosFromKeymap); `contexts`
  // (e.g. ["pocket"]) adds those contexts' maps.
  function combos(keymap, contexts) {
    return bollardeck.gestures.combosFromKeymap(keymap === undefined || keymap === null ? constant("KEYMAP") : keymap, contexts);
  }

  var api = { RAW: RAW, VERSION: VERSION, isGesture: isGesture, resolve: resolve, wantsRaw: wantsRaw, problems: problems, combos: combos };

  bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var keymap = bollardeck.keymap || (bollardeck.keymap = {});
  Object.keys(api).forEach(function (k) { keymap[k] = api[k]; });
  (bollardeck.parts || (bollardeck.parts = {})).keymap = true;
  if (typeof module === "object" && module.exports) module.exports = keymap;
})(typeof globalThis !== "undefined" ? globalThis : this);
