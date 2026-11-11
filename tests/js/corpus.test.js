// SPDX-License-Identifier: Apache-2.0
// bollardeck.corpus: the gate gives every vector under conformance/corpus-gate/ the verdict and
// reason the Python gate gives, and the hub client is exercised against a stand-in fetch. No test
// here talks to a real service.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JS, CONFORMANCE, readJson, jsonFiles, bollardeck } = require("./support.js");

const X = bollardeck.corpus;
const NOON = "2031-06-01T12:00:00Z";
const T0 = X.parseTime(NOON);

test("every gate vector gets its verdict and its reason", () => {
  let count = 0;
  const reasons = new Set(), asked = new Set();
  for (const file of jsonFiles(path.join(CONFORMANCE, "corpus-gate"))) {
    const doc = readJson(file);
    for (const c of doc.cases) {
      count += 1;
      const before = JSON.stringify(doc.manifests[c.manifest]);
      const v = X.judge(doc.manifests[c.manifest], c.capability, c.identity, c.clock, c.standing);
      const got = { allowed: v.allowed, reason: v.reason, pending: v.pending, unverified_since: v.asDict().unverified_since, capability_answered: v.capability };
      for (const [key, want] of Object.entries(c.expect)) assert.deepEqual(got[key], want, path.basename(file) + ": " + c.name + ": " + key + " (" + v.detail + ")");
      assert.equal(v.allowed, v.reason === "allowed");
      assert.ok(X.isVerdict(v) && Object.isFrozen(v));
      assert.equal(JSON.stringify(doc.manifests[c.manifest]), before, "the gate changed a manifest");
      reasons.add(c.expect.reason);
      if (typeof c.capability === "string") asked.add(c.capability);
    }
  }
  assert.ok(count >= 100);
  assert.deepEqual([...reasons].sort(), [...X.REASONS].sort(), "every reason has a vector");
  for (const cap of X.ALL_CAPABILITIES.concat(["study"])) assert.ok(asked.has(cap), cap);
});

const manifest = (extra) => Object.assign({ schema_version: 1, id: "9001-PLACEHOLDERS", number: 9001, slug: "PLACEHOLDERS", name: "Placeholders",
  artist: "Nobody In Particular", display_label: "PLACEHOLDERS", licence: { schema: "popboll.licence/1", scope: "full" } }, extra || {});

test("the gate never throws, and only the gate makes a verdict", () => {
  for (const junk of [undefined, null, 7, "x", [], {}, { id: 5 }, manifest({ licence: 3 })]) {
    for (const cap of ["study", null, 7, {}, "constructor"]) {
      for (const now of [NOON, T0, null, "soon", NaN, true, {}, new Date(T0 * 1000)]) {
        const v = X.judge(junk, cap, { email: 5 }, now, { revalidated_at: "x" });
        assert.equal(v.allowed, false, JSON.stringify([junk, cap, String(now)]));
        assert.ok(X.REASONS.includes(v.reason));
      }
    }
  }
  const good = X.judge(manifest(), "study", null, NOON);
  assert.equal(String(good), "Verdict(allowed musicians_may_study on 9001-PLACEHOLDERS: allowed)");
  assert.deepEqual(good.asDict(), { allowed: true, reason: "allowed", capability: "musicians_may_study", corpus_id: "9001-PLACEHOLDERS", detail: "",
    scope: "full", checked_at: NOON, unverified_since: null, pending: null });
  assert.equal(X.isVerdict(Object.assign({}, good)), false, "a copy of a verdict is not a verdict");
  assert.throws(() => { good.allowed = false; if (good.allowed) throw new TypeError("frozen"); }, TypeError);
  assert.equal(X.judge(manifest(), "study", null, new Date(T0 * 1000)).allowed, true, "a Date is a clock");
  assert.equal(X.judge(manifest(), "study", null, NOON, { source: "hub", revalidated_at: "not a time" }).reason, "bad_clock");
  assert.equal(X.judge(manifest({ licence: { scope: "full", expires_at: "2031-07-01" } }), "study", null, NOON).validUntil, X.parseTime("2031-07-01"));
});

