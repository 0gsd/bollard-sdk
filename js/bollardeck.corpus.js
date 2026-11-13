// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.corpus: read a corpus the way the platform does, respecting its licence and settings.
 *
 * Two things: the gate, and a hub client for a page.
 *
 * THE GATE is the twin of python/bollardeck/corpus/gate.py, held to conformance/corpus-gate/. It is
 * the one decision "may this caller do this with this corpus, now?":
 *
 *   var verdict = bollardeck.corpus.judge(manifest, "study", {email: "ada@example.org"}, Date.now() / 1000);
 *   verdict.allowed, verdict.reason, verdict.detail
 *
 * judge(manifest, capability, identity, now, standing) never throws and fails closed: anything it
 * cannot read, does not know or is not sure of is a refusal with a reason. The checks, in order
 * (the first that fails is the reason): bad_clock, unknown_capability, manifest_invalid,
 * licence_ambiguous, unknown_scope, newer_version, withdrawn, not_visible (the capability "see"
 * is decided here), licence_missing, licence_invalid, revoked, expired, not_granted, allowed.
 *
 *   capability  transcode, store_audio, stream_audio, store_art, store_morpus,
 *               musicians_may_study (short name: study), export_morpus, device_copies, see
 *   identity    {email, service, player, device}; absent is nobody. service: true is the
 *               platform's own engine and is never set for a person
 *   now         seconds since the epoch, a UTC time string, or a Date; absent is this machine's clock
 *   standing    {source, revalidated_at, reachable, withdrawn, witnessed_at}: how fresh the
 *               manifest is. Absent is "local": the manifest is the truth and the clock applies.
 *               For a cache, the gate reads no time earlier than revalidated_at or witnessed_at
 *               (the latest time the cache has seen on its own clock), so a clock that is set
 *               back does not reopen a licence that has closed
 *
 * A verdict is frozen: {allowed, reason, capability, corpusId, detail, scope, checkedAt,
 * unverifiedSince, pending, validUntil}, times in seconds since the epoch. verdict.asDict() gives
 * the Python names with times as UTC strings. Only the gate makes one: isVerdict(v) tells.
 *
 * THE HUB CLIENT speaks to a Bollawax hub with fetch. It mirrors the read methods of Python's
 * HubClient:
 *
 *   var hub = bollardeck.corpus.hub({baseUrl: "https://bollawax.org", token: getToken, actingFor: "ada@example.org"});
 *   hub.listing({actingFor}) -> Promise of rows (forEmail is the older name for actingFor)
 *   hub.version() -> Promise of what the hub says about itself
 *   hub.corpusGate() -> Promise of "enforce", "report" or null: the hub's rollout switch, the
 *       corpus_gate member of /api/version. Information only: this gate always enforces
 *   hub.corpus("9001-PLACEHOLDERS", {actingFor}) -> Promise of a corpus:
 *       corpus.id .number .slug .name .artist .displayLabel .description .editionLabel .visibility
 *       corpus.manifest()                     a copy of the manifest
 *       corpus.licence()                      the licence on paper (status, scope, flags, times)
 *       corpus.notices()                      the attribution a client must show
 *       corpus.may(capability, identity, now) -> verdict, from what is in hand
 *       corpus.check(capability, identity)    -> Promise of a verdict, revalidating first when stale
 *       corpus.refresh()                      -> Promise: revalidate against the hub now
 *       corpus.tracks(verdict)                -> Promise of the recordings; needs an allowed,
 *                                                current verdict for "stream_audio"
 *
 * What it will and will not do:
 *   - The token and the identity are the caller's. `token` is a string or a function that
 *     returns one (or a promise of one), asked at each request. Nothing is written to cookies,
 *     localStorage or any other storage, and the token is not readable from the returned object.
 *   - Who it acts for. A hub's read token alone is study only for a corpus that is
 *     not public: the hub gives such a caller a manifest with the people taken out and answers
 *     404 for tracks, audio, art and bundles. Name the person the page acts for with actingFor
 *     (on the client, or per call; "" is nobody). It is sent in the header X-Pop-For and never
 *     in a URL. The name is what the caller says: the hub checks nothing until sign-in arrives.
 *     A request made in a person's name is sent with cache: "no-store", and the hub must answer
 *     corpus routes with Vary: X-Pop-For, Authorization and no shared caching.
 *   - Errors say why: CorpusUnavailable has .reason ("bad_id", "not_served", "unreachable") and
 *     .status; NotAvailable has .reason ("not_found", "unreachable", "not_licensed",
 *     "bad_answer") and .status; HubError and HubUnreachable have .status (null: no answer).
 *   - It asks only its own hub. With no baseUrl it uses the page's origin; any other host has to
 *     be given as baseUrl. Every request and every URL a listing returns is checked against that
 *     origin, a redirect is refused (fetch cannot check one before following it), and a token is
 *     not sent over plain http except to this machine.
 *   - Not in JavaScript this round: a disk cache (every corpus() is a request, and a corpus the
 *     hub cannot be reached for is unavailable unless it is already in hand), attestation
 *     verification, origin discovery, morpus and audio bytes, and the image release record. Use
 *     the Python client for those.
 */
