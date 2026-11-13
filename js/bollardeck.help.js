// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.help: help content, struggle detection, and scripted tours, for any page.
 *
 * Pure: nothing here touches a page, a timer or a clock of its own. bollardeck.dom.js adds the page
 * helpers (help.listen, help.cta, help.modal, help.spot, help.ui). Python's bollardeck.help validates
 * the same two formats and gives the same caption arithmetic.
 *
 * Content (help-pack/1, schema/help-pack.schema.json)
 *   help.problems(doc)                    [] when doc is a usable pack, else problems {pointer, message, keyword}
 *   help.pack(doc)                        a frozen copy of a valid pack; throws a TypeError naming the problems
 *   help.merge([pack, ...])               one pack from several: the first to define an id keeps it, and a
 *                                         later pack may add only ids that start with "x." (third parties)
 *   help.matches(when, ctx)               does {roles, tiers, sites} match ctx {role, tier, site}?
 *   help.topic(pack, page, id, ctx)       the topic as this person should read it, variants applied, or null
 *   help.intro(pack, page, ctx)           the page's intro for ctx.role, variants applied, or null
 *   help.scenarios(pack, page, ctx)       [{id, topic, detector, target, signal, codes, params}] that apply
 *   help.lint(pack, manifest)             problems where a topic or scenario names a target the page does
 *                                         not have; manifest is {page: {role: [target ids]}}
 *
 * Detection
 *   help.detectors                        {name: fn(events, now, scenario, view) -> {fire, evidence} | null};
 *                                         view is {start, navs}: the last page loads are kept apart in navs
 *   help.detector(name, fn)               add one; a page's own names start with "x-"
 *   help.engine(opts) -> engine           the detectors plus the rules for offering help (below)
 *
 * Direction (help-director/1, schema/help-director.schema.json)
 *   help.directorProblems(doc)            [] when doc is a usable script
 *   help.director(doc)                    a frozen copy of a valid script; throws otherwise
 *   help.sayMs(text) / help.holdMs(step)  how long a step stays up
 *   help.splitCaption(text)               a say line as caption cues: each at most two lines of
 *                                         HELP_CAPTION_LINE characters, broken where the sentence pauses
 *   help.timeline(script, mode)           the steps that run in "capture" or "tour", each with its hold
 *   help.play(script, ui, opts)           run a script against a ui (a Promise of the step log)
 *   help.vtt(log, script) / help.chaptersVtt(log, script)   WebVTT from a recorded step log
 *   help.readText(script)                 [{chapter, text}]: the say lines, a paragraph per chapter
 *   help.lintDirector(script, manifest, signals)            unknown targets and signals
 *
 * EVENTS fed to an engine are plain objects; `t` (ms, the engine's clock) is filled in when absent:
 *   {kind: "activate", target, blocked}    a [data-help] control used; blocked when it was disabled
 *   {kind: "press", x, y, target}          a pointer went down (rage clicks)
 *   {kind: "input"}                        any key or pointer input at all
 *   {kind: "error", code}                  a request or action failed, with the host's code
 *   {kind: "signal", name}                 a named app event (band.timeout, endless.paused, ...)
 *   {kind: "visible", target, on}          a target came into or left view (dwell)
 *   {kind: "toggle", target, open}         a module, menu or dialog opened or closed (bounce)
 *   {kind: "flow", target, state}          a flow "start"ed, was "submit"ted or "cancel"led (abandon)
 *   {kind: "nav", page}                    this page view, with the page the person came from first
 *   {kind: "progress", name}               the person got somewhere: dwell and idle detectors stand down
 *
 * THE RULES an engine applies before it makes an offer (the HELP_* constants; opts.policy overrides):
 * no offer while offers are switched off, while the engine is backing off (HELP_BACKOFF_IGNORES offers in a row
 * left to fade, of any topic: quiet for HELP_BACKOFF_MS, doubling each time up to HELP_BACKOFF_MAX_MS, until an
 * offer is opened), while any quiet zone is on (engine.quiet(name, true), which also withdraws open offers: an offer
 * withdrawn comes back at most once a view, and withdrawn again counts as ignored), or in
 * the first HELP_LANDING_QUIET_MS of a view (except idle-after-landing); HELP_PILLS_AT_ONCE open offers;
 * HELP_OFFERS_PER_VIEW per view; each scenario at most once a view; a topic not again within
 * HELP_TOPIC_COOLDOWN_MS, nor while snoozed (NOT NOW, or HELP_IGNORES_TO_SNOOZE ignored offers:
 * HELP_SNOOZE_MS), nor once read, until its rev rises or its struggle has come back on HELP_RECUR_DAYS
 * different later days. An engine never reads a clock or storage of its own: opts.clock and opts.store.
 */
(function (root) {
  "use strict";

  var bollardeck;                   // set at the bottom of this file
  var DAY = 86400000;
  var ID_RE = /^[a-z][a-z0-9-]*([.][a-z0-9][a-z0-9-]*)+$/;
  var NAME_RE = /^[a-z][a-z0-9_-]*$/;
  var VERBS_SKIPPED_IN_TOUR = { act: true, cut: true };

  function has(o, k) { return o !== null && typeof o === "object" && Object.prototype.hasOwnProperty.call(o, k); }
  function C(name) { return bollardeck.constants[name]; }
  function copy(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
  function freeze(v) {
    if (v && typeof v === "object") { Object.keys(v).forEach(function (k) { freeze(v[k]); }); Object.freeze(v); }
    return v;
  }
  function esc(s) { return String(s).replace(/~/g, "~0").replace(/\//g, "~1"); }
  function problem(pointer, message, keyword) { return { pointer: pointer, message: message, keyword: keyword }; }
  function policy(opts, name) {
    var p = opts && opts.policy;
    return p && has(p, name) ? p[name] : C(name);
  }

  // ── content ──────────────────────────────────────────────────────────────────────────────

  // A link's href is a path on this site. A backslash, a space or a control character could make a browser read
  // "/\\host" or "/<tab>/host" as another site (URL parsers drop tabs and newlines and turn \\ into /), so none may appear.
  var BAD_HREF = /[\u0000-\u0020\u007f\\]/;
  function hrefs(content, at, out) {
    function body(b, where) {
      (b || []).forEach(function (para, i) {
        para.forEach(function (bit, j) {
          if (bit && typeof bit === "object" && typeof bit.href === "string" && BAD_HREF.test(bit.href)) {
            out.push(problem(where + "/" + i + "/" + j + "/href", "a link may not hold a backslash, a space or a control character", "href"));
          }
        });
      });
    }
    body(content.body, at + "/body");
    (content.variants || []).forEach(function (v, k) { body(v.body, at + "/variants/" + k + "/body"); });
  }

  function packProblems(doc) {
    var out = bollardeck.schema.validate("help-pack", doc);
    if (out.length) return out;
    Object.keys(doc.pages).forEach(function (page) {
      var at = "/pages/" + esc(page), p = doc.pages[page], topics = p.topics || {};
      if (!NAME_RE.test(page)) out.push(problem(at, "a page key must be a name (lowercase, digits, _ and -)", "page-name"));
      Object.keys(p.intro || {}).forEach(function (role) {
        if (!NAME_RE.test(role)) out.push(problem(at + "/intro/" + esc(role), "an intro key must be a role name", "role-name"));
        hrefs(p.intro[role], at + "/intro/" + esc(role), out);
      });
      Object.keys(topics).forEach(function (id) {
        var t = topics[id], tat = at + "/topics/" + esc(id);
        if (!ID_RE.test(id)) out.push(problem(tat, "a topic key must be a help id", "topic-id"));
        hrefs(t, tat, out);
        (t.see || []).forEach(function (s, i) {
          if (!has(topics, s)) out.push(problem(tat + "/see/" + i, "names no topic on this page: " + s, "see"));
        });
      });
      Object.keys(p.scenarios || {}).forEach(function (id) {
        var s = p.scenarios[id], sat = at + "/scenarios/" + esc(id);
        if (!ID_RE.test(id)) out.push(problem(sat, "a scenario key must be a help id", "scenario-id"));
        if (!has(topics, s.topic)) out.push(problem(sat + "/topic", "names no topic on this page: " + s.topic, "topic"));
        if (s.detector.indexOf("x-") !== 0 && C("HELP_DETECTORS").indexOf(s.detector) < 0) {
          out.push(problem(sat + "/detector", "is not a built-in detector (a page's own start with x-): " + s.detector, "detector"));
        }
      });
    });
    return out;
  }

  function fail(what, problems) {
    var e = new TypeError(what + ": " + problems.map(function (p) { return (p.pointer || "/") + " " + p.message; }).join("; "));
    e.problems = problems;
    throw e;
  }

  function pack(doc) {
    var p = packProblems(doc);
    if (p.length) fail("bollardeck.help.pack", p);
    return freeze(copy(doc));
  }

  function merge(packs) {
    var out = { schema: "help-pack/1", pack: packs[0].pack, lang: packs[0].lang,
                rev: packs.reduce(function (a, p) { return a + p.rev; }, 0), pages: {} };
    packs.forEach(function (p, n) {
      Object.keys(p.pages).forEach(function (page) {
        var into = out.pages[page] || (out.pages[page] = { intro: {}, topics: {}, scenarios: {} }), from = p.pages[page];
        ["intro", "topics", "scenarios"].forEach(function (kind) {
          Object.keys(from[kind] || {}).forEach(function (k) {
            if (has(into[kind], k)) return;                                    // the first pack keeps it
            if (n > 0 && kind !== "intro" && k.indexOf("x.") !== 0) return;      // later packs add only x.* ids
            if (n > 0 && kind === "intro") return;                              // and never an intro
            into[kind][k] = copy(from[kind][k]);
          });
        });
      });
    });
    return pack(out);
  }

  function matches(when, ctx) {
    if (!when) return true;
    ctx = ctx || {};
    var pairs = [["roles", "role"], ["tiers", "tier"], ["sites", "site"]];
    for (var i = 0; i < pairs.length; i++) {
      var list = when[pairs[i][0]];
      if (list && list.indexOf(ctx[pairs[i][1]]) < 0) return false;
    }
    return true;
  }

  function applyVariants(c, ctx) {
    var out = { title: c.title, body: c.body };
    var v = (c.variants || []).filter(function (x) { return matches(x.when, ctx); })[0];
    if (v) { if (v.title) out.title = v.title; if (v.body) out.body = v.body; }
    return out;
  }

  function topic(p, page, id, ctx) {
    var pg = p.pages[page], t = pg && pg.topics && pg.topics[id];
    if (!t || !matches(t.when, ctx)) return null;
    var shown = applyVariants(t, ctx);
    return { id: id, page: page, title: shown.title, body: shown.body, targets: t.targets || [], see: t.see || [],
             tour: t.tour || null, video: t.video || null, rev: t.rev || 1 };
  }

  function intro(p, page, ctx) {
    var pg = p.pages[page], c = pg && pg.intro && pg.intro[(ctx || {}).role];
    if (!c) return null;
    var shown = applyVariants(c, ctx);
    return { page: page, role: ctx.role, title: shown.title, body: shown.body };
  }

  function scenarios(p, page, ctx) {
    var pg = p.pages[page];
    if (!pg || !pg.scenarios) return [];
    return Object.keys(pg.scenarios).sort().map(function (id) {
      var s = pg.scenarios[id];
      return { id: id, topic: s.topic, detector: s.detector, target: s.target || null, signal: s.signal || null,
               codes: s.codes || null, params: s.params || {}, when: s.when || null };
    }).filter(function (s) {
      return matches(s.when, ctx) && topic(p, page, s.topic, ctx) !== null;
    });
  }

  function lint(p, manifest) {
    var out = [];
    Object.keys(p.pages).forEach(function (page) {
      var known = manifest[page], pg = p.pages[page];
      if (!known) { out.push(problem("/pages/" + esc(page), "the manifest has no page " + page, "page")); return; }
      function check(at, target, when) {
        var roles = (when && when.roles) || Object.keys(known);
        roles.forEach(function (role) {
          if (!known[role]) return;
          if (known[role].indexOf(target) < 0) out.push(problem(at, target + " is not on " + page + " for " + role, "target"));
        });
      }
      Object.keys(pg.topics || {}).forEach(function (id) {
        (pg.topics[id].targets || []).forEach(function (t, i) {
          check("/pages/" + esc(page) + "/topics/" + esc(id) + "/targets/" + i, t, pg.topics[id].when);
        });
      });
      Object.keys(pg.scenarios || {}).forEach(function (id) {
        var s = pg.scenarios[id];
        if (s.target) check("/pages/" + esc(page) + "/scenarios/" + esc(id) + "/target", s.target, s.when || (pg.topics[s.topic] || {}).when);
      });
    });
    return out;
  }

  // ── the detectors ────────────────────────────────────────────────────────────────────────
  // Each is fn(events, now, scenario, view) -> {fire: true, evidence} or null. `events` are in time
  // order; `view` is {start}. params come from the scenario, with these defaults.

  function param(s, name, dflt) { return s.params && has(s.params, name) ? s.params[name] : dflt; }
  function within(events, now, ms) { return events.filter(function (e) { return e.t <= now && e.t > now - ms; }); }
  function aimed(e, s) { return !s.target || e.target === s.target; }

  var detectors = {
    "blocked-repeat": function (events, now, s) {
      var n = param(s, "n", 2), hits = within(events, now, param(s, "window_ms", 8000)).filter(function (e) {
        return e.kind === "activate" && e.blocked && aimed(e, s);
      });
      return hits.length >= n ? { fire: true, evidence: { blocked: hits.length } } : null;
    },
    rage: function (events, now, s) {
      var n = param(s, "n", 3), r = param(s, "radius_px", 30);
      var presses = within(events, now, param(s, "window_ms", 1000)).filter(function (e) {
        return e.kind === "press" && aimed(e, s) && typeof e.x === "number" && typeof e.y === "number";
      });
      for (var i = 0; i + n <= presses.length; i++) {
        var a = presses[i], close = presses.slice(i).filter(function (b) { return Math.hypot(b.x - a.x, b.y - a.y) <= r; });
        if (close.length >= n) return { fire: true, evidence: { presses: close.length } };
      }
      return null;
    },
    "error-code": function (events, now, s) {
      var codes = s.codes || [], n = param(s, "n", 1);
      var hits = within(events, now, param(s, "window_ms", 60000)).filter(function (e) {
        return e.kind === "error" && codes.indexOf(e.code) >= 0;
      });
      return hits.length >= n ? { fire: true, evidence: { code: hits[hits.length - 1].code, errors: hits.length } } : null;
    },
    "signal-repeat": function (events, now, s, view) {
      var n = param(s, "n", 1), ms = param(s, "window_ms", 60000);
      var pool = param(s, "since", "window") === "view" ? events.filter(function (e) { return e.t >= view.start; }) : within(events, now, ms);
      var hits = pool.filter(function (e) { return e.kind === "signal" && e.name === s.signal; });
      return hits.length >= n ? { fire: true, evidence: { signals: hits.length } } : null;
    },
    // In view for `ms` without being used, AND the person busy elsewhere meanwhile (`presses`, default 2:
    // presses or key input not on the target). Someone simply watching a page is not stuck.
    dwell: function (events, now, s) {
      var ms = param(s, "ms", 10000), need = param(s, "presses", 2), since = null, busy = 0;
      events.forEach(function (e) {
        if (e.t > now) return;
        if (e.kind === "visible" && aimed(e, s)) {
          if (!e.on) { since = null; busy = 0; } else if (since === null) { since = e.t; busy = 0; }
        } else if (since !== null && (e.kind === "progress" || (e.kind === "activate" && aimed(e, s)))) { since = e.t; busy = 0; }
        else if (since !== null && (e.kind === "input" || (e.kind === "press" && !aimed(e, s)))) busy += 1;
      });
      return since !== null && now - since >= ms && busy >= need ? { fire: true, evidence: { dwell_ms: now - since, busy: busy } } : null;
    },
    "idle-after-landing": function (events, now, s, view) {
      var ms = param(s, "ms", 20000), unless = param(s, "unless", []);
      if (now - view.start < ms) return null;
      var busy = events.some(function (e) {
        return e.t >= view.start && e.t <= now && (e.kind === "input" || e.kind === "press" || e.kind === "activate" ||
          e.kind === "progress" || (e.kind === "signal" && unless.indexOf(e.name) >= 0));
      });
      return busy ? null : { fire: true, evidence: { idle_ms: now - view.start } };
    },
    bounce: function (events, now, s, view) {
      var n = param(s, "n", 2), ms = param(s, "window_ms", 30000);
      if (param(s, "nav", false)) {
        var pages = (view && view.navs ? view.navs : events).filter(function (e) { return e.kind === "nav" && e.t <= now && e.t > now - ms; })
          .map(function (e) { return e.page; });
        var k = pages.length;
        return k >= 3 && pages[k - 1] === pages[k - 3] && pages[k - 1] !== pages[k - 2] ? { fire: true, evidence: { pages: pages.slice(-3) } } : null;
      }
      var closes = within(events, now, ms).filter(function (e) { return e.kind === "toggle" && !e.open && aimed(e, s); });
      return closes.length >= n ? { fire: true, evidence: { closes: closes.length } } : null;
    },
    abandon: function (events, now, s) {
      var n = param(s, "n", 2), left = 0, open = false;
      within(events, now, param(s, "window_ms", 600000)).forEach(function (e) {
        if (e.kind !== "flow" || !aimed(e, s)) return;
        if (e.state === "start") open = true;
        else if (e.state === "submit") { open = false; left = 0; }
        else if (e.state === "cancel" && open) { open = false; left += 1; }
      });
      return left >= n ? { fire: true, evidence: { abandoned: left } } : null;
    }
  };

  function detector(name, fn) {
    if (!/^x-[a-z][a-z0-9-]*$/.test(name)) throw new RangeError("bollardeck.help.detector: a page's own detector is named x-<name>: " + name);
    if (typeof fn !== "function") throw new TypeError("bollardeck.help.detector: fn must be a function");
    detectors[name] = fn;
  }

  // ── the engine ───────────────────────────────────────────────────────────────────────────

  var NAVS_KEPT = 3;

  function memoryStore() {
    var v = null;
    return { get: function () { return v === null ? null : copy(v); }, set: function (x) { v = copy(x); } };
  }

  function engine(opts) {
    if (!opts || !opts.pack || !opts.page) throw new TypeError("bollardeck.help.engine: opts.pack and opts.page are required");
    if (typeof opts.clock !== "function") throw new TypeError("bollardeck.help.engine: opts.clock is required (the engine has no clock of its own)");
    var ctx = opts.ctx || {}, clock = opts.clock, store = opts.store || memoryStore();
    var keep = opts.keepMs || 600000;
    var list = scenarios(opts.pack, opts.page, ctx);
    var view = { start: has(opts, "viewStart") ? opts.viewStart : clock(), navs: [] };
    var events = [], open = [], offered = 0, fired = {}, withdrawn = {}, quiet = {}, listeners = { offer: [], settle: [] };

    function load() {
      var s = store.get();
      return s && s.v === 1 ? s : { v: 1, off: false, topics: {} };
    }
    function save(s) { store.set(s); }
    function rec(s, id) { return s.topics[id] || (s.topics[id] = {}); }
    function emit(kind, x) { listeners[kind].forEach(function (fn) { fn(x); }); }

    function allowed(s, sc, now) {
      var r = s.topics[sc.topic] || {}, t = topic(opts.pack, opts.page, sc.topic, ctx);
      if (r.snooze_until && now < r.snooze_until) return false;
      if (r.last_offer !== undefined && now - r.last_offer < policy(opts, "HELP_TOPIC_COOLDOWN_MS")) return false;
      if (r.read_rev !== undefined && r.read_rev >= t.rev) {
        var days = (r.recur || []).filter(function (d) { return d > Math.floor(r.read_at / DAY); });
        if (days.length < policy(opts, "HELP_RECUR_DAYS")) return false;
      }
      return true;
    }

    function noteRecurrence(s, sc, now) {
      var r = rec(s, sc.topic);
      if (r.read_at === undefined) return;
      var day = Math.floor(now / DAY);
      r.recur = (r.recur || []).filter(function (d) { return d !== day; }).concat([day]).slice(-31);
    }

    function evaluate(now) {
      var made = [];
      var s = load();
      if (s.off) return made;
      if (s.quiet_until && now < s.quiet_until) return made;      // backing off after offers left alone
      if (Object.keys(quiet).some(function (q) { return quiet[q]; })) return made;
      var changed = false;
      for (var i = 0; i < list.length; i++) {
        var sc = list[i];
        if (fired[sc.id]) continue;
        if (sc.detector !== "idle-after-landing" && now - view.start < policy(opts, "HELP_LANDING_QUIET_MS")) continue;
        var fn = detectors[sc.detector];
        if (!fn) continue;
        var hit = fn(events, now, sc, view);
        if (!hit || !hit.fire) continue;
        // busy (an offer is up, or this view's budget is spent): not spent, it may fire again later
        if (open.length >= policy(opts, "HELP_PILLS_AT_ONCE")) continue;
        if (offered >= policy(opts, "HELP_OFFERS_PER_VIEW")) continue;
        if (open.some(function (o) { return o.topic === sc.topic; })) continue;
        fired[sc.id] = true;
        noteRecurrence(s, sc, now);
        changed = true;
        if (!allowed(s, sc, now)) continue;
        // an offer points at the scenario's target, or else at the topic's first target
        var shown = topic(opts.pack, opts.page, sc.topic, ctx);
        var o = { scenario: sc.id, topic: sc.topic, target: sc.target || (shown && shown.targets[0]) || null,
                  detector: sc.detector, evidence: hit.evidence || {}, t: now };
        rec(s, sc.topic).last_offer = now;
        open.push(o);
        offered += 1;
        made.push(o);
      }
      if (changed || made.length) save(s);
      made.forEach(function (o) { emit("offer", o); });
      return made;
    }

    var api = {
      ctx: ctx,
      view: view,
      scenarios: function () { return list.slice(); },
      feed: function (e) {
        var ev = Object.assign({}, e);
        if (typeof ev.t !== "number") ev.t = clock();
        if (ev.kind === "nav") {                          // the last few page loads, kept apart and never trimmed by age
          view.navs.push(ev);
          view.navs.sort(function (a, b) { return a.t - b.t; });
          if (view.navs.length > NAVS_KEPT) view.navs.splice(0, view.navs.length - NAVS_KEPT);
          return evaluate(ev.t);
        }
        var i = events.length;                            // events arrive in order nearly always: insert from the end
        while (i > 0 && events[i - 1].t > ev.t) i--;
        events.splice(i, 0, ev);
        var newest = events[events.length - 1].t, cut = 0;
        while (cut < events.length && events[cut].t < newest - keep) cut++;
        if (events.length - cut > policy(opts, "HELP_EVENTS_MAX")) cut = events.length - policy(opts, "HELP_EVENTS_MAX");
        if (cut) events.splice(0, cut);
        return evaluate(ev.t);
      },
      tick: function (now) { return evaluate(typeof now === "number" ? now : clock()); },
      on: function (kind, fn) { listeners[kind].push(fn); return function () { listeners[kind] = listeners[kind].filter(function (f) { return f !== fn; }); }; },
      open: function () { return open.slice(); },
      // what became of an offer: "opened", "ignored" (it faded), "dismissed" (closed without reading), or
      // "withdrawn" (a quiet zone began while it was up: the first time in a view it counts against nothing
      // and the offer may come back; a second time it is settled as "ignored")
      settle: function (topicId, outcome) {
        var o = open.filter(function (x) { return x.topic === topicId; })[0];
        open = open.filter(function (x) { return x.topic !== topicId; });
        var s = load(), r = rec(s, topicId), now = clock();
        // a withdrawn offer may come back once a view; withdrawn again, it counts as left alone
        if (outcome === "withdrawn" && o && (withdrawn[o.scenario] = (withdrawn[o.scenario] || 0) + 1) > 1) outcome = "ignored";
        if (outcome === "ignored") {
          r.ignores = (r.ignores || 0) + 1;
          if (r.ignores >= policy(opts, "HELP_IGNORES_TO_SNOOZE")) { r.snooze_until = now + policy(opts, "HELP_SNOOZE_MS"); r.ignores = 0; }
          // and across topics: offers left alone in a row make the whole engine back off, longer each time
          s.ignored_run = (s.ignored_run || 0) + 1;
          if (s.ignored_run >= policy(opts, "HELP_BACKOFF_IGNORES")) {
            s.backoff = (s.backoff || 0) + 1;
            s.quiet_until = now + Math.min(policy(opts, "HELP_BACKOFF_MAX_MS"), policy(opts, "HELP_BACKOFF_MS") * Math.pow(2, s.backoff - 1));
            s.ignored_run = 0;
          }
        } else if (outcome === "opened") { r.ignores = 0; s.ignored_run = 0; s.backoff = 0; s.quiet_until = 0; }
        else if (outcome === "withdrawn") {
          delete r.last_offer;
          offered = Math.max(0, offered - 1);
          if (o) fired[o.scenario] = false;
        }
        save(s);
        emit("settle", { topic: topicId, outcome: outcome, offer: o || null });
      },
      // the person read the topic (the box was open HELP_READ_MS, or a tour or video got halfway)
      read: function (topicId) {
        var t = topic(opts.pack, opts.page, topicId, ctx);
        var s = load(), r = rec(s, topicId);
        r.read_at = clock();
        r.read_rev = t ? t.rev : 1;
        r.recur = [];
        save(s);
      },
      snooze: function (topicId) {                      // NOT NOW
        var s = load();
        rec(s, topicId).snooze_until = clock() + policy(opts, "HELP_SNOOZE_MS");
        save(s);
        api.settle(topicId, "dismissed");
      },
      offersOff: function (off) {                       // STOP OFFERING HELP (true) and back (false)
        var s = load();
        if (off === undefined) return !!s.off;
        s.off = !!off;
        save(s);
        if (s.off) open.slice().forEach(function (o) { api.settle(o.topic, "dismissed"); });
        return s.off;
      },
      // a quiet zone (a dialog, the band asking, typing): no offers while any is on, and turning one on
      // withdraws the offers that are up
      quiet: function (name, on) {
        if (on === undefined) return !!quiet[name];
        quiet[name] = !!on;
        if (quiet[name]) open.slice().forEach(function (o) { api.settle(o.topic, "withdrawn"); });
        return quiet[name];
      },
      size: function () { return { events: events.length, navs: view.navs.length }; },
      watched: function (detectorName) {
        return list.filter(function (s) { return s.detector === detectorName && s.target; }).map(function (s) { return s.target; })
          .filter(function (t, i, a) { return a.indexOf(t) === i; });
      },
      state: function () { return load(); }
    };
    return api;
  }

  // ── the director ─────────────────────────────────────────────────────────────────────────

  function words(text) { var w = String(text).trim().split(/\s+/); return w[0] === "" ? 0 : w.length; }
  function sayMs(text) { return Math.max(C("HELP_SAY_MIN_MS"), C("HELP_SAY_MS_PER_WORD") * words(text)); }
  function holdMs(step) {
    if (typeof step.hold_ms === "number") return step.hold_ms;
    if (step["do"] === "say") return typeof step.ms === "number" ? step.ms : sayMs(step.text);
    return C("HELP_HOLD_MS")[step["do"]] || 0;
  }

  // Wrap words into lines of at most `width`; a word longer than that sits alone on its line.
  function wrap(text, width) {
    var lines = [], line = "";
    String(text).trim().split(/\s+/).forEach(function (w) {
      if (!w) return;
      if (line && (line + " " + w).length > width) { lines.push(line); line = w; } else line = line ? line + " " + w : w;
    });
    if (line) lines.push(line);
    return lines;
  }

  // Cues of at most two lines. Pieces end after . ! ? ; : , or a dash; pieces are joined while
  // the cue still wraps into two lines, and a piece too long for one cue is cut by words.
  function splitCaption(text) {
    var width = C("HELP_CAPTION_LINE");
    var pieces = String(text).trim().split(/(?<=[.!?;:,]|—)\s+/).filter(function (p) { return p; });
    var cues = [], cur = "";
    function fits(s) { return wrap(s, width).length <= 2; }
    function push(s) { if (s) cues.push(wrap(s, width).join("\n")); }
    pieces.forEach(function (p) {
      var next = cur ? cur + " " + p : p;
      if (fits(next)) { cur = next; return; }
      push(cur);
      cur = "";
      if (fits(p)) { cur = p; return; }
      var lines = wrap(p, width);                        // too long alone: two lines at a time
      for (var i = 0; i < lines.length; i += 2) {
        var chunk = lines.slice(i, i + 2).join(" ");
        if (i + 2 >= lines.length) cur = chunk; else push(chunk);
      }
    });
    push(cur);
    return cues;
  }

  function directorProblems(doc) {
    var out = bollardeck.schema.validate("help-director", doc);
    if (out.length) return out;
    var max = C("HELP_SAY_MAX_CHARS");
    doc.steps.forEach(function (s, i) {
      var at = "/steps/" + i;
      if (s["do"] === "say" && s.text.length > max) out.push(problem(at + "/text", "is longer than " + max + " characters", "say-length"));
      if (s.pop === "@say") {
        var rest = doc.steps.slice(i + 1), j = 0;
        while (j < rest.length && rest[j]["do"] !== "say" && rest[j]["do"] !== "spot" && rest[j]["do"] !== "hide") j++;
        if (j >= rest.length || rest[j]["do"] !== "say") out.push(problem(at + "/pop", "@say needs a say step before the next spot or hide", "pop"));
      }
    });
    var length = timeline(doc, "capture").reduce(function (a, s) { return a + (s["do"] === "cut" ? 0 : s.hold + (s["do"] === "wait" && typeof s.ms === "number" ? s.ms : 0)); }, 0);
    if (length > C("HELP_SCRIPT_MAX_MS")) out.push(problem("/steps", "runs " + length + " ms, more than " + C("HELP_SCRIPT_MAX_MS"), "length"));
    return out;
  }

  function director(doc) {
    var p = directorProblems(doc);
    if (p.length) fail("bollardeck.help.director", p);
    return freeze(copy(doc));
  }

  function timeline(script, mode) {
    var tour = mode === "tour";
    return script.steps.map(function (s, i) { return Object.assign({ index: i, hold: holdMs(s) }, s); })
      .filter(function (s) { return !tour || (!s.capture_only && !VERBS_SKIPPED_IN_TOUR[s["do"]]); });
  }

  // ui: an object with a method per verb (each optional; a missing one is a no-op), called with the
  // step and, for say, its caption cues. opts: mode ("capture" | "tour", default "tour"), clock (ms),
  // sleep(ms) -> Promise, waitFor(until, maxMs) -> Promise<bool>, cut(on) (the recorder stops and
  // starts frames). Resolves to the step log [{index, id, verb, t0, t1}]; a capture rejects on a
  // failed wait whose on_timeout is "fail", naming the step.
  function play(script, ui, opts) {
    opts = opts || {};
    var mode = opts.mode || "tour", clock = opts.clock, sleep = opts.sleep, waitFor = opts.waitFor || function () { return Promise.resolve(true); };
    if (typeof clock !== "function" || typeof sleep !== "function") return Promise.reject(new TypeError("bollardeck.help.play: opts.clock and opts.sleep are required"));
    var steps = timeline(script, mode), log = [], k = 0;
    function call(name, a, b) { return ui && typeof ui[name] === "function" ? ui[name](a, b) : undefined; }
    function next() {
      if (k >= steps.length) return Promise.resolve(log);
      var s = steps[k++], verb = s["do"], t0 = clock();
      var entry = { index: s.index, id: s.id || null, verb: verb, t0: t0, t1: t0 };
      log.push(entry);
      var work;
      if (verb === "wait" || verb === "cut") {
        if (verb === "cut" && opts.cut) opts.cut(true);
        work = (typeof s.ms === "number" && !s.until ? sleep(s.ms).then(function () { return true; }) : waitFor(s.until, s.max_ms || 60000))
          .then(function (ok) {
            if (verb === "cut" && opts.cut) opts.cut(false);
            if (ok) return;
            var how = s.on_timeout || (mode === "capture" ? "fail" : "continue");
            if (how === "fail") throw new Error("bollardeck.help.play: step " + s.index + (s.id ? " (" + s.id + ")" : "") + " waited for " + s.until + " in vain");
          });
      } else {
        work = Promise.resolve(call(verb, s, verb === "say" ? splitCaption(s.text) : undefined));
      }
      return work.then(function () { return s.hold ? sleep(s.hold) : null; })
        .then(function () { entry.t1 = clock(); return next(); });
    }
    return next();
  }

  function stamp(ms) {
    ms = Math.max(0, Math.round(ms));
    var h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60, f = ms % 1000;
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return two(h) + ":" + two(m) + ":" + two(s) + "." + ("00" + f).slice(-3);
  }

  // The span each `verbs` step owns: from its start to the start of the next step that ends it.
  function spans(log, script, verbs, enders) {
    var out = [];
    log.forEach(function (e, i) {
      if (verbs.indexOf(e.verb) < 0) return;
      var end = log[log.length - 1].t1;
      for (var j = i + 1; j < log.length; j++) if (enders.indexOf(log[j].verb) >= 0) { end = log[j].t0; break; }
      out.push({ step: script.steps[e.index], start: e.t0, end: end });
    });
    return out;
  }

  function vtt(log, script) {
    var lines = ["WEBVTT", ""];
    spans(log, script, ["say"], ["say", "hide", "chapter"]).forEach(function (sp) {
      var cues = splitCaption(sp.step.text), total = cues.reduce(function (a, c) { return a + c.length; }, 0), at = sp.start;
      cues.forEach(function (c) {
        var len = (sp.end - sp.start) * c.length / total;
        lines.push(stamp(at) + " --> " + stamp(at + len), c, "");
        at += len;
      });
    });
    return lines.join("\n");
  }

  function chaptersVtt(log, script) {
    var lines = ["WEBVTT", ""];
    spans(log, script, ["chapter"], ["chapter"]).forEach(function (sp) { lines.push(stamp(sp.start) + " --> " + stamp(sp.end), sp.step.title, ""); });
    return lines.join("\n");
  }

  function readText(script) {
    var out = [], cur = null;
    script.steps.forEach(function (s) {
      if (s["do"] === "chapter") { cur = { chapter: s.title, text: "" }; out.push(cur); }
      if (s["do"] !== "say") return;
      if (!cur) { cur = { chapter: null, text: "" }; out.push(cur); }
      cur.text = cur.text ? cur.text + " " + s.text : s.text;
    });
    return out.filter(function (c) { return c.text; });
  }

  function lintDirector(script, manifest, signals) {
    var out = [], known = (manifest[script.page] || {})[script.role];
    if (!known) return [problem("/page", "the manifest has no " + script.page + " for " + script.role, "page")];
    script.steps.forEach(function (s, i) {
      if (s.target && known.indexOf(s.target) < 0) out.push(problem("/steps/" + i + "/target", s.target + " is not on " + script.page + " for " + script.role, "target"));
      var u = s.until || "";
      if (u.indexOf("visible:") === 0 && known.indexOf(u.slice(8)) < 0) out.push(problem("/steps/" + i + "/until", u.slice(8) + " is not on the page", "target"));
      if (u.indexOf("signal:") === 0 && signals && signals.indexOf(u.slice(7)) < 0) out.push(problem("/steps/" + i + "/until", "no such signal: " + u.slice(7), "signal"));
    });
    return out;
  }

  var api = {
    FORMATS: { pack: "help-pack/1", director: "help-director/1" },
    problems: packProblems, pack: pack, merge: merge, matches: matches, topic: topic, intro: intro,
    scenarios: scenarios, lint: lint, detectors: detectors, detector: detector, engine: engine,
    memoryStore: memoryStore, sayMs: sayMs, holdMs: holdMs, splitCaption: splitCaption,
    directorProblems: directorProblems, director: director, timeline: timeline, play: play,
    vtt: vtt, chaptersVtt: chaptersVtt, readText: readText, lintDirector: lintDirector
  };

  bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var help = bollardeck.help || (bollardeck.help = {});
  Object.keys(api).forEach(function (k) { help[k] = api[k]; });
  (bollardeck.parts || (bollardeck.parts = {})).help = true;
  if (typeof module === "object" && module.exports) module.exports = help;
})(typeof globalThis !== "undefined" ? globalThis : this);