test("licence times: UTC only, real dates only, and the years Date.UTC gets wrong", () => {
  assert.equal(X.parseTime("1970-01-01T00:00:00Z"), 0);
  assert.equal(X.parseTime("2031-06-01"), X.parseTime("2031-06-01T00:00:00"));
  assert.equal(X.parseTime("2031-06-01T12:00:00.25Z"), T0 + 0.25);
  assert.equal(X.parseTime("0099-12-31T00:00:00Z"), -59011545600);
  assert.equal(X.parseTime("0001-01-01"), -62135596800);
  assert.equal(X.parseTime("2032-02-29"), X.parseTime("2032-03-01") - 86400);
  assert.deepEqual([X.parseTime(null), X.parseTime("")], [null, null]);
  for (const bad of ["2031-02-30", "2031-06-01T12:00:00+02:00", "2031-6-1", "0000-01-01", "yesterday", 5]) assert.throws(() => X.parseTime(bad), X.BadTime, String(bad));
  assert.equal(X.formatTime(T0 + 0.9), NOON);
  const lic = X.licence({ scope: "morpus_only", store_art: true });
  assert.deepEqual([lic.status, lic.grants("store_art"), lic.grants("store_audio"), lic.grants("toString"), lic.whyOff("store_audio"), lic.whyOff("export_morpus")],
    ["ok", true, false, false, "scope morpus_only never allows store_audio", "scope morpus_only does not include export_morpus"]);
  assert.equal(X.licence(null).status, "missing");
  assert.equal(X.licence({ scope: "full", revoked_at: "2031-02-30" }).status, "invalid");
  assert.equal(X.judge(manifest({ licence: { scope: "full", revoked_at: "0000-01-01" } }), "study", null, NOON).reason, "licence_invalid");
});

// ── the hub client, against a stand-in fetch ─────────────────────────────────────────────
function standIn(routes) {
  const calls = [];
  const fetch = (url, init) => {
    calls.push({ url, init });
    // A route may be for one person: "<path> for <name>" answers a request whose X-Pop-For is that name.
    const named = init.headers["X-Pop-For"] ? routes[new URL(url).pathname + new URL(url).search + " for " + init.headers["X-Pop-For"]] : undefined;
    const hit = named !== undefined ? named : routes[new URL(url).pathname + new URL(url).search];
    if (hit === undefined) return Promise.resolve({ status: 404, url, headers: { get: () => null }, text: () => Promise.resolve("") });
    if (hit instanceof Error) return Promise.reject(hit);
    const r = typeof hit === "function" ? hit() : hit;
    const status = r && r.status ? r.status : 200;
    const body = r && r.status ? (r.body || "") : JSON.stringify(r);
    return Promise.resolve({ status, url: (r && r.url) || url, headers: { get: () => null }, text: () => Promise.resolve(body) });
  };
  return { fetch, calls };
}
const HUB = "https://hub.example.test";

