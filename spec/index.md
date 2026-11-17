# Pop Boll Developer Specifications

Version 1.2-draft · Status: speculative draft · Updated 2026-11-17 · As of Bollawax 0.3.7 and Bollard SDK 0.5.0

> **Speculative draft.** No Pop Boll hardware has shipped, and nothing on these pages has been built or validated on hardware. Dimensions, pinouts and protocols will change without notice, and nothing here is an offer, a commitment or a promise of compatibility. We would love to hear about partnership, OEM and dev-kit ideas: use the contact form below.

> **Note:** The band's brain is a removable cart, the **Bolltridge**. It lives in the ball, and the same cart can also go into other docks, such as the Pop Snipler. The software pages here are current with Bollawax 0.3.7. The hardware page is not: [Bollard](bollard.md) still documents the first interface, under the Boll's foot, and the specification that replaces it for the cart is not written.

These pages are for people who want to build things for the Pop Boll: software that changes how the Boll writes songs, clients of its corpora, and docks and accessories. They are open specifications. You do not need our permission, a licence fee or a certification to build to them.

## What the Pop Boll is

The Pop Boll is a glowing ball with a tiny band inside. Sixteen virtual musicians jam, seven judges score every take, and together they write and play pop songs, learning from licensed song collections called corpora.

- **Its brain is a cart.** The band runs on the Bolltridge, a cart that stands in the ball. Take the cart out and the ball is a speaker and a light; put the cart in another dock and the same band plays there.
- **It works offline.** Everything the band needs is on the cart. A Boll that has never been online makes songs exactly like one that has. When it is online, it fetches new corpora and uploads the songs it made.
- **It lights up.** Its lights show each musician in their own colour, in time with the music.
- **It has a front panel**, the medallion, with three buttons, a USB-C port and a 3.5 mm audio output.

## The Bollard SDK

The **Bollard SDK** is the open library (Apache-2.0) that every client of the platform builds on, ours included: the Pop Boll's image and popboll.com run on it. Its import name is `bollardeck`, in Python and in the browser. Bollard SDK 0.5.0 (shipped with Bollawax 0.3.7) holds:

- **routines**: the hooks into the song factory, with a simulator and a command line;
- **the device layer**: buttons and gestures, button cues, the keymap (with a pocket map for a cart on its own battery), device identity and maker codes, draft dock and cart descriptors, and the 13 × 8 light matrix engine, the same code on the device and on the web;
- **the corpus client**: the one way to read a corpus, with a gate that refuses whatever a corpus's licence does not allow, now nine capabilities with `stream_render` for corpora that may be heard rendered through Pop Boll's own sounds (popboll.com plays such a corpus "played from the score" to everyone signed in; a Pop Boll renders it on the device);
- **help**: the help framework the site runs on (help packs, offers when a person seems stuck, guided tours and captioned INTRO videos);
- **Pop Snip files**: reading, writing and checking `.pxs`, a tracker module that carries its song's credits, licences and MIDI;
- **Pop Snip records**: the signed records of Pop Snip apps, the third-party apps at `<name>.popsnip.app`, checked the same way in Python and in the browser, and the check a device makes before it runs one (in Python);
- **a draft deck**: a minimal deck service and client for the dock messages, in one process or over a Unix socket;
- **schemas** for every format, with a validator.

Not available yet, and planned: the deck on devices (over USB and Bluetooth, on a Pop Boll), sign-in, a sandbox for third-party apps, a signed registry, and the Pop Snipler's capability boundary. [bollardeck Part C](bollardeck.md#17-part-c-the-bollard-sdk) has the detail, and [the SDK's own page](/sdk) says where to get it and how to start.

## Bollard and bollardeck

