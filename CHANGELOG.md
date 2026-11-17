# Changelog

What each version of the Bollawax Bollard SDK added and changed. The SDK has its own version, and
its tags are the version number (`0.1.0`, `0.2.0`, `0.3.0`, `0.4.0`, `0.5.0`); it is not the Bollawax image version.

## 0.5.0 (2026-11-17)

Shipped with Bollawax 0.3.7. **One break, in `bollardeck.popsnip`: the revocation list is paged (format B).** The SDK
has no outside users yet, so nothing else changes for anyone. Breaks first:

- **Changed: `popsnip.revocations` no longer carries `entries`.** It is now a signed index: `{seq, prev, at, count,
  page_size: 256, pages: [<id of page 0>, …], kid, signature}`. One signature over the whole list stopped working at
  about 285 entries (Cloud KMS signs at most 64 KiB), and a cart would have fetched every entry on every sync. Now a
  full page never changes again, so a sync fetches the index and, usually, one page. `rule:pages`: the index names
  exactly `ceil(count / page_size)` pages.
- **New kind: `popsnip.revocation-page` `{page, entries}`**, with no signature: the index names its id. A page holds
  1 to 256 entries numbered one after another, page *k* starting at entry `256k + 1` (`rule:page_numbers`). Its
  signer in `SIGNER` is `"index"`.
- **New: `paginate(entries)` and `check_list(index, pages)`** in both twins (JS: `paginate`, and `checkList`, a
  Promise). `check_list` gives every entry when the pages are exactly the ones a checked index names: the right ids,
  in order, every page but the last full, `count` entries in all; anything else is `rule:list`.
- **New: `bollardeck.popsnip.accept(app, release, files, log, head, certs, root_records, revocations, pinned)`**, the
  device check for a Pop Snip app, in Python: `Verdict(ok, code, detail)`, the first refusal
  naming the code (`cert`, `head`, `log`, `launch_key_revoked`, `no_binding`, `rekey_sig`, `repeated_challenge`,
  `not_published`, `version`, `wrong_key`, `release_signature`, `files`, `list_signature`, `list_key_revoked`,
  `list_pages`, `revoked_release`, `revoked_app`, `revoked_key`). It reads nothing but its arguments (no environment,
  disk or network), has no unsigned mode, and takes no pass. `conformance/popsnip/accept.json`: a signed history and
  its variants, and 43 cases. The JavaScript twin follows in a later version.
  - **`held_head` and `held_list`**: what the device already holds. A log or a
    list that does not extend them is refused (`rollback`, `list_rollback`), so a shorter log written from seq 1 by a
    compromised key, an older list or no list never wins. None means nothing held yet; images should bake both in.
  - **Any head signed by a root-revoked key is refused, at any seq, unless a reaffirmation names that head's seq and
    `head_hash`** (below `after_seq` too, or a device behind the cut could be forked by true
    entries plus forged ones under a head by the revoked key). Entries at or below `after_seq` still count under a
    good head. 43 cases
    (`launch_key_revoked`); every valid cancel counts, whatever other cancel names the same seq; a root record no
    pinned key signed refuses (`roots`); malformed arguments refuse (`malformed`), never raise.
- **New optional field on `popsnip.revocations`: `resigned_after`**, the revoked launch key whose list this index
  re-signs. After a root revocation the service's new key re-signs the pages as they are, and
  the owner corrects with new entries; the field says so to every reader. A key never re-signs its own list
  (`rule:resigned_after`).
- **New: `check_extends(old, old_entries, new, new_entries)`** (JS `checkExtends`): a newer list grows the one held,
  with a higher seq, no fewer entries, the held entries first and unchanged, and the same full pages; otherwise
  `rule:extends`. A reader never takes a list that drops or rewrites what it holds, even when every index in it is
  validly signed. `lists.extensions`: 7 cases.
- **New vectors, `states`: an app's account and key at a log position** (the key walk the device check
  and the service's registry share). A change counts for an entry only if its seq is lower and its `effective_at`
  is not after the entry's time; changes take effect in `effective_at` order, then seq. A real signed log of 7
  entries and 9 hand-written answers, including a release logged in the same second as a rotation, and a delayed
  change overtaken by an immediate one.