test("hub: the listing, a corpus, its notices and its gate", async () => {
  let clock = T0;
  const full = manifest({ license_note: " Used with permission. ", midi_sources: [
    { file: "a.mid", source_url: "https://example.test/a", source_licence: "CC-BY-4.0", attribution: "A by Someone" },
    { file: "b.mid", source_url: "https://example.test/b", source_licence: "CC-BY-4.0", attribution: "A by Someone" },
    { file: "c.mid", source_url: "https://example.test/c", source_licence: "PD" }] });
  const net = standIn({
    "/api/corpi": [{ id: "9001-PLACEHOLDERS", name: "Placeholders" }, { id: "not an id" }, "junk", { name: "no id" }],
    "/api/corpi for ada@example.org": [{ id: "9002-PRIVATE" }],
    "/api/corpi/9001-PLACEHOLDERS": full,
    "/api/version": { version: "0.2.4" },
  });
  const hub = X.hub({ baseUrl: HUB + "/", token: "tok-123", player: "test-player", device: "PB0001-TEST-1", fetch: net.fetch, clock: () => clock });
  assert.deepEqual((await hub.listing()).map((r) => r.id), ["9001-PLACEHOLDERS"]);
  assert.deepEqual((await hub.listing({ forEmail: " Ada@Example.org " })).map((r) => r.id), ["9002-PRIVATE"]);
  assert.deepEqual((await hub.listing({ actingFor: "ada@example.org" })).map((r) => r.id), ["9002-PRIVATE"]);
  assert.deepEqual(net.calls.slice(1).map((c) => [c.url, c.init.headers["X-Pop-For"]]), [[HUB + "/api/corpi", "ada@example.org"], [HUB + "/api/corpi", "ada@example.org"]],
    "the name is in a header, never in the URL");
  assert.deepEqual(await hub.version(), { version: "0.2.4" });
  const first = net.calls[0];
  assert.equal(first.url, HUB + "/api/corpi");
  assert.deepEqual(first.init.headers, { Accept: "application/json", "X-Pop-Player": "test-player", "X-Pop-Device": "PB0001-TEST-1", Authorization: "Bearer tok-123" });
  assert.deepEqual([first.init.method, first.init.redirect, first.init.credentials], ["GET", "error", "same-origin"]);
  assert.ok(!JSON.stringify(hub).includes("tok-123") && !Object.values(hub).some((v) => v === "tok-123"), "the token is not readable from the client");

  const corpus = await hub.corpus("9001-PLACEHOLDERS");
  assert.deepEqual([corpus.id, corpus.number, corpus.slug, corpus.name, corpus.artist, corpus.displayLabel, corpus.editionLabel, corpus.visibility, corpus.source],
    ["9001-PLACEHOLDERS", 9001, "PLACEHOLDERS", "Placeholders", "Nobody In Particular", "PLACEHOLDERS", "PB 9001 — PLACEHOLDERS Edition", "public", "hub"]);
  assert.deepEqual(corpus.manifest(), full);
  corpus.manifest().name = "changed";
  assert.equal(corpus.manifest().name, "Placeholders", "the manifest handed out is a copy");
  assert.deepEqual(corpus.notices(), { corpus_id: "9001-PLACEHOLDERS", artist: "Nobody In Particular", edition: "PB 9001 — PLACEHOLDERS Edition",
    license_note: "Used with permission.", lines: ["PB 9001 — PLACEHOLDERS Edition", "Used with permission.", "A by Someone"],
    attributions: [{ file: "a.mid", title: "", attribution: "A by Someone", source_url: "https://example.test/a", source_licence: "CC-BY-4.0" },
      { file: "b.mid", title: "", attribution: "A by Someone", source_url: "https://example.test/b", source_licence: "CC-BY-4.0" }] });
  const v = corpus.may("study", { email: "ada@example.org" });
  assert.deepEqual([v.allowed, v.checkedAt, v.unverifiedSince], [true, T0, null]);
  assert.equal(corpus.may("study", null, "2099-01-01").allowed, true);
  assert.equal(corpus.licence().grants("stream_audio"), true);
});

