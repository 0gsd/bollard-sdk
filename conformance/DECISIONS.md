# Decisions

Where a schema or a specification page left room, this is what the SDK does and why. It is for
someone writing another implementation: the vectors in this folder pin most of these, and the
file that does is named. A schema says what a document may look like; these say what a reader
does with it.

## The corpus gate

Vectors: `corpus-gate/`.

**The licence block**

- **No block, or `"licence": null`, allows nothing** (`licence_missing`). A corpus with no stated
  licence is not assumed to be open. `see` is still answered, so a client can list the corpus and
  say why it cannot be used. (`licence-state.json`)
- **The `license` spelling is honoured only when `licence` is null or absent.** Both present with
  equal content is fine; with different content the manifest is refused (`licence_ambiguous`),
  even for a capability both would allow, because the gate cannot know which was meant.
- **Times are UTC only**, in exactly the schema's form. An offset is refused, not dropped. A date
  alone is midnight UTC. A time that fits the pattern and is not a real moment (30 February)
  closes the block (`licence_invalid`); the schema cannot catch that.
- **A licence closes at the instant itself** (`revoked_at <= now`). When both `revoked_at` and
  `expires_at` have passed, the reason is `revoked`.
- **`unknown_scope` and `newer_version` are named only when they are the manifest's only fault.**
  Otherwise the reason is `manifest_invalid`. All three refuse: what the code does not understand
  is not allowed.

**The manifest**

- **A manifest passes its schema or nothing is read from it.**
- **`id` must equal `number` (four digits) and `slug`, joined by a hyphen.** The schema cannot say
  this.

**Visibility**

- **A missing `visibility` is public.**
- **A corpus that is not public refuses every capability**, not only listing, to an identity that
  is neither its `owner_email` nor in its `access` list (compared trimmed and lower-cased).
  Visibility is checked before the licence, so a stranger does not learn a private corpus's
  licence state. (`visibility.json`)
- **`Identity(service=True)` passes the visibility check.** It stands for the platform's own
  engine, which may study a private corpus if its licence allows study. It is the caller's claim;
  the gate cannot verify it, and a hub decides for itself what it serves to whom.

**Offline, revalidation and the clock**

Vectors: `corpus-gate/offline.json`.

- **A date the device holds applies; news it has not heard waits.** When the hub cannot be
  reached, a cached corpus keeps working on the licence block it holds, and every verdict says
  since when it is unverified. An `expires_at` in that block is honoured by the device's own
  clock, online or not. A revocation made on the hub is news: it applies at the next successful
  revalidation, at once. A `revoked_at` already in the cached block that passes while the hub is
  unreachable is treated as news too (allowed, with `pending: "revoked"`).
- **A corpus read from a local folder has no grace.** Its manifest is the truth and the clock
  applies as given.
- **The clock has a floor, for a cached corpus only.** The gate reads no time earlier than the
  last successful revalidation, or than the latest reading of the device's own clock taken at a
  revalidation attempt since then. So a clock set back while the hub is unreachable does not
  reopen a licence that was seen to close. **It is not a seal.** The reading is taken at attempts,
  so a clock set back between two attempts, to a time after the last one, is believed. A hub
  answer starts the floor again from that moment, which is also how one wrong reading of the
  clock heals. A time the caller supplies to `may(now=...)` is judged and never recorded.
- **Unreachable** is no connection, a timeout, a broken body, HTTP 5xx, and also 401, 403 and
  429. A 404 or 410 for a manifest that was served before marks the corpus `withdrawn`: the gate
  refuses everything, `see` included, until it is served again.
- **Nothing is deleted.** A revoked or withdrawn corpus's cached files stay on disk; the gate
  stops handing them out.
- **A manifest that starts arriving broken closes the corpus** (`manifest_invalid`), and that is
  remembered, so a restart does not reopen it.

**The hub client**

- **The token never leaves the hub.** A redirect to another scheme, host or port is refused, and
  so is any URL in a track listing that points off the hub. A token is not sent over plain http
  except to a loopback address, unless the caller says so. The browser client refuses every
  redirect, because `fetch` follows first and tells afterwards.
- **Who a request is for travels in the `X-Pop-For` header, never in a URL**, and that person's
  copy is cached apart from everyone else's. The name is the caller's claim until sign-in exists.
- **One corpus is never silently substituted for another.** Selecting ids that are missing raises
  unless the caller asks for a fallback, and the result says what was missing.

**Attestation**