**Bollard** is the open ecosystem of docks and accessories, and the interface they share. The published [Bollard Physical Specification](bollard.md) is version 1: a dock mates with the Boll's foot through a 3.5 mm plug, a USB-C plug and a row of 10 spring pins. With the cart, the interface that matters becomes the **Bollport**, the single USB-C connection between a cart and the dock it stands in, and **Bollard v2** will be the open specification for building such a dock. It is not written; [Bollard §25](bollard.md#25-bollard-v2-what-is-decided) lists what is decided.

**bollardeck** is the API and the SDK. **Routines** are small Python programs that hook into the Boll's song factory on your own Boll; they are built and you can write one today. The dock messages (reading what is playing, the song's MIDI stems, the beat, the lights and the buttons, and sending volume, transport, remix and light-sync requests) are a draft. The SDK has a minimal draft service for them, but no Pop Boll runs one yet. The [bollardeck API](bollardeck.md) covers both, and the SDK.

## Device classes

| Class | What it is | Interface | Read |
| :--- | :--- | :--- | :--- |
| **The Bolltridge** | the cart: the computer of the Pop Boll and the Pop Snipler. It runs Bollawax, holds the corpora and the radio, and is the USB host of whatever dock it stands in. Up to two share a dock | the Bollport | [Bollard §25](bollard.md#25-bollard-v2-what-is-decided) |
| **Docks for the cart** | what a cart stands in: the Pop Boll, the Pop Snipler, and docks that others will build to Bollard v2 | the Bollport and a dock descriptor (not written) | [Bollard §25](bollard.md#25-bollard-v2-what-is-decided) |
| **Bollard v1 docks** | anything that mates with the v1 foot: speakers, amps, charging stands, light bases, stackable pucks, and the passive Boll Cap. Drawn before the cart; their future is not decided | Bollard v1, one of four profiles | [Bollard §3](bollard.md#3-profiles) |
| **Wireless accessories** | anything that talks to the deck over Bluetooth Low Energy with no physical connection (draft; no service yet) | bollardeck over BLE | [bollardeck §3](bollardeck.md#3-transports) |
| **Routines** | software only: Python hooks into the song factory that run on your own Boll | bollardeck Part B | [bollardeck Part B](bollardeck.md#11-part-b-routines) |
| **PWHAMSS devices** | devices a person works on alongside the band: a Workshop and context-switching keys, all drawing one frame, with a Bolltridge docked in them. The first is the Pop Snipler, with its clear edition, the Glass Snipler | a dock for the cart | [PWHAMSS](pwhamss.md), the [Pop Snipler](pop-snipler.md) and the [Glass Snipler](glass-snipler.md) |

## PWHAMSS, the Pop Snipler and the Glass Snipler

The Boll plays by itself. **PWHAMSS** (Personal Workshop for Human-Device Animation and MIDI Sync Systems) is the family of Pop Boll devices where a person works alongside the band instead: the same Bollawax engine, the same sixteen musicians and seven judges, the same licensed corpora, with a person at the keys pulling material out of songs, cutting it and handing it back. Every PWHAMSS device keeps an always-visible Workshop, keys that redraw their legends with the mode, a frame that every screen and light draws from, and a personal library that follows the person through HAMS sync. The [PWHAMSS page](pwhamss.md) states those principles, the event and frame contract, and the roadmap.

The **Pop Snipler** is the first PWHAMSS device, and the physical station for Pop Snip, the music-making station inside Pompas. It is a 15.6 inch touch screen in a dock about 38 mm tall, with two slots for carts in its back. It is touch only: Pop Snip draws its keys, pads and knobs on the screen, and the screen floats on a force frame (four corner force sensors and an accelerometer) that gives touches velocity and pressure. It has no computer of its own: a Bolltridge cart docked in its back drives the screen, the same cart that lives in a Pop Boll. The **Glass Snipler** is its clear edition: the same dock in clear resin, with DSP mode (planned), a set of editors on the device for what normally only signed releases change. A clear control layer of keys and knobs is planned as a later accessory, if a stretch goal of the crowdfunding campaign is reached. Both devices are proprietary products; the [Pop Snipler page](pop-snipler.md) has the dock, the force frame, the inputs and what is not decided, and the [Glass Snipler page](glass-snipler.md) says what differs.

Neither device exists in hardware. An earlier version of the design was built as a web simulator at popboll.com/pwhamss, open to superusers during development. The simulator is frozen while the station is rebuilt inside Pompas; the [PWHAMSS page](pwhamss.md) keeps its key maps and its frame and event contract.

## File formats: XMLX stem packs

**[XMLX 6.0](/xmlx)** is the Pop Snip MIDI stem pack. It is a folder (or a zip) of perfectly synced Standard MIDI Files, one per stem, plus one XML manifest. The manifest carries the tempo map, the parts, each stem's sound (a SoundFont by hash and path, with a bank and a program), where each stem came from, how the pack was made, and its licences. It contains no audio. XMLX is also the only sidecar of a `.pxs` song. Its namespace is `https://xmlx.app/ns/6`, and the specification comes with an XSD grammar and Schematron rules. The specification's text is CC BY 4.0, and its tools are Apache-2.0.

## Bollard v1 at a glance

This table is the v1 foot interface. For the cart and the Bollport, see [Bollard §25](bollard.md#25-bollard-v2-what-is-decided).

| Item | Value |
| :--- | :--- |
| Connectors | 3.5 mm TRS + USB-C + BCR-10 (10 spring pins in a straight row at 2.54 mm pitch), all on one floating plate inside a spring piston |
| The Boll's side (female) | a 3.5 mm jack, a USB-C receptacle and 10 hard-gold pads in the floor of a well in the foot; 4 magnets (S pole down); a key pocket at the front |
| Reference plane | Datum A, the Boll's rigid foot face. The pad plane is 7.5 mm above it |
| Piston | Ø 41.5 mm, 15 mm travel, extended face 22.0 mm above Datum A |
| Spring pins | free tips 8.2 mm above Datum A, so 0.7 mm of compression on the pads |
| Profiles | Full (everything), Lite (4 pins, no USB), USB-C (USB only), Passive (audio and power only) |
| Power into the Boll | USB-C VBUS at 5 V, up to 3 A (Full, USB-C, Passive), or V_AUX at 5 V, up to 2 A (Lite) |
| Power from the Boll | none on its foot; at most 5 V / 1.5 A, on its medallion USB-C port only |
| Stack power | V_STACK, 10–17 V, 4 A for the whole stack (Full profile; the Boll does not connect to it) |
| Audio | A-BUS analog line, 1.0 Vrms at 0 dBFS, wired through every module; USB Audio Class 2 optional |
| USB roles | the Boll is always the USB host (it takes the role by a USB PD data-role swap) and only ever sinks power on its foot |
| Identity | Full: an I2C header (magic `BLD1`) and a JSON descriptor; Lite: the same header over 1-Wire; USB-C: USB descriptors and the bollardeck `hello` |
| Sync | a hardware SYNC pin: 60 Hz frame ticks, 2 ms beat pulses, 4 ms downbeat pulses |
| Module sizes | Full Ø 135 mm, Mini Ø 72 mm; heights in 25 mm steps, at least 50 mm |
| Stacks | up to 5 modules plus the Boll above any base, with a static tip angle of at least 12° |
| API | `bollardeck/1`: JSON Lines over USB CDC-ACM (interface string `bollardeck`) or BLE GATT |

## The specifications

- **[Bollard Physical Specification](bollard.md)**, version 1.0-draft, for hardware developers: datums and dimensions, the floating plate and piston, the BCR-10 pins and pinout, power, USB-C roles, analog audio, enumeration, sync, profiles, stacking, the Boll Cap, the Reference Bollard speaker design, hobbyist builds, the conformance checklist, and what is decided for Bollard v2.
- **[bollardeck API](bollardeck.md)**, version 0.2-draft, for software developers: routines (hooks, context, limits, packaging and two complete examples); the Bollard SDK (buttons, gestures, cues, the keymap, the corpus client and its gate, the schemas); and the draft dock messages (transports, the envelope, the handshake and capabilities, stems and rights).
- **[Popsniplish](popsniplish.md)**, edition 0.1.0, for software developers: the MiniCOSM the band inside the Boll speaks, told as a MiniCOSM is told on cosmoes.org: its volumes, modules and kinds, the entries as constructed fabulas and their shorts, the vote, morphs and readings, the knob lexicon, the eight moves it declares for Thym, its checks, FEED on a Boll and conformance, with the reference generated from its manifest and programs.

Good places to start:

- Writing a routine: [hooks](bollardeck.md#12-hooks) and the [example routines](bollardeck.md#15-example-routines).
- Reading a corpus: [the corpus client and the gate](bollardeck.md#19-the-corpus-client-and-the-gate).
- Handling the three buttons or lighting them: [buttons, gestures, cues and the keymap](bollardeck.md#18-buttons-gestures-cues-and-the-keymap).
- Writing dock software (a draft): the [handshake](bollardeck.md#5-handshake-and-capabilities) and the [example dock](bollardeck.md#10-example-dock).
- Building a dock for the cart: [what is decided for Bollard v2](bollard.md#25-bollard-v2-what-is-decided).
- Writing a renderer or a tool for a PWHAMSS device: the [frame and event contract](pwhamss.md#5-the-frame-and-event-contract) and the Pop Snipler's [inputs](pop-snipler.md#4-inputs-a-developer-meets), and the simulator's [modes](pwhamss.md#63-modes) and [sniplets](pwhamss.md#610-sniplets).

## Status and versioning

The hardware pages are speculative drafts. No Pop Boll or dock has been built to these documents, and there is no shipping date. The software is further on: routines and the Bollard SDK are built and run since Bollawax 0.3.0. Each specification ends with an "Open items" section that lists what has not yet been validated on hardware.

| Document | Version | Wire identifiers |
| :--- | :--- | :--- |
| Bollard Physical Specification | 1.0-draft | header magic `BLD1`, JSON `"bollard": "1.0"` |
| bollardeck API, Part A (docks) | 0.2-draft | wire protocol `bollardeck/1`, envelope `"v": 1` |
| bollardeck API, Part B (routines) | 0.2-draft | routine API `api: 1` |
| Bollard SDK | 0.5.0 | licence block `popboll.licence/1`, keymap `"v": 2`, `mrph5/1`, `wbol/1`, `help-pack/1`, `help-director/1`, `pxs/1`, `popsnip/1` |
| Pop Snipler: Device Specification | 0.2.0-draft | keys `0`–`47`, side keys `0`–`5`, knobs `S` `M` `L` `H` |
| Glass Snipler: Device Specification | 0.2.0-draft | as the Pop Snipler |
| PWHAMSS | 0.0.4-draft | frame and event envelope `"v": 1`, sniplet ids `sn_` + 12 hex |
| Popsniplish | edition 0.1.0 | `popsniplish/1` |

- **Bollard** minor versions only add registers, classes, profiles or JSON fields. Any mechanical change, or any change to an assigned pin, is a new major version with a new header magic.
- **bollardeck** additions within a major version are optional fields, new message types, new error codes and new capabilities. Removing a field or changing its meaning is a new major version, negotiated in the `hello` handshake.
- The two move independently. A Bollard v1.0 dock speaks `bollardeck/1`.
- **The Bollard SDK** has its own version numbers, starting at 0.1.0, and says which wire and format versions it speaks (`bollardeck.SPEAKS`).
- Expect breaking changes before the 1.0 final releases. Each page carries its own change log.

### Changes

- **1.2-draft (2026-11-17).** The Pop Snipler is touch only, with a force frame under its screen; the Glass Snipler is its clear edition, with DSP mode; a control layer is a later accessory. The device pages' versions are updated. Brought up to Bollawax 0.3.7 and Bollard SDK 0.5.0.

## Licensing

The platform is licensed in layers: the text of these pages and the hardware specifications are CC BY 4.0, the hardware reference designs (the Reference Bollard, the Lux Puck and the Boll Cap) are CERN-OHL-P v2, so anyone can build and sell closed commercial docks, and the open code, the Bollard SDK with its examples, is Apache-2.0, which includes an explicit patent grant. Everything else is all rights reserved: Bollawax itself (the band, the judges and every image) runs on your device under the standing Bollawax Device Licence, free and without asking; the Sniplers' software and design are all rights reserved for now; and each corpus stays under its own licence and artist agreement and is never redistributable.

- **[Bollawax Device Licence](/device-licence)**: build, sell or own a device that runs a genuine Bollawax image, with no registration and no fee.
- **[Snipler Use Grant](/snipler-use-grant)**: fetch and run the Snipler software on a device that runs a genuine Bollawax image, with no registration and no fee.
- **[Trademark policy](/trademarks)**: the names, and how to say "Runs Bollawax", "Bollard compatible" or "works with the Pop Boll". The licences above cover documents, designs and code, not the names and logos. You may describe a product as "built to the Bollard Physical Specification v1.0, Full profile" (or whichever profile applies).
- **[Maker codes](/makers)**: the free registry of the 3 to 6 letter codes in device serials.
- **[The Pop Boll Shake](https://bollawax.org/shake)** ([PDF](https://bollawax.org/shake.pdf)): the plain-English agreement artists sign to lend their music to Pop Boll.
- **[What "study" means](https://bollawax.org/study)**: exactly what the musicians keep when they study a corpus, and that no AI model is trained on it.
- **[Hosting your own corpus](/hosting-your-own-corpus)**: for artists who keep their recordings on their own server and let Pop Boll pull from it (a draft; the Pop Boll side is not built yet).

None of these pages is legal advice, and the device licence and the trademark policy are drafts awaiting counsel review.

## Get in touch

Use the contact form below. We would especially like to hear from:

- dock, speaker and accessory makers interested in partnership or OEM work;
- developers who want a dev kit when one exists;
- anyone who finds a mistake, an ambiguity or a missing number in these drafts.

Tell us what you want to build and which profile you have in mind. Nothing you send commits either of us to anything.

## FAQ

### Can I build and sell a dock?

Yes. That is the point of an open specification. Build any shape, on any profile, and sell it under your own name at any price. The Reference Bollard speaker is an open reference design that anyone may build and sell as well. Because these are drafts, and because the dock interface is changing for the cart, please do not cut production tooling until Bollard v2 is published.

### Do I need permission?

No. There is no certification, no licence fee and no approval step for hardware. Conformance is self-declared: if you say your product is "Bollard v1.0, Full profile", you are stating that it passes the checklist for that profile. You are responsible for your product's safety and regulatory compliance. A future storefront may list docks, and listing would ask for a short self-declaration, but it will not be required to build or sell anything.

### When will Bolls ship?

There is no date. No Pop Boll hardware has shipped, and this specification is published ahead of the hardware so that people can comment on it and start designing.

### Can I get a dev kit?

Not for hardware. If you would like a dev kit when one exists, say so through the contact form. For software you need nothing from us: the Bollard SDK's simulated board, its routine simulator and its schemas run on any computer.

### Can routines run on the website?

No. Routines run only on your own Pop Boll. The website never runs user routines, and its song factory loads none. Routines work only with the corpora already on your Boll, and no API creates corpora.

### Does my accessory have to touch the Boll?

It will not have to. The draft lets any accessory speak bollardeck over Bluetooth Low Energy with no physical connection at all. That service is not built yet.