test("hub: refusals name what went wrong", async () => {
  const net = standIn({
    "/api/corpi/9003-BROKEN": manifest({ id: "9003-BROKEN", number: 9003, slug: "BROKEN", visibility: "secret" }),
    "/api/corpi/9004-OTHER": manifest(),
    "/api/corpi/9005-BUSY": { status: 503 },
    "/api/corpi/9006-DOWN": new TypeError("network down"),
    "/api/corpi/9007-ODD": { status: 418 },
    "/api/corpi/9008-TEXT": { status: 200, body: "<html>" },
    "/api/corpi/9009-AWAY": () => ({ status: 200, body: "{}", url: "https://elsewhere.example.test/api/corpi/9009-AWAY" }),
    "/api/corpi": { status: 401 },
  });
  const hub = X.hub({ baseUrl: HUB, fetch: net.fetch });
  await assert.rejects(hub.corpus("9002-GONE"), (e) => e instanceof X.CorpusUnavailable && /does not serve it/.test(e.message));
  await assert.rejects(hub.corpus("../etc"), X.CorpusUnavailable);
  await assert.rejects(hub.corpus("9003-BROKEN"), (e) => e instanceof X.ManifestRefused && e.reason === "manifest_invalid" && e.problems.length > 0);
  await assert.rejects(hub.corpus("9004-OTHER"), (e) => e instanceof X.ManifestRefused && /asked for 9004-OTHER/.test(e.message));
  await assert.rejects(hub.corpus("9005-BUSY"), X.HubUnreachable);
  await assert.rejects(hub.corpus("9006-DOWN"), (e) => e instanceof X.HubUnreachable && e instanceof X.HubError && /network down/.test(e.message));
  await assert.rejects(hub.corpus("9007-ODD"), (e) => e instanceof X.HubError && !(e instanceof X.HubUnreachable));
  await assert.rejects(hub.corpus("9008-TEXT"), /not JSON/);
  await assert.rejects(hub.corpus("9009-AWAY"), /somewhere other than the hub/);
  await assert.rejects(hub.listing(), X.HubUnreachable);
  assert.equal(net.calls.filter((c) => c.url.includes("etc")).length, 0, "a bad id is never asked for");
  assert.ok(net.calls.every((c) => !("Authorization" in c.init.headers)), "no token, no header");
});

test("hub: it asks only its own hub, and guards the token", async () => {
  const net = standIn({});
  assert.throws(() => X.hub({ fetch: net.fetch }), RangeError, "under Node there is no page origin: a hub must be named");
  for (const bad of ["ftp://hub.example.test", "hub.example.test", "", "javascript:alert(1)"]) assert.throws(() => X.hub({ baseUrl: bad, fetch: net.fetch }), RangeError, bad);
  assert.throws(() => X.hub({ baseUrl: "http://hub.example.test", token: "t", fetch: net.fetch }), /plain http/);
  X.hub({ baseUrl: "http://hub.example.test", fetch: net.fetch });                                  // no token: fine
  X.hub({ baseUrl: "http://localhost:8080", token: "t", fetch: net.fetch });                        // this machine: fine
  X.hub({ baseUrl: "http://hub.example.test", token: "t", allowInsecureToken: true, fetch: net.fetch });
  assert.throws(() => X.hub({ baseUrl: "http://hub.example.test", token: () => "late", fetch: net.fetch }), /plain http/, "a token to come is a token");
  assert.equal(net.calls.length, 0, "nothing was sent");

  let asked = 0;
  const hub = X.hub({ baseUrl: HUB, token: () => { asked += 1; return Promise.resolve("fresh-" + asked); }, fetch: net.fetch });
  await assert.rejects(hub.listing());
  await assert.rejects(hub.listing());
  assert.deepEqual(net.calls.map((c) => c.init.headers.Authorization), ["Bearer fresh-1", "Bearer fresh-2"], "the token is asked for at each request");
});

