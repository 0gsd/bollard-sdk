# Bollard Physical Specification

Version 1.0-draft · Status: speculative draft, superseded in part · Updated 2026-11-10 · As of Bollawax 0.2.4 and Bollard SDK 0.1.0

> **Speculative draft.** No Pop Boll hardware has shipped, and nothing on this page has been built or validated on hardware. Dimensions, pinouts and protocols will change without notice, and nothing here is an offer, a commitment or a promise of compatibility. We would love to hear about partnership, OEM and dev-kit ideas: use the contact form on this site.

> **Note:** This page is **Bollard v1**, drawn when the Pop Boll's computer was built into the ball and docks mated with its foot. Since 2026-11-09 the band's brain is a removable cart, the **Bolltridge**: it lives in the ball, and the ball and the Glass Snipler are docks for it. That changes this page's premise, not its arithmetic. Please read it with these four corrections, and do not cut tooling to it.
>
> 1. **Bollard v2 will be the open specification for third-party docks.** It is built on the Bollport, the connection between a cart and its dock, and on a dock descriptor. It is not written. §25 records what is decided.
> 2. **The cart is the USB host and takes its power from its dock.** Every rule below that makes "the Boll" the host, the power sink or the Bluetooth central describes v1.
> 3. **The first Pop Boll built around the cart gives the well in its foot to a speaker.** It has no v1 foot connector, so nothing on this page can be docked under it. Whether a later Boll or Bollard v2 keeps any of the foot interface, the pucks or the Boll Cap is not decided.
> 4. **The cartridge class of §17 is retired.**

Bollard v1 is the open interface on the bottom of a Pop Boll: how a dock, a speaker, a charging stand or a stack of light pucks mates with the ball. This document fixes only that interface. Everything else about your device (its shape, its sound, its price) is yours. The software that runs over the connector is the [bollardeck API](bollardeck.md), and the [overview page](index.md) introduces both.

## 1. Scope and conventions

This specification defines how a dock mates with the bottom (the south-pole foot) of a Pop Boll. For the Full profile it also defines how independently made cylindrical modules, called pucks, stack under a Boll in any order. Docks are expected to compete with each other: a three-foot reverse-tapering tower with booming bass, a dock with its own processor that reads the song's MIDI and remixes it, a charging stand with a light ring, a bookshelf amp. The specification fixes only the interface between them and the Boll.

The key words **MUST**, **MUST NOT**, **SHOULD**, **RECOMMENDED** and **MAY** are used as described in RFC 2119.

- All dimensions are in millimetres and all angles in degrees unless stated otherwise.
- Tolerances are given as ± or as upper and lower deviations: Ø 41.5 −0.05/−0.15 means 41.35 to 41.45.
- Figures marked *estimate* come from calculation or datasheets, not from a measured sample.
- Part numbers are examples. Any part that meets the stated requirement is conforming.
- Requirement identifiers (L1, U3, M6 and so on) are stable within a version, so conformance claims can cite them.

### 1.1 Terms

| Term | Meaning |
| :--- | :--- |
| Dock | Anything that mates with a Pop Boll's foot, on any profile (§3) |
| Puck | A Full-profile module with a male top face and a female bottom face, so it stacks |
| Module | Anything with a Full-profile face. The Boll is a module with only a female (bottom) face |
| Top face, male face | The dock side of the interface: piston, plugs and spring pins |
| Bottom face, female face | The Boll's foot, or a puck's underside: well, jack, receptacle and pads |
| BCR-10 | The Bollard Contact Row: 10 spring pins in one straight row at 2.54 mm pitch on the male face, landing on 10 flat pads on the female face |
| Floating plate | The plate inside the dock's piston that carries the 3.5 mm plug, the USB-C plug and the BCR-10 row. It floats ±0.4 mm radially and ±3° in tilt |
| Piston | The spring-loaded pilot that hides the plate when nothing is docked and centres the Boll when it is |
| Stack host | The single module that is the I2C controller and drives CHAIN and SYNC: the Boll when present, otherwise the topmost host-capable module (§14) |
| A-BUS | The analog stereo line on the 3.5 mm contacts (§11) |
| V_STACK | The high-current DC rail on pins 1–2 (§9) |
| V_AUX | The 5 V input on pin 10 that charges the Boll from a Lite dock (§9) |
| Passive module | A module with no USB endpoint, whose USB-C is wired straight through |
| Active-USB module | A module that contains a USB hub or a USB device and terminates USB-C on both faces |
| Class-0 module | A module with no microcontroller: a spacer, a pure battery, a riser (§12.2) |
| Datum A | The reference plane for every height in this document (§4) |
| bollardeck | The JSON-lines API between a dock and the Boll over USB or BLE ([bollardeck API](bollardeck.md)) |

## 2. The interface in brief

**Decision (normative):** the Bollard interface is a 3.5 mm TRS plug, a USB-C plug and a BCR-10 row (a straight 1×10 row of spring pins at 2.54 mm pitch), all on one floating plate inside a spring piston. They mate with a 3.5 mm jack, a USB-C receptacle and 10 hard-gold pads in the floor of the Boll's foot well. Four NdFeB magnets hold the Boll down, and a key bump sets its rotation.

The three connectors split the work:

- **3.5 mm TRS** carries analog stereo audio (A-BUS) down the stack.
- **USB-C** carries power up to the Boll and USB 2.0 data, with the Boll always the USB host.
- **BCR-10** carries the stack rail (V_STACK), ground, I2C for enumeration and control, a service-request line, hardware beat sync, the point-to-point CHAIN line, and a 5 V charging input for docks without USB.

Why a straight spring-pin row:

- Anyone can buy the male side. It is a standard 0.1-inch single-row spring-pin strip that solders straight into perfboard. The female side is copper pads on any PCB.
- The pins ride on the floating plate with the plugs. Once the plugs enter their jacks, the plate is registered to the Boll and the pins land on the pads within the plug fit, so tolerances do not add up through a stack.
- When nothing is docked, the piston face covers the pins and the plugs, so a dropped Boll, a coin or a finger cannot bend or short them.
- The pads sit flush in the floor of a recessed well, away from the face that meets tables, coins and wet worktops.

Alternatives that were evaluated and set aside: magnetic pogo connector pairs (no common standard for pitch, magnets or polarity; their magnets fight the four retention magnets; retail 2.54 mm versions stop at 5 contacts), a second USB-C receptacle used as a custom connector (it shears in a knock, and people would plug chargers into it), a pin header behind a door (not blind-matable), leaf or button spring contacts (short stroke, and they snag when slid sideways), and DIN, mini-DIN or a second TRRS barrel (contacts short while sliding in, and the pins are fragile).

Two of them remain allowed inside a dock. A Lite dock MAY use a magnetic pogo module behind its boss, and any dock MAY use leaf or button spring contacts at the BCR-10 positions, as long as the contact positions, the boss or piston, and conformance items M3 and M6 (§21) are met.

```text
   A Boll seated on a dock (side view, not to scale)

              .-------------------------------.
             /            POP BOLL             \
            |      glowing ball, Ø 135 mm       |
             \                                 /
              '----.  foot well (female)  .---'     well floor: 3.5 mm jack, USB-C
          ~~~~~~~~~|______________________|~~~~~~   receptacle and 10 gold pads
          =========|  piston (pushed in)  |======   dock top face (male): plugs and
          |        | [3.5]  [C]  :::::::: |     |   BCR-10 pins on the floating plate
          |        '----------------------'     |
          |                 DOCK                |
          '-------------------------------------'
```

## 3. Profiles

All profiles mate with the same foot. They differ only in which of its features they use, and no profile adds a connector. A dock declares exactly one profile.

| Profile | Dock top face | Uses on the Boll's foot | Typical docks |
| :--- | :--- | :--- | :--- |
| **Full** | piston and floating plate with the 3.5 mm plug, the USB-C plug and all 10 BCR-10 pins; 4 magnets | jack, receptacle, pads 1–10 | stackable pucks, speakers that want stack order, light sync and V_STACK |
| **Lite** | fixed pilot boss with the key bump; spring pins at BCR-10 positions 3, 7, 8 and 10 only; magnets or steel discs | pads 3 (GND), 7 (1-Wire ID), 8 (SYNC), 10 (V_AUX) | simple docks with no USB: charging stands, light bases, toys |
| **USB-C** | pilot and a floating USB-C plug; no pins | receptacle only | docks with their own processor: power into the Boll, USB audio both ways, bollardeck over USB |
| **Passive** | pilot with a 3.5 mm plug and a USB-C plug on a floating plate; no pins | jack and receptacle (power only) | the simplest powered speaker dock: an amp fed by line audio that also charges the Boll |

Any dock, on any profile or with no physical connection at all, MAY also speak bollardeck over BLE.

```text
            what each profile puts against the Boll's foot (dock top faces, side view)

   Full                 Lite                 USB-C                Passive
   ___|piston|___       ___|boss|___         ___|boss|___         ___|piston|___
  | [3.5] [C]    |     |  (no plugs)  |     |     [C]     |      | [3.5]  [C]   |
  | ::::::::::   |     | :  ::  :     |     |  no pins    |      |  no pins     |
  | BCR-10 (10)  |     | pins 3,7,8,10|     |  magnets    |      |  magnets     |
  '--------------'     '--------------'     '-------------'      '--------------'
   stack, sync,         charge (V_AUX),      USB power, USB       line audio,
   V_STACK, A-BUS       1-Wire ID, SYNC      audio, bollardeck    USB-C charge
```

A USB-C or Passive dock may use either the piston or a fixed boss (rules C1 and P1 below), so the drawing shows one of each.

### 3.1 Compatibility matrix

✓ = works · opt = works if the dock implements the optional part · — = not available.

