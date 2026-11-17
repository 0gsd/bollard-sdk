# bollardeck API

Version 0.2-draft · Status: speculative draft · Updated 2026-11-17 · As of Bollawax 0.3.7 and Bollard SDK 0.5.0

> **Speculative draft.** No Pop Boll hardware has shipped, and most of this API has not run against a real Boll yet. Message names, fields and limits will change without notice, and nothing here is an offer, a commitment or a promise of compatibility. We would love to hear about partnership, OEM and dev-kit ideas: use the contact form on this site.

> **Note:** The band's brain is a removable cart, the **Bolltridge**. It lives in the ball, and the same cart can also go into other docks, such as the Pop Snipler. The deck is the cart's service, so where Part A says "the Boll" it means the deck on the cart. Part A was written before the cart and is still a draft: the SDK has a minimal draft deck service for it (§17.1), and no Pop Boll runs one yet. Part B is built. The old Part C (foot cartridges) is retired; Part C is now the Bollard SDK.

bollardeck is the software side of Bollard: everything above the physical connector, which is specified in the [Bollard Physical Specification](bollard.md). It is also the import name of the **Bollard SDK**, the open library (Apache-2.0) that the Pop Boll's own image and popboll.com are built on. The [overview page](index.md) explains how the pieces fit together.

## 1. Overview

| Part | For | What it covers |
| :--- | :--- | :--- |
| **A. Docks** (§2–§10) | anyone building a dock or an accessory | what a dock can read from a Pop Boll (now playing, MRPH5 stems, LED frames, buttons, battery, corpus labels) and what it can send (audio routing, volume, transport, remix and stem-balance requests, light sync), over USB or BLE |
| **B. Routines** (§11–§16) | anyone who wants to change how the Boll writes songs | custom Python logic that runs inside the song factory on your own Boll, working only with the corpora already on the device |
| **C. The Bollard SDK** (§17–§20) | anyone writing software against the platform | what `import bollardeck` gives you today: routines, buttons and gestures, cues, the keymap, the light matrix engine, the corpus client and its gate, help, Pop Snip files, a draft deck and the schemas; and what is decided about the cart and its docks |

| Item | Version |
| :--- | :--- |
| This document | 0.2-draft |
| Bollard SDK | 0.5.0 (the first, 0.1.0, shipped with Bollawax 0.2.4) |
| Wire protocol (Part A) | `bollardeck/1` |
| Message envelope | `"v": 1` |
| Routine API (Part B) | `api: 1` |
| Corpus licence block | `popboll.licence/1` |
| Engagement keymap | `"v": 2` |

**Status.**

- **Built:** Part B (routines) and everything in Part C marked as shipped. The Pop Boll's image and popboll.com run on the same SDK code.
- **Not built:** the deck service of Part A on a device (the USB and BLE transports, the BLE layout, the consent prompts on a Boll), sign-in, the sandbox for third-party apps, the registry, and the Pop Snipler's capability boundary. They are planned, and this page gives no date for them. Meanwhile the SDK's `bollardeck.deck` is a minimal draft that runs in one process or over a Unix socket, `bollardeck.device.dock` holds only draft dock and cart descriptors, and `bollardeck.snipler` is a placeholder.
- §22 lists everything that is still open.

Conventions:

- The key words **MUST**, **MUST NOT**, **SHOULD**, **RECOMMENDED** and **MAY** are used as described in RFC 2119.
- JSON examples are sometimes wrapped for reading. On the wire every message is a single line.
- An ellipsis (…) in an example stands for an elided value.
- Latencies and transfer rates marked *estimate* have not been measured.

## 2. Part A: Docks