test("hub: recordings need an allowed, current verdict for stream_audio", async () => {
  let clock = T0;
  const routes = {
    "/api/corpi/9001-PLACEHOLDERS": manifest(),
    "/api/corpi/9001-PLACEHOLDERS/tracks": { tracks: [
      { file: "2004/b side.mp3", album: "Second", track_no: "2", duration_sec: "181.5", bytes: 4000, art: "cover.png" },
      { file: "2004/a.mp3", album: "Second", track_no: 1, title: "A", artist: "Nobody", art_url: "/api/corpi/9001-PLACEHOLDERS/art/x.png" },
      { file: "first.wbol", album: "First", url: HUB + "/api/corpi/9001-PLACEHOLDERS/wbol/first.wbol/chapter/3" },
      { file: "stolen.wbol", album: "First", url: "https://elsewhere.example.test/api/corpi/9001-PLACEHOLDERS/wbol/first.wbol/chapter/3" },
      { file: "../escape.mp3" }, { file: "notes.txt" }, { file: "c.mp3", art_url: "https://elsewhere.example.test/art.png", track_no: -1, bytes: "many" }, "junk"] },
  };
  const net = standIn(routes);
  const hub = X.hub({ baseUrl: HUB, fetch: net.fetch, clock: () => clock });
  const corpus = await hub.corpus("9001-PLACEHOLDERS");
  const stream = corpus.may("stream_audio");
  const tracks = await corpus.tracks(stream);
  assert.deepEqual(tracks.map((t) => t.file), ["c.mp3", "first.wbol", "2004/a.mp3", "2004/b side.mp3"]);
  assert.deepEqual(tracks[3], { file: "2004/b side.mp3", title: "b side", album: "Second", track_no: 2, artist: "", duration_sec: 181.5, bytes: 4000,
    audio_url: HUB + "/api/corpi/9001-PLACEHOLDERS/audio/2004/b%20side.mp3", art_url: HUB + "/api/corpi/9001-PLACEHOLDERS/art/cover.png",
    content_type: "audio/mpeg", audio_format: "mp3" });
  assert.deepEqual([tracks[1].audio_url, tracks[1].audio_format, tracks[1].content_type], [HUB + "/api/corpi/9001-PLACEHOLDERS/wbol/first.wbol/chapter/3", "wbol/1", "audio/webm"]);
  assert.equal(tracks[2].art_url, HUB + "/api/corpi/9001-PLACEHOLDERS/art/x.png");
  assert.deepEqual([tracks[0].art_url, tracks[0].track_no, tracks[0].bytes], [null, null, null], "a cover on another host is dropped");

  const asks = () => net.calls.filter((c) => c.url.endsWith("/tracks")).length;
  const before = asks();
  const other = X.judge(manifest({ id: "9002-OTHER", number: 9002, slug: "OTHER" }), "stream_audio", null, T0);
  for (const [bad, why] of [[undefined, /needs a verdict/], [{ allowed: true, corpusId: corpus.id, capability: "stream_audio" }, /needs a verdict/],
    [Object.assign({}, stream), /needs a verdict/], [corpus.may("study"), /this needs stream_audio/], [corpus.may("nonsense"), /refused: unknown_capability/],
    [other, /is for 9002-OTHER/], [X.judge(manifest(), "stream_audio", null, T0), /has changed since/]]) {
    await assert.rejects(corpus.tracks(bad), (e) => e instanceof X.GateRequired && why.test(e.message), String(why));
  }
  clock = T0 + X.VERDICT_TTL_SEC + 1;
  await assert.rejects(corpus.tracks(stream), /too old/);
  assert.equal(asks(), before, "nothing was fetched without the gate");
  assert.equal((await corpus.tracks(corpus.may("stream_audio"))).length, 4);

  routes["/api/corpi/9001-PLACEHOLDERS/tracks"] = { audio: "not_licensed", message: "no recordings" };
  await assert.rejects(corpus.tracks(corpus.may("stream_audio")), (e) => e instanceof X.NotAvailable && /no recordings/.test(e.message));
  routes["/api/corpi/9001-PLACEHOLDERS/tracks"] = { status: 404 };
  await assert.rejects(corpus.tracks(corpus.may("stream_audio")), X.NotAvailable);
});

