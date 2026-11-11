// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.gestures: button presses in, gestures out.
 *
 * The twin of python/bollardeck/device/gestures.py: a pure state machine that never reads a
 * clock. Every call carries a time in milliseconds on a clock of your choosing, as long as it
 * never runs backwards. Both are held to conformance/gestures/timelines.json.
 *
 *   var engine = bollardeck.gestures.engine();   // HOLD_MS, TAP_FOLLOW_MS and the keymap's combos
 *   engine.down(1, 0);                           // []
 *   engine.up(1, 120);                           // []  (button 1 has a triple tap: wait and see)
 *   engine.tick(621);                            // [{name: "tap1", button: 1, kind: "tap", count: 1, tMs: 620}]
 *   engine.down(3, 1000);                        // []
 *   engine.tick(1800);                           // [{name: "hold3", ... tMs: 1800}]  fires while still down
 *
 * Call tick(now) from a timer; nextDeadlineMs() says when the next tick will have something to
 * say (null: nothing is waiting on the clock). down and up advance the clock themselves.
 * bollardeck.dom.js adds gestures.listen(elements, onGesture), which feeds an engine from
 * pointer and keyboard events and keeps that one timer.
 *
 * The rules. Names: tap<b> one tap, tap<b>x<n> a chain of n taps, hold<b> a hold; <b> is 1, 2, 3.
 *  1. Hold. A press becomes hold<b> at the moment it has lasted holdMs, while still down. Its
 *     release then means nothing. A press released at exactly holdMs is a hold.
 *  2. Tap. A press released sooner is a tap.
 *  3. Combos. `combos` says which chain lengths are gestures of their own, per button:
 *     {1: [3], 3: [3]} gives buttons 1 and 3 a triple tap. A button with no combos reports each
 *     tap at its release, with no delay.
 *  4. Chains. On a button with combos, taps chain when the next press begins no later than
 *     tapFollowMs after the last release. A chain that reaches the button's longest combo is
 *     reported at once, at the release of its last tap.
 *  5. A chain ends early when its window closes, when another button goes down, or when a hold
 *     fires. It is then reported as tap<b>x<n> when n is one of the button's combos, otherwise
 *     as n separate tap<b>. So a lone tap on a button with combos is reported tapFollowMs late.
 *  6. When. Each gesture carries the time it became certain. A window that closes at time D is
 *     reported by the first call with a time later than D; a press at exactly D still chains.
 *  7. Cancel. cancel(b, t) drops a press that was not meant (the pointer left, the page lost
 *     focus). It is not a tap. If it had continued a chain, the chain's window starts again at t.
 *  8. Odd input. down for a button already down, and up or cancel for one that is not, are
 *     ignored. A time earlier than the last one seen, or a button that is not 1, 2 or 3, throws
 *     a RangeError.
 *
 *  9. Key events. key(event, nowMs) takes the device's key events. A complete press
 *     {t: "key", i: button, down: 0, hold_ms, t_ms} is a tap or a hold by its hold_ms alone,
 *     never by when it is read: a release read late is still the tap it says it is. A press
 *     beginning {t: "key", i: button, down: 1, t_ms} is a hint and never a gesture: while taps
 *     are pending on that button and the press began inside their window, the window is not
 *     closed until the press ends or has lasted holdMs, and the press is then placed at
 *     began .. began + hold_ms. A beginning whose release never comes is a lost press: it yields
 *     nothing, the next press on that button is its own, and the hint is forgotten after
 *     pressLostMs. A hold that arrives as a key event is reported when its release is read.
 *     A release is matched to a beginning before the beginning is believed. One that states
 *     its own t_ms and hold_ms describes a press that began at t_ms - hold_ms: it belongs to
 *     the announced press only when that is within PRESS_MATCH_MS of the announcement (so the
 *     two must be on one clock). Began later: the announced press was lost, the hint is
 *     dropped and the release is a press of its own. Began earlier: an older press, and the
 *     hint is kept. A release with no time of its own is read late at worst, so it belongs
 *     unless it began before the announcement. A release with no hold_ms is measured from its
 *     announcement only while that makes it a tap; otherwise it is a press of no length.
 * 10. How long. Each gesture carries holdMs, how long its press lasted: a tap's down to
 *     release; a chain's last tap; the engine's holdMs for a hold that fires while still down;
 *     the whole press for a hold fed as a complete press.
 *
 * The clock is yours to keep: the engine throws when a time is earlier than the last one it was
 * given and never clamps. A host that mixes two clocks clamps before it calls.
 *
 * Debouncing is not here: drop contact bounce before it reaches the engine.
 */