**Read this part as a draft of the message shapes.** No device runs a deck service yet (the SDK's draft deck, §17.1, runs in one process or over a Unix socket), and the part was written when the computer was built into the ball. What the cart changes:

- The deck runs on the cart. "The Boll" below means the deck on the cart, and the cart is the USB host and the only radio.
- A Pop Boll or a Pop Snipler is itself a dock for the cart. How such a dock introduces itself (its descriptor and its slots) is decided in outline (§20) and not written.
- The transports, the BLE roles, the `dock.profile` values and the light messages below still describe the Bollard v1 foot. They will be rewritten with Bollard v2. No message yet carries a dock's encoder or its EJECT button.
- Buttons are numbered 1, 2 and 3 on the SDK's surface (§18). On the `bollardeck/1` wire of this part they keep the labels `inner`, `middle` and `outer`.

A **dock** is anything that mates with the Boll's foot, on any Bollard profile, or an accessory with no physical connection that talks over BLE. A dock always talks to the Boll's bollardeck service. The song factory itself never talks to a dock.

| Dock | Transport |
| :--- | :--- |
| USB-C profile | USB CDC-ACM (REQUIRED by Bollard rule C3) |
| Full profile, active-USB module | USB CDC-ACM |
| Full profile, passive module | BLE only |
| Lite or Passive profile | BLE only: there is no data path on the connector |
| No physical connection | BLE |

A session opens after the physical layer has worked out what docked ([Bollard §12](bollard.md#12-enumeration-and-identity)):

```text
 physical attach ──► (Full)  CHAIN and I2C header: vid, pid, class bit 11 "bollardeck"
                 └─► (USB-C) USB descriptors: a CDC interface named "bollardeck"
                 └─► (any)   BLE: the DECK_INFO characteristic
 dock  -> hello      vid and pid MUST equal the physical header's, when there is one
 boll  -> welcome    capabilities granted now, and those pending the user's consent
 boll  -> state, nowplaying, …   only the topics that are granted and subscribed
```

## 3. Transports

### 3.1 USB CDC-ACM

- The dock is the USB device and the Boll stays the USB host (Bollard rule U1).
- The dock exposes a CDC-ACM interface whose **interface string is `bollardeck`**. The Boll binds the interface by that string, and the baud rate is ignored.
- One CDC interface carries one session.
- Latency is about 1–2 ms (estimate).

### 3.2 BLE GATT

- The dock is a peripheral and the Boll is the central.
- Pairing uses LE Secure Connections. The first pairing needs a long press of the Boll's inner (play/pause) button, button 1.
- Latency is about 15–30 ms (estimate).
- Airtime is shared with Bluetooth audio and the Boll's other accessories, so the Boll MAY lower `led` messages to 4–10 Hz on BLE.

The UUIDs below are **placeholders**. A random 128-bit base will be allocated, and the final UUIDs registered, with version 1.0.

| Item | UUID (placeholder) | Properties | Content |
| :--- | :--- | :--- | :--- |
| bollardeck service | `b011a2d0-0000-4c6b-9e1a-6f2d0b011a2d` | primary | advertised in the scan response, with the dock's product name |
| `DECK_TX` (Boll → dock) | `b011a2d0-0001-4c6b-9e1a-6f2d0b011a2d` | notify | the JSON-lines byte stream in ATT MTU-sized chunks (≤ 244 bytes with Data Length Extension), reassembled at each newline |
| `DECK_RX` (dock → Boll) | `b011a2d0-0002-4c6b-9e1a-6f2d0b011a2d` | write without response | the same, in the other direction |
| `DECK_INFO` | `b011a2d0-0003-4c6b-9e1a-6f2d0b011a2d` | read | `{"v":1,"api":["bollardeck/1"],"vid":…,"pid":…}`, so the Boll can filter before connecting |
| `DECK_LED` (optional) | `b011a2d0-0004-4c6b-9e1a-6f2d0b011a2d` | notify | binary LED frames (§6.3) for docks that want lights without parsing JSON |

## 4. Envelope and errors

### 4.1 Framing and envelope

- **JSON Lines.** Each message is one JSON object on one line, UTF-8, terminated by a newline (`\n`), at most 64 KiB.
- **Envelope.** Every message has `"v": 1` (the envelope version) and `"t": "<type>"`. All other fields are the payload, at the top level.
- **Requests and replies.** A request MAY carry `"id"`, an integer chosen by the sender. The reply carries `"re"` with that id.
- **Unknown fields MUST be ignored.** An unknown `t` is answered with an `unknown_type` error, and the session stays open.

```json
{"v":1,"t":"volume","id":12,"set":0.55}
{"v":1,"t":"ok","re":12}
```

### 4.2 Rates

- The Boll MAY drop or coalesce messages to keep the link healthy, but it never drops `button`, `remix_status` or `error`.
- A dock SHOULD keep its own requests to at most 20 per second.

### 4.3 Errors

```json
{"v":1,"t":"error","re":7,"code":"not_granted","msg":"stems needs the user's consent"}
```

| Code | Meaning |
| :--- | :--- |
| `unknown_type` | the message type is not known; the session stays open |
| `bad_request` | the message is malformed or a field is out of range |
| `not_granted` | the capability the message needs has not been granted |
| `pending_consent` | the capability is waiting for the user's consent on the Boll |
| `rate_limited` | the dock is sending too fast |
| `no_common_api` | the dock and the Boll share no protocol major version |
| `identity_mismatch` | the `hello` identity does not match the physical header |
| `not_found` | the requested song, bundle or item does not exist |
| `corpus_rules` | the corpus does not allow this (for example, stems of a corpus song) |
| `busy` | the Boll cannot take the request right now |

## 5. Handshake and capabilities

### 5.1 hello

The dock opens every session with `hello`.

```json
{"v":1,"t":"hello","id":1,"api":["bollardeck/1"],
 "dock":{"vendor":"Example Labs","product":"Bass Lean","vid":4617,"pid":49152,
         "profile":"usb-c","fw":"0.1","url":"https://example.org/bass-lean"},
 "want":["state","nowplaying","stems","beat","led","buttons","corpus"],
 "can":["remix","stem_balance","volume","transport","audio_out","audio_in","light_sync"]}
```

| Field | Meaning |
| :--- | :--- |
| `api` | every protocol major the dock speaks; the Boll picks the highest one in common |
| `dock.vendor`, `dock.product` | names shown in the Boll's UI |
| `dock.vid`, `dock.pid` | USB-style vendor and product IDs. A physically attached dock MUST send the same values as its Bollard header |
| `dock.profile` | the Bollard profile: `full`, `lite`, `usb-c` or `passive` |
| `dock.fw`, `dock.url` | firmware version and a product page |
| `want` | the topics the dock wants to read (capability flags of §5.4) |
| `can` | the things the dock wants to send or control |

### 5.2 welcome

```json
{"v":1,"t":"welcome","re":1,"api":"bollardeck/1",
 "boll":{"model":"Pop Boll Rev B","fw":"…","serial":null},
 "grants":["state","nowplaying","beat","led","buttons","corpus","volume","transport",
           "light_sync"],
 "pending":["stems","remix","stem_balance","audio_in"],
 "limits":{"led_hz":60,"max_line":65536}}
```

- `grants` are the capabilities the dock may use now.
- `pending` capabilities wait for the user's consent (§5.3).
- `boll.serial` is `null` unless the user has turned on "share serial with docks".
- `limits` gives the LED frame rate the Boll will send and the maximum line length.
- Granted topics named in `want` are sent from the start (the example dock in §10 relies on this). `subscribe` and `unsubscribe` change the set later (§7.1).
- A physical dock whose `hello` vid and pid do not match its header gets an `identity_mismatch` error, and the Boll then grants only `state` and `nowplaying`.

### 5.3 Consent

The first time a given dock asks for a consent capability, the user approves it on the Boll with a long press on the medallion, or in the Boll's local web UI. A dock is identified by its vid, pid and its USB serial number or BLE identity. When the grants change, the Boll sends:

```json
{"v":1,"t":"grants","grants":["state","nowplaying","beat","led","buttons","corpus","volume",
 "transport","light_sync","stems","stem_balance"]}
```

### 5.4 Capability flags

| Flag | Direction | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `state` | read | granted | battery, charging, volume, mode, online |
| `nowplaying` | read | granted | song metadata and position |
| `corpus` | read | granted | labels and ids of the active corpora (never their files) |
| `beat` | read | granted | beat and bar events |
| `led` | read | granted | persona colours |
| `led_ring` | read | granted | the full 24-LED light-ring frame |
| `matrix` | read | granted | optional: the 13 × 8 LED matrix frame and its RGB LEDs |
| `buttons` | read | granted | medallion button events |
| `stems` | read | **consent** | MRPH5 bundles of the current song (§8) |
| `volume`, `transport` | write | granted | volume and play, pause, stop, next, previous |
| `light_sync` | write | granted | the dock drives or offsets the Boll's lights (§7.7) |
| `remix`, `stem_balance` | write | **consent** | remix and re-balance requests (§7.4, §7.5) |
| `audio_out` | write | granted | the Boll's mix to the dock over USB Audio (§7.6); not over BLE |
| `audio_in` | write | **consent** | the dock's audio into the Boll over USB Audio (§7.6); not over BLE |

## 6. Boll to dock messages

### 6.1 Song and device state

| `t` | Rate | Grant | Content |
| :--- | :--- | :--- | :--- |
| `state` | on change | `state` | battery, charging and power source, volume (0–1), mode, whether the Boll is online, and what the factory is doing: `idle`, `planning`, `jamming`, `overdub`, `exporting` or `paused` |
| `nowplaying` | on change, and every 5 s | `nowplaying` | song id, title, origin, form, corpora, tempo, key, time signature, the part list, the routines that shaped the song, and the playback position |
| `corpus` | on change | `corpus` | the active corpora: id, label, number of songs, whether it is a remote corpus, and the edition |

```json
{"v":1,"t":"state","battery_pct":72,"charging":true,"source":"dock_vbus","volume":0.6,
 "mode":"playing","online":false,"factory":"jamming"}

{"v":1,"t":"nowplaying","song_id":"pb0042_d03_s012_…","title":"…","origin":"factory",
 "form":"single","corpus_ids":["0007-DEMO"],"corpus_labels":["PB 0007 — Demo corpus"],
 "bpm":118.0,"key":"A Major (Hexatonic Pop)","time_sig":"4/4",
 "parts":[{"index":1,"label":"Intro","category":"Intro","bar":1,"bars":8}],
 "routines":["mixolydian_bridge"],"position_ms":12345,"duration_ms":201000}

{"v":1,"t":"corpus","active":[{"id":"0007-DEMO","label":"PB 0007 — Demo corpus","songs":40,
 "remote":true}],"edition":"…"}
```

### 6.2 Stems, beats and buttons

| `t` | Rate | Grant | Content |
| :--- | :--- | :--- | :--- |
| `stems` | on song change | `stems` | the current song's MRPH5 stems: id, MIDI channel, role, musician persona, program, gain and mute, plus the bundle's size and SHA-256. `stems` is an empty list when the song has no bundle |
| `beat` | every beat | `beat` | bar, beat, whether it is a downbeat, tempo, and `at_ms` on the Boll's monotonic clock (use `ping` to learn the offset) |
| `button` | on event | `buttons` | `btn` is `inner`, `middle` or `outer` (ids `BTN_1_PLAY_PAUSE`, `BTN_2_ONLINE_UPLOAD`, `BTN_3_POWER`); `ev` is `tap`, `double`, `triple`, `hold`, `release` or `combo`. The Boll's own button actions still happen |
| `cues` | on change | `buttons` | what should be lit for each button: a list of `{"btn", "state", "role"}` with `btn` `inner`, `middle` or `outer`, `state` `off`, `on`, `pulse` (2 Hz) or `chase`, and `role` `a`, `b`, `c`, `live`, `go`, `warn` or null; at most one cue for a button, and an empty list clears them. The three buttons have no LEDs: a cue is rendered by the Boll's lights and matrix, the Pop Snipler's keys, or a dock |

`inner`, `middle` and `outer` are the wire's labels for buttons 1, 2 and 3. The SDK works in numbers and translates at the wire: `bollardeck.device.cues.to_wire` turns `[{"button": 1, "state": "pulse", "role": "go"}]` into `[{"btn": "inner", "state": "pulse", "role": "go"}]`, `from_wire` goes back, and `bollardeck.constants.BUTTONS` holds the number, label and id of each button. The `ev` words are older than the SDK's gesture engine and do not match its gesture names (§22).

```json
{"v":1,"t":"stems","song_id":"…","format":"mrph5/1",
 "stems":[{"id":"ch03_benthos","channel":3,"role":"bass","persona":"Benthos","program":33,
           "gain_db":0.0,"mute":false}],
 "bundle_bytes":48213,"sha256":"…"}

{"v":1,"t":"beat","bar":12,"beat":3,"downbeat":false,"bpm":118.0,"at_ms":918273}

{"v":1,"t":"button","btn":"inner","id":"BTN_1_PLAY_PAUSE","ev":"tap"}
```

### 6.3 LED frames

| `t` | Rate | Grant | Content |
| :--- | :--- | :--- | :--- |
| `led` | 60 Hz on USB, ≤ 10 Hz as JSON on BLE | `led` | the frame number and 16 persona colours. With `led_ring`, also `ring`: a hex string of 24 RGB triples, the 16 outer-ring LEDs first, then the 8 inner LEDs |
| `led_bin` | as `led` | `led` | the binary frame below, base64-encoded, for USB docks that subscribe to the `led_bin` topic |
| `matrix` | ≤ 15 Hz on USB, ≤ 5 Hz on BLE, only while subscribed and only when it changes | `matrix` | optional. The frame on the Boll's 13 × 8 LED matrix: `frame`, `t_ms`, `px` (208 hex characters: 104 pixels, row-major, 13 wide, row 0 on top, 0–255) and `rgb` (three colours: LED1, LED3, LED4). A dock with a display can mirror it |

```json
{"v":1,"t":"led","frame":4711,"personas":["#ff3355","…"],"ring":"ff3355…"}
{"v":1,"t":"led_bin","b64":"…"}
```

The binary LED frame is 78 bytes. It is what the optional `DECK_LED` BLE characteristic notifies, and what `led_bin` carries on USB.

| Offset | Size | Field |
| :-: | :-: | :--- |
| 0 | 2 | `frame_no`, unsigned, little-endian |
| 2 | 1 | flags: bit 0 beat, bit 1 downbeat |
| 3 | 1 | brightness |
| 4 | 72 | 24 × (R, G, B): 16 outer-ring LEDs, then 8 inner LEDs |
| 76 | 2 | reserved |

### 6.4 Replies and status

| `t` | When | Content |
| :--- | :--- | :--- |
| `blob` | reply to `get` | the size, SHA-256 and number of chunks that follow |
| `chunk` | after `blob` | one chunk: sequence number and up to 2,048 raw bytes as base64 |
| `remix_status` | on change | the state of a `stem_balance` or `remix` request: `applied`, `queued`, `rendering`, `done` (with `new_song_id`) or `refused` |
| `grants` | when grants change | the full list of current grants (§5.3) |
| `pong` | reply to `ping` | the Boll's monotonic clock in ms |
| `ok` | reply | the request succeeded |
| `error` | reply, or unsolicited | a code from §4.3 and an optional message |

```json
{"v":1,"t":"blob","re":7,"size":48213,"sha256":"…","chunks":24}
{"v":1,"t":"chunk","re":7,"seq":0,"b64":"…"}
{"v":1,"t":"remix_status","re":4,"state":"done","song_id":"…","new_song_id":"…"}
{"v":1,"t":"pong","re":9,"boll_ms":918300}
{"v":1,"t":"ok","re":12}
{"v":1,"t":"error","re":4,"code":"pending_consent","msg":"remix is waiting for the user"}
```

## 7. Dock to Boll messages

### 7.1 Session

| `t` | Grant | Meaning |
| :--- | :--- | :--- |
| `hello` | none | opens the session (§5.1) |
| `subscribe`, `unsubscribe` | the topic's own | add or remove topics, for example `led_ring`, `beat` or `led_bin` |
| `ping` | none | ask for the Boll's clock, to align `at_ms` timestamps |

```json
{"v":1,"t":"subscribe","topics":["led_ring","beat"]}
{"v":1,"t":"unsubscribe","topics":["beat"]}
{"v":1,"t":"ping","id":9}
```

### 7.2 get

`get` fetches a file. The Boll answers with `blob` and then `chunk` messages (§6.4).

| `what` | Fields | Grant |
| :--- | :--- | :--- |
| `mrph5` | `song_id` | `stems` |
| `routine` | `ref`, a registry reference with a digest | not yet defined (§22) |

```json
{"v":1,"t":"get","id":7,"what":"mrph5","song_id":"…"}
{"v":1,"t":"get","id":8,"what":"routine","ref":"bollawax.org/examplelabs/bass-lean@sha256:…"}
```

### 7.3 Volume and transport

| `t` | Payload | Grant |
| :--- | :--- | :--- |
| `volume` | `set` (0–1), or `step` (+1 or −1, one of 16 steps) | `volume` |
| `transport` | `cmd`: `play`, `pause`, `stop`, `next` or `prev` | `transport` |

```json
{"v":1,"t":"volume","id":12,"set":0.55}
{"v":1,"t":"volume","id":13,"step":1}
{"v":1,"t":"transport","id":14,"cmd":"next"}
```

### 7.4 stem_balance

The Boll plays its songs by synthesizing them from MIDI, so a dock can change how the current song sounds without touching any audio: `stem_balance` re-balances the stems live, and `remix` (§7.5) asks the factory for a new version of the song.

`stem_balance` re-balances the Boll's current playback, stem by stem. It lasts until the song changes, or until the dock sends `"reset": true`. Gains are clamped to −24…+12 dB. The Boll answers with `remix_status` (`applied`). Grant: `stem_balance`.

```json
{"v":1,"t":"stem_balance","id":3,"song_id":"…",
 "stems":{"ch03_benthos":{"gain_db":4.0},"ch06_gallium":{"mute":true}}}
{"v":1,"t":"stem_balance","id":5,"song_id":"…","reset":true}
```

### 7.5 remix

`remix` with `"mode": "render"` asks the factory for a new version of a song. The new version joins the library with the origin `dock:<vendor>/<product>`, and is uploaded like any song, subject to the user's settings. The factory makes it from the song's own plan and the corpora already on the Boll (never a new corpus), and installed routines apply to it as to any song. The Boll reports progress with `remix_status`: `queued`, `rendering`, then `done` with the new song id, or `refused`. Grant: `remix`.

```json
{"v":1,"t":"remix","id":4,"song_id":"…","mode":"render",
 "stems":{"ch03_benthos":{"gain_db":4.0}},"tempo":1.0,"transpose":0,"note":"bass forward"}
```

A `remix` with `"mode": "live"` MUST be treated as `stem_balance`.

### 7.6 Audio routing

Audio itself flows over USB Audio Class 2 or the analog A-BUS. Only the routing goes over the API, and it is **not available over BLE**.

| `dir` | Meaning | Grant |
| :--- | :--- | :--- |
| `from_boll` | the Boll sends its mix to the dock's USB Audio sink (`iface`, `rate`, `ch`) | `audio_out` |
| `to_boll` | the Boll takes the dock's USB Audio source; `use` is `replace`, `mix` or `record` | `audio_in` |
| `abus` | selects the Boll's analog outputs; `route` is `foot`, `medallion` or `both` | see §22 |

```json
{"v":1,"t":"audio","id":5,"dir":"from_boll","iface":"uac2","rate":48000,"ch":2}
{"v":1,"t":"audio","id":6,"dir":"to_boll","use":"mix"}
{"v":1,"t":"audio","id":7,"dir":"abus","route":"foot"}
```

### 7.7 Light sync

`light_sync` either shifts the Boll's lightshow to match the dock's audio latency (`offset_ms`), or lets the dock's own palette of 16 colours drive the Boll's light ring until the dock hands control back. Grant: `light_sync`.

```json
{"v":1,"t":"light_sync","offset_ms":-12}
{"v":1,"t":"light_sync","follow":"dock","palette":["#ff0000","…"]}
{"v":1,"t":"light_sync","follow":"boll"}
```

### 7.8 plugin

`plugin` tells the Boll which published dock plugin the dock is running, so the Boll's UI can show it. No grant is needed.

```json
{"v":1,"t":"plugin","name":"examplelabs/bass-lean","ref":"sha256:…","state":"running"}
```

## 8. Stems and rights

### 8.1 MRPH5 bundles

An MRPH5 bundle is a per-song zip (media type `application/x-mrph5`, zip comment `MRPH5/1`). It is written with fixed timestamps, so the same song always gives the same bytes.

| Entry | Content |
| :--- | :--- |
| `mimetype` | the text `application/x-mrph5`, stored uncompressed, first in the zip |
| `combined.mid` | the full multitrack MIDI, exactly as the song plays |
| `stems/chNN_<label>.mid` | one Standard MIDI File per instrument stem: track 0 is a conductor track with every tempo, time-signature, key-signature, marker and text event; track 1 is that stem's channel messages at their original ticks |
| `meta.yaml` | everything else, machine-friendly (below) |
| `blueprint.md` or `song.json` | the corpus track's blueprint, or the generated song's record |

- Stem names use the MIDI channel as two digits (`ch01` to `ch16`). For a generated song, the label is the musician persona; for a corpus track, it is the track name.
- Playing every file in `stems/` together gives the same notes and tempo map as `combined.mid`.
- The proposed stem **roles** are `ch01` lead, `ch02` harmony, `ch03` bass and `ch10` drums, with the other channels named by persona. This mapping is a proposal until MRPH5 is frozen.
- `meta.yaml` includes the format and kind, title, tempo, time signature, key, the part list (bars, start and end times, active channels, chords), the channel table, the MIDI tempo, time-signature and key maps, groove descriptors (swing ratio, syncopation per stem, note density, velocity arc, kick and snare pattern) and statistics per stem. Every time is given in both ticks and seconds.

### 8.2 Who gets which stems

- The Boll hands out stems of **songs it generated** once the user grants `stems`.
- It hands out stems of **corpus songs** only where the corpus allows it (a proposed per-corpus `dock_stems` setting).
- A dock **never** receives corpus audio in any form, or the Boll's account tokens or credentials. A request for them fails with `corpus_rules`.

### 8.3 MIDI-only corpora

Some corpora are **MIDI-only**: the artist licensed Pop Boll to transcribe the recordings but not to keep or play them, so no audio exists for them anywhere in Pop Boll, not on the Boll and not on the service. A dock must not assume that a corpus has recordings.

- Each entry of the `corpus` message (§6.1) carries `"audio": "licensed"` or `"audio": "not_licensed"`. A dock that finds no `audio` field must treat the corpus as `"not_licensed"`.
- Everything a dock can get for a corpus song, MRPH5 bundles and their stems included, is made from the corpus's MIDI transcriptions. It works the same for MIDI-only corpora.
- A dock that wants corpus recordings gets nothing for a MIDI-only corpus and should say so ("MIDI-only corpus"). Asking for its audio fails with `corpus_rules`, as for any corpus.

## 9. Versioning

- The envelope's `v` changes only if the framing changes.
- The protocol is `bollardeck/<major>`. `hello` lists every major the dock speaks, and the Boll picks the highest one in common, or answers `no_common_api`.
- Within a major version, additions are new optional fields, new message types, new error codes and new capability flags, discovered through `want`, `can` and `grants`. Removing a field or changing its meaning requires a new major version.
- The physical specification and this API move independently. A Bollard v1.0 dock speaks `bollardeck/1`.

## 10. Example dock

**Bass Lean** is a minimal dock: a Linux single-board computer on the USB-C profile that runs as a USB gadget, whose CDC-ACM function (interface string `bollardeck`) appears to it as `/dev/ttyGS0`. It pushes the bass forward on every song. It needs pyserial.

```python
#!/usr/bin/env python3
import json
import serial

port = serial.Serial("/dev/ttyGS0", timeout=1)
PLAN = {"bass": +4.0, "drums": +1.5, "lead": -2.0}   # dB per stem role


def send(t, **payload):
    port.write((json.dumps({"v": 1, "t": t, **payload}, separators=(",", ":")) + "\n").encode())


send("hello", id=1, api=["bollardeck/1"],
     dock={"vendor": "Example Labs", "product": "Bass Lean", "profile": "usb-c", "fw": "0.1"},
     want=["nowplaying", "stems"], can=["stem_balance"])

next_id = 2
for raw in port:
    if not raw.strip():
        continue
    msg = json.loads(raw)
    if msg["t"] in ("welcome", "grants"):
        print("balance allowed" if "stem_balance" in msg.get("grants", []) else "waiting for consent")
    elif msg["t"] == "stems" and msg["stems"]:
        gains = {s["id"]: {"gain_db": PLAN[s["role"]]} for s in msg["stems"] if s.get("role") in PLAN}
        if gains:
            send("stem_balance", id=next_id, song_id=msg["song_id"], stems=gains)
            next_id += 1
    elif msg["t"] == "error":
        print("boll:", msg.get("code"), msg.get("msg", ""))
```

## 11. Part B: Routines

A **routine** is a small piece of Python that changes how your Pop Boll writes songs. It hooks into the song factory on the Boll, runs only on **your own Boll**, and works only with the corpora already on the device.

The routine API is the SDK's `bollardeck.routines` package, and the Pop Boll's song factory loads and runs routines through it. Where a table below restates a limit or a field, the SDK is the authority: the hard caps are `bollardeck.routines.HARD_LIMITS` and the manifest is the `routine-manifest` schema. You can try a routine without a Boll:

- `python3 -m bollardeck.routines <paths>` lists what would load, in what order, and what would be skipped and why.
- `bollardeck.routines.sim` is a toy song factory that calls every hook of a loaded routine on a made-up song. It checks that your hooks keep the rules. It writes no music, and its chord list is wider than the Boll's.

How a song is made, so the hooks make sense:

1. A **planning summit** plans the song (a single, or a multi-movement suite): key, tempo, and a list of parts (Intro, Verse, Chorus and so on), each with a chord progression, an energy level and a length in bars.
1. A band of virtual musicians **jams each part in takes**.
1. After each take, **seven judges** score it. When they vote to lock a take, the part is done. A take ceiling makes sure every part finishes.
1. When every part is locked, the band votes on **overdubs**.
1. The song is **exported** as MIDI and a song record.
1. A device can also render a **making-of film** from the session.

### 11.1 What a routine can never do (normative)

- **No network.** No sockets, HTTP, DNS or subprocesses.
- **No file writes outside its own folder.** A folder routine may write inside its folder. A zipped routine may write inside a `<zip name>.data/` folder next to the zip.
- **No corpus creation or change.** No API creates a corpus, by design, and corpora are read-only to routines. A routine sees corpus labels, summaries and musical DNA through frozen views, and never gets a handle or a path to a corpus.
- **No score forging.** A routine can read every judge's score, and can add directives or veto a lock. It cannot change a score, a vote or the lock rule.
- **No hidden state across songs that matters to the factory.** A routine's module stays loaded for the process, but everything it returns is validated on every call.

## 12. Hooks

A routine defines one or more of these as plain module-level functions in `routine.py`.

| Hook | Called | May | May not |
| :--- | :--- | :--- | :--- |
| `on_plan(plan, ctx)` | once per song, right after the planning summit | re-order the parts of a single; change each part's progression, energy, bars and label | add or remove parts; change any other plan or part field; re-order the parts of a suite |
| `on_part_candidate(part, notes, ctx)` | every take of every part, after synthesis and autotune, before the judges | return a transformed note list: add, remove or change notes, which are then judged as they are | exceed 2 × the input notes + 512; produce a note outside the part or outside MIDI ranges |
| `on_verdict(part, verdicts, ctx)` | every take, after the judges | add up to 4 directive codes to the next take; veto a lock | change a score, a vote or a threshold |
| `on_overdub(plan, bus, ctx)` | once, after the band's overdub votes | add notes to locked parts (≤ 512 per part) | remove or change locked notes |
| `on_export(meta, ctx)` | once, before the song record is written | return a JSON mapping (≤ 16 KiB) stored under the routine's name | change any other part of the record |
| `on_drama(shots, ctx)` | when a device renders the making-of film | re-order shots; add up to 32 shots | remove or alter an original shot |

### 12.1 on_plan

- **Receives** a copy of the song plan. Return the plan, or `None` to keep the edits you made to the copy in place.
- **May** re-order the parts of a single (not a suite), and change each part's `progression` (1–8 chords from `I`, `ii`, `iii`, `IV`, `V`, `vi` and `bVII`), `energy` (0–1), `bars` (a multiple of 4 from 4 to 32) and `label` (truncated to 40 characters). `part_index` is renumbered in the new order, and the plan's `total_bars` is recomputed.
- **May not** add or remove parts, change any other plan field (key, tempo, teams, taste, corpora, title and so on) or any other part field (category, assigned teams, study-break channel, movement, leitmotif role).
- A result that breaks any of these rules is rejected as a whole, and the routine is disabled for the rest of the song.

### 12.2 on_part_candidate

- **Receives** a copy of the part and a list of copied note events.
- **Returns** a new list, or `None` after editing the list in place. The routine owns those notes, and the judges hear them as they are.
- **Limits:** at most 2 × the input count + 512 notes, and every note valid: `channel_1based` 1–16, `pitch` 0–127, `velocity` 1–127, `duration_ticks` greater than 0, and `start_tick` from 0 up to (not including) `bars` × 1,920.

### 12.3 on_verdict

- **Receives** the part and the seven judges' verdicts as frozen views.
- **Returns** `None`, or `{"directives": [...], "veto": bool, "reason": str}`.
- **Directives:** up to 4 codes matching `^[A-Z][A-Z0-9_]{2,47}$`, added to the next take of the part (§12.7).
- **Veto:** stops the take from locking, so the band goes again. A veto expires at the take ceiling, so a song always finishes.
- The views are frozen: writing to one raises an error and disables the routine. So does returning a key other than `directives`, `veto` and `reason`. Repeated directive codes count once.

### 12.4 on_overdub

- **Receives** a copy of the plan and a frozen view, `{"locked_parts": {part_index: (note, …)}}`.
- **Returns** `{part_index: [note, …]}`: notes to **add**, at most 512 per part. They are tagged with `origin_tag` `routine:<name>` and listed in the song's overdub record.
- Locked notes cannot be removed or changed. Notes for a part that is not locked are refused, and added notes must be valid as in §12.2.

### 12.5 on_export

- **Receives** the song's metadata, frozen.
- **Returns** a JSON-serialisable mapping of at most 16 KiB, stored in the song record at `routine_meta.<name>`.

### 12.6 on_drama

- **Receives** a copy of the making-of film's shot list. It runs only on devices.
- **May** re-order shots, and add up to 32 shots of the form `{"kind": str, "duration_ms": 180–20000, "data": {}}`, which are marked `by_routine` with the routine's name. `duration_ms` is an integer. Timings are recomputed.
- **May not** remove or alter an original shot.

### 12.7 Directive codes

Directives are advisory codes that the next take of a part reads. The factory currently **acts on** these:

| Code | Effect on the next take |
| :--- | :--- |
| `EVOLVE_COUNTERPOINT_AND_VELOCITY_ARC` | develop counterpoint and the velocity arc |
| `EVOLVE_CALL_AND_RESPONSE_DUEL` | develop call-and-response between players |
| `DUCK_COMPING_UNDER_LEAD_MELODY` | keep accompaniment under the lead melody |
| `REINFORCE_BEAT_2_4_BACKBEAT` | reinforce the backbeat on 2 and 4 |
| `ADD_KICK_SNARE_FOUNDATION` | add a kick and snare foundation |
| `REDUCE_CHROMATIC_QUIRKS` | reduce chromatic notes |
| `AUTOTUNE_SNAP_SOUR_NOTES` | snap sour notes to the scale |
| `TIGHTEN_RHYTHMIC_POCKET_GRID` | tighten timing to the grid |

Any other well-formed code is recorded with the take and carried into the next take's directive set, but it does not change the notes until the factory learns it. The `MORE_HOOK` code in the `judge_heckler` example (§15.2) is one of these.

### 12.8 Data types

**Parts** (in `plan.parts`, and as the `part` argument):

| Field | Type | Editable in `on_plan` |
| :--- | :--- | :-: |
| `part_index` | int, 1…N | renumbered |
| `label` | str, for example "Verse 1" | yes |
| `category` | `Intro`, `Verse`, `Chorus`, `Bridge`, `Instrumental Break` or `Outro` | no |
| `bars` | int, a multiple of 4 | yes |
| `progression` | list of chord symbols, for example `["I", "V", "vi", "IV"]` | yes |
| `energy` | float, 0–1 | yes |
| `assigned_team_ids`, `study_break_channel`, `movement_index`, `leitmotif_role` | band and suite bookkeeping | no |

The plan also carries read-only fields such as `song_id`, `title`, `bpm`, `key_str`, `form` (`single` or `suite`), `corpus_ids`, `corpus_labels` and `total_bars`.

**Note events:**

| Field | Meaning |
| :--- | :--- |
| `channel_1based` | MIDI channel, 1–16 |
| `pitch` | MIDI note number, 0–127 |
| `start_tick` | offset from the start of the part; 480 ticks per quarter note, 1,920 per bar |
| `duration_ticks` | length in ticks |
| `velocity` | 1–127 |
| `origin_tag` | where the note came from, for example `jam`, `overdub` or `routine:<name>` |
| `was_autotuned`, `quirk_waiver_granted` | factory bookkeeping |

To make a new note, copy one you received with `dataclasses.replace(note, pitch=…, start_tick=…)`.

**Verdict views** (frozen): `judge_id` (a string that starts with the judge's code, such as `J2` for the Melodic Hook judge), `judge_number`, `domain`, `score`, `threshold`, `lock_vote`, `metrics` (a mapping of names to floats) and `directives` (a tuple of codes).

## 13. Context and limits

### 13.1 The context

| Attribute | What | Writable |
| :--- | :--- | :--- |
| `ctx.routine_name`, `ctx.routine_version`, `ctx.api` | who is running, and the API version (1) | no |
| `ctx.hook`, `ctx.song_id`, `ctx.part`, `ctx.take` | where in the song: `part` is a frozen summary, and `take` is the 1-based take for per-take hooks | no |
| `ctx.corpus` | a frozen view with `ids`, `labels`, `summaries` and `dna` (the merged musical DNA of the active corpora). There is no handle to a corpus | no |
| `ctx.roster` | `{"musicians": {channel: …}, "judges": {judge_id: …}}`, the evolving roster, frozen | no |
| `ctx.taste_dna` | the song's taste profile, frozen | no |
| `ctx.device` | `{"serial", "song_id_prefix"}`; never probes hardware | no |
| `ctx.rng` | a `random.Random` seeded from the song seed, the routine name, the hook, the part and the take: deterministic per song, and separate from the factory's own random numbers, so a routine never shifts the band's dice | yes (it is the routine's own) |
| `ctx.log(msg)` | one line (≤ 200 characters, ≤ 50 lines per song) into the song record | append-only |
| `ctx.folder` | the routine's own folder, the only place it may write | yes |

### 13.2 Limits

A manifest's `limits` can only tighten these caps.

| Limit | Hard cap |
| :--- | :--- |
| `max_ms_per_call` | 250 ms of wall time, measured after the call (Python cannot pre-empt it) |
| `max_directives_per_verdict` | 4 |
| `max_notes_factor` | 2.0 (× the input notes, + 512) |
| `max_overdub_notes_per_part` | 512 |
| `max_export_bytes` | 16,384 |
| `max_added_shots` | 32 |
| `max_log_lines` | 50 |

### 13.3 Failures and the song record

Every hook call is wrapped. **An exception, a guard refusal, a result that breaks the hook's rules, or a call slower than the time limit disables that routine for the rest of the song.** Its results from that call are discarded, and the song carries on. The song record shows what happened:

```json
"routines_applied": [
  {"name": "mixolydian_bridge", "version": "0.1.0", "author": "Pop Boll examples",
   "source": "/data/routines/mixolydian_bridge", "hooks_called": {"on_plan": 1},
   "log": ["part 5 Bridge: vi-iii-IV-V -> I-bVII-IV-I"]}
],
"routines_failed": [
  {"name": "boom", "version": "0.0.1", "hook": "on_part_candidate",
   "where": "on_part_candidate part 1 take 2", "error": "ValueError: kaboom"}
],
"routine_meta": {"calm": {"ok": 1}}
```

- `routines_failed` also lists packages that failed to load (with `"hook": "load"`): a bad manifest, a banned import or a duplicate name.
- Each part's take history also records the directives routines added, their vetoes, and whether a lock was vetoed.
- **With no routine installed, none of these keys exist, and the song is byte-identical to one made by a factory without hooks.**
- The record survives pausing and resuming a song.

## 14. Packaging and installation

### 14.1 Package layout

A routine is a folder, or a `.zip` of one (with the files at its root or inside one top-level folder):

```text
mixolydian_bridge/
  routine.yaml     manifest (a YAML subset; one JSON object also parses)
  routine.py       the hooks, as plain module-level functions
  README.md        optional
```

### 14.2 Manifest

```yaml
name: mixolydian_bridge          # ^[a-z0-9][a-z0-9_.-]{1,63}$, unique on the device
version: 0.1.0
author: Pop Boll examples
api: 1                           # the routine API version
description: Every Bridge plays the Mixolydian jam cell.
hooks: [on_plan]                 # each MUST be defined in routine.py
order: 100                       # optional; lower runs first
limits: {max_ms_per_call: 20}    # optional; can only be tighter than the hard caps
```

The manifest is checked against the SDK's `routine-manifest` schema.

- `name`, `version`, `author` and `hooks` are required. `api` may be left out and then means 1; `order` then means 100.
- An unknown key under `limits` is refused. A limit looser than its hard cap is read as the cap. Other unknown top-level keys are ignored.
- The file is read by the SDK's own reader, `bollardeck.routines.yamlsubset`, which takes a strict subset of YAML and coerces nothing. Indent with spaces. Anchors, aliases, tags, merge keys, mappings inside a list item and nested flow collections are refused. Plain values that YAML would guess at are refused too: `yes`, `no`, `on`, `off`, numbers with leading zeros or underscores, hex, exponents, and anything shaped like a date or a time. Put quotes around them. `version: 0.1` is a number and is refused; `version: 0.1.0` or `version: "0.1"` is fine.

### 14.3 Load order

1. The Boll loads routines from the `routines/` folder of its data directory, in name order, skipping names that start with `.` or `_`. Further search paths can be given in the `POPBOLLARD_ROUTINES` environment variable; each is one routine or a folder of routines, read in the order given.
1. The first routine with a given `name` wins. Later ones become `duplicate name` load failures.
1. The loaded routines run in order of (`order`, discovery position), and every hook calls them in that order. Each routine sees the results of the routines before it.
1. Setting `POPBOLLARD_NO_ROUTINES=1` turns all routines off.

Routines are picked up when the next song starts.

### 14.4 Installing on a Boll

Copy the routine's folder, or a zip of it, into the `routines/` folder of the Boll's data directory. Today that means a computer connected to the Boll's medallion USB-C port, which gives the computer a network link to the Boll. A friendlier install flow, and installs from the registry (§21), are planned. Installing a routine is always the owner's act, on their own device.

## 15. Example routines

### 15.1 mixolydian_bridge

`on_plan`: every Bridge's progression becomes the Mixolydian jam cell **I – bVII – IV – I** (in C: C, B♭, F, C), and each change is logged. Nothing else in the plan changes.

```yaml
# A bollardeck routine. Its "bollawax file" is this folder, or a zip of it.
name: mixolydian_bridge
version: 0.1.0
author: Pop Boll examples
api: 1
description: >
  Every Bridge plays the factory's Mixolydian jam cell (I - bVII - IV - I) instead of the
  progression the planning summit picked. Nothing else about the plan changes.
hooks: [on_plan]
limits:
  max_ms_per_call: 20
```

```python
"""mixolydian_bridge: force every Bridge onto the Mixolydian jam cell and log it.

The cell is the "corpus quirk: Mixolydian Jam Break" progression of the factory's
Instrumental Break table, I - bVII - IV - I (in C: C, Bb, F, C).
"""

MIXOLYDIAN_JAM_CELL = ["I", "bVII", "IV", "I"]


def on_plan(plan, ctx):
    for part in plan.parts:
        if part.category == "Bridge" and list(part.progression) != MIXOLYDIAN_JAM_CELL:
            ctx.log(f"part {part.part_index} {part.label}: {'-'.join(part.progression)} -> "
                    f"{'-'.join(MIXOLYDIAN_JAM_CELL)}")
            part.progression = list(MIXOLYDIAN_JAM_CELL)
    return plan
```

### 15.2 judge_heckler

`on_verdict`: when J2 (the Melodic Hook judge) scores a take below 0.6, it adds the directive `MORE_HOOK`. It never changes a score, and every take's scores and votes stay identical to a run without it. `MORE_HOOK` is not yet a code the factory acts on, so it is a heckle you can see in the song record: it does not change the music.

```yaml
name: judge_heckler
version: 0.1.0
author: Pop Boll examples
api: 1
description: >
  Heckles from the back of the room: whenever J2 (Melodic Hook) scores a take below 0.6 it
  adds a MORE_HOOK directive for the next take. It never changes a score or a vote.
hooks: [on_verdict]
limits:
  max_ms_per_call: 20
  max_directives_per_verdict: 1
```

```python
"""judge_heckler: shout MORE_HOOK whenever J2's score is below 0.6. Scores stay untouched.

Verdicts arrive as frozen views, so a routine cannot forge a score even by accident; the
only things on_verdict can hand back are directives, a veto and a reason.
"""

THRESHOLD = 0.6


def on_verdict(part, verdicts, ctx):
    j2 = next((v for v in verdicts if v.judge_id.startswith("J2")), None)
    if j2 is None or j2.score >= THRESHOLD:
        return None
    ctx.log(f"part {part.part_index} take {ctx.take}: J2 {j2.score:.3f} < {THRESHOLD} -> MORE_HOOK")
    return {"directives": ["MORE_HOOK"], "reason": f"J2 scored {j2.score:.3f}"}
```

## 16. Security

**A routine is ordinary Python running inside the song factory on your Boll.** The factory enforces the rules of §11.1 in three layers:

1. **Before loading**, statically: imports of network, process and foreign-function modules are refused (the SDK's `bollardeck.routines.BANNED_IMPORTS`: `socket`, `ssl`, `http`, `urllib`, `requests`, `httpx`, `aiohttp`, `asyncio`, `subprocess`, `multiprocessing`, `ctypes`, `cffi` and similar), and so are imports of the host's own closed modules, which the host adds to that list.
1. **During each hook call**, at run time: a Python audit hook refuses socket, subprocess, `os.system`, exec, spawn, fork and `ctypes` events, and any open-for-write, remove, rename, mkdir or chmod outside the routine's folder, and any SQLite database opened outside it. The same guard is on while the routine's module is first loaded.
1. **On every result:** the factory validates what comes back and keeps only what each hook is allowed to change.

That is a **guard rail for honest code, not a sandbox** against hostile code. Python offers no in-process sandbox, and a determined routine can get around audit hooks. Install only routines you have read, or that come from someone you trust.

For the same reason:

- **Routines run only on your own Boll.** The website never runs user routines: its song factory loads none, whatever is installed.
- **No API creates corpora.** Routines work with the corpora on the device, and cannot add, change or export them.
- **A curated path for the web** (routines reviewed by a person and allowlisted, or routines compiled to WebAssembly and run in a WASI sandbox with only the hook payloads as input) is a possible future path, and is not built. Until something like it exists, the website stays routine-free.

## 17. Part C: The Bollard SDK

The **Bollard SDK** is the open library every client of the platform builds on, ours included. Its Python package and its browser global are both named `bollardeck`. Bollawax 0.2.4 is the first release built on it: the Pop Boll's image and popboll.com run the SDK's code for everything in §17.1, so what a third party imports is what the device runs.

The earlier Part C described a cartridge that docked under the Boll's foot as a USB device and ran one signed image. That device class is retired: a Bolltridge is now the core cart (§20). Its messages (`caps`, `clock`, `midi`, `voice_claim`, `health`, the image relay and the `cartridge.yaml` manifest) are withdrawn and are not part of `bollardeck/1`. Whether add-on images and voice takeover come back as software on the cart is open.

### 17.1 What the SDK contains

Bollard SDK 0.5.0, shipped with Bollawax 0.3.7, pages the Pop Snip revocation list (a signed index of pages of 256 entries, so that a full page never changes) and adds `bollardeck.popsnip.accept`, the check a device makes before it runs a Pop Snip app, in Python. Bollard SDK 0.4.0, shipped with Bollawax 0.3.6, adds `bollardeck.popsnip`: the signed records of Pop Snip apps (the third-party apps at `<name>.popsnip.app`), with one canonical form, strict parsers and the same refusal codes in Python and in the browser, and vectors in `conformance/popsnip/`. It also refuses an Ed25519 public key of small order, as libsodium does. Bollard SDK 0.3.0, first shipped with Bollawax 0.3.0, brought `bollardeck.help`, `bollardeck.pxs`, the draft deck, the `nowplaying`, `transport`, `help-pack` and `help-director` schemas and the ninth licence capability, and changed how attestation and a person's hub answers work (§19). The cart's pieces (the optional hal parts, the pocket keymap, the dock and cart descriptors, the decoders) were added in Bollard SDK 0.2.0, which shipped with Bollawax 0.2.5.

| Module | What it is | State |
| :--- | :--- | :--- |
| `bollardeck.routines` | the routine API of Part B: loader, guard, limits, a simulator and a command line | shipped |
| `bollardeck.device` | the hal protocols with a simulated board and optional parts (playing a file, audio routes, Bluetooth, the power source and charging), the rule that recognises an Arduino Uno Q, device identity and maker codes, gestures, cues, the keymap (§18), and audio decoders | shipped |
| `bollardeck.matrix` | the 13 × 8 light matrix engine, every renderer included, in Python and JavaScript | shipped |
| `bollardeck.corpus` | the corpus reader, the licence gate, the hub client, attestation checks, self-hosted corpus discovery (§19) | shipped |
| `bollardeck.schema` | a JSON Schema validator and the schemas of §17.2, in Python and JavaScript | shipped |
| `bollardeck.constants` | one source of the timings, button names, cue values and keymap, generated into Python and JavaScript | shipped |
| `bollardeck.help` | help packs, the detectors that offer help when a person seems stuck, director scripts for guided tours and captioned videos, and the page helpers in JavaScript | shipped |
| `bollardeck.pxs` | reads, writes and checks `.pxs`, the Pop Snip format: an Impulse Tracker module followed by a block with the song's credits, licences and MIDI. Python only | shipped |
| `bollardeck.device.dock`, `bollardeck.device.cart` | draft dock and cart descriptors and their checks; the dock protocol itself waits for Bollard v2 and the deck rewrite (§20) | draft |
| `bollardeck.deck` | a minimal deck service and client for Part A: `hello` and `welcome`, grants with the user's consent per dock, subscriptions, the `nowplaying` and `transport` messages, in one process or over a Unix socket. No USB or BLE | draft |
| `bollardeck.snipler` | Snipler types and data formats | placeholder; two draft schemas ship |

The JavaScript side is plain scripts with no build step. It has the constants, the validator, gestures, cues, the keymap, the matrix engine, the corpus gate, help and a `fetch` hub client. It has no disk cache, no attestation check and no origin discovery.

`bollardeck.SPEAKS` names the wire and format versions the SDK speaks, and `bollardeck.MIN_BOLLAWAX` the oldest Bollawax it is tested against.

### 17.2 Schemas

Every format has a JSON Schema in the SDK, identified as `https://popboll.com/sdk/schema/<name>.schema.json`. The schema is the authority for field names and types; this page does not restate them.

| Name | What it describes |
| :--- | :--- |
| `corpus-manifest` | a corpus's `corpus.json` |
| `licence` | the corpus licence block, `popboll.licence/1` |
| `origin` | the discovery file of a self-hosted corpus, `popboll.origin/1` |
| `routine-manifest` | `routine.yaml` (§14.2) |
| `cue` | a button cue list (§18.3) |
| `keymap` | the engagement keymap (§18.4) |
| `device-identity`, `makers` | a device's identity file and the maker-code registry |
| `image-release` | the `latest.json` record of an image release |
| `snipler-events`, `snipler-frame` | the Snipler's events and frame (drafts) |
| `dock-descriptor`, `cart-descriptor` | what a dock and a cart say about themselves (drafts for Bollard v2) |
| `nowplaying`, `transport` | the draft deck's now-playing message and its transport requests |
| `help-pack`, `help-director` | a help pack (topics, intros and the scenarios that offer them) and a director script (a guided tour or an INTRO video) |

### 17.3 What is planned and not available

- **The deck service on a device:** the USB and BLE transports, and the owner's consent asked on the device itself. The SDK's draft deck already has `hello` and `welcome` and the grants (reads free, writes by consent).
- **Sign-in,** planned; no version promised yet. Until it exists, a person's name sent to the hub is self-declared (§19.3).
- **A sandbox** for third-party apps on the cart and in the browser, through the same client.
- **A signed registry** at bollawax.org with an affirmation step, and sideloading in hacker mode (both in §21).
- **The Pop Snipler's capability boundary:** third-party code asks the deck for Snipler capabilities and never imports the engine, which stays closed.
- **Signed layers.** Image releases are signed since Bollawax 0.2.5 (each release record carries Pop Boll's signature); the Snipler Layer is not signed yet.
- **A C header.** `bollardeck.h` will carry the descriptor structs and message names.

No version or date is promised yet for any of these, sign-in included.

## 18. Buttons, gestures, cues and the keymap

All four are data in `bollardeck.constants`, read by the device and the website alike.

### 18.1 Buttons

On the SDK's surface a button is its number: 1, 2 or 3 (`BUTTON_NUMBERS`). "Inner", "middle" and "outer" are labels for where the three sit on the Boll's medallion, and the words the `bollardeck/1` wire uses for them (§6.2); `BUTTONS` maps one to the other.

A board reports presses as **key lines**, one per line of text:

```text
1 down 91200        button 1 went down at 91,200 ms: a press beginning
1 140 91340         button 1 was held 140 ms and released at 91,340 ms: a complete press
```

- `<button> <hold_ms> [release_ms]` is a complete press.
- `<button> down [t_ms]` is a press beginning. It is a hint and never a gesture by itself: a late or lost release line can never turn a tap into a hold.
- `bollardeck.device.hal.base.parse_key_line` reads a line and `key_line` writes one.

### 18.2 Gestures

The gesture engine (`bollardeck.device.gestures`, and `bollardeck.gestures` in the browser) turns presses into named gestures.

- A complete press is a tap or a hold by its `hold_ms` alone: `HOLD_MS` or longer is a hold. Releasing a hold means nothing more.
- Taps on one button that follow each other within `TAP_FOLLOW_MS` chain into a multiple tap, up to `TAP_CHAIN_MAX`. Which chains a button waits for comes from the keymap, so a single tap is not delayed where no multiple tap is bound.
- Names are `tap<button>`, `tap<button>x<count>` and `hold<button>`: `tap1`, `tap3x3`, `hold2`. `GESTURES` lists them.
- A `Gesture` carries `name`, `button`, `kind`, `count`, `t_ms` and `hold_ms`, how long its press lasted. Its `to_dict()` is `{"gesture": "tap1", "t_ms": 91340}`: the name says the button.

The numbers behind the names are `HOLD_MS`, `TAP_FOLLOW_MS`, `PRESS_MATCH_MS`, `PRESS_LOST_MS` and `TAP_CHAIN_MAX`. Read them from the constants; do not copy them.

### 18.3 Cues

A cue says how a button should be lit. In the SDK a cue list is an array of at most three `{"button", "state", "role"}` objects, with `button` 1, 2 or 3, checked by the `cue` schema.

- `state` is one of `CUE_STATES`: `off`, `on`, `pulse` or `chase`. A pulse beats twice a second (`PULSE_PERIOD_MS`) and a chase turns once a second (`CHASE_PERIOD_MS`).
- `role` is one of `CUE_ROLES` (`a`, `b`, `c`, `live`, `go`, `warn`) or null. An `off` cue has a null role.
- **One cue per button.** A list with two cues for one button is invalid.
- A button with no cue is not driven, and an empty list clears every cue.

`bollardeck.device.cues` checks and renders a list in Python, and `bollardeck.cues` does in the browser. The buttons have no LEDs of their own, so whatever renders a cue (the Boll's lights, a web page, a dock) draws it from these rules.

### 18.4 The keymap

The engagement keymap says what a gesture means while the band is asking the person something, and when it is not. It is `bollardeck.constants.KEYMAP`, version 2, checked by the `keymap` schema.

```json
{"v": 2,
 "always": {"hold3": "power"},
 "idle":   {"tap1": "skip_to_frontier"},
 "prompt": {"tap1":  {"abc": {"choice": "A"}, "spectrum": {"choice": -1}, "game": {"do": "raw"}},
            "hold1": {"abc": {"do": "replay"}, "spectrum": {"do": "replay"}, "game": null}}}
```

- It has three maps keyed by gesture name, and an optional fourth. `always` is checked first; then `prompt` while a prompt is showing, and `idle` while none is. `pocket`, the fourth, is for a cart running with no dock on a battery of its own: when the device names that context, it is looked at before `idle`, and it maps gestures to player verbs (`POCKET_VERBS`: play and pause, stop, volume, what's on, previous and next, share, and `pair` on `tap2x3`).
- In `always`, `idle` and `pocket`, a gesture's value is a string: the name of an action.
- In `prompt`, a gesture's value is an object with one member for each kind of prompt (`PROMPT_KINDS`: `abc`, `spectrum`, `game`). Each member is `{"choice": …}` (answer the prompt with that value), `{"do": …}` (a named action) or null (the gesture is taken and does nothing).
- `bollardeck.device.keymap.resolve(gesture, prompt, context=None)` applies it and `problems(keymap)` checks one; the browser twin does the same. With no context named, the pocket map is never used. The example above is a valid keymap, cut down from the shipped one.

A keymap whose `"v"` is not 2 is refused.

## 19. The corpus client and the gate

A **corpus** is a licensed song collection, and its `corpus.json` carries a licence block, `popboll.licence/1`, that says what may be done with it. `bollardeck.corpus` is the one way a client reads a corpus, and it will not hand over content without first asking what is allowed.

### 19.1 Asking

```python
from bollardeck.corpus import Corpus, Identity

corpus = Corpus.load("path/to/a/corpus")
verdict = corpus.may("study", Identity(service=True))
if not verdict.allowed:
    print(verdict.reason)          # for example "licence_missing"
```

- A capability is one of `bollardeck.corpus.licence.CAPABILITIES` (`transcode`, `store_audio`, `stream_audio`, `store_art`, `store_morpus`, `musicians_may_study`, `export_morpus`, `device_copies`, `stream_render`) or `see`. `study` is short for `musicians_may_study`.
- `stream_render`, the ninth, lets a corpus's MIDI be played rendered through Pop Boll's own sounds, never as a recording. A public-domain MIDI corpus has it by default; other scopes have it only when the licence grants it. An edition signed before the ninth capability existed holds it at its scope's default.
- `bollardeck.corpus.gate.listen(manifest, identity, render=False)` asks whether a person may listen: a recording needs `stream_audio`, a render `stream_render`.
- **Renders.** A corpus whose licence grants `stream_render` may carry renders: each piece of its MIDI played through Pop Boll's own sounds and stored as a pack beside its albums (`renders/<album>.wbol`). The hub lists them at `/api/corpi/<ID>/renders` and serves them only while the licence grants `stream_render`, and a track list made from them marks each track `source: render`, labelled "played from the score". popboll.com plays a render-only corpus, such as the public-domain Beethoven corpus 0006-BONNBINGO once its renders are published, to everyone signed in, whatever their tier. Recordings keep their tiers, and signed out you hear neither. A Pop Boll needs no render from the hub: it plays a corpus's MIDI through its own sounds, on the device.
- The answer is a `Verdict`: allowed or not, with one reason from `bollardeck.corpus.gate.REASONS`.
- Every accessor that returns content demands a fresh verdict and raises `GateRequired` without one.

### 19.2 The rules of the gate

The gate fails closed. `REASONS` is the full list; the rules that surprise people are these.

- **No licence block, no access.** A corpus whose manifest has no licence block, or a null one, is refused with `licence_missing` for every capability of the licence. Only `see`, which asks about visibility and nothing else, is answered without a licence block.
- **What the code does not understand is refused:** an unknown scope (`unknown_scope`), a newer licence version (`newer_version`), a manifest that fails its schema (`manifest_invalid`), or two differing blocks under `licence` and `license` (`licence_ambiguous`).
- **Private means private to people.** A corpus that is not public is refused with `not_visible` to anyone who is neither its owner nor on its access list. The band's engines may still study it if its licence allows study.
- **An expiry the device already holds is honoured offline,** by the device's own clock (`expired`). For a corpus cached from the hub, setting the clock back does not reopen it. A corpus read from a local folder follows the clock as it is given.
- **A revocation is news,** so it takes effect when the device next reaches the network (`revoked`). Until then a cached corpus keeps working, and the verdict says since when it has been unverified.
- `not_granted` means the licence is in order and does not include the capability.

### 19.3 The hub client

`bollardeck.corpus.HubClient` is the client for bollawax.org: one token, conditional requests, a disk cache that revalidates, and no silent substitution of one corpus for another.

- **The read token alone is for study only.** For a corpus that is not public, a caller that presents only the token gets the morpus and a manifest with the people's addresses removed. Track lists, audio, art and bundles are not found.
- **A named person gets more.** `acting_for=` names the person a request is for. It travels in the `X-Pop-For` header and never in a URL. What the hub sends back for a person is held in memory (at most `HELD_MAX` answers, least used first out; `forget(person)` drops one) and never written to disk, unless the client is made with `keep_for_person=True`, which caches that person's copy on disk apart from everyone else's.
- **Names are self-declared for now.** The hub believes the name it is given until sign-in exists (planned, no version promised yet; §17.3). Do not build anything that depends on the name being proved.

### 19.4 Attestation and self-hosted corpora

- `bollardeck.corpus.attest.verify_attestation` checks a corpus edition's signed record: that the manifest's signed fields match it (`signed_field_problems` lists any that do not), and its Ed25519 signature. `Corpus.attestation_record(edition)` fetches the record, from the corpus's own folder or from the hub. The ML-DSA-65 signature is checked only where the platform's OpenSSL knows the algorithm; where it does not, the result says `not_checked` for that signature and `partial` overall, never `verified`.
- `bollardeck.corpus.fetch_origin` reads the discovery file of a [self-hosted corpus](/hosting-your-own-corpus). The service that pulls such a corpus into Pop Boll is not built.

## 20. The cart and its docks: what is decided

The bollardeck text for the cart is not written. This section records what is decided, so that nobody builds against the retired arrangement.

- **The Bolltridge is the core.** The cart holds the computer, the corpora, a secure element and the only radio, and runs Bollawax and the deck. A Pop Boll and a Pop Snipler are docks for it.
- **The cart is the USB host** of whatever dock it stands in, and takes its power from the dock. The connection is the Bollport ([Bollard §25](bollard.md#25-bollard-v2-what-is-decided)).
- **A dock describes itself** with the Bollard JSON descriptor and a bollardeck `hello`, with fields for the dock added and a `slots` field for its cart positions. The field list, the dock classes and the transport are for Bollard v2 to fix.
- **One image, picked by the dock.** A cart runs one Bollawax image and chooses what to be from the dock's class.
- **At most two carts in one dock.** The cart in the first slot is the brain. A second cart is a guest: a USB device of the first, lending its corpora and its computing, and showing nothing of its own.
- **The serial belongs to the cart.** A dock has a model and a serial of its own in its descriptor and no device serial.

Since Bollawax 0.2.5, the image has carried the cart's software for pocket mode (a cart running with no dock, on a battery of its own) and a revised dock descriptor. No cart exists yet, and none of it is verified on hardware. This section describes the cart as it was introduced in Bollawax 0.2.4; nothing in it has changed since.

Not written: who sends `hello` first between a cart and its dock, the link between two carts, the guest's `hello` and how its secure element proves its licences, and the events for a dock's encoder and EJECT button.

## 21. Distribution (planned)

None of this exists yet. Today a routine reaches a Boll by being copied onto it (§14.4).

The plan is a signed registry at bollawax.org for routines, dock plugins and third-party apps, with routines first, because they are small and need no hardware.

- **Publishing.** A developer records an affirmation (name, contact, licence, and the right to distribute everything inside), and publishes under their own name. Published work may bundle soundfonts, samples and audio under licences that permit redistribution. It must not bundle anything extracted from a corpus.
- **Automated checks.** Routines are loaded with the static checks and run under the guard on fixture songs, and are rejected if they fail, break a limit or touch the guard.
- **Signing.** What passes is signed, and a device verifies the signature before it installs anything.
- **Sideloading and hacker mode.** Hacker mode is the owner's switch on one device they own, so a developer can build and test there before publishing. It is turned on at the device itself and confirmed there; it cannot be set over bollardeck, over the network or by a routine, and the device shows that it is on. While it is on, that device accepts unsigned work, labelled as unsigned. Every other rule still holds: corpus rules, consents, and no corpus files or credentials to third-party code. Unsigned work is never distributed. How the switch is thrown on a cart and its docks is not written.
- **What a developer accepts:** the SDK's Apache-2.0 licence, the [Bollawax Device Licence](/device-licence) for images, and the [Snipler Use Grant](/snipler-use-grant) for the Snipler's fetched files. There is no sign-up agreement.

The packaging format, the label names and the review steps will be published with the registry.

## 22. Open items

Not yet validated on hardware. Nothing in Part A has run on a Boll.

- **Not built yet:** everything in §17.3, the BLE UUID allocation (the UUIDs in §3.2 are placeholders), the binary LED characteristic, and `remix` in `render` mode.
- **Not written yet:** the bollardeck text for the cart (§20) and Bollard v2.
- **Part A against the SDK.** The `matrix` message of §6.3 splits a frame into `px` and `rgb`; the SDK's engine packs a frame as 113 bytes, the 104 pixels and then the three RGB LEDs. One of the two will change. The `led` messages describe a 24-LED ring, and the lights of the cart's docks are not fixed.
- **Estimates:** every latency, rate and transfer time in this document.
- **Undefined grants:** the grant that covers `get` with `"what": "routine"`, and the grant that covers `audio` with `"dir": "abus"`.
- **The `hello` profile value** for an accessory with no physical connection (BLE only) is not defined, and there is none for a Bollport dock.
- **MRPH5:** the stem role mapping is a proposal until the format is frozen, and so is the per-corpus `dock_stems` setting.
- **Routines:** the plan and part fields beyond those listed in §12.8 are not frozen, and there is no stable import path yet for creating note objects from scratch (copy a received note instead). The chord symbols and the ticks per bar are the Boll's song factory's, not the SDK's.
- **Buttons and gestures on the wire.** `bollardeck/1` names buttons `inner`, `middle` and `outer`, and its `ev` words (§6.2) do not match the gesture names the SDK's engine reports (§18.2). A wire that carries button numbers and the SDK's gesture names is proposed for a later protocol version; within `bollardeck/1` the fields stay as they are (§9).

### Changes

- **2026-11-17.** Brought up to Bollawax 0.3.7 and Bollard SDK 0.5.0: the paged Pop Snip revocation list and the device check (§17.1). No message, field or schema of `bollardeck/1` changed.
- **2026-11-16.** Brought up to Bollawax 0.3.6 and Bollard SDK 0.4.0: `bollardeck.popsnip`, the Pop Snip records (§17.1). No message, field or schema of `bollardeck/1` changed.
- **2026-11-16.** The Glass Snipler is now called the Pop Snipler, its open-firmware edition keeping the name Glass Snipler (named 2026-11-11). No message, field or schema changed.
- **2026-11-12.** Brought up to Bollawax 0.3.0 and Bollard SDK 0.3.0: the SDK's help, Pop Snip files and draft deck (§17.1), six more schemas (§17.2), the ninth licence capability `stream_render`, `gate.listen` and renders on popboll.com (§19.1), the pocket keymap (§18.4), a person's hub answers held in memory (§19.3), attestation by signed fields (§19.4), and signed image releases (§17.3).
- **0.2-draft (2026-11-10).** The Bollard SDK 0.1.0 is described (Part C, §17–§19); the SDK's buttons, gestures, cues and keymap are described beside the wire's own labels; the cartridge messages and `cartridge.yaml` of the old Part C are withdrawn; §20 records what is decided about the cart; Part B points at the SDK's schema, limits, reader and simulator; the licence is no longer "proposed".
- **0.1-draft.** First draft.

## 23. Licence

- **This specification text:** CC BY 4.0.
- **The Bollard SDK**, including the example dock and the example routines on this page: Apache-2.0.
- **Not open:** Bollawax itself (the band, the judges and every image), which runs on your device under the [Bollawax Device Licence](/device-licence); the Snipler engine and files, all rights reserved; and every corpus, which stays under its own licence.

These licences cover the documents and code, not the project's names and logos.