(function (root) {
  "use strict";

  var bollardeck;                   // set at the bottom of this file
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function schema() {
    if (!bollardeck.schema) throw new Error("bollardeck.corpus needs bollardeck.schema (load bollardeck.schema.js and bollardeck.schemas.js)");
    return bollardeck.schema;
  }
  function freeze(v) {
    if (v && typeof v === "object" && !Object.isFrozen(v)) { Object.keys(v).forEach(function (k) { freeze(v[k]); }); Object.freeze(v); }
    return v;
  }
  function copy(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
  // What Python's str.strip() removes.
  var WS = "[\\t-\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]+";
  var STRIP_RE = new RegExp("^" + WS + "|" + WS + "$", "g");
  function strip(s) { return s.replace(STRIP_RE, ""); }

  // ── the licence block (popboll.licence/1) ───────────────────────────────────────────────

  var VERSION = 1;
  var CAPABILITIES = ["transcode", "store_audio", "stream_audio", "store_art", "store_morpus",
    "musicians_may_study", "export_morpus", "device_copies", "stream_render"];
  // [A, B]: A is on only while B is on.
  var IMPLIES = [["stream_audio", "store_audio"], ["musicians_may_study", "store_morpus"], ["export_morpus", "store_morpus"]];
  function all(on, off) {
    var out = {};
    CAPABILITIES.forEach(function (k) { out[k] = on; });
    (off || []).forEach(function (k) { out[k] = false; });
    return out;
  }
  // scope -> [defaults, hard limits nothing in the block can override]
  var SCOPES = {
    __proto__: null,
    full: [all(true, ["stream_render"]), {}],
    morpus_only: [all(true, ["store_audio", "stream_audio", "store_art", "export_morpus", "stream_render"]), { store_audio: false, stream_audio: false }],
    public_domain_midi: [all(true, ["transcode", "store_audio", "stream_audio", "store_art"]), { store_audio: false, stream_audio: false }]
  };
  var OK = "ok", MISSING = "missing", INVALID = "invalid", UNKNOWN_SCOPE = "unknown_scope", NEWER_VERSION = "newer_version";
  var TIME_RE = /^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])(?:T([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])(\.[0-9]+)?Z?)?$/;

  function BadTime(message) { this.name = "BadTime"; this.message = message; }
  BadTime.prototype = Object.create(Error.prototype);

  // Seconds since the epoch for a licence time; null for null or "". Throws BadTime.
  function parseTime(text) {
    if (text === null || text === undefined || text === "") return null;
    if (typeof text !== "string") throw new BadTime("a time is a string, not " + JSON.stringify(text));
    var m = TIME_RE.exec(text);
    if (!m) throw new BadTime(JSON.stringify(text) + " is not a UTC time (YYYY-MM-DDTHH:MM:SS[.fff][Z] or YYYY-MM-DD; no offsets)");
    var year = +m[1], month = +m[2], day = +m[3];
    if (year < 1) throw new BadTime(JSON.stringify(text) + " is not a real date");
    var d = new Date(Date.UTC(2000, month - 1, 1, +(m[4] || 0), +(m[5] || 0), +(m[6] || 0)));
    d.setUTCFullYear(year);                       // Date.UTC would read years 0 to 99 as 1900 to 1999
    d.setUTCDate(day);
    if (d.getUTCMonth() !== month - 1) throw new BadTime(JSON.stringify(text) + " is not a real date");
    return d.getTime() / 1000 + (m[7] ? parseFloat(m[7]) : 0);
  }

  // A moment as the licence format writes it, to the second: 2031-02-03T04:05:06Z.
  function formatTime(ts) {
    return new Date(Math.floor(ts) * 1000).toISOString().slice(0, 19) + "Z";
  }

  // `when` as seconds since the epoch: absent is now, a number is itself, a string is parsed.
  function toEpoch(when, clock) {
    if (when === null || when === undefined) when = (clock || function () { return Date.now() / 1000; })();
    if (when instanceof Date) when = when.getTime() / 1000;
    if (typeof when === "number" && when === when) return when;
    var ts = typeof when === "string" ? parseTime(when) : null;
    if (ts === null) throw new BadTime("a clock is a number or a UTC time string");
    return ts;
  }

  function resolveFlags(scope, block) {
    var flags = {}, defaults = SCOPES[scope][0], fixed = SCOPES[scope][1];
    CAPABILITIES.forEach(function (k) { flags[k] = typeof block[k] === "boolean" ? block[k] : defaults[k]; });
    Object.keys(fixed).forEach(function (k) { flags[k] = fixed[k]; });
    IMPLIES.forEach(function (p) { if (flags[p[0]] && !flags[p[1]]) flags[p[0]] = false; });
    return flags;
  }

  function makeLicence(status, scope, version, flags, revokedAt, expiresAt, problems, block) {
    var lic = {
      status: status, scope: scope || "", version: version === undefined ? VERSION : version,
      flags: status === OK && flags ? flags : all(false),
      revokedAt: revokedAt === undefined ? null : revokedAt, expiresAt: expiresAt === undefined ? null : expiresAt,
      problems: problems || [],
      // What the block says on paper. Not an answer to "may I": ask the gate.
      grants: function (capability) { return has(lic.flags, capability) && lic.flags[capability] === true; },
      // Why a capability of an OK block is off, in words a UI can show.
      whyOff: function (capability) {
        if (status !== OK || CAPABILITIES.indexOf(capability) < 0 || lic.flags[capability]) return "";
        var defaults = SCOPES[scope][0], fixed = SCOPES[scope][1];
        if (has(fixed, capability)) return "scope " + scope + " never allows " + capability;
        var explicit = isObject(block) && has(block, capability) ? block[capability] : null;
        if (explicit === false) return "the licence switches " + capability + " off";
        if (!defaults[capability] && explicit === null) return "scope " + scope + " does not include " + capability;
        for (var i = 0; i < IMPLIES.length; i++) {
          if (IMPLIES[i][0] === capability && !lic.flags[IMPLIES[i][1]]) return capability + " needs " + IMPLIES[i][1] + ", which is off";
        }
        return capability + " is off";
      },
      summary: function () {
        var out = { status: lic.status, scope: lic.scope, version: lic.version };
        CAPABILITIES.forEach(function (k) { out[k] = lic.flags[k] === true; });
        out.revoked_at = lic.revokedAt !== null ? formatTime(lic.revokedAt) : null;
        out.expires_at = lic.expiresAt !== null ? formatTime(lic.expiresAt) : null;
        return out;
      }
    };
    return freeze(lic);
  }

  // Read a licence block. Never throws: a block that cannot be read is a closed licence.
  function licence(block) {
    if (block === null || block === undefined) return makeLicence(MISSING, "", VERSION, null, null, null, ["the corpus has no licence block"]);
    var problems = schema().validate("licence", block);
    if (problems.length) {
      var said = problems.map(String);
      if (isObject(block)) {
        var scope = block.scope, version = has(block, "version") ? block.version : VERSION;
        if (typeof scope !== "string" || !SCOPES[scope]) return makeLicence(UNKNOWN_SCOPE, typeof scope === "string" ? scope : "", VERSION, null, null, null, said, block);
        if (typeof version === "number" && version > VERSION) return makeLicence(NEWER_VERSION, scope, Math.trunc(version), null, null, null, said, block);
        return makeLicence(INVALID, scope, VERSION, null, null, null, said, block);
      }
      return makeLicence(INVALID, "", VERSION, null, null, null, said);
    }
    var revoked, expires;
    try {
      revoked = parseTime(block.revoked_at);
      expires = parseTime(block.expires_at);
    } catch (e) {
      return makeLicence(INVALID, block.scope, VERSION, null, null, null, [e.message], block);
    }
    return makeLicence(OK, block.scope, has(block, "version") ? Math.trunc(block.version) : VERSION, resolveFlags(block.scope, block), revoked, expires, [], block);
  }

  // ── the gate ───────────────────────────────────────────────────────────────────────────

  var SEE = "see", ALLOWED = "allowed";
  var ALL_CAPABILITIES = CAPABILITIES.concat([SEE]);
  var REASONS = ["bad_clock", "unknown_capability", "manifest_invalid", "licence_ambiguous", "unknown_scope", "newer_version",
    "withdrawn", "not_visible", "licence_missing", "licence_invalid", "revoked", "expired", "not_granted", ALLOWED];
  var DETAIL = {
    __proto__: null,
    licence_missing: "this corpus has no licence block, so nothing is allowed",
    licence_ambiguous: 'the manifest carries two different licence blocks ("licence" and "license")',
    unknown_scope: "the licence names a scope this software does not know",
    newer_version: "the licence is a newer version than this software understands",
    withdrawn: "the hub no longer serves this corpus to this client",
    not_visible: "this corpus is private and you are not on its access list"
  };
  var VERDICT_TTL_SEC = 900;

  // The capability's canonical name ("study" is "musicians_may_study"), or null.
  function canonicalCapability(capability) {
    if (typeof capability !== "string") return null;
    var name = capability === "study" ? "musicians_may_study" : capability;
    return ALL_CAPABILITIES.indexOf(name) >= 0 ? name : null;
  }

  function normEmail(email) { return typeof email === "string" ? strip(email).toLowerCase() : ""; }

  function readIdentity(data) {
    data = isObject(data) ? data : {};
    return { email: normEmail(data.email), service: data.service === true, player: String(data.player || ""), device: String(data.device || "") };
  }

  // Throws BadTime when revalidated_at or witnessed_at cannot be read.
  function readStanding(data) {
    data = isObject(data) ? data : {};
    var at = has(data, "revalidatedAt") ? data.revalidatedAt : data.revalidated_at;
    if (at instanceof Date) at = at.getTime() / 1000;
    var seen = has(data, "witnessedAt") ? data.witnessedAt : data.witnessed_at;
    if (seen instanceof Date) seen = seen.getTime() / 1000;
    var s = { source: String(data.source || "local"), revalidatedAt: typeof at === "number" && at === at ? at : parseTime(at),
              reachable: data.reachable !== false, withdrawn: data.withdrawn === true,
              witnessedAt: typeof seen === "number" && seen === seen ? seen : parseTime(seen) };
    s.unverified = s.source !== "local" && !s.reachable;
    // The earliest "now" the gate will believe: the latest time this cache has witnessed.
    s.floor = s.source === "local" ? null : [s.revalidatedAt, s.witnessedAt].reduce(function (best, v) {
      return v !== null && (best === null || v > best) ? v : best;
    }, null);
    return s;
  }

  // JSON equality as Python's dict equality reads it: key order does not matter.
  function sameJson(a, b) {
    if (Array.isArray(a) || Array.isArray(b)) {
      return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every(function (x, i) { return sameJson(x, b[i]); });
    }
    if (isObject(a) || isObject(b)) {
      if (!isObject(a) || !isObject(b)) return false;
      var ka = Object.keys(a);
      return ka.length === Object.keys(b).length && ka.every(function (k) { return has(b, k) && sameJson(a[k], b[k]); });
    }
    return a === b;
  }

  function pad4(n) {
    var s = String(Math.trunc(n));
    while (s.length < 4) s = "0" + s;
    return s;
  }

  // Read a manifest for the gate: either refused whole (refusal is a reason), or its licence and
  // settings. Never throws, never reads part of a manifest that fails.
  function readManifest(manifest) {
    var closed = licence(null);
    var cid = isObject(manifest) && typeof manifest.id === "string" ? manifest.id : "";
    function reading(refusal, problems, lic, visibility, owner, access) {
      return freeze({ corpusId: cid, refusal: refusal, problems: problems, licence: lic,
                      visibility: visibility || "public", ownerEmail: owner || "", access: access || [] });
    }
    var problems = schema().validate("corpus-manifest", manifest);
    if (problems.length) {
      var reason = "manifest_invalid";
      if (isObject(manifest)) {
        // Say the more useful thing when the only trouble is a licence from the future.
        var statuses = ["licence", "license"].filter(function (k) { return isObject(manifest[k]); })
          .map(function (k) { return licence(manifest[k]).status; });
        var elsewhere = problems.filter(function (p) { return p.pointer.indexOf("/licence") !== 0 && p.pointer.indexOf("/license") !== 0; });
        if (!elsewhere.length) {
          if (statuses.indexOf(UNKNOWN_SCOPE) >= 0) reason = UNKNOWN_SCOPE;
          else if (statuses.indexOf(NEWER_VERSION) >= 0) reason = NEWER_VERSION;
        }
      }
      return reading(reason, problems.map(String), closed);
    }
    if (manifest.id !== pad4(manifest.number) + "-" + manifest.slug) {
      return reading("manifest_invalid", ["#/id: " + JSON.stringify(manifest.id) + " is not number " + manifest.number + " and slug " + JSON.stringify(manifest.slug) + " joined"], closed);
    }
    var main = has(manifest, "licence") ? manifest.licence : null;
    var alias = has(manifest, "license") && isObject(manifest.license) ? manifest.license : null;   // "license": "CC BY" is a note, not a block
    if (main !== null && alias !== null && !sameJson(main, alias)) {
      return reading("licence_ambiguous", ['#/license: "licence" and "license" are both licence blocks and differ'], closed);
    }
    return reading(null, [], licence(main !== null ? main : alias), has(manifest, "visibility") ? manifest.visibility : "public",
      normEmail(manifest.owner_email), (has(manifest, "access") ? manifest.access : []).map(normEmail));
  }

  var verdicts = new WeakMap();     // every verdict the gate made -> the reading and standing it was made from

  function makeVerdict(reason, capability, reading, detail, scope, checkedAt, unverifiedSince, pending, validUntil, standingKey) {
    var v = {
      allowed: reason === ALLOWED, reason: reason, capability: capability, corpusId: reading ? reading.corpusId : "",
      detail: detail, scope: scope, checkedAt: checkedAt,
      unverifiedSince: unverifiedSince === undefined ? null : unverifiedSince,
      pending: pending === undefined ? null : pending, validUntil: validUntil === undefined ? null : validUntil,
      // Plain values for a UI or a log, with the Python binding's names. Times are UTC strings.
      asDict: function () {
        return { allowed: v.allowed, reason: v.reason, capability: v.capability, corpus_id: v.corpusId, detail: v.detail, scope: v.scope,
                 checked_at: formatTime(v.checkedAt), unverified_since: v.unverifiedSince !== null ? formatTime(v.unverifiedSince) : null,
                 pending: v.pending };
      },
      toString: function () { return "Verdict(" + (v.allowed ? "allowed " : "refused ") + v.capability + " on " + (v.corpusId || "?") + ": " + v.reason + ")"; }
    };
    Object.freeze(v);
    verdicts.set(v, { reading: reading, standingKey: standingKey || "" });
    return v;
  }

  // Did the gate make this verdict? A look-alike object is not one.
  function isVerdict(v) { return isObject(v) && verdicts.has(v); }

  // The decision for a manifest already read (readManifest). Never throws.
  function decide(reading, capability, identity, now, standing, clock) {
    var who = readIdentity(identity), t, st;
    try {
      t = toEpoch(now, clock);
      st = readStanding(standing);
    } catch (e) {
      return makeVerdict("bad_clock", String(capability), reading, "the clock given to the gate is not a UTC time", "", 0);
    }
    var cap = canonicalCapability(capability), lic = reading.licence;
    var unverified = st.unverified ? st.revalidatedAt : null;
    var key = [st.source, st.revalidatedAt, st.reachable, st.withdrawn].join("|");
    function answer(reason, detail, pending, validUntil) {
      return makeVerdict(reason, cap || String(capability), reading, detail || DETAIL[reason] || "", lic.scope, checkedAt, unverified, pending, validUntil, key);
    }
    var checkedAt = t;
    if (cap === null) return answer("unknown_capability", JSON.stringify(capability) + " is not a capability (known: " + ALL_CAPABILITIES.join(", ") + ")");
    if (reading.refusal) return answer(reading.refusal, reading.problems.slice(0, 3).join("; "));
    if (st.withdrawn) return answer("withdrawn");
    if (reading.visibility !== "public" && !who.service) {
      if (!who.email || (who.email !== reading.ownerEmail && reading.access.indexOf(who.email) < 0)) return answer("not_visible");
    }
    if (cap === SEE) return answer(ALLOWED);
    if (lic.status === MISSING) return answer("licence_missing");
    if (lic.status !== OK) {
      return answer(lic.status === UNKNOWN_SCOPE || lic.status === NEWER_VERSION ? lic.status : "licence_invalid", lic.problems.slice(0, 3).join("; "));
    }
    var pending = null, closes = [[lic.revokedAt, "revoked"], [lic.expiresAt, "expired"]];
    if (st.floor !== null && st.floor > t) t = st.floor;        // the clock was set back: time does not run backwards here
    for (var i = 0; i < closes.length; i++) {
      var moment = closes[i][0], name = closes[i][1];
      if (moment === null || moment > t) continue;
      var knownOnline = st.revalidatedAt === null || moment <= st.revalidatedAt;
      // An expiry is a date the device holds: its own clock applies it, online or not.
      if (name === "expired" || !st.unverified || knownOnline) {
        return answer(name, "the licence " + (name === "revoked" ? "was revoked" : "expired") + " at " + formatTime(moment));
      }
      pending = pending || name;
    }
    if (!lic.grants(cap)) return answer("not_granted", lic.whyOff(cap));
    var ahead = closes.map(function (c) { return c[0]; }).filter(function (m) { return m !== null && m > t; });
    return answer(ALLOWED, pending ? "the licence's revocation date passed while this device was offline; it keeps working until the hub is reached" : "",
      pending, ahead.length ? Math.min.apply(null, ahead) : null);
  }

  // The gate, for a manifest. Never throws; refuses what it cannot read.
  // May this listener hear the corpus? A recording needs stream_audio; a render of its MIDI through Pop
  // Boll's own sounds (render true, never a recording) needs stream_render.
  function listen(manifest, identity, render, now, standing) {
    return judge(manifest, render ? "stream_render" : "stream_audio", identity, now, standing);
  }

  function judge(manifest, capability, identity, now, standing) {
    return decide(readManifest(manifest), capability, identity, now, standing);
  }

  // The attribution a client must show with anything made from or played out of a corpus: the
  // edition label, the corpus's own notice and each MIDI source's attribution. `lines` is the
  // same, ready to print. For a manifest that passed readManifest.
  function editionLabel(manifest) {
    return manifest.edition || "PB " + pad4(manifest.number) + " \u2014 " + manifest.slug + " Edition";
  }
  function notices(manifest) {
    var attributions = [], seen = [], lines;
    (manifest.midi_sources || []).forEach(function (row) {
      var text = strip(row.attribution || "");
      if (!text) return;
      attributions.push({ file: row.file || "", title: row.title || "", attribution: text, source_url: row.source_url || "", source_licence: row.source_licence || "" });
      if (seen.indexOf(text) < 0) seen.push(text);
    });
    var note = strip(manifest.license_note || "");
    lines = [editionLabel(manifest)].concat(note ? [note] : [], seen);
    return { corpus_id: manifest.id, artist: manifest.artist, edition: editionLabel(manifest), license_note: note, attributions: attributions, lines: lines };
  }

  // ── errors ─────────────────────────────────────────────────────────────────────────────

  function errorType(name, parent) {
    function E(message, extra) {
      this.name = name;
      this.message = message;
      if (extra) for (var k in extra) if (has(extra, k)) this[k] = extra[k];
      if (Error.captureStackTrace) Error.captureStackTrace(this, E); else this.stack = (new Error(message)).stack;
    }
    E.prototype = Object.create((parent || Error).prototype);
    E.prototype.constructor = E;
    return E;
  }
  var HubError = errorType("HubError");                           // the hub answered, and the answer cannot be used: .status
  var HubUnreachable = errorType("HubUnreachable", HubError);     // the hub did not answer (.status null), or would not talk just now
  var CorpusUnavailable = errorType("CorpusUnavailable");         // the corpus is not on the hub: .reason, .status
  var ManifestRefused = errorType("ManifestRefused");             // a manifest the SDK will not read: .reason, .problems
  var GateRequired = errorType("GateRequired");                   // content asked for without an allowed, current verdict
  var NotAvailable = errorType("NotAvailable");                   // the gate allowed it and the hub has nothing of that kind: .reason, .status
  HubError.prototype.status = null;
  CorpusUnavailable.prototype.status = NotAvailable.prototype.status = null;
  CorpusUnavailable.prototype.reason = "unreachable";
  NotAvailable.prototype.reason = "not_found";

  // The name of the person a client acts for, as it is sent in X-Pop-For: trimmed and
  // lower-cased, "" for nobody. A RangeError for a name that cannot be a header value.
  function person(value) {
    var name = normEmail(value);
    if (value !== null && value !== undefined && typeof value !== "string") {
      throw new RangeError("the person a client acts for is a string (an address), not " + JSON.stringify(value));
    }
    if (!/^[\x21-\x7e]{0,320}$/.test(name)) throw new RangeError(JSON.stringify(value) + " cannot be sent as the person a client acts for (printable ASCII, no spaces)");
    return name;
  }

  // ── the hub client ─────────────────────────────────────────────────────────────────────

  var CORPUS_ID = /^[0-9]{4}-[A-Za-z0-9_]+$/;
  var MAX_JSON_BYTES = 8 * 1024 * 1024;
  var LOOPBACK = ["localhost", "127.0.0.1", "[::1]", "::1"];

  function safeName(name) {
    return typeof name === "string" && name.length > 0 && name.length <= 255 && name.indexOf("/") < 0 && name.indexOf("\\") < 0 &&
      name.charAt(0) !== "." && !/[\x00-\x1f\x7f]/.test(name);
  }
  function safeRelPath(raw) {
    var rel = typeof raw === "string" ? strip(raw) : "";
    if (!rel || rel.length > 1024 || rel.charAt(0) === "/" || rel.indexOf("\\") >= 0) return "";
    return rel.split("/").every(safeName) ? rel : "";
  }
  function quote(part, keepSlash) {
    var s = encodeURIComponent(part).replace(/[!'()*]/g, function (c) { return "%" + c.charCodeAt(0).toString(16).toUpperCase(); });
    return keepSlash ? s.replace(/%2F/g, "/") : s;
  }
  function count(v, whole) {
    var n = null;
    if (typeof v === "boolean") n = v ? 1 : 0;
    else if (typeof v === "number" && isFinite(v)) n = whole ? Math.trunc(v) : v;
    else if (typeof v === "string" && (whole ? /^\s*[+-]?[0-9]+\s*$/ : /^\s*[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?\s*$/).test(v)) n = +v;
    return n !== null && n >= 0 ? n : null;
  }

  function hub(opts) {
    opts = opts || {};
    var fetchFn = opts.fetch || (typeof root.fetch === "function" ? function (u, o) { return root.fetch(u, o); } : null);
    if (!fetchFn) throw new Error("bollardeck.corpus.hub: no fetch here; pass one as opts.fetch");
    var pageOrigin = root.location && typeof root.location.origin === "string" && root.location.origin !== "null" ? root.location.origin : "";
    var base = strip(String(opts.baseUrl || pageOrigin || "")).replace(/\/+$/, "");
    var at;
    try { at = new URL(base); } catch (e) { at = null; }
    if (!at || (at.protocol !== "http:" && at.protocol !== "https:") || !at.hostname) {
      throw new RangeError("a hub address is http(s)://host[:port], not " + JSON.stringify(opts.baseUrl === undefined ? base : opts.baseUrl));
    }
    var origin = at.origin, host = at.hostname;
    var token = opts.token;                          // held here and nowhere else; never written to any storage
    if (token && at.protocol === "http:" && LOOPBACK.indexOf(host) < 0 && !opts.allowInsecureToken) {
      throw new RangeError("refusing to send a token over plain http to " + host);
    }
    var clock = opts.clock || function () { return Date.now() / 1000; };
    var timeoutMs = opts.timeoutMs === undefined ? 10000 : opts.timeoutMs;
    var revalidateAfter = opts.revalidateAfter === undefined ? 300 : opts.revalidateAfter;
    var stats = { requests: 0, errors: 0 };
    var actingFor = person(opts.actingFor);          // the person this client acts for; "" is nobody
    // The person one call acts for: the call's own (forEmail is the older name), else the client's.
    function who(o) {
      if (o && o.actingFor !== undefined && o.actingFor !== null) return person(o.actingFor);
      if (o && o.forEmail) return person(o.forEmail);
      return actingFor;
    }

    function url(parts, query, keepSlash) {
      var u = base + "/api/" + parts.map(function (p) { return quote(p, keepSlash); }).join("/");
      var q = Object.keys(query || {}).filter(function (k) { return query[k]; })
        .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(query[k]); });
      return u + (q.length ? "?" + q.join("&") : "");
    }

    // An absolute URL on this hub for a reference a listing returned, or null.
    function onHub(ref) {
      ref = typeof ref === "string" ? strip(ref) : "";
      if (!ref) return null;
      if (ref.charAt(0) === "/" && ref.charAt(1) !== "/") ref = base + ref;
      if (!/^https?:\/\//.test(ref)) return null;
      try { return new URL(ref).origin === origin ? ref : null; } catch (e) { return null; }
    }

    // One GET on the hub -> {status, body}. 200, 404 and 410 come back; the hub being down, busy
    // or unwilling (5xx, 401, 403, 429) is HubUnreachable; anything else is HubError.
    function get(target, forWhom) {
      var where;
      try { where = new URL(target); } catch (e) { where = null; }
      if (!where || where.origin !== origin) return Promise.reject(new HubError("refused to ask " + (where ? where.host : target) + ": not this hub"));
      return Promise.resolve(typeof token === "function" ? token() : token).then(function (bearer) {
        var headers = { Accept: "application/json" };
        if (opts.player) headers["X-Pop-Player"] = String(opts.player);
        if (opts.device) headers["X-Pop-Device"] = String(opts.device);
        if (forWhom) headers["X-Pop-For"] = forWhom;             // in a header, never in the URL
        if (bearer) {
          if (at.protocol === "http:" && LOOPBACK.indexOf(host) < 0 && !opts.allowInsecureToken) throw new HubError("refusing to send a token over plain http to " + host);
          headers.Authorization = "Bearer " + bearer;
        }
        var init = { method: "GET", headers: headers, redirect: "error", credentials: opts.credentials || "same-origin" };
        // One URL answers differently for different people: the browser's cache keeps nothing
        // of an answer made in a person's name. (The hub must send Vary: X-Pop-For, Authorization.)
        if (forWhom) init.cache = "no-store";
        var timer = null;
        if (typeof AbortController === "function" && timeoutMs > 0) {
          var abort = new AbortController();
          init.signal = abort.signal;
          timer = setTimeout(function () { abort.abort(); }, timeoutMs);
        }
        stats.requests += 1;
        var done = function () { if (timer !== null) clearTimeout(timer); };
        return Promise.resolve().then(function () { return fetchFn(target, init); }).then(function (resp) {
          var status = resp.status;
          if (resp.url) {
            var came = null;
            try { came = new URL(resp.url).origin; } catch (e) { came = null; }
            if (came !== origin) throw new HubError("refused an answer that came from somewhere other than the hub");
          }
          if (status === 404 || status === 410) return { status: status, body: "" };
          if (status === 401 || status === 403 || status === 429 || status >= 500) { stats.errors += 1; throw new HubUnreachable(host + " answered " + status, { status: status }); }
          if (status !== 200) throw new HubError(host + " answered " + status, { status: status });
          var length = resp.headers && typeof resp.headers.get === "function" ? +resp.headers.get("Content-Length") : 0;
          if (length > MAX_JSON_BYTES) throw new HubError(host + " sent more than " + MAX_JSON_BYTES + " bytes");
          return resp.text().then(function (body) {
            if (body.length > MAX_JSON_BYTES) throw new HubError(host + " sent more than " + MAX_JSON_BYTES + " bytes");
            return { status: 200, body: body };
          }, function (e) { throw new HubUnreachable(host + ": the answer broke off (" + (e && e.message) + ")"); });
        }, function (e) {
          if (e instanceof HubError) throw e;
          stats.errors += 1;
          throw new HubUnreachable(host + " is not answering (" + (e && e.message ? e.message : e) + ")");
        }).then(function (r) { done(); return r; }, function (e) { done(); throw e; });
      });
    }

    function getJson(target, forWhom) {
      return get(target, forWhom).then(function (r) {
        if (r.status !== 200) throw new HubError(host + " answered " + r.status + " for " + new URL(target).pathname, { status: r.status });
        try { return JSON.parse(r.body); } catch (e) { throw new HubError(host + " sent something that is not JSON"); }
      });
    }

    // The hub's corpus listing: one summary row per corpus, as the hub wrote it. For a person
    // (actingFor, or the client's own), only what that person may see; the name goes in
    // X-Pop-For. Rows without a corpus id are dropped.
    function listing(o) {
      var forWhom;
      try { forWhom = who(o); } catch (e) { return Promise.reject(e); }
      return getJson(url(["corpi"]), forWhom).then(function (data) {
        return (Array.isArray(data) ? data : []).filter(function (r) { return isObject(r) && typeof r.id === "string" && CORPUS_ID.test(r.id); });
      });
    }

    function version() {
      return getJson(url(["version"]), "").then(function (data) { return isObject(data) ? data : {}; });
    }

    // The hub's rollout switch, the corpus_gate member of /api/version: "enforce" (the hub
    // refuses what the gate refuses) or "report" (it still answers the old way for a manifest
    // with no licence block, and counts). null when the hub states neither.
    function corpusGate() {
      return version().then(function (v) { return v.corpus_gate === "enforce" || v.corpus_gate === "report" ? v.corpus_gate : null; });
    }

    function fetchManifest(id, forWhom) {
      return get(url(["corpi", id]), forWhom).then(function (r) {
        if (r.status !== 200) return { gone: true, status: r.status };
        var manifest;
        try { manifest = JSON.parse(r.body); } catch (e) { throw new HubError(host + " sent something that is not JSON"); }
        return { manifest: manifest };
      });
    }

    function track(id, raw) {
      var file = safeRelPath(raw.file), low = file.toLowerCase();
      if (!file || !(/\.mp3$/.test(low) || /\.wbol$/.test(low))) return null;
      var packed = /\.wbol$/.test(low), audio;
      if (packed) {                              // only the hub's own chapter extract, never another host
        audio = onHub(raw.url);
        var prefix = url(["corpi", id, "wbol"]) + "/";
        var tail = audio && audio.indexOf(prefix) === 0 ? audio.slice(prefix.length).split("/") : [];
        if (tail.length !== 3 || tail[1] !== "chapter" || !/^[0-9]+$/.test(tail[2]) || !tail[0] || tail[0].indexOf("..") >= 0) return null;
      } else {
        audio = url(["corpi", id, "audio", file], null, true);
      }
      var art = raw.art_url || raw.art;
      art = typeof art === "string" ? strip(art) : "";
      var artUrl = /^(\/|https?:\/\/)/.test(art) ? onHub(art) : (safeName(art) ? url(["corpi", id, "art", art]) : null);
      var leaf = file.split("/").pop();
      return { file: file, title: String(raw.title || (leaf.lastIndexOf(".") >= 0 ? leaf.slice(0, leaf.lastIndexOf(".")) : leaf)),
               album: String(raw.album || ""), track_no: count(raw.track_no, true), artist: String(raw.artist || ""),
               duration_sec: count(raw.duration_sec, false), bytes: count(raw.bytes, true), audio_url: audio, art_url: artUrl,
               content_type: packed ? "audio/webm" : "audio/mpeg", audio_format: packed ? "wbol/1" : "mp3" };
    }

    // One corpus, fetched now. Rejects with CorpusUnavailable (the hub does not serve it),
    // ManifestRefused (the SDK will not read it), HubUnreachable or HubError.
    function corpus(id, o) {
      if (typeof id !== "string" || !CORPUS_ID.test(id)) return Promise.reject(new CorpusUnavailable(JSON.stringify(id) + " is not a corpus id", { reason: "bad_id" }));
      var where = url(["corpi", id]), forWhom;
      try { forWhom = who(o); } catch (e) { return Promise.reject(e); }
      return fetchManifest(id, forWhom).then(function (got) {
        if (got.gone) throw new CorpusUnavailable(id + ": the hub does not serve it", { reason: "not_served", status: got.status });
        var manifest = got.manifest, reading = readManifest(manifest);
        if (reading.refusal) throw new ManifestRefused(where + ": " + reading.refusal + ": " + reading.problems.slice(0, 5).join("; "), { reason: reading.refusal, problems: reading.problems, where: where });
        if (manifest.id !== id) throw new ManifestRefused(where + ": manifest_invalid: asked for " + id + ", got " + JSON.stringify(manifest.id), { reason: "manifest_invalid", problems: ["#/id: asked for " + id + ", got " + JSON.stringify(manifest.id)], where: where });
        var state = { manifest: freeze(copy(manifest)), reading: reading, revalidatedAt: clock(), reachable: true, withdrawn: false, witnessedAt: null };
        // The latest time this page has seen on its own clock: the gate reads no time before it.
        function witness() { var t = clock(); if (typeof t === "number" && t === t && (state.witnessedAt === null || t > state.witnessedAt)) state.witnessedAt = t; }
        function standing() {
          return { source: "hub", revalidatedAt: state.revalidatedAt, reachable: state.reachable, withdrawn: state.withdrawn, witnessedAt: state.witnessedAt };
        }
        witness();

        var c = {
          id: id, number: manifest.number, slug: manifest.slug, name: manifest.name, artist: manifest.artist,
          displayLabel: manifest.display_label, description: manifest.description || "", editionLabel: editionLabel(manifest),
          visibility: reading.visibility, source: "hub", where: where, actingFor: forWhom,
          manifest: function () { return copy(state.manifest); },
          licence: function () { return state.reading.licence; },
          standing: standing,
          notices: function () { return notices(state.manifest); },

          // The gate's answer from what is in hand. Never throws.
          may: function (capability, identity, now) { witness(); return decide(state.reading, capability, identity, now, standing(), clock); },

          // Revalidate against the hub now. A manifest the hub now serves that the SDK cannot
          // read closes the corpus; a hub that cannot be reached leaves it working, unverified.
          refresh: function () {
            witness();
            return fetchManifest(id, forWhom).then(function (again) {
              state.reachable = true;
              state.revalidatedAt = clock();
              state.witnessedAt = state.revalidatedAt;           // the hub answered: the floor starts again from here
              if (again.gone) { state.withdrawn = true; return c; }
              state.withdrawn = false;
              var fresh = readManifest(again.manifest);
              if (again.manifest && again.manifest.id !== id && !fresh.refusal) {
                fresh = freeze({ corpusId: id, refusal: "manifest_invalid", problems: ["#/id: asked for " + id + ", got " + JSON.stringify(again.manifest.id)],
                                 licence: licence(null), visibility: "public", ownerEmail: "", access: [] });
              }
              if (!sameJson(again.manifest, state.manifest)) {      // an unchanged manifest keeps earlier verdicts good
                state.reading = fresh;
                if (!fresh.refusal) state.manifest = freeze(copy(again.manifest));
              }
              return c;
            }, function (e) {
              if (!(e instanceof HubUnreachable)) throw e;
              state.reachable = false;
              return c;
            });
          },

          // The gate's answer, revalidating first when the last check is older than revalidateAfter
          // or the hub was not reached last time.
          check: function (capability, identity) {
            // Also when the clock is behind what this page has witnessed: one of the two readings
            // was wrong, and only the hub can say the block still stands.
            var stale = clock() - state.revalidatedAt > revalidateAfter || !state.reachable ||
              (state.witnessedAt !== null && clock() < state.witnessedAt);
            return (stale ? c.refresh() : Promise.resolve(c)).then(function () { return c.may(capability, identity); });
          },

          // The recordings a player can stream. Needs an allowed, current verdict for "stream_audio".
          tracks: function (verdict) {
            try { admit(verdict, ["stream_audio"]); } catch (e) { return Promise.reject(e); }
            return get(url(["corpi", id, "tracks"]), forWhom).then(function (r) {
              var data = null;
              if (r.status !== 200) throw new NotAvailable(id + ": the hub has no track listing for this caller", { reason: "not_found", status: r.status });
              try { data = JSON.parse(r.body); } catch (e) { data = null; }
              if (isObject(data) && data.audio === "not_licensed") {
                throw new NotAvailable(id + ": " + (data.message || "the hub has no recordings to give"), { reason: "not_licensed", status: r.status });
              }
              var rows = isObject(data) ? data.tracks : data;
              if (!Array.isArray(rows)) throw new NotAvailable(id + ": the hub sent no usable track listing", { reason: "bad_answer", status: r.status });
              return rows;
            }, function (e) {
              if (e instanceof HubUnreachable) throw new NotAvailable(id + ": could not fetch the track listing (" + e.message + ")", { reason: "unreachable", status: e.status });
              throw e;
            }).then(function (rows) {
              var out = rows.filter(isObject).map(function (row) { return track(id, row); }).filter(Boolean);
              var keyOf = function (t) { return [t.album.toLowerCase(), t.track_no || 0, t.file.toLowerCase()]; };
              return out.sort(function (a, b) {
                var x = keyOf(a), y = keyOf(b);
                for (var i = 0; i < 3; i++) { if (x[i] < y[i]) return -1; if (x[i] > y[i]) return 1; }
                return 0;
              });
            });
          }
        };

        function admit(verdict, capabilities) {
          if (!isVerdict(verdict)) throw new GateRequired("corpus content needs a verdict from corpus.may() or corpus.check()");
          var extra = { verdict: verdict }, made = verdicts.get(verdict), now = clock();
          if (!verdict.allowed) throw new GateRequired("refused: " + verdict.reason + " (" + verdict.detail + ")", extra);
          if (verdict.corpusId !== id) throw new GateRequired("that verdict is for " + verdict.corpusId + ", not " + id, extra);
          if (capabilities.indexOf(verdict.capability) < 0) throw new GateRequired("that verdict allows " + verdict.capability + "; this needs " + capabilities.join(" or "), extra);
          var st = standing();
          if (made.reading !== state.reading || made.standingKey !== [st.source, st.revalidatedAt, st.reachable, st.withdrawn].join("|")) {
            throw new GateRequired("the corpus has changed since that verdict; ask the gate again", extra);
          }
          if (now - verdict.checkedAt > VERDICT_TTL_SEC || now < verdict.checkedAt - 1) throw new GateRequired("that verdict is too old; ask the gate again", extra);
          if (verdict.validUntil !== null && now >= verdict.validUntil) throw new GateRequired("the licence has closed since that verdict; ask the gate again", extra);
        }

        return Object.freeze(c);
      });
    }

    return Object.freeze({ baseUrl: base, origin: origin, actingFor: actingFor, stats: stats, listing: listing, corpus: corpus,
                           version: version, corpusGate: corpusGate });
  }

  var api = {
    CAPABILITIES: CAPABILITIES, ALL_CAPABILITIES: ALL_CAPABILITIES, REASONS: REASONS, SCOPES: Object.keys(SCOPES), VERDICT_TTL_SEC: VERDICT_TTL_SEC,
    judge: judge, listen: listen, decide: decide, readManifest: readManifest, isVerdict: isVerdict, canonicalCapability: canonicalCapability,
    licence: licence, parseTime: parseTime, formatTime: formatTime, notices: notices, hub: hub,
    BadTime: BadTime, HubError: HubError, HubUnreachable: HubUnreachable, CorpusUnavailable: CorpusUnavailable,
    ManifestRefused: ManifestRefused, GateRequired: GateRequired, NotAvailable: NotAvailable
  };

  bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var corpusNs = bollardeck.corpus || (bollardeck.corpus = {});
  Object.keys(api).forEach(function (k) { corpusNs[k] = api[k]; });
  (bollardeck.parts || (bollardeck.parts = {})).corpus = true;
  if (typeof module === "object" && module.exports) module.exports = corpusNs;
})(typeof globalThis !== "undefined" ? globalThis : this);