(function (root) {
  "use strict";

  var NAME_RE = /^(tap|hold)([1-9])(?:x([1-9][0-9]*))?$/;
  var bollardeck;                   // set at the bottom of this file

  function constant(name) {
    var k = bollardeck.constants;
    if (!k || k[name] === undefined) throw new Error("bollardeck.gestures: no " + name + " (load bollardeck.js, or pass it in)");
    return k[name];
  }
  function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

  // "tap1", "tap3x3", "hold2".
  function gestureName(kind, button, count) {
    if (kind === "hold") return "hold" + button;
    return count === undefined || count === 1 ? "tap" + button : "tap" + button + "x" + count;
  }

  // {kind, button, count} for one of the names in GESTURES; a RangeError for anything else.
  function parseGesture(name) {
    var m = typeof name === "string" ? NAME_RE.exec(name) : null;
    if (!m || constant("GESTURES").indexOf(name) < 0) {
      throw new RangeError(JSON.stringify(name) + " is not a gesture name (one of " + constant("GESTURES").join(", ") + ")");
    }
    return { kind: m[1], button: +m[2], count: m[3] ? +m[3] : 1 };
  }

  // The chain lengths a keymap gives a meaning to, per button: the combos an engine needs so
  // that every gesture the keymap names can happen. {1: [3], 3: [3]} for the platform's keymap.
  function combosFromKeymap(keymap) {
    var found = {};
    ["prompt", "idle", "always"].forEach(function (section) {
      var block = keymap && keymap[section];
      Object.keys(isObject(block) ? block : {}).forEach(function (name) {
        var m = NAME_RE.exec(name);
        if (m && m[1] === "tap" && m[3]) {
          var list = found[m[2]] || (found[m[2]] = []);
          if (list.indexOf(+m[3]) < 0) list.push(+m[3]);
        }
      });
    });
    Object.keys(found).forEach(function (b) { found[b].sort(function (x, y) { return x - y; }); });
    return found;
  }

  function checkCombos(combos) {
    var out = {}, buttons = constant("BUTTON_NUMBERS"), max = constant("TAP_CHAIN_MAX");
    Object.keys(combos).forEach(function (key) {
      var button = /^[0-9]+$/.test(key) ? +key : key;
      if (buttons.indexOf(button) < 0) throw new RangeError("combos: " + JSON.stringify(key) + " is not a button (1, 2 or 3)");
      var ns = [];
      (combos[key] || []).forEach(function (n) {
        if (typeof n !== "number" || Math.floor(n) !== n || n < 2 || n > max) {
          throw new RangeError("combos: a chain is 2 to " + max + " taps, not " + JSON.stringify(n));
        }
        if (ns.indexOf(n) < 0) ns.push(n);
      });
      ns.sort(function (x, y) { return x - y; });
      if (ns.length) out[button] = ns;
    });
    return out;
  }

  // One engine per set of three buttons. opts: holdMs, tapFollowMs, combos, pressLostMs; each
  // defaults to the platform's (bollardeck.constants HOLD_MS, TAP_FOLLOW_MS, PRESS_LOST_MS, and
  // the combos KEYMAP names). setCombos(combos) changes the combos of a running engine.
  function engine(opts) {
    opts = opts || {};
    var holdMs = opts.holdMs === undefined ? constant("HOLD_MS") : opts.holdMs;
    var followMs = opts.tapFollowMs === undefined ? constant("TAP_FOLLOW_MS") : opts.tapFollowMs;
    var lostMs = opts.pressLostMs === undefined ? constant("PRESS_LOST_MS") : opts.pressLostMs;
    if (typeof holdMs !== "number" || typeof followMs !== "number" || typeof lostMs !== "number" ||
        !(holdMs > 0) || !(followMs >= 0) || !(lostMs >= 0)) {
      throw new RangeError("holdMs must be above 0, and tapFollowMs and pressLostMs 0 or more");
    }
    holdMs = Math.trunc(holdMs);
    followMs = Math.trunc(followMs);
    lostMs = Math.trunc(lostMs);
    var combos = checkCombos(opts.combos === undefined || opts.combos === null ? combosFromKeymap(constant("KEYMAP")) : opts.combos);
    var buttons = constant("BUTTON_NUMBERS");
    var now = null;
    var down = {};                  // button -> [down time, hold already fired]
    var began = {};                 // button -> when a key source said a press began (a hint)
    var chainHolds = [];            // how long each pending tap lasted, oldest first
    var chainDropped = false;       // setCombos took the pending chain's combos away: report it
    var chainButton = null, chainCount = 0;
    var chainRelease = 0;           // when the chain's last tap was released
    var chainOpen = false;          // the chain's button is down again, in time

    function gesture(kind, b, count, t, held) {
      return { name: gestureName(kind, b, count), button: b, kind: kind, count: count, tMs: t, holdMs: held };
    }
    function has(map, b) { return Object.prototype.hasOwnProperty.call(map, b); }
    // Drop the hint of a press whose release has not come pressLostMs after it began.
    function forgetLost(t) {
      Object.keys(began).forEach(function (b) { if (t - began[b] > lostMs) delete began[b]; });
    }
    // Is the pending chain waiting on an announced press that began in its window and may still
    // be a tap at time t?
    function heldBack(t) {
      return chainButton !== null && has(began, chainButton) && began[chainButton] <= chainRelease + followMs &&
        t < began[chainButton] + holdMs;
    }
    function button(b) {
      if (typeof b !== "number" || buttons.indexOf(b) < 0) throw new RangeError("button must be 1, 2 or 3, not " + JSON.stringify(b));
      return b;
    }
    function time(t) {
      if (typeof t !== "number" || t !== t) throw new RangeError("a time must be a number, not " + JSON.stringify(t));
      if (now !== null && t < now) throw new RangeError("time ran backwards: " + t + " after " + now);
      now = t;
      return t;
    }

    // After setCombos: can the pending chain no longer grow (its button has no combos now, or
    // it is already as long as the longest)?
    function chainOver() {
      var counts = chainCount ? combos[chainButton] : null;
      return chainCount > 0 && (!counts || chainCount >= counts[counts.length - 1]);
    }
    // Report a chain that setCombos ended, as of time t.
    function dropped(t) {
      if (!chainDropped) return [];
      chainDropped = false;
      return chainOver() ? flush(chainOpen ? t : Math.min(t, chainRelease + followMs)) : [];
    }

    // End the pending chain and report it as of time t.
    function flush(t) {
      var b = chainButton, n = chainCount, holds = chainHolds, out = [];
      chainButton = null; chainCount = 0; chainOpen = false; chainHolds = [];
      if (!n || b === null) return out;
      if ((combos[b] || []).indexOf(n) >= 0) return [gesture("tap", b, n, t, holds[holds.length - 1])];
      for (var i = 0; i < n; i++) out.push(gesture("tap", b, 1, t, holds[i]));
      return out;
    }

    // A tap on button b, `held` long, was released at time t.
    function tap(b, t, held) {
      var counts = combos[b];
      if (!counts) return flush(t).concat([gesture("tap", b, 1, t, held)]);
      var out = chainCount && chainButton !== b ? flush(t) : [];
      chainButton = b; chainOpen = false;
      chainCount += 1;
      chainHolds.push(held);
      // A tap that is reported late (a key event from the past) never moves the window back.
      chainRelease = chainCount === 1 ? t : Math.max(chainRelease, t);
      if (chainCount >= counts[counts.length - 1]) {
        var n = chainCount;
        chainButton = null; chainCount = 0; chainHolds = [];
        out.push(gesture("tap", b, n, chainRelease, held));
      }
      return out;
    }

    // Everything the clock alone decides up to time t, oldest first.
    function advance(t) {
      var out = [];
      forgetLost(t);
      out = dropped(t);
      for (;;) {
        var holdAt = null, holdButton = null;
        Object.keys(down).map(Number).sort().forEach(function (b) {
          var d = down[b];
          if (!d[1] && d[0] + holdMs <= t && (holdAt === null || d[0] + holdMs < holdAt)) { holdAt = d[0] + holdMs; holdButton = b; }
        });
        var closeAt = null;
        if (chainCount && !chainOpen && chainRelease + followMs < t && !heldBack(t)) closeAt = chainRelease + followMs;
        if (closeAt !== null && (holdAt === null || closeAt <= holdAt)) {
          out = out.concat(flush(closeAt));
        } else if (holdAt !== null) {
          out = out.concat(flush(holdAt));              // a hold is never part of a chain
          down[holdButton][1] = true;
          out.push(gesture("hold", holdButton, 1, holdAt, holdMs));
        } else {
          return out;
        }
      }
    }

    // The end of a press, without touching any hint.
    function up(b, tMs) {
      var t = time(tMs), out = advance(t);                      // a press that reached holdMs fires here
      if (!has(down, b)) return out;
      var fired = down[b][1], downMs = down[b][0];
      delete down[b];
      return fired ? out : out.concat(tap(b, t, t - downMs));
    }

    var api = {
      holdMs: holdMs,
      tapFollowMs: followMs,
      pressLostMs: lostMs,
      combos: combos,

      // Change which chain lengths are gestures, on a running engine. Nothing in flight is lost:
      // a button that is down stays down, and pending taps stay pending. They are judged by the
      // new combos from here on: taps pending on a button that no longer has a combo are
      // reported by the next call (stamped with the end of their window, or with that call's
      // time when the window is still open).
      setCombos: function (next) {
        combos = checkCombos(next === undefined || next === null ? combosFromKeymap(constant("KEYMAP")) : next);
        api.combos = combos;
        chainDropped = chainOver();
        return api;
      },

      // Taps waiting to learn whether they are part of a chain.
      pending: function () { return chainCount; },
      // Is this button down, as down and up have told it? (A press a key source only announced
      // is not: see waiting.)
      isDown: function (b) { return has(down, b); },
      // Has a key source announced a press (on this button, or on any) whose release is still
      // expected?
      waiting: function (b) { return b === undefined ? Object.keys(began).length > 0 : has(began, b); },

      // The earliest time at which tick would report something if nothing else happens.
      nextDeadlineMs: function () {
        var best = null;
        Object.keys(down).forEach(function (b) {
          if (!down[b][1] && (best === null || down[b][0] + holdMs < best)) best = down[b][0] + holdMs;
        });
        if (chainDropped && chainCount) return now === null ? 0 : now;
        if (chainCount && !chainOpen) {
          // An announced press that began inside the window holds it until it could no longer be a tap.
          // ... or until it is given up on, whichever is sooner.
          var closes = chainRelease + followMs, at = closes + 1;
          if (has(began, chainButton) && began[chainButton] <= closes) {
            at = Math.max(at, Math.min(began[chainButton] + holdMs, began[chainButton] + lostMs + 1));
          }
          if (best === null || at < best) best = at;
        }
        return best;
      },

      // Say what time it is. Returns what became certain since the last call.
      tick: function (tMs) { return advance(time(tMs)); },

      down: function (b, tMs) {
        button(b);
        var t = time(tMs), out = advance(t);
        if (api.isDown(b)) return out;
        if (chainCount) {
          if (chainButton !== b) out = out.concat(flush(t));    // another button ends a chain
          else chainOpen = true;                                // pressed in time: wait for this one
        }
        down[b] = [t, false];
        return out;
      },

      up: function (b, tMs) {
        button(b);
        if (api.isDown(b)) delete began[b];                     // an edge is the truth: a hint for this button is over
        return up(b, tMs);
      },

      cancel: function (b, tMs) {
        button(b);
        var t = time(tMs), out = advance(t);
        delete began[b];                                        // a cancelled press takes its announcement with it
        if (!api.isDown(b)) return out;
        delete down[b];
        if (chainCount && chainButton === b && chainOpen) {
          chainOpen = false;
          chainRelease = t;                                     // the window starts again
        }
        return out;
      },

      // One complete press: down then up.
      press: function (b, downMs, upMs) { return api.down(b, downMs).concat(api.up(b, upMs)); },

      // One of the device's key events (rule 9). A press beginning is a hint and returns [].
      // Only a button that down() itself was called for is ended by a {down: 0} event as an edge.
      key: function (event, nowMs) {
        var b = button(event.i);
        var release = event.t_ms;
        if (release === null || release === undefined) release = nowMs;
        if (release === null || release === undefined) throw new RangeError("this key event has no time: pass nowMs");
        forgetLost(nowMs === null || nowMs === undefined ? release : Math.max(release, nowMs));
        if (event.down) { began[b] = release; return []; }      // a hint, and nothing more
        if (api.isDown(b)) {                                    // the end of a press down() began
          delete began[b];
          return api.up(b, now === null ? release : Math.max(release, now));
        }
        var hinted = has(began, b), start0 = began[b];
        var stated = event.hold_ms;
        if (hinted) {
          // Is this the release of the press that was announced? (rule 9)
          var belongs, stale;
          if (stated === null || stated === undefined) {
            var age = release - start0;
            belongs = age >= 0 && age < holdMs; stale = true;   // never a hold from the hint's age
            stated = belongs ? age : null;
          } else {
            var starts = release - Math.max(0, Math.trunc(+stated || 0));   // when the press it describes began
            var ownTime = event.t_ms !== null && event.t_ms !== undefined, match = constant("PRESS_MATCH_MS");
            belongs = ownTime ? Math.abs(starts - start0) <= match : starts >= start0 - match;
            stale = starts > start0;                            // the announced press was lost
          }
          if (belongs || stale) delete began[b];
          hinted = belongs;
        }
        var held = Math.max(0, Math.trunc(+stated || 0));
        if (hinted) release = start0 + held;                    // placed by its beginning
        var start = release - held;
        if (now === null || start >= now) {
          return api.down(b, start).concat(up(b, release)).map(function (g) {    // not api.up: a hint kept above stays
            if (g.kind === "hold" && g.button === b) g.holdMs = held;
            return g;
          });
        }
        // The press began before the last time this engine was told about (a tick ran while the
        // button was down, or the event arrived late). Judge it by its own two times.
        var out = dropped(now);
        if (chainCount && chainButton !== b) out = out.concat(flush(start));
        if (held >= holdMs) {
          out = out.concat(flush(start + holdMs));
          out.push(gesture("hold", b, 1, start + holdMs, held));
        } else {
          out = out.concat(tap(b, release, held));
        }
        now = Math.max(now, release);
        return out;
      },

      // One event as the conformance vectors write it: {t_ms, edge: "down" | "up" | "cancel",
      // button}, {t_ms, edge: "tick"}, {t_ms, edge: "key", key: {a device key event}}, which is
      // key(event.key, event.t_ms): a key event read at t_ms, or {edge: "combos", combos}, which
      // is setCombos(event.combos).
      feed: function (event) {
        if (event.edge === "key") return api.key(event.key, event.t_ms);
        if (event.edge === "combos") { api.setCombos(event.combos); return []; }
        if (event.edge === "tick") return api.tick(event.t_ms);
        if (event.edge === "down" || event.edge === "up" || event.edge === "cancel") return api[event.edge](event.button, event.t_ms);
        throw new RangeError("edge must be down, up, cancel, tick, key or combos, not " + JSON.stringify(event.edge));
      },

      // Every gesture a list of events produces, in order.
      run: function (events) {
        var out = [];
        events.forEach(function (event) { out = out.concat(api.feed(event)); });
        return out;
      }
    };
    return api;
  }

  var api = { engine: engine, gestureName: gestureName, parseGesture: parseGesture, combosFromKeymap: combosFromKeymap };

  bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var gestures = bollardeck.gestures || (bollardeck.gestures = {});
  Object.keys(api).forEach(function (k) { gestures[k] = api[k]; });
  (bollardeck.parts || (bollardeck.parts = {})).gestures = true;
  if (typeof module === "object" && module.exports) module.exports = gestures;
})(typeof globalThis !== "undefined" ? globalThis : this);