test("hub: refresh and check keep the licence current", async () => {
  let clock = T0;
  const routes = { "/api/corpi/9001-PLACEHOLDERS": manifest() };
  const net = standIn(routes);
  const hub = X.hub({ baseUrl: HUB, fetch: net.fetch, clock: () => clock, revalidateAfter: 300 });
  const corpus = await hub.corpus("9001-PLACEHOLDERS");
  const asks = () => net.calls.length;
  let n = asks();
  assert.equal((await corpus.check("study")).allowed, true);
  assert.equal(asks(), n, "fresh enough: no request");
  clock = T0 + 301;
  const held = corpus.may("stream_audio");
  assert.equal((await corpus.check("study")).allowed, true);
  assert.equal(asks(), n + 1, "stale: revalidated first");
  await assert.rejects(corpus.tracks(held), /has changed since/, "a verdict from before a revalidation is not current");

  routes["/api/corpi/9001-PLACEHOLDERS"] = manifest({ licence: { scope: "full", revoked_at: "2031-06-01T12:04:00Z" } });
  clock = T0 + 700;
  const revoked = await corpus.check("study");
  assert.deepEqual([revoked.allowed, revoked.reason], [false, "revoked"], "a revocation applies at the next contact");

  routes["/api/corpi/9001-PLACEHOLDERS"] = { status: 503 };
  clock = T0 + 1100;
  const offline = await corpus.check("see");
  assert.deepEqual([offline.allowed, offline.unverifiedSince], [true, T0 + 700], "unreachable: it keeps working on what it holds, and says since when");

  routes["/api/corpi/9001-PLACEHOLDERS"] = manifest({ visibility: "secret" });
  await corpus.refresh();
  assert.equal(corpus.may("see").reason, "manifest_invalid", "a manifest the SDK cannot read closes the corpus");
  assert.equal(corpus.manifest().visibility, undefined, "and the last readable manifest is still the one in hand");

  routes["/api/corpi/9001-PLACEHOLDERS"] = manifest();
  await corpus.refresh();
  assert.equal(corpus.may("see").allowed, true, "and a readable one opens it again");
  routes["/api/corpi/9001-PLACEHOLDERS"] = { status: 410 };
  await corpus.refresh();
  assert.equal(corpus.may("see").reason, "withdrawn");
});