- `conformance/popsnip/records.json`: 143 records (the revocation cases now on pages, 11 new), `page_size`, and
  `lists`: 8 whole-list cases over pages and indexes written once by name (two pages of 257 entries, an empty list,
  pages swapped, missing or changed, a short page before the last, a count the pages don't hold).
- **`MIN_BOLLAWAX` is now 0.3.7**, the Bollawax this version was tested against: Bollawax 0.3.6 writes the revocation
  list unpaged. **`SPEAKS` is unchanged** (`popsnip: "popsnip/1"`): Bollawax 0.3.6 shipped its Pop Snip service
  switched off, so no unpaged list was ever published, and a 0.4.0 reader refuses a paged list rather than misreading
  it.

## 0.4.0 (2026-11-16)

Shipped with Bollawax 0.3.6. **Mostly additive, with two stricter checks.** Breaks first:

- **Changed meaning: `bollardeck.pxs` reads `HEAD` as strict JSON (the PXS specification, §5).** A new public
  `pxs.loads(text)` takes RFC 8259 and no more: no `NaN` or `Infinity`, every number one a 64-bit float
  holds (`1e400` is refused), every whole number one 64 signed bits hold, and at most 32 lists and objects
  one inside another, counted before parsing so it never raises `RecursionError` (a deep `HEAD` did on
  Python 3.11). `_check_head` uses it in place of `json.loads`, so `validate` now reports V7 for a `HEAD`
  it used to pass, as the Pop Snip engine's reader already did. `conformance/pxs/blocks.json`: 43 vectors
  (8 new: `v7-head-nan`, `v7-head-infinity`, `v7-head-number-too-large`, `v7-head-wide-integer`,
  `v7-head-nested-33`, `v7-head-nested-1500`, `head-nested-32`, `head-widest-integers`).
- **`bollardeck.corpus._ed25519.verify` refuses a public key or an `R` of small order** (the 8 torsion points), as
  libsodium does. Such a key has no secret behind it: the identity point "signs" every message. No real key or
  signature is affected.

New: `bollardeck.popsnip`, and `SPEAKS` gains `popsnip: "popsnip/1"`.

- **`bollardeck.popsnip`, a new part** (`python/bollardeck/popsnip/`, `js/bollardeck.popsnip.js`): the signed records
  of Pop Snip apps, the third-party apps that live at `<name>.popsnip.app`.
  - Twelve kinds:
    - the launch-key certificate, its revocation, and a reaffirmation (signed by the release key);
    - launch, publish, rekey, rekey-cancel, the log head and the revocation list (signed by a launch key);
    - the release manifest, the key proof and the rekey request (signed by the developer's key; a rekey
      request's signature travels as the rotation's `old_key_sig`).
  - **One canonical form:** the record minus `signature`, keys sorted, no spaces, printable ASCII strings and safe
    integers only. Every signature covers `popsnip/1\n` plus that form, so a Pop Snip signature can never pass as a
    signature on a Bollawax release record.
  - **Strict parsers in both languages:** no repeated keys, no fractions, no `NaN`, nesting at most 32 deep.
    Depth is counted over the text first, without recursion, so deep input is `bad_json` before anything else.
    An integer literal past 2⁵³−1 is refused as `bad_number`, however long.
  - **The same refusal codes in both languages.** `check(record, signed=False)` checks a record about to be
    signed. Every signer checks before signing and again after.
  - Vectors in `conformance/popsnip/records.json`, written by `tools/popsnip_vectors.py`, with real Ed25519
    signatures by test keys whose seeds are printed there.
  - Public keys in records must be able to sign: the canonical encoding of a point on the curve, not of small
    order. That's checked in both twins (`isPublicKey` in JS). A challenge stays 32 bytes of anything.
  - `data-parts` takes `popsnip`.

## 0.3.0 (2026-11-12)

Shipped with Bollawax 0.3.0. **Mostly additive, with breaks.** Nobody outside Bollawax used 0.2.0, so
these changes are noted here and not deprecated first. Each is marked "Changed meaning" below unless it
says otherwise:

- the gesture engine reads two kinds of late key event differently;
- a `HubClient` keeps a person's manifest in memory, not on disk;
- `attest.verify_attestation` binds a manifest's signed fields, so a rights change needs a new edition;
- the licence gains a ninth capability, `stream_render`, off for `full` and `morpus_only`;
- the keymap's pocket context gives button 2 a triple tap;
- `bollardeck.deck` is no longer a placeholder, and the schema validator refuses NaN and infinities.

New parts: `bollardeck.help`, `bollardeck.pxs`, `bollardeck.deck`, and the `nowplaying` and `transport` schemas.

- **`bollardeck.help`, a new part** (`js/bollardeck.help.js`, page helpers in `js/bollardeck.dom.js`,
  `python/bollardeck/help.py`): help content keyed by page and scenario (`help-pack/1`), eight struggle
  detectors and the rules for offering help without nagging (`help.engine`), and scripts that drive the
  help boxes for tours and recorded videos (`help-director/1`, `help.play`, WebVTT captions). The page
  helpers never set a `style` attribute. Constants `HELP_*`; schemas `help-pack`, `help-director` with
  vectors; `data-parts` takes `help`.
- **`bollardeck.pxs`: read, write and validate `.pxs`, the Pop Snip format** (Pompas' extended song format,
  PXS specification v1): an IT module followed by a PXS block (a 16-byte header, typed chunks, and a 12-byte
  footer with the block's offset and a CRC-32). `validate(data)` applies rules V1-V9 with the amendments agreed
  with Amorphus (detection by content, HEAD checked for meaning, only HEAD's flags checked) and never raises;
  `attach(module, chunks)` writes a block (chunks other than HEAD deflated) and the `PXS1` fingerprint;
  `read_chunks(data)` reads them back; `measure_it(data)` is the IT structure check and finds the module's end.
  `conformance/pxs/blocks.json`: 35 vectors (11 valid, one or more invalid per rule), written by
  `tools/pxs_vectors.py` from a made-up module.
- **`cues.at()` and `cues.compile()` no longer need `bollardeck.schema.js`.** A page that loads only
  `bollardeck.js` and the cue part could not draw a cue list: checking it threw "checking a cue list
  needs bollardeck.schema". Without the validator, `cues.problems()` now checks the `cue` schema's
  rules itself (the same verdict on every vector) and reports them with the same pointers, keywords
  and text; with it loaded, the schema is asked as before. `cues.run(..., {properties: false})` works
  on such a page. Nothing that worked changes.
- **The gesture engine's clock can be read, and a host time after the host's last is never refused.**
  When `key()` places an announced press by its beginning (rule 9), its release may land at
  `began + hold_ms`, later than any time the host gave; `tick`, `down`, `up` or `cancel` with a later
  host time then raised "time ran backwards". Such a time is now read as the engine's clock; a time
  behind the host's own last one still raises. New: `engine.now_ms` (JS `engine.nowMs()`).
- **Changed meaning: a release read more than `PRESS_LOST_MS` after its announcement is still that
  press.** `key()` matched the release only after giving up announcements older than
  `PRESS_LOST_MS`, so a late-read release was placed at its reading and chained with taps made after
  it. It is now matched first and placed at its announcement; only announcements nothing is read for
  are given up.
- **Changed meaning: a press judged by its own two times closes a chain's window that closed before
  it began.** A late key event whose press began after the pending chain's window had closed (an
  announcement held the window, and was lost) joined that chain. The chain is now reported as it
  stood when its window closed, and the press starts its own.
- Vectors: `key-engine-clock-ahead-reads-a-later-host-time-as-its-own`,
  `key-engine-clock-ahead-still-refuses-a-time-behind-the-host-s`,
  `key-release-read-after-press-lost-ms-is-matched-before-the-hint-is-given-up`,
  `key-press-judged-by-its-own-times-closes-a-window-that-closed-before-it-began`.
- **`ManifestRefused.manifest`**: the manifest that was refused, as plain dicts and lists that are the
  caller's own (None when there was nothing to read). A host no longer has to read the cache's copy
  after a refusal.
- **Changed meaning: a person's manifest is never written to disk.** What a `HubClient` fetches for a
  named person (`acting_for`: a manifest with the owner's address and the access list, a listing)
  is held in that client's memory, where ETag revalidation and the offline fallback still work for
  as long as the client lives; nothing is written under `<cache>/.for/`. `HubClient(...,
  keep_for_person=True)` keeps the 0.2.0 behaviour (a separate copy on disk per person). What a client holds
  for people is bounded (`HELD_MAX`, the least used first out) and `HubClient.forget(person)` lets
  it go.
- **`Corpus.open_art_ranged(name, verdict, byte_range=None, range_header=None)`**: one cover image,
  streamed for a relay, as `open_audio_ranged` streams a recording (the source's status, 200, 206 or
  416, and the headers a relay passes on). Needs "store_art". `name` is an art file's name or a row
  from `tracks()`, whose `art_url` must point into the corpus's art. Hub and local corpora. A row's
  `art_url` and `audio_url` are checked segment by segment after decoding (no empty, `.` or `..`
  segment, even percent-encoded twice), not by prefix alone.
- **`Corpus.attestation_record()`**: the signed edition record the manifest's `attestation` block names,
  as `attest.verify_attestation()`'s keyword arguments (None for a file that could not be had). A
  local corpus reads `<root>/locker/<edition>/`; a hub corpus asks the hub's new route
  `/api/corpi/<ID>/attestation/<edition>/<file>`, which a hub serves where it serves the whole
  manifest (never to the study-only engine for a corpus that is not public), and keeps a whole record
  beside the cached corpus, so a corpus mirrored from a hub can be checked like a local one
  (Bollawax 0.3.0). Metadata: no verdict needed.
- **Changed meaning: `attest.verify_attestation` binds the manifest's signed fields.** `record` fails unless the
  manifest says what the edition signed (`attest.signed_field_problems`): the corpus's id, number, slug, name,
  artist and edition label; the licence's scope and its eight permission flags (`SIGNED_FLAGS`, read as the SDK
  reads a block on paper); consent; the owner's address. Everything the edition does not sign may change after it
  without a new edition: packing fields, counts, descriptions, the licence block's bookkeeping; `access` and
  `visibility` are not signed. A record that states no licence does not vouch for the manifest's rights. Before,
  a manifest rewritten around a genuine attestation block (another licence or owner) verified.
- **Licence: a ninth capability, `stream_render`** (Bollawax 0.3.0): the corpus's MIDI may be
  played rendered through Pop Boll's own sounds, never a recording. On by default for `public_domain_midi`, off for
  `full` and `morpus_only` unless the block grants it; `stream_audio` still means recordings. The schema, both
  bindings' scope tables, `attest.SIGNED_FLAGS` (an edition signed before the ninth flag existed holds it at the signed
  scope's default: such an edition still verifies, and a manifest cannot grant `stream_render` around it) and gate vectors. New: `gate.listen(manifest, identity, render=False)` (JS
  `corpus.listen(manifest, identity, render)`): a recording needs `stream_audio`, a render `stream_render`.
- **Keymap: `tap2x3` in the pocket context is `pair`** (a new verb in `POCKET_VERBS`): it starts pairing the cart with
  a person's Pop Boll account (Bollawax 0.3.0). In the pocket context button 2 now has a triple
  tap, so `combos_from_keymap(KEYMAP, ("pocket",))` gives it (2, 3); with no context nothing changes.
- `parse_key_line` says what it always did: the word `down` is lower case only, and a line with
  `DOWN` is not a key line. No change in meaning.
- **Schemas `nowplaying` and `transport`**, with vectors: what a player is playing (the bollardeck
  `nowplaying` body; `song_id`, `title` and `position_ms` required, unknown members allowed, optional
  `lane` 0 to 3 and `player`), and the transport and volume writes that control one (`cmd` play, pause,
  stop, next, prev; volume `set` 0 to 1 or `step` ±1, never both; optional `lane`). Shared by docks,
  watches and players (Bollawax 0.3.0).
- **`bollardeck.deck`, a minimal deck service and its client** (a draft, as Part A is): the bollardeck/1
  handshake (`hello`, `welcome`), grants with the spec's defaults and the user's consent per dock
  (`Deck.approve`, `revoke`; `consent=` is told what waits), subscriptions, writes answered by a
  registered handler (`volume` and `transport` checked against the `transport` schema; `nowplaying`
  published only when it fits its schema), the spec's error codes. Transports: in one process
  (`pair`) and a Unix-domain socket (`serve_unix`, `connect_unix`); BLE and USB come with the cart's
  deck. `bollardeck.deck.sim` has a made-up player and dock; `examples/deck_client.py` is a sample
  third-party client (Bollawax 0.3.0).
  Hardened before release: consent is applied only to a session whose transport proved who the peer is (on
  a Unix socket, the kernel's peer uid, and on Linux its executable; `peer_identity`), never to vid
  and pid alone; NaN and Infinity are bad requests, and the schema validator refuses non-finite
  numbers; a handler that fails is answered `busy` or `bad_request` and the session lives on; each
  Unix-socket peer has a bounded outbox and its own writer, and one that stops reading is
  disconnected without holding up `publish`; requests past `rate` (20 a second) are `rate_limited`;
  `limits["max_line"]` is enforced and never above `MAX_LINE`; a server takes at most `max_sessions`
  connections and lets closed ones go; client callbacks that fail are logged, a callback may not call
  `request()`, and `inbox` keeps only what no callback took, the newest `INBOX`.
  Also: a callback may not call `request()` on any transport, in-process `pair()`
  included (it deadlocked there); the state topics (`COALESCED`: state, nowplaying, corpus, led,
  led_ring, matrix) keep only their latest message in a peer's outbox, so a burst never drops a peer
  that is reading; `serve_unix` replaces only a stale socket at its path (a regular file is
  FileExistsError, a live deck's socket EADDRINUSE) and `close()` removes only its own; a macOS
  `xucred` of an unknown version fails closed, and a Linux peer whose executable cannot be read is
  known by its uid alone, said once in the log. A session that ends still writes what it
  had queued (the peer refused with `no_common_api` reads why), and writes from all sessions
  together are limited too (`write_rate`, 40 a second).

## 0.2.0 (2026-11-11)

Additions for a cart: a handheld player that plays on its own and in a dock. Bollawax 0.2.5 is built
on it. **Additive only**: no existing vector or schema changes meaning, `PowerState` above all, and
with no context named every keymap answer and the default combos are what they were in 0.1.0. No cart
exists yet: the cart's additions are tested against the simulated board, not on hardware.

- **Detection finds a Uno Q by its board model and inside a container.** The built-in rule also takes the
  model `Arduino SA,Imola`, which the board's device tree says. With no device-tree model at all (a
  container: Docker hides `/sys/firmware`), a Unix socket at `$ARDUINO_ROUTER_SOCKET` (default
  `/var/run/arduino-router.sock`) means `unoq`; a `tcp://` address or a plain file does not. A model naming
  another board still decides, registered families' rules still come first, and `$BOLLAWAX_HAL` still
  wins. `detection.router_socket(env)`, constants `ROUTER_SOCKET_ENV`, `ROUTER_SOCKET`, `UNOQ_MODELS`.
- **Keymap: an optional `pocket` context.** A keymap may carry a `pocket` map (player verbs for a cart
  with no dock), looked at before `idle` when no prompt is showing and the caller names the context:
  `keymap.resolve(gesture, prompt=None, keymap=KEYMAP, context=None)`, JS `resolve(g, p, keymap,
  context)`. `combos_from_keymap(keymap, contexts=())` and JS `combosFromKeymap(keymap, contexts)`,
  `keymap.combos(keymap, contexts)`. Constants `KEYMAP_CONTEXTS`, `POCKET_VERBS`; the platform `KEYMAP`
  gains its `pocket` map. With no context every answer and the default combos are what they were.
- **`PowerState.source` and `PowerState.charging`**, with defaults ("unknown", None): the three-field
  form means what it did. Constant `POWER_SOURCES`.
- **Optional hal subsystems**: `FilePlayer` (`play_file(path, offset_ms) -> Handle`, `can_play`),
  `AudioRoutes` with `Route` (`available`, `current`, `select`, `volume`, `set_volume`), `Bluetooth`
  with `BtDevice` (`devices`, `pair`, `pairing_until`, `connect`, `disconnect`, `forget`);
  `Board.files()`, `Board.routes()`, `Board.bluetooth()`. A board module without them gets the
  simulator's (`sim.NullFiles`, `sim.SimRoutes` from `$BOLLAWAX_SIM_ROUTES`, `sim.SimBluetooth`).
  `HAL_API` stays 1. Constant `AUDIO_ROUTES`.
- **Descriptors**: schemas `dock-descriptor` (version 1, a draft for Bollard v2, with the cart-made
  classes `none` and `plain` and the charge budget `charge_w`) and `cart-descriptor` (version 1), with
  vectors. `device.dock` gains `NO_DOCK`, `PLAIN`, `problems`, `charge_budget_w`, `role_for`,
  `is_dock`; `AVAILABLE` stays False (the `Dock` protocol still waits for Bollard v2).
  New `device.cart` (`problems`, `ROLES`). Constant `CART_ROLES`.
- **Decoders for `play_file`**: `device.decode`, standard library only. A registry (`register`,
  `unregister`, `decoders`, `for_path`) asked newest first, so a program can add a container of its
  own; built-ins `webm-opus` (a small Matroska reader, `webm_packets`, with libopus through ctypes),
  `sndfile` (libsndfile through ctypes: MP3, FLAC, Ogg, WAV, AIFF) and `faad` (the program, for AAC in
  MP4/M4A or ADTS). Each reports `available()` False where its library or program is missing.
- **Decoders: one error type, and faad that cannot hang `open`**:
  `decode.DecodeError` (a `ValueError`) for every damaged or unreadable file, from any
  decoder, in `open` or in `read` (a short field, which raised `struct.error`, included); faad gets the
  file's absolute path, has `FAAD_HEADER_S` (10 s) to begin its WAV before it is stopped, and reaches a
  raw ADTS offset on the first `read` rather than inside `open`.

## 0.1.0 (2026-11-10)

The first version. Bollawax 0.2.4 is built on it. It contains:

- **Schemas and constants.** JSON Schemas for eleven formats with one validator in Python and
  JavaScript, and `constants/constants.json`, the one source of the timings, button names, cue
  values and the keymap, generated into both languages. The maker registry, `constants/makers.json`.
- **The corpus client and its gate** (`bollardeck.corpus`): a corpus reader that hands over
  content only against a verdict, the licence gate, the hub client with its cache, attestation
  checks and the discovery file of a self-hosted corpus. The browser has the gate and a `fetch`
  hub client.
- **The device layer** (`bollardeck.device`): the hardware abstraction with a simulated board,
  device identity and maker codes, the gesture engine, button cues and the keymap.
- **Routines** (`bollardeck.routines`): the loader, the guard, the limits, the manifest reader, a
  simulator and a command line.
- **The browser binding** (`js/`): plain scripts with no build step, for a page and for Node.
- **The matrix engine** (`bollardeck.matrix` and `js/bollardeck.matrix.js`): every frame of the
  13 × 8 LED matrix, the same in both languages.
- **Conformance vectors** (`conformance/`): what any implementation of the above must pass.

The dock protocol, the deck client and the Glass Snipler types are placeholders.

### Notes from Bollawax's adoption

Before this version was cut, Bollawax's own adoption of the SDK asked for the things below. Each
is an addition unless its line says **changed**; "changed" compares with the SDK as Bollawax first
pinned it, before 0.1.0.

#### Device

- **Key lines for a press beginning.** `hal.base.parse_key_line` reads `<button> down [t_ms]` as
  `{"t": "key", "i": button, "down": 1, "t_ms": ...}`; `hal.base.key_line(button, down=True, t_ms=...)`
  writes it; `hal.sim.StdinKeys` yields it. `hal.base.KEY_DOWN_WORD`.
- **Changed: a press beginning is only a hint**, in `GestureEngine.key` and the JS `engine.key`. A
  press is a tap or a hold by the `hold_ms` its release states, never by when the release is read.
  A beginning with no release is a lost press: it yields nothing and the next press on that button
  is its own. Before, `key({"down": 1})` fed an edge, so a late or lost release became a hold.
  What the hint does: it keeps a tick from reporting pending taps as singles while the next press
  of their chain is held (for at most `hold_ms`).
- `GestureEngine(press_lost_ms=)`, `engine.waiting(button=None)`, the constant `PRESS_LOST_MS`
  (5000). JS: `pressLostMs`, `engine.waiting(b)`.
- **`Gesture.hold_ms`** (JS `holdMs`): how long the press lasted. **Changed:** `Gesture` has a
  sixth field, so a `Gesture` built by hand with five no longer equals the engine's.
- `GestureEngine.set_combos(combos)` and JS `engine.setCombos(combos)`: change the combos of a
  running engine without losing a press in flight or a pending tap.
- The gesture vectors' events gained `{"edge": "key", "key": {...}}` and `{"edge": "combos", ...}`,
  and an emitted gesture may state `hold_ms`. 24 new timelines.
- A release is matched to its announcement before the hint is believed: one that states its own
  time belongs only when it began within `PRESS_MATCH_MS` (100, a new constant) of it. A release
  with no `hold_ms` is never a hold from a hint's age. `up()` and `cancel()` end a hint for their
  button. A key event from the past never moves a chain's window back.
- The engine's docstring says it raises on a time that runs backwards and that clamping is the
  host's job.
- **A routine manifest may be JSON.** `routines.yamlsubset.loads` reads a document that is one
  JSON object (and a one-line flow mapping at the top), as `spec/bollardeck.md` says. Nothing
  nested more than 64 deep, and no `\ud800` to `\udfff` escape. 23 vectors.
- `device.keymap.is_gesture(name)`.

#### Browser

- `gestures.listen`: `opts.onChange(button, isDown, {tMs, raw, kind})` for every press beginning
  and ending, and `listening.setCombos(combos)`.
- `cues.apply(elements, entries, {properties: false, undriven: "off"})`, and the same two options
  on `cues.run`.
- `data-parts` takes a list: `data-parts="cues matrix"`. An empty `data-parts` still loads
  every part.
- `gestures.listen`: the engine is fed even when `onChange` throws, and `stop()` cancels a press
  in flight, telling `onChange` (kind `"cancel"`). **Changed:** `stop()` used to leave a press
  in flight as it was.
- `keymap.isGesture(name)`.

#### Corpus

- **Who a client acts for.** `HubClient(acting_for=)`, `hub.corpus(id, acting_for=)`,
  `hub.listing(acting_for=)`, `hub.corpora(acting_for=)`, sent as `X-Pop-For`. JS: `actingFor`.
  **Changed:** `listing(for_email=)` sends the header too; the address is no longer in the URL
  (`?for=`). A corpus fetched for a person is cached under `<cache>/.for/<hash>/`.
- **Reasons on errors.** `CorpusUnavailable.reason` / `.status`, `NotAvailable.reason` / `.status`
  (`model.NOT_AVAILABLE_REASONS`), `HubError.status`. JS the same. **Changed (JS):** a track
  listing the hub cannot be reached for rejects with `NotAvailable` (`unreachable`), as Python does.
- `Corpus.open_audio_ranged(file, verdict, byte_range=, range_header=)` returns a `RangedAudio`
  (status 200, 206 or 416, the headers a relay passes on). `open_audio` takes a suffix range
  `(None, n)`. **Changed:** `open_audio` checks its `byte_range` before asking (a range it
  cannot read, such as `(5, 2)`, is `NotAvailable`, `bad_range`, where it was sent to the hub
  as written), and every audio open asks for the bytes uncompressed (`Accept-Encoding: identity`).
- `HubClient.listing()` returns a `Listing` (a list) whose `from_cache` says when the hub was not
  reached.
- The DNA is revalidated with its ETag instead of fetched again. `Corpus.manifest_view()` is a
  read-only manifest with no copy per call; `copy.deepcopy`, `copy.copy` and `pickle` of it give
  plain dicts and lists.
- A name for `acting_for` that is not a string raises. A hub answer that is not HTTP is
  `HubUnreachable`. JS sends `cache: "no-store"` on a request made in a person's name; a hub must
  answer corpus routes with `Vary: X-Pop-For, Authorization`.
- **Changed: the gate has a floor under its clock for a corpus held in a cache.** It reads no
  time earlier than the last revalidation (`Standing.revalidated_at`) or than the new
  `Standing.witnessed_at`, the latest reading of the device's own clock at a revalidation attempt
  since then. So a clock set back while the hub cannot be reached does not reopen a licence that
  was seen to close. It is not a seal: the reading is taken at attempts (at most `retry_after`
  apart while offline), and a hub answer starts the floor again from that moment, which is also
  how one wrong reading of the clock heals. Python and JS.
- **Changed:** `Corpus.may(now=...)` judges at `now` and does nothing else. Revalidation runs on
  the corpus's own clock; asking about another time writes nothing and asks nobody.
- `HubClient.corpus_gate()` (JS `hub.corpusGate()`): the hub's `corpus_gate` in `/api/version`.
- The corpus-manifest schema's description of `licence` says a missing block is refused.
- Vectors: redaction (18 gate cases, one schema vector), the clock set back (11 cases).

#### Matrix

- **`bollardeck.matrix`**, the Python LED matrix frame engine, the twin of `js/bollardeck.matrix.js`.
- `tools/pin_vectors.py` pins the matrix vectors from the SDK's own Python. 150 new matrix
  vectors (1,135).
- **Changed (JS):** a temperament whose `period`, `floor` or `span` is `null` is read as 0, as the
  device reads it, not as the default.
