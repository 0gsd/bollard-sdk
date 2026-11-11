# Changelog

What each version of the Bollawax Bollard SDK added and changed. The SDK has its own version, and
its tags are the version number (`0.1.0`, `0.2.0`); it is not the Bollawax image version.

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