test("the corpus code keeps nothing: no storage, no cookies, no page", () => {
  const code = fs.readFileSync(path.join(JS, "bollardeck.corpus.js"), "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, "");
  for (const word of ["localStorage", "sessionStorage", "indexedDB", "document.", "cookie", "window.", "caches."]) assert.ok(!code.includes(word), word);
});

test("hub: who the client acts for goes in X-Pop-For, on the client or per call", async () => {
  const whole = manifest({ id: "9002-PRIVATE", number: 9002, slug: "PRIVATE", visibility: "private", owner_email: "ada@example.org", access: ["grace@example.org"],
    license_note: "Used with the permission of Ada Example.", licence: { scope: "full", granted_by: { legal_name: "Ada Example" }, statements: [{ key: "mine", text: "I am Ada Example." }] } });
  const redacted = JSON.parse(JSON.stringify(whole));
  for (const k of ["owner_email", "access", "license_note"]) delete redacted[k];
  delete redacted.licence.granted_by; delete redacted.licence.statements;
  const net = standIn({
    "/api/corpi/9002-PRIVATE": redacted,                                  // the token alone: study only
    "/api/corpi/9002-PRIVATE for ada@example.org": whole,
    "/api/corpi/9002-PRIVATE/tracks for ada@example.org": { tracks: [{ file: "one.mp3" }] },
    "/api/corpi/9002-PRIVATE for mallory@example.org": { status: 404 },
    "/api/version": { version: "0.2.4", corpus_gate: "report" },
  });
  const engine = X.hub({ baseUrl: HUB, token: "tok", fetch: net.fetch, clock: () => T0 });
  const studied = await engine.corpus("9002-PRIVATE");
  assert.equal(net.calls[0].init.headers["X-Pop-For"], undefined);
  assert.deepEqual([studied.actingFor, studied.manifest().owner_email, studied.may("study", { service: true }).allowed, studied.may("study").reason], ["", undefined, true, "not_visible"]);
  for (const who of [{ service: true }, null]) {
    for (const cap of ["see", "study", "stream_audio", "export_morpus"]) assert.equal(studied.may(cap, who).reason, X.judge(whole, cap, who, T0).reason, cap);
  }
  await assert.rejects(studied.tracks(studied.may("stream_audio", { service: true })), (e) => e instanceof X.NotAvailable && e.reason === "not_found" && e.status === 404);

  const forAda = X.hub({ baseUrl: HUB, token: "tok", fetch: net.fetch, clock: () => T0, actingFor: " Ada@Example.org " });
  assert.equal(forAda.actingFor, "ada@example.org");
  const hers = await forAda.corpus("9002-PRIVATE");
  assert.equal(hers.manifest().owner_email, "ada@example.org");
  assert.deepEqual((await hers.tracks(hers.may("stream_audio", { email: "ada@example.org" }))).map((t) => t.file), ["one.mp3"]);
  await hers.refresh();
  assert.ok(net.calls.slice(-3).every((c) => c.init.headers["X-Pop-For"] === "ada@example.org"));
  assert.ok(net.calls.every((c) => !/@|%40|for=/.test(c.url)), "never in a URL");
  assert.equal((await engine.corpus("9002-PRIVATE", { actingFor: "ada@example.org" })).manifest().owner_email, "ada@example.org", "per call");
  assert.equal((await forAda.corpus("9002-PRIVATE", { actingFor: "" })).manifest().owner_email, undefined, "and nobody, per call");
  await assert.rejects(engine.corpus("9002-PRIVATE", { actingFor: "mallory@example.org" }), (e) => e instanceof X.CorpusUnavailable && e.reason === "not_served" && e.status === 404);
  await assert.rejects(engine.corpus("9002-PRIVATE", { actingFor: "ada@example.org\r\nX-Evil: 1" }), RangeError);
  await assert.rejects(engine.listing({ actingFor: "a b@example.org" }), RangeError);
  for (const bad of [7, ["ada@example.org"], { email: "ada@example.org" }, true]) {
    await assert.rejects(engine.corpus("9002-PRIVATE", { actingFor: bad }), RangeError, "a name that is not a string is refused, not read as nobody");
    assert.throws(() => X.hub({ baseUrl: HUB, fetch: net.fetch, actingFor: bad }), RangeError);
  }
  // A request made in a person's name asks the browser's cache to keep nothing; one for nobody says nothing.
  assert.ok(net.calls.length > 6 && net.calls.every((c) => c.init.cache === (c.init.headers["X-Pop-For"] ? "no-store" : undefined)));
  assert.throws(() => X.hub({ baseUrl: HUB, fetch: net.fetch, actingFor: "ädä@example.org" }), RangeError);

  // The rollout switch is read for nobody, and is information only.
  assert.equal(await forAda.corpusGate(), "report");
  assert.equal(net.calls[net.calls.length - 1].init.headers["X-Pop-For"], undefined);
  for (const [stated, want] of [["enforce", "enforce"], ["sometimes", null], [undefined, null]]) {
    const h = X.hub({ baseUrl: HUB, fetch: standIn({ "/api/version": stated === undefined ? { version: "0.2.3" } : { corpus_gate: stated } }).fetch });
    assert.equal(await h.corpusGate(), want);
  }
});

test("hub: errors carry a reason and the status the hub answered with", async () => {
  const net = standIn({
    "/api/corpi/9001-PLACEHOLDERS": manifest(),
    "/api/corpi/9001-PLACEHOLDERS/tracks": { audio: "not_licensed", tracks: [] },
    "/api/corpi/9005-BUSY": { status: 503 },
    "/api/corpi/9006-DOWN": new Error("no route"),
    "/api/corpi/9007-ODD": { status: 418 },
  });
  const hub = X.hub({ baseUrl: HUB, fetch: net.fetch, clock: () => T0 });
  const why = (p) => p.then(() => assert.fail("it should have been refused"), (e) => [e.constructor === X.CorpusUnavailable ? "CorpusUnavailable" : e.name, e.reason, e.status]);
  assert.deepEqual(await why(hub.corpus("nope")), ["CorpusUnavailable", "bad_id", null]);
  assert.deepEqual(await why(hub.corpus("9009-ABSENT")), ["CorpusUnavailable", "not_served", 404]);
  assert.deepEqual(await why(hub.corpus("9005-BUSY")), ["HubUnreachable", undefined, 503]);
  assert.deepEqual(await why(hub.corpus("9006-DOWN")), ["HubUnreachable", undefined, null]);
  assert.deepEqual(await why(hub.corpus("9007-ODD")), ["HubError", undefined, 418]);
  const c = await hub.corpus("9001-PLACEHOLDERS");
  assert.deepEqual(await why(c.tracks(c.may("stream_audio"))), ["NotAvailable", "not_licensed", 200]);
});

test("gate: a clock that is set back does not reopen a licence a hub corpus holds", async () => {
  let clock = T0;
  const net = standIn({ "/api/corpi/9001-PLACEHOLDERS": manifest({ licence: { scope: "full", expires_at: X.formatTime(T0 + 1000) } }) });
  let down = false;
  const fetch = (u, i) => (down ? Promise.reject(new Error("offline")) : net.fetch(u, i));
  const hub = X.hub({ baseUrl: HUB, fetch, clock: () => clock, revalidateAfter: 300 });
  const c = await hub.corpus("9001-PLACEHOLDERS");
  assert.equal(c.may("study").allowed, true);
  down = true;
  clock = T0 + 2000;
  assert.equal((await c.check("study")).reason, "expired");
  clock = T0 + 500;                                                      // back to before the date
  const v = c.may("study");
  assert.deepEqual([v.reason, v.checkedAt], ["expired", T0 + 500], "the page has seen a later time than this clock");
  assert.equal(c.standing().witnessedAt, T0 + 2000);
  assert.equal(c.may("see").allowed, true);
  // The same through judge, with the standing spelled either way; a local manifest follows the clock.
  const m = manifest({ licence: { scope: "full", expires_at: "2031-06-10" } });
  const at = (standing) => X.judge(m, "study", null, "2031-06-07T00:00:00Z", standing).reason;
  assert.equal(at({ source: "hub", revalidated_at: "2031-06-05T00:00:00Z", reachable: false, witnessed_at: "2031-06-12T00:00:00Z" }), "expired");
  assert.equal(at({ source: "hub", revalidatedAt: X.parseTime("2031-06-05"), reachable: false, witnessedAt: new Date(Date.UTC(2031, 5, 12)) }), "expired");
  assert.equal(at({ source: "hub", revalidated_at: "2031-06-05T00:00:00Z", reachable: false }), "allowed");
  assert.equal(at({ source: "local", witnessed_at: "2031-06-12T00:00:00Z" }), "allowed");
  assert.equal(at({ source: "hub", witnessed_at: "not a time" }), "bad_clock");
});

test("gate: one wrong reading of the clock heals at the next contact, and a what-if leaves no trace", async () => {
  let clock = T0, down = false;
  const net = standIn({ "/api/corpi/9001-PLACEHOLDERS": manifest({ licence: { scope: "full", expires_at: X.formatTime(T0 + 30 * 86400) } }) });
  const hub = X.hub({ baseUrl: HUB, fetch: (u, i) => (down ? Promise.reject(new Error("offline")) : net.fetch(u, i)), clock: () => clock, revalidateAfter: 300 });
  const c = await hub.corpus("9001-PLACEHOLDERS");
  // Asking about another time writes nothing: the page's own clock is all it witnesses.
  assert.equal(c.may("study", null, T0 + 365 * 86400).reason, "expired");
  assert.equal(c.may("study", null, X.formatTime(T0 + 365 * 86400)).reason, "expired");
  assert.deepEqual([c.standing().witnessedAt, c.may("study").allowed], [T0, true]);
  // The clock reads twenty years ahead for one call, then is corrected.
  clock = T0 + 20 * 365 * 86400;
  assert.equal(c.may("study").reason, "expired");
  clock = T0 + 60;
  assert.equal(c.may("study").reason, "expired", "until the hub is reached, a clock set back is not believed");
  assert.equal((await c.check("study")).allowed, true, "the hub answered: the floor starts again");
  assert.deepEqual([c.standing().witnessedAt, c.standing().revalidatedAt], [T0 + 60, T0 + 60]);
  // The same glitch offline stays closed until the hub is reached.
  down = true;
  clock = T0 + 20 * 365 * 86400;
  assert.equal((await c.check("study")).reason, "expired");
  clock = T0 + 120;
  assert.equal((await c.check("study")).reason, "expired");
  down = false;
  assert.equal((await c.check("study")).allowed, true);
});