- **Five checks, each reported for itself**: the listing's hash, the attestation document against
  the manifest and the listing, the key id, Ed25519, ML-DSA-65. The whole is `verified` only when
  all five verified. Where the platform's OpenSSL does not know ML-DSA-65, that check is
  `not_checked` and the whole is `partial`, never `verified`.
- **The caller supplies the public keys.** The module fetches nothing.
- **A self-hosted origin is discovered and checked, never read as a corpus.** HTTPS only, and a
  discovery file that carries a secret is refused by its schema.

## The device layer

Vectors: `gestures/`, `keymap/`, `cues/`, `cue-render/`, `yaml/`.

- **A button is its number**, 1, 2 or 3. `inner`, `middle` and `outer` are the `bollardeck/1`
  wire's words; `cues.to_wire` and `from_wire` translate at that boundary and nowhere else, and a
  wire-form cue is refused by the SDK's own readers so the two cannot be mixed by accident.
- **Two cues for one button make the list invalid**; the order of a list means nothing. A strict
  reader refuses. A light loop must not stop for one bad cue, so `normalise` repairs instead
  (it keeps the last) and reports every repair. Nothing is dropped silently.
- **All three buttons are always answered when a list is rendered**, with `driven: false` for a
  button the list does not mention: "not driven" is not `off`. Reduced motion draws pulse and
  chase as on. A level becomes a pixel by rounding half to even.
- **The gesture engine is driven by edges and by times it is given.** It keeps no clock, and a
  time that runs backwards is an error: clamping is the host's job. Debouncing belongs to the
  board. A hold fed as edges is reported the moment the press has lasted `HOLD_MS`, while the
  button is down. A complete press from a board is a tap or a hold by the `hold_ms` it states,
  never by when its line was read.
- **A press beginning is a hint, not a gesture.** It can keep pending taps from being reported
  early; it cannot turn a tap into a hold when the release is late or lost. A release is matched
  to a beginning only when their times agree within `PRESS_MATCH_MS`, and a beginning with no
  release is forgotten after `PRESS_LOST_MS`.
- **A gesture carries the time it became certain.** A lone tap on a button that waits for a
  multiple tap is reported when the wait ends, with that time.
- **In the keymap a prompt meaning says what it is**: `{"choice": x}`, `{"do": name}` or null.
  Null takes the gesture and does nothing, which is different from a gesture the keymap does not
  claim. `always` is consulted first, then `prompt` while a prompt shows, else `idle`. A keymap
  whose version is not 2 is refused, so an older file cannot be misread.
- **Identity is read and never assigned.** A device identity file that exists and cannot be used
  is an error, not an absence, so a caller cannot overwrite a damaged identity by mistake.
- **The routine manifest reader coerces nothing.** It takes a strict subset of YAML and refuses
  every plain value that YAML 1.1 and 1.2 read differently (`yes`, `010`, `1e3`, a date), with the
  line number. A document that is one JSON object is read as JSON, refusing what the two would
  read differently: a repeated key, an exponent, a surrogate escape, nesting deeper than 64.
- **A limit looser than its hard cap is read as the cap.** An unknown limit is refused.

## The browser binding

- **The two validators report the same places.** For every schema vector they agree on the set of
  (pointer, keyword) pairs, not only on valid or invalid. Message wording is not compared.
  Patterns are ASCII for `\d` and `\w` in both languages, and a length is counted in code points.
- **A verdict is real only if the gate made it.** A copied or hand-built object is refused, and a
  verdict from before a revalidation or a changed manifest is not accepted.
- **The token is asked for, not kept**: it may be a function called at each request, and the
  client names no storage API. A request made in a person's name is never served from the
  browser's cache.
- **A keymap is looked up by own members only**, so `toString` and `constructor` are not gestures.
- **The browser client has no disk cache**, no attestation check and no origin discovery. When
  the hub cannot be reached, a corpus the page already holds keeps working and says since when it
  is unverified; one it does not hold is unavailable.

## The matrix engine

Vectors: `matrix/`.

- **A frame is a pure function of its inputs.** Randomness is a hash of the song id, so the same
  inputs give the same 113 bytes in Python and in JavaScript.
- **Malformed input draws something and never throws**: a song with no shots, a segment with the
  wrong types, a name such as `__proto__`. The vectors include these on purpose.
- **Where the two languages would naturally differ, the vectors decide**: a temperament member
  that is null is read as 0, not as the default.

## Where Python and JavaScript may still differ

On input the vectors do not cover: the wording of a verdict's detail text; a track number written
as a string (JavaScript reads plain decimals only); the order of track titles outside the Basic
Multilingual Plane; redirects, which Python follows when they stay on the hub and the browser
never does.