| Pop Boll feature | Full | Lite | USB-C | Passive | BLE bollardeck (any) |
| :--- | :-: | :-: | :-: | :-: | :-: |
| Boll charges from the dock | ✓ VBUS 5 V / 3 A | ✓ V_AUX 5 V / 2 A | ✓ VBUS | ✓ VBUS | — |
| Analog line audio to the dock (A-BUS) | ✓ | — | — | ✓ | — |
| Digital audio Boll → dock and dock → Boll (USB Audio) | opt (active-USB) | — | ✓ | — | — |
| Dock identity | ✓ I2C header and JSON | ✓ 1-Wire header | ✓ USB descriptors and `hello` | — (shown as "passive") | ✓ `hello` |
| Hardware beat and frame SYNC (sub-millisecond) | ✓ | ✓ | — (`beat` message, about 1–2 ms, estimate) | — | — (`beat`, 15–30 ms, estimate) |
| LED frames | ✓ I2C broadcast ≤ 16 Hz; bollardeck `led` at 60 Hz | — | ✓ `led` | — | ✓ `led` (rate-limited) |
| LED matrix frames (13 × 8, optional) | opt (bollardeck `matrix` over USB if active-USB) | — | ✓ `matrix` ≤ 15 Hz | — | ✓ `matrix` ≤ 5 Hz |
| Now playing, MRPH5 stems, buttons, battery, remix requests | opt (bollardeck over USB if active-USB) | — | ✓ | — | ✓ |
| Stack order, several modules under one Boll | ✓ CHAIN | — | — | — | — |
| V_STACK power for loads in a stack | ✓ | — | — | — | — |
| Works with no Boll docked (§14) | ✓ | lights only | the dock's own functions | amp only | — |

### 3.2 Lite profile rules

- **L1 Pilot.** A fixed boss Ø 41.5 −0.05/−0.15 with a 2.5 × 45° lead chamfer and the key bump of §5.2. Its face is at +7.0 above Datum A, so it stops 0.5 mm short of the well floor (+7.5).
- **L2 Pins.** Spring pins at BCR-10 positions 3, 7, 8 and 10 only (§6), with free tips 0.7 ± 0.25 mm above the pad plane at seat (+8.2 above Datum A). The other six positions MUST be empty.
- **L3 Retention.** Magnets N pole up at the §5.2 positions, or steel discs at the same positions.
- **L4 V_AUX.** 5.0 V ± 5 %, at most 2.0 A, current-limited (an eFuse set to ≤ 2.2 A), and switched on only when a seated Boll is detected (a Hall sensor under one of the Boll's magnets, or a pilot switch). The Boll treats V_AUX ≥ 4.5 V for 50 ms as attach.
- **L5 ID.** A 1-Wire slave (standard speed) on pin 7 that holds the 32-byte binary header of §12.5, followed by up to 96 bytes of short descriptor. A 1-Wire EEPROM works, and so does a small microcontroller emulating one (example: WCH `CH32V003`).
- **L6 SYNC.** Pin 8, receive only. There is no I2C, CHAIN or colour-frame broadcast on the Lite profile.
- **L7 Terminal.** A Lite dock is the bottom of the stack and MUST NOT offer a female face.

### 3.3 USB-C profile rules

- **C1 Pilot.** The piston of §5.2 is RECOMMENDED. A fixed boss per L1 is allowed if the USB-C plug floats (±0.4 mm radial, ±3° tilt).
- **C2 Power and roles.** The dock is a USB Type-C Source to the Boll (5 V, up to 3 A; USB PD optional) and MUST accept a data-role swap (DR_Swap) from the Boll (§10, U1).
- **C3 Device.** The dock is a USB 2.0 device with a CDC-ACM interface whose interface string is `bollardeck` ([bollardeck transports](bollardeck.md#3-transports)). It MAY add USB Audio Class 2 sink and/or source functions.
- **C4 No pad contact.** Nothing touches the pads, and the Boll leaves them high-impedance.

### 3.4 Passive profile rules

These rules are numbered P1–P4 within the Passive profile. They are separate from the power rules P1–P8 in §9.2, and the checklist in §21 says which is meant.

- **P1 Pilot.** As C1, with both plugs on one floating plate.
- **P2 Audio.** The 3.5 mm plug receives A-BUS per §11.
- **P3 Power.** The dock is a Source only. D+ and D− are left unconnected, or wired straight to a rear receptacle under rules U3 and U5 (§10).
- **P4 Identity.** None. The Boll sees a USB-C attach with no USB data partner and no answer at I2C address 0x2F. It labels the dock "passive", routes audio to its foot jack and charges.

## 4. Coordinates and datums

- The origin is on the module axis, in the interface plane.
- +Y points to the module's front, which on the Boll is the direction of its medallion (the control panel with its buttons and ports). This direction is 0°.
- +X points to the right when you look down at a dock's top face with +Y pointing away from you. The 3.5 mm plug is at negative X and the USB-C plug at positive X.
- The Boll's foot, seen from below, is the mirror image: its +X points to the left, so pad 1 (x = −11.43) is on the right when you look up at the Boll.
- **Datum A** is the top of the dock's rigid land, which is the same plane as the Boll's rigid foot face when the Boll is docked. All heights are measured from Datum A, positive toward the Boll (upward, for a dock standing on a table).
- The only angular positions in this version lie on the axes: the four magnets on the ±X and ±Y axes (0°, 90°, 180° and 270°), and the Boll's well drain and the Boll Cap's side ports at the rear (−Y, 180°).

### 4.1 Heights at a glance

| Height above Datum A | Male side (dock) | Female side (Boll or puck) |
| ---: | :--- | :--- |
| +22.0 | extended piston face (nothing docked) | — |
| ≤ +21.5 | plug tips, fixed on the plate, at least 0.5 mm below the extended piston face | 3.5 mm plug fully engaged, 14.0 mm past the well floor |
| +8.2 ± 0.15 | pin free tips (nothing docked) | — |
| +7.5 | piston face when docked (pressed against the well floor); pins compressed 0.7 mm to here | well floor = pad plane, ±0.10 |
| +7.0 | retracted piston hard stop; fixed pilot boss face (L1) | — |
| +3.0 | — | end of the lead-in cone: the well is Ø 42.0 from here up to the floor |
| 0.0 | Datum A: top of the rigid land (Ø 56 / Ø 50) | Datum A: the rigid foot face |
| −2.5 | the deck and the TPE seat ring (the land stands 2.5 mm proud of the deck) | — |
| −3.0 | — | TPE rim plane with nothing docked: the rim stands 3.0 mm proud of the foot face and is compressed 0.5 mm onto the seat ring when docked |

The well floor is 7.5 mm above Datum A, which is 10.5 mm above the Boll's TPE rim plane. Earlier drafts measured the 10.5 mm from Datum A; the figures above are the corrected ones.

## 5. Mechanical interface

### 5.1 Module classes

These classes apply to Full-profile modules. Docks on other profiles, and terminal docks that offer no female face, may be any shape that meets the stability rules of §16.

| Class | Outer diameter | Height H | Use |
| :--- | :--- | :--- | :--- |
| **Full** | Ø 135.0 ± 0.3 | n × 25 mm, at least 50 mm | speakers, batteries, woofers, large light pucks |
| **Mini** | Ø 72.0 ± 0.3 | n × 25 mm, at least 50 mm | light rings, sensors, controller pucks, a Boll stand. **The mass above a Mini module MUST be ≤ 1.0 kg** |
| **Thin** (reserved) | Ø 135 or Ø 72 | 25 mm | needs a coaxial 3.5 mm and USB-C pass-through part that does not exist yet |

A module with both faces is at least 48.5 mm tall, because two assemblies stack on the same axis: the top plug assembly (15 mm of piston travel, the piston guide and the plug bodies, about 23 mm) sits above the bottom jack assembly (the 10.5 mm well measured from the rim plane, plus jack bodies of about 15 mm). 50 mm is the first multiple of 25 mm above that.

### 5.2 Top face (male)

| Feature | Requirement |
| :--- | :--- |
| Datum A land | rigid annulus Ø 56 / Ø 50, 2.5 mm above the deck |
| Compliant seat | TPE seat ring Ø 70 / Ø 58 on the deck, which receives the Boll's squish rim |
| Piston | Ø 41.5 −0.05/−0.15, lead chamfer 2.5 × 45°, extended face at +22.0, travel 15.0 ± 0.3 (retracted face at +7.0, 0.5 mm short of the well floor); spring 6 N preload, 10 N compressed; guide length in its bore ≥ 20 mm |
| Rotation key | bump Ø 3.0 × 2.0 high at (0, +15.0) on the piston face |
| Piston face openings | openings for both plugs, plus a 25.0 × 3.6 mm slot over the BCR-10 row. With the piston extended, plug tips and pin tips sit at least 0.5 mm below the piston face |
| 3.5 mm plug | TRS plug, axis at (−7.0, 0.0), on the floating plate |
| USB-C plug | Type-C plug, centre at (+8.0, 0.0), long axis parallel to Y, on the floating plate |
| BCR-10 | 10 spring pins on the floating plate, one row parallel to X at y = −11.0 (§6) |
| Floating plate | carries both plugs and the row; ±0.4 mm radial and ±3° tilt, on a spring gimbal |
| Magnets | 4 × NdFeB Ø 6 × 3 (grade N42–N52) at R 29.0 on the ±X and ±Y axes, **N pole up** |

```text
   DOCK TOP FACE, viewed from above (piston drawn retracted; +Y = front = 0°)

                               magnet (N up)
                 .-------------------------------------------.
               .'   TPE seat ring Ø70 / Ø58, land Ø56 / Ø50   '.
              /      .--------------------------------.         \
   magnet    |      /  piston Ø41.5                    \         |    magnet
   (N up)    |     |          key bump o (0, +15)       |        |    (N up)
             |     |                                    |        |
             |     |    ( )                [=USB-C=]    |        |
             |     |  3.5 (-7, 0)           (+8, 0)     |        |
             |     |                                    |        |
             |     |   1  2  3  4  5  6  7  8  9 10     |        |
             |     |  [:  :  :  :  :  :  :  :  :  :]    |   BCR-10 pins, y = -11.0
             |      \   slot 25.0 x 3.6 in the piston  /         |
              \      '--------------------------------'         /
               '.                                             .'
                 '-------------------------------------------'
                               magnet (N up)
                              -Y (rear, 180°)
```

### 5.3 Bottom face (female)

The Boll's foot and the underside of every puck present the same female face.

| Feature | Requirement |
| :--- | :--- |
| Datum A | the rigid foot face, 3.0 mm above the TPE rim plane |
| Compliant seal | TPE rim Ø 70 / Ø 58, 3.0 mm proud of the foot face, Shore A 20–40 |
| Well | Ø 50.0 at the TPE rim plane (−3.0), narrowing to Ø 42.0 at +3.0 (the lead-in cone), then a Ø 42.0 +0.10/0 cylinder up to the well floor |
| Well floor (pad plane) | **+7.5 above Datum A** (10.5 mm above the rim plane), ±0.10 |
| Key pocket | Ø 3.2 × 2.2 deep at (0, +15.0) in the well floor |
| 3.5 mm jack | TRS jack, mouth at (−7.0, 0.0) in the well floor, 14.0 mm engagement |
| USB-C receptacle | mouth at (+8.0, 0.0) in the well floor, long axis parallel to Y |
| BCR-10 pads | 10 pads 1.8 (X) × 3.0 (Y) mm at the same positions as the pins, ≥ 0.76 µm hard gold over nickel, flush with the well floor ±0.05 |
| Magnets | 4 × NdFeB Ø 6 × 3 at R 29.0 on the ±X and ±Y axes, **S pole down** |
| Rigidity | the jack, the receptacle and the pads are rigid in the face; all compliance is on the male side |

The Boll's own foot adds a drain and specific parts (§15).

```text
   BOLL FOOT, viewed from below (looking up at the Boll; medallion toward the top of the page)
   This is the mirror image of the dock view: interface +X points LEFT here.

                               magnet (S down)
                 .-------------------------------------------.
               .'    TPE rim Ø70 / Ø58, foot face inside      '.
              /      .--------------------------------.         \
   magnet    |      /  well Ø50 -> Ø42                 \         |    magnet
   (S down)  |     |          key pocket o (0, +15)     |        |    (S down)
             |     |                                    |        |
             |     |   [=USB-C=]               ( )      |        |
             |     |    (+8, 0)            3.5 (-7, 0)  |        |
             |     |                                    |        |
             |     |  10  9  8  7  6  5  4  3  2  1     |        |
             |     |  [] [] [] [] [] [] [] [] [] []     |   pads in the well floor, y = -11.0
             |      \          o drain (0, -16)        /         |
              \      '--------------------------------'         /
               '.        drain exits to the rim at 180°       .'
                 '-------------------------------------------'
                               magnet (S down)
```

### 5.4 Piston and floating plate

- The piston hides the plate when nothing is docked. Its face covers both plugs and the pin row, which sit at least 0.5 mm below it.
- The plate carries both plugs and the BCR-10 row and floats ±0.4 mm radially and ±3° in tilt on a spring gimbal. The plugs register the plate to the Boll, and the pins move with the plate.
- **Lateral loads MUST flow well ↔ piston ↔ piston bore** (guide length ≥ 20 mm). Neither the plate, nor the plugs, nor the pins may be a structural load path.
- **Bayonet or twist retention is not allowed**: it would shear the USB-C plug.

**Order of engagement** while a Boll is pressed down: the lead chamfer finds the well (capture about ±4 mm), and the key finds its pocket at up to ±8° of rotation, self-correcting. The piston retracts. The plugs enter the jack and the receptacle and pull the floating plate into registration. The pins touch the pads last, 0.7 mm before Datum A seats. The pads therefore never see a pin slide across them under load, and no pin touches a plug shell.

### 5.5 Forces and tolerances

| Item | Requirement |
| :--- | :--- |
| Insertion | ≤ 40 N in total (USB-C 5–20 N, 3.5 mm 5–15 N, piston 10 N, 10 pins ≤ 10 N, minus the magnets) |
| Retention | magnets 6–10 N total pull at Datum A contact, plus connector friction |
| Extraction | MUST be less than the weight of the lower module and everything beneath it, so the stack does not lift as a unit. Otherwise the manual MUST say "hold below to undock". ≤ 22 N is RECOMMENDED |
| Radial alignment | piston-to-well clearance 0.55–0.75 mm on diameter from the tolerances above (at most ±0.37 mm radial), absorbed by the ±0.4 mm plate float. Once the plugs engage, the pin-to-pad error is ≤ ±0.2 mm (estimate, set by the plug fit) against ±0.5 mm of pad margin (1.8 mm pad, pin tip Ø ≤ 0.8 mm) |
| Axial | per interface: well floor 7.5 ± 0.10 above Datum A on the female side, pin free height 8.2 ± 0.15 on the male side, so the compression is 0.7 ± 0.25 mm, inside the ≥ 1.2 mm pin stroke |
| Stack | up to 5 modules plus the Boll above any base. **The static tip angle of the stack MUST be ≥ 12°.** Mass and centre of gravity MUST be published in the descriptor (§12.7) |
| Durability | 5,000 dock cycles; spring pins rated for ≥ 10,000 cycles |

## 6. BCR-10 contact row

| Item | Male (dock, on the floating plate) | Female (well floor) |
| :--- | :--- | :--- |
| Positions | one row parallel to X at y = −11.0; pin n at x = −11.43 + 2.54 × (n − 1), so pin 1 at −11.43 and pin 10 at +11.43 | pad n at the same (x, y) |
| Contact | spring pin, tip Ø ≤ 0.8 mm | pad 1.8 (X) × 3.0 (Y) mm |
| Height | free tip at +8.2 ± 0.15 (0.7 mm above the pad plane) | flush with the well floor at +7.5, ±0.05 to the floor |
| Stroke and force | stroke ≥ 1.2 mm; 0.4–1.0 N per pin at working height | — |
| Finish | — | ≥ 0.76 µm hard gold over nickel for products (ENIG is fine for hobby builds) |
| Life | ≥ 10,000 cycles | 5,000 dock cycles, with pin plus pad < 50 mΩ afterwards |

```text
   BCR-10 row on the dock's top face, viewed from above (row at y = -11.0, pitch 2.54 mm)

   pin:      1       2       3       4       5       6       7       8       9      10
   x:     -11.43   -8.89   -6.35   -3.81   -1.27   +1.27   +3.81   +6.35   +8.89  +11.43
            [ ]     [ ]     [ ]     [ ]     [ ]     [ ]     [ ]     [ ]     [ ]     [ ]
          V_STACK V_STACK   GND     GND     SDA     SCL   ATTN_N   SYNC   CHAIN   V_AUX
```

Example male parts: a 10-position, 2.54 mm single-row spring-pin strip such as Mill-Max `823-22-010-10-040101`, or any generic 2.54 mm spring-pin strip for hobby builds. Mill-Max offers several 10-position single-row series (818, 823, 837, 873 and others) with different strokes and heights, and the stroke and force of the example part have not yet been checked against the requirement above. Generic strips are usually not rated for 5,000 cycles.

The female side is a strip of pads on any PCB. On the Boll it is a 1.0 mm FR-4 pad strip potted flush with the well floor. A reference pad-strip layout will be published with v1.0 final.

## 7. Pinout

The two power pairs sit at one end of the row and the 5 V input at the other, so a half-seated or tilted plate cannot bridge V_STACK to a logic pin before ground makes contact: pins 3 and 4 always sit between them.

| Pin | x (mm) | Name | Type | Level, rating | Function |
| :-: | ---: | :--- | :--- | :--- | :--- |
| 1 | −11.43 | V_STACK | power | 10.0–17.0 V, 3 A per pin | stack power rail (§9) |
| 2 | −8.89 | V_STACK | power | as pin 1 | |
| 3 | −6.35 | GND | power | 3 A per pin | V_STACK return; bonded to USB-C ground and chassis |
| 4 | −3.81 | GND | power | 3 A per pin | |
| 5 | −1.27 | SDA | I2C, open-drain | 3.3 V, 100 or 400 kHz | enumeration and control (§12) |
| 6 | +1.27 | SCL | I2C, open-drain | 3.3 V | |
| 7 | +3.81 | ATTN_N | open-drain, wired-OR (Full); 1-Wire (Lite) | 3.3 V | service request, held low by every unenumerated module. On Lite, the 1-Wire ID line (L5) |
| 8 | +6.35 | SYNC | push-pull from the stack host | 3.3 V CMOS | frame and beat timing (§13) |
| 9 | +8.89 | CHAIN | **point-to-point per interface** | 3.3 V CMOS | top-face pin 9 is CHAIN_IN, bottom-face pad 9 is CHAIN_OUT (§12.3) |
| 10 | +11.43 | V_AUX | power, into the Boll only | 5.0 V ± 5 %, ≤ 2.0 A | 5 V that charges the Boll from a Lite dock (§9) |

- In a pass-through module, pins 1–8 and 10 are wired straight through: top pin n to bottom pad n.
- Pin 9 MUST NOT be wired through, except in Class-0 modules (§12.2).
- On the Boll itself, pads 1 and 2 (V_STACK) are not connected: the Boll neither sources nor sinks V_STACK.
- A Lite dock populates only positions 3, 7, 8 and 10.

## 8. Electrical limits

| Item | Limit |
| :--- | :--- |
| Contact resistance (pin plus pad) | ≤ 30 mΩ new, ≤ 50 mΩ after 5,000 cycles |
| Current per pin | 3 A continuous on pins 1–4, 2 A on pin 10, 100 mA on signal pins |
| I2C bus | ≤ 400 pF in total, so each module ≤ 30 pF on SDA and SCL including traces. **Only the stack host fits pull-ups** (2.2 kΩ to 3.3 V, switchable) |
| Back-powering | every SDA, SCL, ATTN_N, SYNC and CHAIN input MUST be safe when the module is unpowered (open-drain, or pins with an I_off rating) |
| ESD | ≥ ±8 kV contact discharge on every pin, pad, USB-C contact and 3.5 mm contact (example protection: TI `TPD4E05U06`) |
| **Undocked safety** | a module's female contacts (bottom pads, jack and receptacle) MUST carry no voltage until it detects a seated module (a USB-C attach, or V_AUX on Lite). Its male contacts SHOULD stay off until attach. This prevents electrolysis on wet pads |
| Logic levels | 3.3 V CMOS. 5 V-tolerant inputs are RECOMMENDED |

## 9. Power

### 9.1 The three rails

| | USB-C VBUS | V_STACK (pins 1–2) | V_AUX (pin 10) |
| :--- | :--- | :--- | :--- |
| Purpose | power and charge **the Boll** | power **loads in the stack** (amps, LEDs, motors) | charge the Boll from a dock without USB (Lite) |
| Direction | upward only | shared bus, diode-ORed sources | toward the Boll only |
| Voltage and current | 5 V (a dock MAY also offer USB PD 9 V; the Boll sinks 5 V / 3 A) | 10.0–17.0 V; 4 A continuous and 6 A for 10 ms for the whole stack | 5.0 V ± 5 %, ≤ 2.0 A |
| Charging batteries | a module MAY charge its own battery from VBUS arriving at its bottom receptacle | MUST NOT be used to charge batteries in v1.0 | only the Boll sinks it |

### 9.2 Power rules

- **P1** A module MUST NOT source VBUS on its bottom receptacle. It MAY source VBUS on its top plug, and is then the Boll's power source.
- **P2** A V_STACK source MUST feed the rail through an ideal diode or a diode-OR (example controllers: TI `LM74700`, TI `LM66100`), limit its own current to ≤ 4 A and stay within 10.0–17.0 V.
- **P3** A V_STACK sink MUST declare `vstack_ma_avg` and `vstack_ma_peak` (§12.5) and MUST tolerate the rail vanishing at any time.
- **P4** V_STACK inrush MUST be ≤ 1 A for ≥ 1 ms, with ≤ 47 µF before the soft-start.
- **P5** The stack host sums the declared loads. If they exceed what is available, it MUST switch off the lowest-priority loads (command 0x11, POWER_OFF, §12.4).
- **P6** Module logic SHOULD be diode-ORed from VBUS pass-through and V_STACK into a ≤ 3.3 V regulator, so the module can enumerate on either rail.
- **P7** A passive module's VBUS pass-through MUST be ≤ 0.10 Ω round trip at 3 A. At most 2 passive modules may sit between a VBUS source and the Boll.
- **P8** A V_AUX source MUST hold 5.0 V ± 5 %, limit to ≤ 2.2 A and feed through an ideal diode. V_AUX MUST NOT power loads in the stack.

### 9.3 Power classes

| Class | Average draw | Source |
| :--- | :--- | :--- |
| L (logic) | ≤ 0.5 W | VBUS pass-through or V_STACK |
| S (standard) | ≤ 10 W | V_STACK |
| H (high) | ≤ 30 W average, ≤ 60 W peak | V_STACK; needs a declared V_STACK source in the stack |

### 9.4 What the Boll sources and sinks

- **The Boll never sources power on its foot.** Its foot USB-C only receives power, its V_STACK pads are not connected, and pad 10 is an input only.
- On its foot the Boll sinks USB-C VBUS at 5 V, up to 3 A, or V_AUX at 5 V, up to 2 A.
- The only place a Boll supplies power is its medallion USB-C port, at most 5 V / 1.5 A (7.5 W), for cable-attached accessories. Those are USB accessories, not Bollard devices.
- So every powered dock and speaker on the foot brings its own power, and charges the Boll as a side effect.

## 10. USB-C roles

- **U1** Where USB data exists, the Boll is always the USB host (DFP) of the stack. On its foot receptacle it is a power **sink** and becomes host through a USB PD **DR_Swap**. The Boll never sources VBUS on its foot.
- **U2** An active-USB module's top plug MUST be a Type-C Source with USB PD and MUST accept DR_Swap. Its bottom receptacle MUST be a Sink, presented downstream through a USB 2.0 hub port. (The Reference Bollard does this with an ST `STM32G0B1`, which has USB PD controllers for both ports, and a Microchip `USB2422` hub.)
- **U3** A passive module MUST wire VBUS, GND, CC1 to CC1, CC2 to CC2, D+ and D− straight through, MUST leave SBU and the SuperSpeed pairs unconnected, and MAY draw ≤ 100 mA from VBUS.
- **U4** No module may present Rp or Rd on a pass-through CC line.
- **U5** USB 2.0 High-Speed only. A passive D+/D− pair MUST be 90 Ω ± 15 % differential and ≤ 60 mm long.
- **U6** The foot's USB-C is a real USB-C port and MUST behave like one. Nothing in the Bollard interface uses a USB-C connector for non-USB signals.

Notes for dock designers:

- If a partner refuses the Boll's DR_Swap, dock USB data stays off. Power, A-BUS and I2C still work.
- The foot USB-C sits behind the Boll's internal USB hub, so a computer plugged into the foot (directly, or through a pass-through like the Boll Cap) charges the Boll but gets no data link. Computers configure a Boll through its medallion port.

## 11. Analog audio bus

| Parameter | Value |
| :--- | :--- |
| Signal | tip = left, ring = right, sleeve = audio ground (AGND) |
| Level | **1.0 Vrms at 0 dBFS** from the Boll; taps MUST accept 2.0 Vrms without clipping |
| Source impedance | ≤ 100 Ω |
| Tap input | ≥ 20 kΩ, ≤ 100 pF per module; at most 6 tapping modules |
| Grounding | AGND bonded to system ground at exactly one point per module, at the pin 3/4 entry |

- **A1 A wire through every module.** The top plug's tip, ring and sleeve MUST connect directly to the bottom jack's tip, ring and sleeve, so A-BUS passes through even an unpowered module. Modules *tap* the line (for example, a woofer puck sums left and right through 2 × 47 kΩ).
- **A2 One driver.** Only one module drives A-BUS: the Boll when present, or otherwise a stack host that declares `abus_source`. A processor module that breaks and re-drives the line (EQ, crossover) MUST bypass with a normally-closed switch when unpowered, and MUST declare `abus_break`.
- **A3 Digital audio is optional.** A module MAY expose USB Audio Class 2 behind an active-USB hub. bollardeck routes it (the `audio` message). No profile requires it.
- **A4 The Boll's foot jack is its own output.** The Boll's medallion 3.5 mm output and its foot A-BUS come from the same DAC. Their routing (foot only, medallion only, or both) is a Boll setting that a dock MAY request over bollardeck ([dock messages](bollardeck.md#7-dock-to-boll-messages)).

## 12. Enumeration and identity

### 12.1 How the Boll tells what docked

| Profile | First sign | Then | Identity source |
| :--- | :--- | :--- | :--- |
| Full | USB-C attach (CC) on the foot | DR_Swap to USB host; CHAIN high; I2C enumeration (§12.3) | binary header and JSON at 0x2F, then at 0x30 + n; if active-USB, a CDC interface named `bollardeck` and its `hello` |
| Lite | V_AUX ≥ 4.5 V for 50 ms on pad 10 (no CC) | 1-Wire reset and presence on pad 7 | 1-Wire header |
| USB-C | USB-C attach | DR_Swap; the USB device enumerates; the CDC interface named `bollardeck` | USB descriptors and `hello` |
| Passive | USB-C attach, no USB data partner after 1 s, no ACK at 0x2F | route audio to the foot jack and charge | none ("passive") |

Physical enumeration comes first and the bollardeck session second. A dock that answered the I2C or 1-Wire header and then opens bollardeck MUST send the same `vid` and `pid` in its `hello` ([handshake](bollardeck.md#5-handshake-and-capabilities)). This lets the Boll tie the API session to a physical position in the stack.

### 12.2 Required hardware per enumerable module

Every enumerable module carries a small microcontroller acting as an I2C target (example: WCH `CH32V003`; any ATtiny, RP2040 or STM32 works). It implements the register map of §12.4, reads CHAIN_IN, and drives CHAIN_OUT and ATTN_N.

**Class-0** modules (a spacer, a pure battery, a riser) have no microcontroller and MAY tie CHAIN_IN to CHAIN_OUT. They are then invisible to the host, and MUST be Power Class L or a V_STACK source only.

### 12.3 CHAIN algorithm

```text
 host:  pull-ups on; CHAIN_OUT(host) = LOW; wait 10 ms; n = 0
 loop:
   host:   raise CHAIN_OUT (first module)        -- or the previous module raises its CHAIN_OUT
   module: sees CHAIN_IN HIGH -> answers at default address 0x2F within 50 ms
   host:   read 32-byte header @0x2F; write NEW_ADDR = 0x30 + n; write CMD = COMMIT
   module: moves to 0x30+n, releases ATTN_N, raises its CHAIN_OUT within 10 ms
   host:   n += 1; no ACK at 0x2F for 100 ms -> done (n modules, in stack order)
 host:  read JSON descriptors; configure; enable loads within the power budget
```

- Only a module whose CHAIN_IN is high and which has no address yet answers at 0x2F, so exactly one module answers at a time.
- The bus holds at most 15 enumerable modules (addresses 0x30–0x3E).
- The I2C general-call address 0x00 carries broadcast frames (§13.2).
- **Hot-plug:** a newly attached module holds ATTN_N low, and the host re-enumerates from the top (under 200 ms for 5 modules).

### 12.4 Register map

| Register | R/W | Size | Content |
| :--- | :-: | :-: | :--- |
| 0x00–0x1F | R | 32 B | binary header (§12.5) |
| 0x20 | W | 1 | CMD: 0x01 COMMIT, 0x02 RESET, 0x10 POWER_ON, 0x11 POWER_OFF, 0x20 IDENTIFY (blink) |
| 0x21 | R | 1 | STATUS flags: assigned, powered, fault, overtemp, vstack_ok, vbus_ok |
| 0x22 | W | 1 | NEW_ADDR |
| 0x23–0x24 | W | 2 | DESC_PTR |
| 0x25 | R | 32 | DESC_DATA (auto-increment window into the JSON descriptor) |
| 0x40–0x7F | R/W | | class registers (light: brightness, palette; amp: gain, mute) |
| 0x80–0xFF | R/W | | vendor-specific |

The bit positions of the STATUS flags are not yet assigned (§22).

### 12.5 Binary header

The header is little-endian. Its fields, in order:

| Offset | Size | Field | Meaning |
| :-: | :-: | :--- | :--- |
| 0x00 | 4 | `magic` | ASCII `BLD1` for this major version |
| 0x04 | 1 | `spec_major` | 1 |
| 0x05 | 1 | `spec_minor` | 0 |
| 0x06 | 2 | `vid` | vendor ID (see below) |
| 0x08 | 2 | `pid` | product ID |
| 0x0A | 4 | `class_bits` | capability bits (§12.6) |
| 0x0E | 1 | `od_mm` | outer diameter, mm |
| 0x0F | 1 | `height_mm` | module height, mm |
| 0x10 | 2 | `mass_g` | mass, g |
| 0x12 | 1 | `cog_mm` | height of the centre of gravity, mm |
| 0x13 | 2 | `vstack_ma_avg` | average V_STACK draw, mA |
| 0x15 | 2 | `vstack_ma_peak` | peak V_STACK draw, mA |
| 0x17 | 2 | `vbus_ma` | VBUS draw, mA |
| 0x19 | 2 | `json_len` | length of the JSON descriptor, bytes |
| 0x1B | 2 | `fw_ver` | firmware version |
| 0x1D | 2 | `crc16` | header checksum |
| 0x1F | 1 | — | not assigned in this draft (§22) |

Vendor and product IDs: open-hardware makers SHOULD take a VID/PID from the pid.codes open registry (VID 0x1209), so the same IDs work for USB, for this header and for the bollardeck `hello`.

### 12.6 Class bits

| Bit | Name | Set when the module… |
| :-: | :--- | :--- |
| 0 | `abus_tap` | listens to A-BUS |
| 1 | `abus_break` | breaks and re-drives A-BUS (with a normally-closed bypass, A2) |
| 2 | `abus_source` | can drive A-BUS when no Boll is present |
| 3 | `vstack_source` | sources V_STACK |
| 4 | `vstack_sink` | draws from V_STACK |
| 5 | `vbus_source_top` | sources VBUS on its top plug |
| 6 | `usb_active` | is an active-USB module |
| 7 | `light` | has lights that follow SYNC and colour frames |
| 8 | `sensor` | is a sensor module |
| 9 | `host_capable` | can act as stack host with no Boll above it (§14) |
| 10 | `battery` | contains a battery |
| 11 | `bollardeck` | speaks bollardeck |
| 12–14 | — | were assigned to the retired cartridge class (§17); do not use |
| 15–31 | — | reserved |

### 12.7 JSON descriptor

Every enumerable Full-profile module also carries a JSON descriptor of at most 1,024 bytes, UTF-8, read through DESC_PTR and DESC_DATA.

```json
{
  "bollard": "1.0",
  "profile": "full",
  "vendor": "Example Labs", "product": "Lux Puck",
  "class": ["light"],
  "od_mm": 135, "height_mm": 50, "mass_g": 280, "cog_mm": 22,
  "power": { "class": "S", "vstack_ma_avg": 350, "vstack_ma_peak": 900, "vbus_ma": 0 },
  "abus": { "tap": false, "break": false, "source": false },
  "usb": { "active": false, "bollardeck": false },
  "light": { "pixels": 24, "layout": "ring", "sync": ["frame", "beat"], "personas": 16 },
  "controls": [
    { "reg": 64, "name": "brightness", "type": "u8", "min": 0, "max": 255 },
    { "reg": 65, "name": "mode", "type": "enum", "values": ["follow", "beat", "static"] }
  ],
  "url": "https://example.org/lux-puck"
}
```

- The Boll's UI shows enumerated modules from these fields alone.
- A module of an unknown class still gets its declared `controls`, which point at its class or vendor registers.
- Hosts MUST ignore unknown fields.
- The `bolltridge` object of earlier drafts is withdrawn with the cartridge class (§17). Bollard v2 reuses this descriptor for docks, with dock fields and a `slots` field added (§25).

### 12.8 Lite identity over 1-Wire

A Lite dock has no I2C. Its identity is the same 32-byte binary header, followed by up to 96 bytes of short descriptor, served by a 1-Wire slave on pin 7 (L5). The Boll's 1-Wire master enables its 4.7 kΩ pull-up on pad 7 only after it has seen a Lite attach (V_AUX present).

## 13. SYNC and lighting

### 13.1 SYNC line

SYNC is driven push-pull by the stack host through a series 100 Ω resistor. Each module input is ≥ 10 kΩ and ≤ 20 pF.

| Pulse width | Meaning |
| :--- | :--- |
| 0.25 ms | frame tick, 60 Hz (the Boll's light-ring frame) |
| 2.0 ms | beat (replaces the next frame tick) |
| 4.0 ms | downbeat, the start of a bar |

Modules MUST tolerate an absent SYNC and free-run.

### 13.2 Colour frames

The stack host MAY send I2C general-call (0x00) writes at up to 16 Hz: `0xC0, frame_no, 16 × (R, G, B)`, one colour per musician persona (the 16 channels of the Boll's lightshow). Light pucks latch each frame on the next SYNC tick. Docks that want the full 60 Hz, 24-pixel light ring use the bollardeck `led` message instead.

## 14. Docks without a Boll

| Profile | Behaviour (normative) |
| :--- | :--- |
| Full | A host-capable module (`host_capable`) that sees CHAIN_IN low and no USB-C attach on its top plug for 500 ms becomes stack host: it enables its pull-ups and drives SYNC and its CHAIN_OUT. When CHAIN_IN later rises (a Boll or another host docked above), it MUST within 20 ms disable its pull-ups, tri-state SYNC, assert ATTN_N and revert to an unassigned target. V_STACK keeps working, and VBUS simply has no load. **Known limitation:** modules above a non-Boll host are not enumerated. They get SYNC and power and run their defaults |
| Lite | V_AUX stays off (L4). The dock MAY light itself from its own supply. Its top contacts are dead |
| USB-C | with no USB-C partner, the dock is standalone. Its plug MUST NOT source VBUS until a USB-C attach |
| Passive | the amplifier MAY play its other inputs. The plug's VBUS stays off until attach |
| All | the undocked-safety rule (§8) holds: no voltage on exposed contacts without a seated partner |

The Reference Bollard (§19) is a complete Bluetooth speaker in this state, and it is the stack host for pucks below it.

## 15. What the Pop Boll provides

### 15.1 The foot

The Boll's south pole is a rigid die-cast foot, the fixed female half of the interface. It floats on an elastomer isolation collar inside the ball, so it can move up to about 4 mm on impact, and the squishy outer ball is moulded around it.

| # | What the Boll's foot provides |
| :-: | :--- |
| B1 | the female face of §5.3: well Ø 50 → Ø 42, floor 7.5 mm above Datum A (10.5 mm above the rim plane), key pocket at (0, +15), a 3.5 mm TRS jack at (−7, 0) (the Boll uses Same Sky `SJ1-43502PM`), a vertical USB-C receptacle at (+8, 0) (the Boll uses GCT `USB4225-03-1000-C`), and 4 magnets S pole down at R 29 |
| B2 | the 10 BCR-10 pads in the well floor, 1.8 × 3.0 mm, ≥ 0.76 µm hard gold over nickel, on a 1.0 mm FR-4 pad strip potted flush (±0.05) with the floor, row parallel to X at y = −11.0, pad n at x = −11.43 + 2.54 × (n − 1). Viewed from below, pad 1 is on the right |
| B3 | a Ø 1.5 mm drain from the well floor at (0, −16.0) to the gap behind the TPE rim at the rear (180°), so a wet Boll does not pond water on the pads |
| B4 | every pad, the jack and the receptacle are dead until a dock is detected (§12.1): pads high-impedance, no VBUS on the receptacle ever, pad 10 an input only |
| B5 | pad 10 is a V_AUX input through an ideal diode and a 5 V TVS into the Boll's dock power node, ≤ 2.0 A |
| B6 | stack-host hardware: switchable 2.2 kΩ I2C pull-ups, CHAIN_OUT drive on pad 9, SYNC push-pull through 100 Ω, an ATTN_N input, and a 1-Wire master on pad 7 (4.7 kΩ pull-up enabled only after a Lite attach) |
| B7 | the USB-C dock port is a sink only, takes the USB host role by DR_Swap, and runs USB 2.0 High-Speed |
| B8 | A-BUS drive at 1.0 Vrms at 0 dBFS, ≤ 100 Ω source impedance (§11) |
| B9 | the bollardeck service on the Boll: binds the CDC interface by its string, acts as BLE central, and shows the consent prompts ([bollardeck API](bollardeck.md)). This is planned software and is not built yet |
| B10 | pads 1 and 2 (V_STACK) are not connected |

The Boll's interior is sealed. The exposed foot contacts are designed to get wet and dry out, which is why every contact stays dead until attach.

### 15.2 The medallion

The medallion is the Boll's front panel (the +Y direction of the interface). It has three concentric buttons (inner: play/pause, middle: online/upload, outer: power), a USB-C port and a 3.5 mm TRS headphone and line output.

The three buttons have no LEDs. When the Boll wants a button lit (a button cue, bollardeck's `cues` message), the cue is rendered by its light ring, its matrix, the Glass Snipler's keys or a dock.

| Medallion USB-C use | Power role | Data role |
| :--- | :--- | :--- |
| wall charging | sink, 5 V / 3 A | none |
| a computer configuring the Boll | sink | USB device (a network link to the Boll's local web UI, plus storage and a console) |
| cable-attached accessories | **source, at most 5 V / 1.5 A** | USB host |
| Boll-to-Boll | either (the fuller battery sources) | either |

Medallion accessories are USB devices on a cable, not Bollard devices, but they may speak the same bollardeck messages.

### 15.3 Size, mass and balance

| Item | Value |
| :--- | :--- |
| Ball | Ø 135 mm, soft and self-righting, glowing from the inside |
| South-pole flat | Ø 70 mm, carrying the TPE squish rim (Ø 70 / Ø 58) |
| Mass | about 464 g (estimate) |
| Centre of gravity | about 43 mm above the TPE rim plane, so about 40 mm above Datum A (estimate) |

Use these figures when you compute the tip angle of a dock or stack with a Boll on top (§16).

## 16. Stacking

```text
        [ POP BOLL ]        female foot (the fixed half)
   ======|piston|======     Full male face: 3.5 mm + USB-C + BCR-10 on the floating plate
   |   SPEAKER DOCK    |    for example the Reference Bollard: stack host when no Boll is on top
   ======|  well  |=====    Full female face: pads in the well floor
   ======|piston|======
   |    LIGHT PUCK     |    taps nothing, passes everything through, lights on SYNC
   ======|  well  |=====
   |   BATTERY BASE    |    V_STACK source; sources VBUS up toward the Boll
   '-------------------'
```

- **Order:** Full-profile modules stack in any order. CHAIN tells the host the order.
- **Depth:** at most 5 modules plus the Boll above any base, and at most 15 enumerable modules on one I2C bus.
- **Stability:** the static tip angle of the whole stack with a Boll on top MUST be ≥ 12°. Every module MUST publish its mass and centre of gravity in its descriptor, so the host can check.
- **Mini modules:** the mass above a Mini (Ø 72) module MUST be ≤ 1.0 kg.
- **Pass-through:** pins 1–8 and 10, the 3.5 mm contacts and (for passive modules) USB-C are wired straight through. Pin 9 is point-to-point.
- **Passive USB depth:** at most 2 passive modules between a VBUS source and the Boll (P7).
- **A-BUS taps:** at most 6 tapping modules; only one driver (A2).
- **Stack host:** the Boll when present; otherwise the topmost host-capable module (§14). Only the stack host fits I2C pull-ups.
- **Power budget:** the host sums declared V_STACK loads and sources and switches off the lowest-priority loads first (P5).
- **Lite docks** are terminal: always at the bottom (L7).

## 17. Bolltridge device class

**Retired.** Earlier drafts of this chapter defined a Bolltridge as a cartridge that docked under the Boll's foot: a USB device of the Boll with its own small Linux computer, running one signed image, powering itself, chained up to four deep, with a reference design called the Dev Puck. None of that is current, and no product should be built to it.

**A Bolltridge is now the core cart**: the computer of the Pop Boll and of the Glass Snipler. It is the USB host of the dock it stands in, takes its power from that dock, runs Bollawax itself, and holds the corpora, a secure element and the only radio. At most two carts share a dock, joined through the dock and never cart to cart. §25 lists what is decided. The Bolltridge's own specification is an open document and is not on this site yet.

What went with the old class: the class bits 12–14 and the `bolltridge` descriptor object (§12), the power profiles `self`, `vstack`, `below` and `boll`, the compute tiers and the board table, the signed cartridge images, the conformance items T1–T10, and the Dev Puck. Whether add-on images and hacker mode return as software on the cart is open.

## 18. The Boll Cap

*The cap exists because the v1 Boll has a foot well. The first Boll built around the cart has none (see the note at the top), so the cap's future is not decided.*

Every Pop Boll ships with the **Boll Cap** fitted to its foot. It is the simplest Bollard device there is, and the zero-feature reference: a Passive-profile pass-through with no chip, no power of its own, no identity and no pins.

- **Protection:** it fills the well, so lint, crumbs and coins stay out.
- **Cables from the side:** a USB-C cable and a 3.5 mm cable plug into its rear wall, so the Boll stays upright instead of balancing on a plug.
- **A flat stand:** the Boll's Ø 70 mm flat sits on the cap's deck, and the cap's Ø 80 mm base sits on the table.
- **The upgrade path:** pull it off and put any Bollard device on the same foot.

### 18.1 Electrical

| Boll foot (female) | Cap top (male) | Cap side (rear wall at 180°) |
| :--- | :--- | :--- |
| 3.5 mm TRS jack at (−7, 0) | 3.5 mm TRS plug | 3.5 mm TRS jack: tip, ring and sleeve straight through |
| USB-C receptacle at (+8, 0) | vertical USB-C plug (USB 2.0) | 16-pin USB 2.0 USB-C receptacle: VBUS, GND, CC1 to CC1, CC2 to CC2, D+ and D− straight through; SBU and SuperSpeed not connected (U3) |
| 10 BCR-10 pads | none | — |

- No Rp, Rd or Ra anywhere in the cap (U4). Whatever is plugged into the side is the Boll's USB-C partner directly, so the Boll's role rules apply unchanged.
- D+/D−: a 90 Ω ± 15 % pair, ≤ 45 mm from plug to receptacle (the limit is 60 mm, U5).
- VBUS and GND: ≤ 0.10 Ω round trip at 3 A (P7), using both VBUS and both GND pins of each connector.
- ESD: ±8 kV contact on every exposed contact (example: a `TPD4E05U06` on CC1, CC2, D+ and D− at the side receptacle, and two 5 V bidirectional TVS diodes on tip and ring at the side jack).
- Orientation: the key fixes the cap's rotation, so its plug's CC contact always lands on the Boll's CC1. The side receptacle is reversible as usual, and the Boll detects the cable's orientation as on any port.
- **Naming:** a receptacle-to-plug pass-through like this is not a USB-C cable extension under the USB-C specification. It MUST NOT be sold or described as a "USB-C extension" and MUST NOT carry a USB-IF logo. Describe it as a Bollard Passive device.
- **No ID, by design.** An ID would need pins and would need the Boll to probe pad 7 before anything attached, which breaks the dead-until-attach rule (B4). With an empty side, the Boll reports nothing attached; with a cable in the side, it reports the partner. The cap's floor under the pad row is left flat and empty, 0.5 mm below the pads, so a later cap could add pins.

### 18.2 What works from the side ports

| Plugged into the side | Power | Data |
| :--- | :--- | :--- |
| a USB-C charger (5 V / 3 A or PD) | charges the Boll at 5 V, up to 3 A | — |
| a self-powered USB device that sources power and accepts DR_Swap (for example a USB-C-profile dock on a cable) | charges the Boll | works, as if it were docked |
| an accessory that needs the Boll to power it | does not power up: the foot never sources power. Use the medallion | — |
| a computer | charges the Boll from the computer's port | no data link (the computer stays host, §10). Configure the Boll on the medallion |
| another Pop Boll's medallion (C-to-C) | the other Boll's medallion may source 5 V / 1.5 A | decided by the medallion side |
| another Boll's cap (foot to foot) | nothing | nothing; both are sinks, which is safe |
| headphones, powered speakers, an amplifier or a recorder on the 3.5 mm side jack | — | the side jack carries A-BUS (1.0 Vrms at 0 dBFS); whether it is live follows the Boll's audio routing setting (A4) |

Charge-only USB cables charge the Boll with no data. USB 3.x, USB4 and 5 A e-marked cables work as USB 2.0 at 3 A. USB-A-to-C cables, which are always live, charge at the Default USB rate.

### 18.3 Mechanical

| Feature | Value |
| :--- | :--- |
| Base | Ø 80.0, flat, with a silicone anti-slip ring Ø 76 / Ø 66 × 0.8 |
| Deck | 12.0 mm above the table (room for the side connectors below it) |
| Land, Datum A | Ø 56 / Ø 50 annulus, 2.5 mm above the deck; the Boll's TPE rim is preloaded 0.5 mm on the deck |
| Pilot | a fixed boss per L1 (allowed for Passive through P1 and C1), with the key bump at (0, +15.0) |
| Plugs | the USB-C plug at (+8.0, 0.0) and the 3.5 mm plug at (−7.0, 0.0), with their shoulders at the well floor (+7.5), on one stiffener that floats ±0.4 mm and ±3° on a 0.8 mm silicone pad. The 3.5 mm plug engages 14.0 mm |
| Retention | 4 steel discs Ø 6 × 1 at R 29.0 on the ±X and ±Y axes, under a 0.5 mm skin of the deck; about 2–3 N against the Boll's magnets (estimate) |
| Side ports | rear wall at 180°: USB-C receptacle centred 5.5 mm above the table, 3.5 mm jack centred 8.0 mm above the table, 12 mm apart |
| Cable channel | a 12 × 7 mm groove across the underside from the rear ports to the front, plus 6 mm notches at the sides, so a right-angle cable can leave in any of three directions |
| Lanyard | a 3 × 2 mm slot in a lug under the deck |
| Mass | about 28 g (estimate) |
| Stability | static tip angle with a Boll on top about 35° (estimate), against the 12° minimum |
| Body | PC/ABS (rigid, so the boss tolerance holds), with a stick-on silicone anti-slip ring |

### 18.4 Conformance

The cap claims the Passive subset (§21.4): M2 face fit on the reference foot gauge; M4 insertion ≤ 40 N and extraction ≤ 22 N, or the manual says "hold the cap to lift the Boll off"; M5 50 lateral knock-offs with no plug damage; M6 5,000 cycles; E5 ESD; E6 A-BUS straight through; power rule P1 (it has no source); Passive P3 (the side partner is the source); U1 straight through.

## 19. Reference Bollard

The **Reference Bollard** is the worked example of the Full profile: an open reference design that anyone may build and sell, under any name and at any price (under the licence of §24), with no certification. It has not been built.

### 19.1 Overview

- A Ø 135 × 300 mm extruded-aluminium tube that is a complete Bluetooth speaker on its own, and the dock for the Boll.
- A male Full face on top and a female Full face on the bottom, so pucks stack above or below it.
- Two 3.5-inch full-range drivers firing front and back, and two passive radiators firing left and right, in force-cancelling pairs, in a 2.2 L chamber.
- A DSP amplifier at about 20 W per channel, running straight off a 4S 72 Wh battery pack.
- A docked Boll feeds it over A-BUS and is charged over USB-C at 5 V / 3 A.
- Halo LEDs under a diffuser ring at the top edge glow in time with the Boll over SYNC.

```text
        [ POP BOLL ]        female foot (the fixed half)
   ======|piston|======     Full male face: 3.5 mm + USB-C + BCR-10 on the floating plate
   | REFERENCE BOLLARD |    Ø 135 × 300 mm, Bluetooth speaker, 72 Wh, halo on SYNC
   ======|  well  |=====    Full female face: pads in the well floor
        [  PUCK  ]          for example a woofer or battery puck
```

### 19.2 Block diagram

```text
  AUDIO PATH
    top 3.5 mm plug (A-BUS in) ---+-----------------------------> bottom 3.5 mm jack
                                  |                               (wired straight through, A1)
                                  v
                            PCM1808 ADC ----I2S---> +------------+
                                                    | I2S 2:1    |---> TAS5825M amp and DSP
           Bluetooth module (QCC3034 class) --I2S-> | bus switch |           |
                                                    +------------+           v
                                                           2 x 3.5" drivers + 2 radiators
  USB AND CONTROL
    top USB-C plug (the Boll is host) <--> USB2422 hub <--> bottom USB-C receptacle
                                               |
                                               +--> STM32G0B1 (firmware update, status)
    STM32G0B1: USB PD on both USB-C ports, Bollard stack host or target, buttons, halo LEDs,
               I2C to the amplifier, the charger and the Bluetooth module
    top pins 1-8 and 10 <------ wired straight through ------> bottom pads 1-8 and 10
    top pin 9 (CHAIN_IN) --> STM32G0B1 --> bottom pad 9 (CHAIN_OUT)

  POWER PATH
    rear USB-C (charge only) --> TPS25750 PD sink --+
    bottom USB-C VBUS (from a puck below) ----------+--> TPS2121 input mux --> BQ25792 charger
                                                                                     |
                                    4S 72 Wh pack with BQ76905 protector <-----------+
                                       |
            +--------------------------+------------------------------+
            v                          v                              v
     amplifier rail (direct)   TPS62933 5.1 V buck --> TPS2595   LM74700 ideal diode
                               eFuse --> top VBUS to the Boll    --> V_STACK (pins 1-2)
```

The docked Boll's audio arrives analog on purpose: the A-BUS input costs one ADC, works through unpowered pucks, works with any phone or player on a 3.5 mm adapter, and does not depend on the Boll's software. USB data is still carried for control, for firmware updates from the Boll, and for USB devices further down the stack.

### 19.3 Behaviour

| State | Detection | Behaviour |
| :--- | :--- | :--- |
| Standalone | no USB-C attach on top, CHAIN_IN low for 500 ms | Bluetooth speaker. Becomes stack host for pucks below: pull-ups on, drives CHAIN downward, generates 60 Hz SYNC from the amplifier's level meter |
| Boll docked | USB-C attach and CHAIN_IN high | sources 5 V / 3 A to the Boll and accepts its DR_Swap; releases the stack-host role, turns off its pull-ups and re-enumerates as a target; plays A-BUS. Bluetooth stays connectable, and a Bluetooth play event can pause the Boll (configurable) |
| Docked, own battery below 10 % | charger telemetry | reduces the Boll's VBUS to 5 V / 1.5 A, and drops it at 5 %; the Boll's own battery carries on |
| Sitting on a battery puck | USB PD contract on the bottom receptacle | charges from VBUS below (≤ 15 W) and draws amplifier current from V_STACK through the diode-OR |

### 19.4 Parts list

Example parts, as designed. Any equivalent part is fine.

| Subsystem | Example parts |
| :--- | :--- |
| Drivers | 2 × Dayton Audio `ND90-4` 3.5-inch aluminium-cone full-range (80 Hz–15 kHz, 86 dB, 20 W RMS) |
| Passive radiators | 2 × 3.5-inch passive radiators (Dayton `DSA90-PR` class) |
| Amplifier | TI `TAS5825M` (2 × BTL with DSP) with output inductors |
| Bluetooth | Feasycom `FSC-BT1026D` (Qualcomm QCC3034, Bluetooth 5.1, aptX HD, aptX, AAC, SBC); a QCC3086-based module is the LE Audio upgrade path |
| Dock audio input | TI `PCM1808` 24-bit ADC; TI `SN74CBTLV3257` I2S source switch |
| Control and USB | ST `STM32G0B1CEU6` (two USB PD ports); Microchip `USB2422` hub; 3 × TI `TPD4E05U06` ESD arrays |
| Power path | TI `BQ25792` charger; TI `TPS25750` USB PD sink controller; TI `TPS2121` input mux; TI `TPS62933` buck; TI `TPS2595` eFuse; TI `TPS7A20` LDO; TI `LM74700` ideal-diode controller |
| Battery | 4 × Samsung `INR21700-50E` (4S1P, 14.4 V nominal, 72 Wh) with a TI `BQ76905` protector and balancer |
| Top face (male) | JAE `DX07P024MJ2R1500` USB-C plug; Same Sky `SP-3533-02` 3.5 mm plug on a daughterboard (prototype; a custom vertical plug in production); Mill-Max `823-22-010-10-040101` BCR-10 strip; 4 × N52 Ø 6 × 3 magnets; piston, spring and gimbal |
| Bottom face (female) | GCT `USB4225-03-1000-C` receptacle; Same Sky `SJ1-43502PM` jack; hard-gold BCR-10 pad strip; 4 × N52 magnets; TPE foot rim |
| User interface | 4 × C&K `KSC721J` buttons under a membrane; `SK6805-EC15` LEDs (12 in the halo, 5 in the status bar); a rear sealed USB-C receptacle |
| Enclosure | 6063-T5 aluminium tube Ø 135 × 2.0 wall × 300; die-cast top deck with a 20 mm piston guide; base casting with a 350 g steel ballast ring; glass-filled PC/ABS internal chassis |

The rear USB-C port is charge-only (USB PD sink at 5, 9, 15 or 20 V, up to 45 W).

### 19.5 Stability

Estimates, with the TPE foot rim as the contact ring (radius 64 mm):

| Configuration | Mass | Centre of gravity | Static tip angle |
| :--- | ---: | ---: | ---: |
| Reference Bollard alone | 2.79 kg | 127.8 mm | 26.6° |
| plus a Boll | 3.25 kg | 158.5 mm | 22.0° |
| plus 3 full-size pucks (50 mm, 300 g each) | 4.15 kg | 222 mm | 16.1° |
| plus 5 full-size pucks | 4.75 kg | 267 mm | 13.5° |

A Reference Bollard supports at most 5 full-size pucks above it. The 350 g ballast ring in its base is the cheapest stability lever (about +0.8° per 100 g). Its weight (about 27 N) is above the estimated Boll extraction force (about 3–22 N), so lifting a Boll off leaves the speaker on the table.

## 20. Hobbyist builds

### 20.1 Lux Puck (Full, 50 mm)

The smallest thing that is a real Full-profile module is a 24-LED light puck. It passes everything through and lights on SYNC.

1. **Top face:** a vertical USB-C plug (example: JAE `DX07P024MJ2R1500`), a 3.5 mm plug (example: Same Sky `SP-3533-02` on a 90° daughterboard; there is no off-the-shelf vertical PCB-mount 3.5 mm plug), and one 1×10 2.54 mm spring-pin strip (example: Mill-Max `823-22-010-10-040101`, or a generic strip). All three go on a small plate PCB that floats on 3 printed flexures. Add 4 magnets N up and a printed piston and spring (PETG or POM is fine for hobby use).
1. **Bottom face:** a vertical USB-C receptacle (example: GCT `USB4225-03-1000-C`) and a 3.5 mm jack (example: Same Sky `SJ1-43502PM`), panel-mounted in the well. The pads are a pad-strip PCB (ENIG for hobby use, hard gold for products). Add 4 magnets S down.
1. **Pass-through:** USB-C VBUS, GND, CC1, CC2, D+ and D− straight through (a short 90 Ω pair); 3.5 mm tip, ring and sleeve straight through; pins 1–8 and 10 straight through (pins 1–4 on traces at least 2 mm wide in 2 oz copper).
1. **Logic power:** V_STACK into a buck converter (example: TI `TPS62933`) to 5 V for the LEDs, then an LDO to 3.3 V. A Schottky diode from VBUS feeds the 5 V node, so the puck enumerates on VBUS alone (with the LEDs limited to 100 mA).
1. **Microcontroller:** a WCH `CH32V003F4U6` as I2C target (no pull-ups), with CHAIN_IN on a GPIO with a 100 kΩ pull-down, CHAIN_OUT push-pull starting low, ATTN_N open-drain, and SYNC on a timer capture input.
1. **Load:** 24 × `SK6805-EC15` LEDs on a ring behind a diffuser, switched by a P-FET that the microcontroller turns on after the POWER_ON command.
1. **Protection:** a `TPD4E05U06` on pins 5–9, an `SMBJ18A` TVS on V_STACK, and a 1 A polyfuse.

Its JSON descriptor is the example in §12.7.

### 20.2 The perfboard route

For a first light puck (not a product): the BCR-10 pitch is 0.1 inch, so the spring strip solders straight into 2.54 mm perfboard. The pad strip can be any 2.54 mm-pitch board with pads at least 1.6 mm wide. Generic strips are not rated for 5,000 cycles.

Indicative single-unit hobby costs, November 2026: a generic 2.54 mm spring-pin strip about $1–3, a Mill-Max 10-position strip about $7. A whole Lux Puck with generic strips and printed parts comes to roughly $22–28; with the Mill-Max strip and ordered PCBs, roughly $28–36. These are indicative only.

### 20.3 The Lite minimum

A charging-and-light stand needs a printed boss, 4 spring pins (positions 3, 7, 8 and 10 of a 1×10 strip with 6 pins pulled), a 5 V USB-C receptacle on its back for its own power, an eFuse, a Hall sensor, a `CH32V003` acting as 1-Wire slave and SYNC reader, and a ring of LEDs. That is roughly $10–15 as a hobby build (indicative).

## 21. Conformance checklist

There is no certification. A maker who says **"Bollard v1.0, Full profile"** (or Lite, USB-C or Passive) states that every applicable item below passes. Test fixtures will be published with v1.0 final: a reference Boll-foot gauge (female) and a reference dock-top gauge (male, Full).

### 21.1 Mechanical

| Item | Requirement |
| :--- | :--- |
| M1 | outer diameter 135.0 ± 0.3 (Full) or 72.0 ± 0.3 (Mini); height a multiple of 25 mm, at least 50 mm |
| M2 | faces match §5 (gauge fit, key, magnet polarity N up and S down, BCR-10 positions) |
| M3 | pin free height +8.2 ± 0.15 above Datum A; tips at least 0.5 mm below the extended piston face |
| M4 | insertion ≤ 40 N; extraction ≤ 22 N, or the manual warns (§5.5) |
| M5 | lateral loads go through the piston and the well; 50 lateral knock-offs with no plug, plate or pin damage |
| M6 | 5,000 dock cycles, with pin plus pad < 50 mΩ afterwards |
| M7 | declared mass and centre of gravity within ±10 % of measured |

### 21.2 Electrical and power

| Item | Requirement |
| :--- | :--- |
| E1 | pins 1–8 and 10 straight through; pin 9 per §12 (or a Class-0 short) |
| E2 | no I2C pull-ups unless acting as stack host; ≤ 30 pF per line |
| E3 | no back-powering through any signal pin when unpowered |
| E4 | female contacts dead until attach (§8) |
| E5 | ESD ±8 kV contact on all pins, pads, USB-C contacts and 3.5 mm contacts |
| E6 | A-BUS straight through on tip, ring and sleeve; taps ≥ 20 kΩ; breaks use a normally-closed bypass |
| P1 (power) | never sources VBUS on the bottom receptacle |
| P2 (power) | V_STACK sources diode-ORed, ≤ 4 A, 10.0–17.0 V; inrush ≤ 1 A; survives the loss of V_STACK |
| P3 (power) | declared power class within ±10 % of measured; lithium-ion modules have independent protection (and UN 38.3 if shipped) |

### 21.3 USB and protocol

| Item | Requirement |
| :--- | :--- |
| U1 | passive: straight through, no Rp or Rd, ≤ 100 mA, 90 Ω pair ≤ 60 mm |
| U2 | active: top is a USB PD Source that accepts DR_Swap; bottom is a Sink behind a hub port; the High-Speed eye at the Boll passes through 2 modules |
| R1 | answers at 0x2F only with CHAIN_IN high and while unassigned; raises CHAIN_OUT ≤ 10 ms after COMMIT |
| R2 | header magic `BLD1`, CRC and JSON (valid, ≤ 1,024 bytes) correct |
| R3 | holds ATTN_N low until assigned; re-enumerates after hot-plug |
| R4 | survives an absent SYNC; latches colour frames on SYNC if it declares `light` |
| R5 | host-capable modules hand over within 20 ms of CHAIN_IN rising |
| R6 | if it speaks bollardeck, the `hello` vendor and product IDs match the header (§12.1) |

### 21.4 Profile subsets

| Profile | Items that apply |
| :--- | :--- |
| Lite | M2 (with the L1 boss), M4, M6, M7 · E3, E4, E5 · L2 only pins 3, 7, 8 and 10 present · L4 V_AUX 5.0 V ± 5 %, current-limited, fed through an ideal diode, off until a Boll is seated · L5 1-Wire header valid · R4 |
| USB-C | M2, M4–M7 (with the C1 pilot) · E5 · P1 (power) · C2 Source that accepts DR_Swap · C3 a `bollardeck` CDC interface that answers `hello` · C4 nothing touches the pads |
| Passive | M2, M4–M7 (with the P1 pilot) · E5, E6 (A-BUS input ≥ 20 kΩ) · P1 (power) · P3 (Passive): Source only |
| Full | everything in §21.1–21.3 that applies to the module |

### 21.5 Bolltridge items

Withdrawn with the cartridge class (§17). There is no conformance checklist for carts or for Bollport docks yet; docks get theirs in Bollard v2.

### 21.6 Listing (planned)

A future storefront will list docks and pucks. Listing is planned to be free, with no testing by the storefront (each listing will say so). To be listed, a maker gives:

1. the specification version (for example "Bollard v1.0") and the profile;
1. whether the product speaks bollardeck (USB, BLE or both, and which API major);
1. a photo of the product with a Pop Boll docked;
1. a safety self-declaration: which regulations the maker states the product meets (for example FCC and CE EMC, IEC 62368-1 for mains products, UN 38.3 and IEC 62133-2 for lithium-ion cells), with a name, a contact and a product URL.

A listing can be removed after credible safety complaints.

## 22. Open items

Not yet validated on hardware. Nothing in this specification has been built, so every item below is open until an engineering sample exists.

- **BCR-10 has no physical sample.** The 0.7 mm compression, the ±0.2 mm registration through the plugs, and whether the force of 10 pins (up to 10 N) can tilt the plate against the piston all need a prototype build.
- **Clearance under the well floor** between the pad row (y = −11.0) and the bodies of the 3.5 mm jack and the USB-C receptacle has been checked against nominal outlines only, not against the vendors' 3D models.
- **The example spring-pin strip** has not been checked against the 1.2 mm stroke and 0.4–1.0 N requirement; a different series may be the right part.
- **The well's lead-in cone** is defined by its two diameters and heights (Ø 50.0 at −3.0, Ø 42.0 at +3.0). An earlier draft also quoted a 21.8° half-angle, which does not match those figures; the angle is under review.
- **The binary header** lists fields that fill 31 of its 32 bytes; the position of the remaining byte, the CRC-16 variant and the bytes it covers are not yet specified. `height_mm` and `cog_mm` are single bytes, so modules taller than 255 mm (such as the 300 mm Reference Bollard) cannot yet declare their height. The STATUS register's bit positions are not assigned.
- **Unknown class bits:** the rule that hosts ignore unknown JSON fields does not yet say the same for unknown class bits.
- **Module height H** does not yet name its reference planes (rim plane or Datum A, top and bottom).
- **Enumeration above a non-Boll host** is not possible in v1.0 (§14).
- **The Boll Cap's detailed drawings** are being redrawn to the corrected datum of §4. The cap is the easiest part to adjust and will be tooled last. Its extraction force (two friction plugs, weak steel-disc retention) may exceed the Boll's weight, so the cap could lift with the Boll; that will be measured.
- **The Reference Bollard** acoustic figures are estimates from assumed driver parameters, and the amplifier's thermal path to the tube has not been checked.
- **The premise.** Everything the note at the top lists: Bollard v2 is not written, the Boll built around the cart is not drawn as a specification, and the fate of the foot interface, the pucks and the Boll Cap is not decided.
- **To be published with v1.0 final:** the reference gauges, the reference pad-strip layout, and the Reference Bollard design files.

## 23. Versioning and change log

- The binary header carries `spec_major` and `spec_minor`, and the JSON descriptor carries `"bollard": "1.0"`.
- **Minor versions** only add registers, classes, profiles or JSON fields. Hosts MUST ignore unknown fields.
- **Major versions** are for any mechanical change or any change to an assigned pin. Each major version gets a new header magic.
- The bollardeck API is versioned independently (`bollardeck/1`). A Bollard v1.0 dock speaks `bollardeck/1`.
- **Candidates for v1.1:** upward enumeration above a non-Boll host, the Thin class with a coaxial pass-through, V_STACK battery-charging rules, the published gauges and the reference pad-strip layout.

| Version | Date | Changes |
| :--- | :--- | :--- |
| 1.0-draft, revised | 2026-11-10 | The cartridge class of §17, its class bits, its descriptor object and its conformance items are withdrawn; the note at the top and §25 record the change to the cart; the licence is no longer "proposed". No v1 dimension, pin or register changed |
| 1.0-draft | 2026-11-07 | First public draft. A straight BCR-10 row on the floating plate replaces the earlier contact arc; the four connector options become the Full, Lite, USB-C and Passive profiles; header magic `BLD1`; well floor corrected to 7.5 mm above Datum A, with the piston travel lengthened to 15 mm; Bolltridge class bits 12–14 and the `bolltridge` descriptor object; the Boll Cap |
| 0.2 | 2026-11-07 | Unpublished draft: four connector options, pin 10 assigned to V_AUX, ten pogo pins on an arc on the foot face, header magic `PSK0` |
| 0.1 | 2026-11-06 | Unpublished draft: the first pogo-arc interface (9 pins and a reserved pin), header magic `PSK0` |

Nothing was built to 0.1 or 0.2, so no adapters are planned.

## 24. Licence

- **Hardware designs** (the Reference Bollard and Lux Puck designs, the reference pad strip, the gauges and the mechanical drawings): **CERN-OHL-P v2**, a permissive licence, so anyone can build and sell closed commercial docks.
- **Firmware and code** (the puck microcontroller reference, the Bollard SDK, the example routines): **Apache-2.0**, which includes an explicit patent grant.
- **This specification text:** **CC BY 4.0**.

These licences cover the documents and designs, not the project's names and logos. You may describe a product as "built to the Bollard Physical Specification v1.0, Full profile" (or whichever profile applies).

## 25. Bollard v2: what is decided

Bollard v2 is not written. These points are decided and will be in it. Everything else about it, including every dimension not given here, is open.

**The Bollport**

- A cart meets its dock through one USB-C connection: a receptacle on the cart, a floating plug in the dock, and magnets that seat the cart. The dock's slot carries the load, not the connector.
- It is real USB-C. Only USB, USB Power Delivery and DisplayPort Alt Mode run over it.
- **The cart is the USB host.** The dock is the power source and the cart the sink.
- **Power.** Every dock offers at least 9 V at 3 A and should offer 15 V at 3 A, so that later carts fit today's docks.
- **Screens.** A dock with a display receives DisplayPort from the cart over the same connector. A dock without one does not advertise it.
- **Size.** A cart is 24 mm thick and a dock's slot is 24.8 mm, on every cart and every dock.

**Docks**

- A dock gives the cart what it needs to be a product: speakers, lights, a screen, power, controls. Pop Boll's own docks have no computer and no radio. That is our rule for our docks, not a rule of Bollard: a third-party dock may have a radio.
- A dock presents a USB hub to the cart, with the dock's own microcontroller on it.
- **The dock descriptor** is the JSON descriptor of §12 and the bollardeck `hello`, with fields for the dock added and a `slots` field that says which cart positions the dock has and which are occupied. The field list and the list of dock classes are not fixed.
- The cart runs one Bollawax image and chooses what to be from the dock's class.

**Carts**

- A cart carries a secure element that holds its edition and its licences.
- The device serial belongs to the cart. A dock reports a model and a serial of its own in its descriptor.
- **Two carts at most.** The cart in a dock's first slot is the brain and the USB host. A second cart is a guest: a USB device of the first, connected through the dock. A guest lends its corpora and its computing while it is seated, and drives no screen and no sound of its own.
- This round's carts are built on the Arduino Uno Q. The Raspberry Pi family stays in the open Bolltridge specification for other makers and later rounds.

**In 0.2.5.** Bollawax 0.2.5 carries the cart's software for pocket mode (a cart running with no dock, on a battery of its own) and a revised dock descriptor. No cart exists yet, and none of it is verified on hardware. This section still describes the cart as Bollawax 0.2.4 specifies it.

**Not decided, or not written:** the dock classes and the descriptor's fields; the Bollport's tolerances, magnets and cycle life; whether any of the v1 foot interface survives; the Pop Boll's dimensions as a dock; and a conformance checklist.
