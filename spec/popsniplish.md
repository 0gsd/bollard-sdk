# Popsniplish: what a band says to itself

Version 0.1.0 · Status: speculative draft · Updated 2026-11-10

> **Speculative draft.** No Pop Boll hardware has shipped, and nothing on this page has been built or validated on hardware. Names, kinds, fields and moves will change without notice, and nothing here is an offer, a commitment or a promise of compatibility. We would love to hear about partnership, OEM and dev-kit ideas: use the contact form on this site.

This page is Popsniplish as its one text says it (edition 0.1.0, revised 2026-11-10), told the way a MiniCOSM is documented on cosmoes.org: the text itself; the reference, generated from its manifest and its programs; and its atem, an outline and a glossary. The [overview page](index.md) introduces the rest of the Pop Boll ecosystem.

*Edition 0.1.0 · revised 2026-11-10 · home: Pop Boll's private repository, until the owner calls it stable and it
gets a cosmoes.org host of its own*

*This edition describes the `popsniplish/1` MiniCOSM and the moves it declares for `thym 1`.*

Popsniplish is the language a Pop Boll's band speaks: what its sixteen virtual musicians, its seven judges and DJ PB
say to one another about musical intentions and results, and what they keep on their cheat sheets. It is a MiniCOSM
of MacroCOSM OES (https://macro.cosmoes.org/): every message and every entry is a *constructed fabula*, a standalone
`fabula/1` file of flavour fabulan built item by item by rules, and *told* as a short, plain English with each
claim's stance in words and the footer line that says it was compiled by rules, without a model. Its moves are
declared for Thym (https://thym.cosmoes.org/) and every one transcodes, so every Popsniplish program plans and runs
agent-free: there is no model on a Boll, ever, and a song generated twice says the same things twice, byte for byte.
The owner named it on 2026-11-09.

**Status.** This text is normative for Pop Boll's own code. Its reference implementation is the `popsniplish`
package there; the `talkback` package (the channel inside the song factory, the Studio Cheat Sheet and the personal
public cheat sheets) has a specification of its own, not published, and uses the language. Where this text and the
package disagree, one of them is in error, and the Changes section records which was corrected. MacroCOSM's words
(volume, catalog, module, kind, item, envelope, reference, check, lens, atem, short, fabula, dialectic) and Thym's
(move, contract, morph, holomorph, isomorph, reading) keep their meaning here.

## Contents

1. [Provenance and the name](#1-provenance-and-the-name)
2. [The model on one page](#2-the-model-on-one-page)
3. [The design rules](#3-the-design-rules)
4. [The volumes](#4-the-volumes)
5. [The modules and their kinds](#5-the-modules-and-their-kinds)
6. [Entries: constructed fabulas and their shorts](#6-entries-constructed-fabulas-and-their-shorts)
7. [The dialectic, applied: the vote](#7-the-dialectic-applied-the-vote)
8. [Morphs: holomorphs, isomorphs, voice and readings](#8-morphs-holomorphs-isomorphs-voice-and-readings)
9. [The knob lexicon](#9-the-knob-lexicon)
10. [The moves](#10-the-moves)
11. [Checks](#11-checks)
12. [FEED on a Boll](#12-feed-on-a-boll)
13. [Conformance](#13-conformance)
14. [Changes](#14-changes)

The page adds, generated from the manifest and the programs: [the reference, generated](#the-reference-generated); [the atem, an outline and a glossary](#the-atem); [a colophon](#colophon).

## How to read this

**Must and may.** *Must* is a rule the package keeps and a check enforces. *May* is a permission. *Should* is advice.

**The family of words.** A **holder** is who owns a personal sheet and speaks on the talkback: a musician (`m01` to
`m16`, the riff book's ids), a judge (`j1` to `j7`) or DJ PB (`djpb`). A **call** is a musician's message before a
take, a **response** a judge's after a lock vote, a **notice** the house's message of an event. The **Studio Cheat
Sheet** (SCS) is the band's sheet, a page per band day, unanimous; a **personal public cheat sheet** (PPCS) is one
holder's own. An **entry** is one item of a sheet: a constructed fabula file and its short. A **knob** is a factory
input an agreement may name, from a closed lexicon. **Holomorph**, **isomorph** and **reading** are Thym's.

---

## 1. Provenance and the name

Popsniplish was drawn on 2026-11-09 for the Bollawax Talkback: the owner asked for an original system, living inside
the Boll, that lets musicians and judges communicate in a structured way about musical intentions and results, with
the underlying language based on MacroCOSM and Thym and the entries written as constructed fabulas told as readable
English, so that the holomorph and isomorph ideas could be tested on a band that writes every day. *Popsniplish* is
Pop, snip and English: the language of the Pop Boll, as the Snipler is its instrument. It is stewarded by the owner,
Graham Smith: the language and its name are his, and this specification's text is published under CC BY 4.0
(the colophon).

## 2. The model on one page

```text
   the factory                     Popsniplish                            the surfaces
   plan · roster · directives      a constructed fabula (fabula/1,        a short (plain English, by rules)
   verdicts · study · mutation     fabulan, standalone) per message       the film's caption (its atem line)
        │                          or entry                                   │
        └── intend / judge / notice ──▶ fabula ── tell ──▶ short ──────────────┘
                                          │                                a reading, through a morph
                                          └── voice with <isomorph> ──▶ (labelled, never the source)

   a day's talkback ── nominate ──▶ proposals ── question ⇢ every musician votes ⇢ record · adopt ──▶ the studio sheet
                                               (two runs, by rules; unanimity; must → should → may → dropped)

   a holder's own shorts ── measure ──▶ holomorph (private, with evidence) ── release ──▶ isomorph (public, scales only)
```

- A **volume** is a studio sheet, a personal sheet or one song's talkback (section 4). Its items index the entries
  and name the knobs, holders, votes and forms (section 5).
- An **entry** is a file beside the catalog: `<slug>.fabulan.cosm`, and its shorts (section 6).
- The **vote** is the core's dialectic with a bank of one question, answered by rules (section 7).
- A **morph** is Thym's, measured by rules on the seven statistics scales, with the judgement scales pinned by the
  holder's persona; `voice` renders one without a model (section 8).
- Every move **transcodes** (section 10). The checks are the generic ones and seven of Popsniplish's own (section 11).

## 3. The design rules

1. **It reads.** Every item's `summary` is a complete English sentence that names everyone, so the rules short,
   "the ordered outline itself, said in the items' own sentences", reads as prose and not as a database.
2. **Nothing is invented.** Every call, response and notice is built from structures the factory already makes;
   every word a voice adds is a FEED headword from a fixed list; every name and number in a reading is in its fabula.
3. **No model, ever.** Every move is `asks: false`. What a model would judge (humour, allusion, figure) is pinned by
   the holder or left `{pending: "not measured"}`, never guessed.
4. **The clock is the song's.** Timestamps come from the song record and the band day, never the wall clock, so a
   regenerated song reproduces its talkback byte for byte. Votes are seeded by the soul, the day, the entry's digest
   and the holder.
5. **Agreements bite, bounded.** An adopted agreement names one knob from a closed lexicon with one force; the
   summit applies at most a few per song, as routines are bounded. A proposal that fails weakens and never
   strengthens (the stance ladder's rule, applied to force).
6. **Private stays private.** A holomorph, with its evidence, never leaves the device; an isomorph leaves with its
   scales, direction, pins and confidence and nothing else.
7. **Each smaller scale keeps the order of the larger.** Popsniplish adds kinds, fields, closed lists, checks and
   moves; it changes nothing MacroCOSM or Thym means.

## 4. The volumes

| `kind` | file | holds |
|---|---|---|
| `studio` | `studio.cosm` at the root of a folder; `days/<day>/<nn>-<slug>.fabulan.cosm` and the shorts beside it; module files `S/ K/ H/ V/ F/ D/` | the band's Studio Cheat Sheet: the adopted entries by day, the knobs, the holders, the votes, the dialectic |
| `personal` | `personal.cosm`; `entries/<day>-<n>-<slug>.fabulan.cosm`; `<holder>.morph.cosm` beside the folder, never inside; `public/` the projection | one holder's personal public cheat sheet, their holomorph, their releases |
| `talkback` | `<song>.talkback.cosm`, one file, or a folder `<song>/<part>/take-<n>/` of fabulas and shorts | one song's calls, responses and notices |

**The catalog's keys**, in order: `oes` (`popsniplish/1`), `macrocosm`, `id` (`popsniplish/<slug>`), `name`,
`kind`, `band` (the soul fingerprint, never a serial), `device`, `holder` and `handle` (a personal volume),
`calendar` (`{edition, day}`, a studio volume; the band day, from the longitudinal index), `editions` (a studio
volume: `{day, digest, entries}` per day with adoptions, appended; the digest is what a song's meta names), `releases`
and `morphs` (a personal volume, as Ascribe records them), `song` and `day` (a talkback volume), `nodes`.

## 5. The modules and their kinds

| Letter | Module | Kind | What it holds |
|---|---|---|---|
| S | Sheet | `entry` | one entry's row: `holder`, `day`, `kind`, `fabula` and `short` (file names), `atem` (the line, copied), `visibility`; an agreement's `force` and `knob`; `adopted`, `proposed` (the question), `weakened-from`; `forms` |
| K | Knobs | `knob` | one factory input: `key`, `family` (`directive`, `writer`, `plan`, `study`, `roster`), `reads`, `range`, `says` |
| H | Holders | `holder` | `role` (`musician`, `judge`, `dj`, `panel` for the seven as one voice, `house` for the factory), `channel` or `judge`, `pronouns`, `pins` (the judgement scales the holder pins), `active` |
| V | Votes | `vote` | `holder`, `entry`, `question`, `value` (`yes`, `no`, `unknown`), `says` (the holder's words, voiced), `seed`, `day`; its provenance is `dialectic` |
| F | Forms | `form` | the music things entries are about, as Ascribe's forms: `feed: {word, pos, origin}` or `{pending: "not in FEED"}` |
| D | Dialectic | `question`, `session` | inherited from the core: the proposals' questions and the sitting each vote was given in |

**The envelope** is MacroCOSM's: `id type name summary provenance` required; `status`, `visibility`, `pending`,
`links` (the fabula's nine relations, closed) and Thym's `made`. Every item a rules pass reads exactly carries
`{mode: derived, confidence: 1}`; what a vote wrote carries `{mode: dialectic, sources: [D:session/<id>]}`.

**Closed lists.** `kind`: on a studio sheet `tip`, `trick`, `agreement`; on a personal sheet Ascribe's ten,
`affinity belief concern experience interest opinion quale skill understanding yearning`, used as the ten kinds of
thing a holder can say; in a talkback `call`, `response`, `notice`. `force`: `must should may`. `role`, `value`,
`family` and `feed.origin` as above.

## 6. Entries: constructed fabulas and their shorts

An entry's fabula is a **standalone fabulan**: `oes: fabula/1`, `flavour: fabulan`, no `source:`, named
`<slug>.fabulan.cosm`, its `derived` saying `by: rules`, `mode: rules`, `completeness: full`, `chunks: 0`, and the
program and run that built it. Its items are the fabula's kinds, in their modules: what the holder means to do is
`N:aim` (with `measure`, how one would know) and `N:decision` (`chose`, `over`, `because`); what they studied is
`I:influence` naming the track as `E:work`; what they hold or measured is `P:claim` with its stance (`opinion` for a
judgement, `observed` for a measurement) and salience; what happened is `T:event`; the music words are `L:term`,
grounded in FEED; the ideas are `K:concept`; the people and parts are `E:person` and `E:thing`. A catchphrase the
holder's persona carries is a `C:device` with `figure: catchphrase`, and an allusion to a studied work an
`I:allusion`: that is where the judgement scales come from, and nothing a voice renders is outside the fabula.
`N:requirement` belongs to the fabulac and is never written in a fabulan: an agreement's force and knob live on its
`S:entry` row (check `one-requirement`).

Every item's `summary` is one complete sentence naming everyone. The **atem** is constructed with the items: the
line (15 to 25 words), the focus, the push (the holder's aim) and the pull (what it leans on). Ids follow the Canon
slug rule, with the first six hex digits of the name's sha256 on a collision.

A **short** is compiled by rules (MacroCOSM OES 18.4.4): by weight for a standalone fabula. Popsniplish tells, in
order, the claims (by salience, grouped by the concept they lean on, each with its stance phrase: the reference
implementation's), *what it sets out to do* (aims, audiences, decisions, exclusions), *what it came from*
(influences, allusions, occasions), *what happens* (events in before/after order), *how it is built* (voices,
devices, parts), *who made it*, *how it can be read*, and the terms. The footer is the spec's:
`*a short of <slug>.fabulan.cosm, a standalone fabula, told by weight, compiled on <day> by rules, without a model*`.
The file is `<slug>.short-<YYYY-MM-DD-HHMM>.md` beside the fabula, `-2` on a collision; the fabula records it in
`shorts:` without a byte of the rest changing.

## 7. The dialectic, applied: the vote

The bank holds one question, put to every active musician holder for every proposal, in no one's voice: "Does
{name} agree to this for the studio?" (`kind: yes-no`, `to: holder`, `why: intent`). The two runs are the core's:
`nominate` lands the proposals and their questions with the studio volume; each holder's `vote` answers by rules,
seeded, with a `says` line in their own voice; `record` appends the answers; `adopt` settles. An entry is adopted
only when every active musician said yes (check `unanimous`); judges and DJ PB propose and comment but hold no vote.
A proposal that fails weakens one step, `must` to `should` to `may`, and is put again the next day
(`weakened-from`, check `weakens-only`); a `may` that fails is dropped, and the proposal stays on its proposer's
personal sheet, marked not adopted. "I don't know" is `unknown` and blocks adoption as a no does.

## 8. Morphs: holomorphs, isomorphs, voice and readings

Thym's ten scales are measured as its section 13.3 says, with the reference implementation's thresholds and word
lists, FEED's bands and the nine-letter rule; under 300 words or three paragraphs a statistics scale reports a
confidence of at most 50. The **null** telling of a fabula is its rules short; measured with the fabula's own words
exempt, its register is 1. The three judgement scales are **pinned** by the holder's persona (`H:holder#pins`) or left
`{pending: "not measured"}`.

A holder's **holomorph** is the scale-wise median of the morphs of their own shorts and `says` lines, its confidence
rising with the count (the median confidence plus five per further text, at most 95), kept as `<holder>.morph.cosm`
beside the personal volume with its evidence, which never leaves the device. Their **isomorph** is the same shape
marked `shared`, released to `public/isomorph.morph.cosm` with `scales`, `toward`, `pinned` and `confidence` and never
`evidence` or `derived.from` (check `isomorph-bare`).

**`voice`** renders a fabula in a morph by rules: it takes the rules outline as paragraphs of sentences and applies
the morph scale by scale, re-measuring after each pass, until every statistics scale is within one step
(`scales-met`) or no move is left, and says which scales it could not meet. Its moves are listed in the package:
the stance phrases said in the first or second person; an item whose holder is the reader
said as *I*, the verb agreeing; a hedge from the 13.3 list put in front of a sentence (a hedge reads as the weakest
stance, so it never strengthens); contractions and casual heads, or Latinate stand-ins from a fixed table of FEED
headwords; a rarer or commoner synonym from FEED's pairs for an adjective or an adverb only; sentences joined with
", and" or split at one; sentences dealt into even or uneven paragraphs. Nothing is invented (`nothing-added`). The
output is a **reading** whenever the morph is not the author's: `read_through: <morph>` in its front matter, the
reading footer, saved as `<stem>.read-<morph>-<YYYY-MM-DD-HHMM>.md`, never at an input's path (`never-source`).

## 9. The knob lexicon

An agreement names exactly one knob, so it can only bite where the factory can feel it. The lexicon is closed and
generated from the factory itself: every
directive code the judges issue, the part writers' knobs (`wildness leap sync quirk solo`) and the persona appetites
they read (`density syncopation chromatic_spice velocity`), the summit's plan choices (`form key_changes tempo_band
hook_source`), the study choice (`study_first`) and the roster choice (`bench`). A studio volume copies the lexicon
into its K module when it is made, so an old sheet keeps the knobs it was written with.

## 10. The moves

Declared in the manifest's moves sidecar, `popsniplish.moves.cosm`, for `thym 1`, every one `asks: false`:

| move | signature | contract |
|---|---|---|
| `intend` | volume → fabula; `by` item (the holder) | `fabula-checks` `grounded-in-pop` `atem-shape` `provenance` |
| `judge` | volume → fabula; `by` item (the judge, or the panel) | the same |
| `notice` | item → fabula | `fabula-checks` `atem-shape` `provenance` |
| `nominate` | volume → list of item; `with` volume (the studio) | `one-requirement` `no-duplicate` `provenance` |
| `vote` | item → item; `by` item (the holder); `in` volume | `addressed` `provenance` |
| `adopt` | volume → volume | `addressed` `only-the-asked` `unanimous` `weakens-only` `provenance` |
| `voice` | fabula → short; `with` morph; `in` context | `coverage` `no-invention` `stance-kept` `scales-met` `labelled` `never-source` `nothing-added` `provenance` |
| `release` | volume → volume | `isomorph-bare` `default-deny` `provenance` |

The 1 to 16 Music Notes a judge gives leave a response banded, by Thym's `band` move, as `[rough, working, tight,
soaring]`, four bands of four. `voice` is the language's; the other seven are the Talkback's, specified in the plan.

## 11. Checks

A Popsniplish volume runs the generic checks of MacroCOSM OES 12.2 and the dialectic's own, then seven of its own:

| Check | Holds |
|---|---|
| `entry-kind` | a studio entry's kind is `tip`, `trick` or `agreement`; a personal entry's one of the ten; a talkback entry's `call`, `response` or `notice` |
| `grounded-in-pop` | every form's `feed` is a FEED word or the open question; every knob an entry names is a `K:knob` of the volume |
| `one-requirement` | an agreement carries exactly one `force` and one `knob`; no other kind carries either |
| `unanimous` | an adopted entry has one yes vote from every active musician holder of the volume, and no other vote |
| `weakens-only` | an entry proposed again carries a force at or below the last |
| `one-day` | an entry's day is a whole number from 1, at or below the calendar's day |
| `isomorph-bare` | a shared morph carries no `evidence` and no `derived.from` |

`fabula-checks` on an entry's fabula is the fabula's own contract, run by `popsniplish.checks`; the reference reader,
enough, lints the same files with zero errors (section 13).

## 12. FEED on a Boll

The register scale, term grounding and `voice` need the dictionary. A trimmed FEED ships in the image:
every word's band and part of speech, the synonym pairs, the 13.3 word lists, the
edition and its digests, and the dictionary's notice; no definition, example or translation. The full FEED is kept
privately, and the trim can also be built from it. The data is the
owner's, all rights reserved, and ships only inside Pop Boll's own images.

## 13. Conformance

A reader of Popsniplish must read every `.cosm` file in the COSM YAML subset and refuse the forbidden constructs by
name; run the generic checks under the manifest; run the seven own checks; and build, tell, measure and voice as
sections 6 and 8 say, the same bytes twice from the same inputs. The conformance evidence this edition ships is the
reference implementation's test suite and, when an enough checkout is at hand, enough's own reader: it lints the
spec's example fabula, a constructed call, a morph volume and a studio volume with zero errors, and identifies a
Popsniplish volume by this manifest (`python -m enough.macrocosm identify …`, given the manifest).

## 14. Changes

- **0.1.0 (2026-11-09).** First edition: the MiniCOSM, its moves, the knob lexicon, the trimmed FEED, the builder,
  shorts by rules, measurement, voice and readings. An agreement's force and knob live on its `S:entry` row, not on
  an `N:requirement`, because the fabula's manifest gives that kind to the fabulac alone (its `flavours`).

---

## The reference, generated

DocOES joins a document's items to the ones it generates from the manifests: the format, its modules and kinds, its closed lists, checks and lenses (MacroCOSM OES 18.5.3, "The reference, generated"). These tables are read from the MiniCOSM's manifest, its moves sidecar `popsniplish.moves.cosm` and its knob lexicon, and from its programs. The words for each volume, kind, list, move and check are the text's, in sections [4](#4-the-volumes), [5](#5-the-modules-and-their-kinds), [10](#10-the-moves) and [11](#11-checks), joined by the id in the first cell. Nobody edits a generated row: its words are changed where they are written.

### The MiniCOSM

| Key | As the manifest declares it |
| :--- | :--- |
| Declaration | `oes: popsniplish/1`; absent: refuse; unknown: refuse |
| Manifest | `minicosm/0`, written for MacroCOSM 0.6.0 |
| Name | `popsniplish`, version 1: Popsniplish |
| Summary | What a band says to itself: the entries of its studio and personal cheat sheets and the calls, responses and notices of its talkback, each a constructed fabula told as a short, indexed with the knobs, holders, votes and forms they name. |
| Format | `.cosm`, the COSM YAML subset; forbidden: anchors, aliases, tags, multiple documents; booleans `true`, `false`; utf-8 |
| Volumes | catalogs `studio.cosm`, `personal.cosm`, `talkback.cosm`, `<song>.talkback.cosm`; module files `<module folder>/**/*.cosm`; one file: true |
| Entries | `days/<day>/<nn>-<slug>.fabulan.cosm` with its shorts beside it (studio); `entries/<day>-<n>-<slug>.fabulan.cosm` (personal) |
| Morphs | `<holder>.morph.cosm` beside a personal volume, never inside it: the holomorph; public/isomorph.morph.cosm: the shared one |
| Modules | 5 (S, K, H, V, F), 5 kinds, and the core's D |
| Text | this specification, edition 0.1.0; reference implementation: Pop Boll's `popsniplish` package |
| Moves | the sidecar `popsniplish.moves.cosm`, 8 moves |
| Extension | not built |

### The catalog

Its keys, in the manifest's order, with what the manifest says of each.

| Key | Holds |
| :--- | :--- |
| `oes` | — |
| `macrocosm` | — |
| `id` | `popsniplish/<slug>` |
| `name` | — |
| `kind` | `studio`, `personal`, `talkback` |
| `band` | the band's id: its soul fingerprint (SOUL-…); never a serial |
| `device` | the device serial the volume was written on |
| `holder` | a personal volume: the holder's id, m01 to m16 for a musician, j1 to j7 for a judge, djpb for DJ PB |
| `handle` | a personal volume: the holder's name as the band knows them |
| `calendar` | a studio volume: {edition, day}, the band day the volume stands at (the longitudinal index's, never the wall clock) |
| `editions` | a studio volume: one entry per day with adoptions, appended: {day, digest, entries}; the digest is what a song's meta names |
| `releases` | a personal volume: every release of its isomorph or its public page, as Ascribe records one: {epoch, as, program, trace, at, sha256, items} |
| `morphs` | a personal volume: the bare file names of its morph volumes, each ending .morph.cosm |
| `song` | a talkback volume: the song id |
| `day` | a talkback volume: the band day |
| `nodes` | — |

### The envelope

| Field | Declared |
| :--- | :--- |
| fields | `id`, `type`, `name`, `summary`, `status`, `visibility`, `provenance`, `pending`, `links`, `made` |
| required | `id`, `type`, `name`, `summary`, `provenance` |
| references | `links` |
| status | `active`, `dormant`, `planned`, `retired` |
| visibility | `public`, `internal`, `restricted`; absent: `internal` |
| provenance | fields `mode`, `sources`, `confidence`, `state`; states `known`, `pending`, `not-disclosed`, `stale`, default `known`; confidence a number from 0 to 1 |
| provenance modes | `dialectic`, `net-scan`, `system-scan`, `integration`, `structured-intake`, `manual`, `derived`, `asserted`, `archetype`, `catalogue`, `directory`, `accounting` |
| by rules | `{mode: derived, sources: [<the song record, the take, the session>], confidence: 1}: what a rules pass read exactly` |
| by a vote | `{mode: dialectic, sources: [D:session/<id>], confidence}: what a vote wrote` |
| made | `{move, run, step, engine: rules}: the Popsniplish move that made the item (Thym 5.3)` |
| open question | `{pending: "<the question>"}` |
| sentinels | `none`, `self` |
| unknown fields | allowed and kept |
| links | `is-a`, `part-of`, `depends-on`, `supports`, `contradicts`, `resolves`, `exemplifies`, `defines`, `mentions` |

### Modules and kinds

| Module | Kind | References | Checked fields | Required beyond the envelope |
| :--- | :--- | :--- | :--- | :--- |
| **S** Sheet: The entries, one row each, pointing at their fabulas and shorts | `entry` | `holder`, `knob`, `proposed`, `forms`, `links` | `day`, `kind`, `fabula`, `short`, `atem`, `force`, `adopted`, `visibility` | `holder`, `day`, `kind`, `fabula` |
| **K** Knobs: The closed list of factory inputs an agreement may name | `knob` | — | `key`, `family`, `reads`, `range`, `unit`, `says` | `key`, `family` |
| **H** Holders: Who holds a sheet or speaks on the talkback | `holder` | — | `role`, `channel`, `judge`, `pronouns`, `pins`, `active` | `role` |
| **V** Votes: What each holder said to a proposal, and the seed that decided it | `vote` | `holder`, `entry`, `question` | `day`, `value`, `says`, `seed` | `holder`, `entry`, `value` |
| **F** Forms: The music things the entries are about, grounded in FEED | `form` | `links` | `feed`, `when` | — |

The reader adds the core's module D, the dialectic's questions and sessions, to these 5.

### Closed lists

| Field | Values |
| :--- | :--- |
| `kind` | `tip`, `trick`, `agreement`, `affinity`, `belief`, `concern`, `experience`, `interest`, `opinion`, `quale`, `skill`, `understanding`, `yearning`, `call`, `response`, `notice` |
| `force` | `must`, `should`, `may` |
| `role` | `musician`, `judge`, `dj`, `panel`, `house` |
| `value` | `yes`, `no`, `unknown` |
| `family` | `directive`, `writer`, `plan`, `study`, `roster` |
| `feed.origin` | `feed`, `user` |

### The bank

The dialectic is applied; the core's questions and sessions in module D, beside the modules (section 7 of the text). Its questions go to `holder`, write `S:entry`, and what an answer writes carries `{mode: dialectic, sources: [D:session/<id>], confidence: <the vote's confidence>}`.

| Question | Asks | Kind | About | To | Why |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `agree` | Does {name} agree to this for the studio? | `yes-no` | `S:entry` | `holder` | intent |

### Checks

The generic checks the manifest selects, then Popsniplish's own; their words are in section [11](#11-checks) and in MacroCOSM OES 12.2.

| Check | Selected by | Severity |
| :--- | :--- | :--- |
| `load` | generic, `load` | the core's |
| `duplicate-id` | generic, `envelope` | the core's |
| `id-grammar` | generic, `envelope` | the core's |
| `id-module` | generic, `envelope` | the core's |
| `type` | generic, `envelope` | the core's |
| `type-prefix` | generic, `envelope` | the core's |
| `identity-min` | generic, `envelope` | the core's |
| `provenance` | generic, `envelope` | the core's |
| `status` | generic, `envelope` | the core's |
| `visibility` | generic, `envelope` | the core's |
| `ref-grammar` | generic, `envelope` | the core's |
| `ref-unresolved` | generic, `envelope` | the core's |
| `closed-list` | generic, `envelope` | the core's |
| `pending-shape` | generic, `envelope` | the core's |
| `catalog-key` | generic, `envelope` | the core's |
| `entry-kind` | Popsniplish's own | error |
| `grounded-in-pop` | Popsniplish's own | error |
| `one-requirement` | Popsniplish's own | error |
| `unanimous` | Popsniplish's own | error |
| `weakens-only` | Popsniplish's own | error |
| `one-day` | Popsniplish's own | error |
| `isomorph-bare` | Popsniplish's own | error |

### Lenses

| Lens | Makes | Draws |
| :--- | :--- | :--- |
| `sheet` | a day's entries as their shorts, in order, each with its holder and its vote | `table`: columns: day, id, kind, holder, force, knob, adopted |
| `talkback` | a song's calls, responses and notices by part and take, each as its atem line | `table`: columns: id, kind, holder, atem |
| `holder` | a holder's page, an isograph-style card of what they say, with their public shorts and their isomorph | `mermaid`: diagram: mindmap, include: S, F |
| `text-tree` | the text tree | `python -m enough.macrocosm tree` |

### The moves

Declared in the sidecar for `thym 1` (`moves-of: popsniplish/1`): 8 moves, none of which asks a model.

| Move | Takes | Gives | Modifiers | Contract | Code | Says |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `intend` | `volume` | `fabula` | `by: item` | `fabula-checks`, `grounded-in-pop`, `atem-shape`, `provenance` | `talkback.calls:intend` | a musician's call before a take, what they mean to do and why, as a fabula |
| `judge` | `volume` | `fabula` | `by: item` | `fabula-checks`, `grounded-in-pop`, `atem-shape`, `provenance` | `talkback.responses:judge` | a judge's response after a lock vote, what was measured and what is required, as a fabula |
| `notice` | `item` | `fabula` | — | `fabula-checks`, `atem-shape`, `provenance` | `talkback.notices:notice` | the house's notice of an event, as a fabula |
| `nominate` | `volume` | `list of item` | `with: volume` | `one-requirement`, `no-duplicate`, `provenance` | `talkback.studio:nominate` | what a day's talkback nominates for the studio, as proposals |
| `vote` | `item` | `item` | `by: item`, `in: volume` | `addressed`, `provenance` | `talkback.votes:vote` | one holder's answer to a proposal, by rules, seeded, with their words |
| `adopt` | `volume` | `volume` | — | `addressed`, `only-the-asked`, `unanimous`, `weakens-only`, `provenance` | `talkback.studio:adopt` | the settled studio volume, every unanimous proposal adopted and every other weakened or dropped |
| `voice` | `fabula` | `short` | `with: morph`, `in: context` | `coverage`, `no-invention`, `stance-kept`, `scales-met`, `labelled`, `never-source`, `nothing-added`, `provenance` | `popsniplish.voice:voice` | a fabula told in a morph by rules, a reading when the morph is not the author's |
| `release` | `volume` | `volume` | — | `isomorph-bare`, `default-deny`, `provenance` | `talkback.personal:release` | a holder's public page and isomorph, nothing private in either |

### The knob lexicon

41 knobs in 5 families (26 directive, 9 writer, 4 plan, 1 study, 1 roster), generated from the factory itself; a studio volume copies them into its K module when it is made.

| Knob | Family | Read by | Range | Says |
| :--- | :--- | :--- | :--- | :--- |
| `ADD_BASS_REGISTER_ANCHOR` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (add bass register anchor) |
| `ADD_FINAL_BAR_TURNAROUND_FILL` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (add final bar turnaround fill) |
| `ADD_HARMONIC_COMPING` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (add harmonic comping) |
| `ADD_KICK_SNARE_FOUNDATION` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (add kick snare foundation) |
| `ADD_MONOPHONIC_LEAD_MELODY` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (add monophonic lead melody) |
| `ADJUST_SYNCOPATION_TO_TASTE_DNA` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (adjust syncopation to taste dna) |
| `AUTOTUNE_SNAP_SOUR_NOTES` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (autotune snap sour notes) |
| `CLEAR_LOW_REGISTER_MUD` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (clear low register mud) |
| `DUCK_COMPING_UNDER_LEAD_MELODY` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (duck comping under lead melody) |
| `EMPHASIZE_POP_PILLARS_CFGA` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (emphasize pop pillars cfga) |
| `FILL_EMPTY_BARS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (fill empty bars) |
| `GENERATE_PITCHED_NOTES` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (generate pitched notes) |
| `INCREASE_LEAD_MOTIF_DENSITY` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (increase lead motif density) |
| `INJECT_CORPUS_CELLS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (inject corpus cells) |
| `INJECT_CORPUS_MOTIF_CELL` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (inject corpus motif cell) |
| `INSERT_PHRASE_BREATH_RESTS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (insert phrase breath rests) |
| `LOCK_BASS_TO_KICK_TRANSIENTS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (lock bass to kick transients) |
| `POPULATE_ALL_BARS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (populate all bars) |
| `POPULATE_ARRANGEMENT` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (populate arrangement) |
| `REDUCE_CHROMATIC_QUIRKS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (reduce chromatic quirks) |
| `RESOLVE_MINOR_SECOND_COLLISIONS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (resolve minor second collisions) |
| `SMOOTH_LEAD_VOICE_LEADING` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (smooth lead voice leading) |
| `STRENGTHEN_BAR_CHORD_TRIADS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (strengthen bar chord triads) |
| `THIN_ARRANGEMENT_DENSITY` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (thin arrangement density) |
| `TIGHTEN_RHYTHMIC_POCKET_GRID` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (tighten rhythmic pocket grid) |
| `TRIM_BAR_BOUNDARY_OVERRUNS` | directive | `judges` | issued, waived | a judge directive the writers obey on the next take (trim bar boundary overruns) |
| `wildness` | writer | `part_writers.knobs_for` | 0 to 1 | how far a take may stray from the plan |
| `leap` | writer | `part_writers.knobs_for` | 0 to 1 | how wide a melodic interval the lead may take |
| `sync` | writer | `part_writers.knobs_for` | 0 to 1 | the appetite for off-beat placement |
| `quirk` | writer | `part_writers.knobs_for` | 0 to 1 | the chromatic spice a line may carry |
| `solo` | writer | `part_writers.knobs_for` | 0 to 1 | the ego drive that puts a musician out front |
| `density` | writer | `personas.MusicalBehavior.density_range` | 0 to 16 | notes per bar |
| `syncopation` | writer | `personas.MusicalBehavior.syncopation_appetite` | 0 to 1 | the persona's own syncopation appetite |
| `chromatic_spice` | writer | `personas.MusicalBehavior.chromatic_spice` | 0 to 1 | the persona's own chromatic spice |
| `velocity` | writer | `personas.MusicalBehavior.velocity_bias` | 1 to 127 | the base MIDI velocity |
| `form` | plan | `song_form` | verse-chorus, aaba, through, suite | the song's form |
| `key_changes` | plan | `ralph_factory.run_plenary_planning_summit` | 0 to 3 | how many key changes the song may have |
| `tempo_band` | plan | `ralph_factory.run_plenary_planning_summit` | slow, mid, fast | the tempo band of the plan |
| `hook_source` | plan | `ralph_factory.run_plenary_planning_summit` | hall-of-fame, fresh, corpus-cell | where the chorus hook comes from |
| `study_first` | study | `longitudinal_engine.run_musician_study_break` | favourite, least-studied, judge-pick | which corpus track a study break takes first |
| `bench` | roster | `ralph_factory.run_ralph_loop_for_part` | captain, rival, nobody | who sits out a part when the teams are drafted |

### The programs

9 programs, each `thym 1`, each built from the moves above.

| Program | File | Takes | Gives | Why |
| :--- | :--- | :--- | :--- | :--- |
| `call-a-take` | `call-a-take.thym` | `take: volume`, `who: item` | `s: short` | before a take, a musician says what they mean to do and why, as a fabula the band can check and a short the band can read. |
| `land-the-vote` | `land-the-vote.thym` | `proposal: item`, `who: item`, `studio: volume` | `v: item` | one holder answers one proposal, by rules, seeded by the soul, the day, the entry and the holder, with their own words. |
| `measure-a-holder` | `measure-a-holder.thym` | `t: text`, `f: fabula` | `m: morph` | a holder's text measured against the null telling of its fabula: the holomorph, the departure from the plainest telling on ten scales. |
| `nominate-to-the-studio` | `nominate-to-the-studio.thym` | `day: volume`, `studio: volume` | `g: volume` | the day's talkback nominates what the studio should keep; each proposal lands with the studio volume and the one question the bank asks of every musician. |
| `notice-an-event` | `notice.thym` | `event: item` | `s: short` | the house says what happened: a study break, a mutation, the song's end, a retirement, a recruit. |
| `release-a-sheet` | `release-a-sheet.thym` | `sheet: volume` | `p: volume` | a holder's personal sheet leaves the device as its public page and its isomorph, with nothing private in either. |
| `respond-to-a-take` | `respond-to-a-take.thym` | `panel: volume`, `who: item` | `s: short` | after a lock vote, a judge says what was measured and what is required, as a fabula and a short. |
| `settle-the-vote` | `settle-the-vote.thym` | `studio: volume`, `said: volume` | `g: volume` | what the band said is written into the studio, each answer where its question pointed; every unanimous proposal is adopted and every other weakened or dropped; nothing else in the volume moves. |
| `voice-an-entry` | `voice-an-entry.thym` | `f: fabula`, `mine: morph`, `now: context` | `r: short` | an entry is told in a holder's morph, by rules, for this occasion; a reading when the morph is not the author's, labelled and never the source. |

What they keep, and what was decided when they were written:

| Program | Must | Decided | Decision |
| :--- | :--- | :--- | :--- |
| `call-a-take` | nothing in the call is invented: every item is read from the plan, the roster, the directives and what the musician studied. | 2026-11-09 | the call is a standalone fabulan, told by rules, without a model. |
| `land-the-vote` | — | 2026-11-09 | a vote is yes, no or unknown; unknown blocks adoption as a no does. |
| `measure-a-holder` | — | 2026-11-09 | only standard moves, so the reference compiler can check this program as it is; under rules the seven statistics scales are measured and the three judgement scales are pending. |
| `nominate-to-the-studio` | a proposal that is an agreement names exactly one force and one knob. | 2026-11-09 | the questions land in this run; the votes come back in another; no run waits. |
| `notice-an-event` | — | 2026-11-09 | a notice is a fabula like a call, told the same way. |
| `release-a-sheet` | the holomorph, with its evidence, never leaves. | 2026-11-09 | the release is recorded in the sheet, as Ascribe records one. |
| `respond-to-a-take` | a measurement is observed and a verdict is an opinion; a directive issued is a must, a waived one a may. | 2026-11-09 | the 1 to 16 notes leave banded, four bands of four. |
| `settle-the-vote` | — | 2026-11-09 | must weakens to should, should to may, and a may that fails is dropped to its proposer's personal sheet. |
| `voice-an-entry` | nothing is added: every name and number is the fabula's, every other word is FEED's. | 2026-11-09 | voice is Popsniplish's own move, not Thym's read, which asks a model. |

## The atem

The document at its atem density, as DocOES tells it: one line per section, the text's own where it sets one and the first sentence of the section's first paragraph where it does not, cut at a clause break when it runs long; then the terms the text defines, each with its definition.

### Outline

- [How to read this](#how-to-read-this) — the rule words and the family of words: holders, calls, sheets, entries, knobs
- **1** [Provenance and the name](#1-provenance-and-the-name) — where Popsniplish comes from, and what the name says
- **2** [The model on one page](#2-the-model-on-one-page) — the factory, the fabula, the short and the vote, drawn once
- **3** [The design rules](#3-the-design-rules) — seven rules every part of Popsniplish answers to
- **4** [The volumes](#4-the-volumes) — studio, personal and talkback volumes, their files and their catalog keys
- **5** [The modules and their kinds](#5-the-modules-and-their-kinds) — six modules, their kinds, the envelope and the closed lists
- **6** [Entries: constructed fabulas and their shorts](#6-entries-constructed-fabulas-and-their-shorts) — an entry is a standalone fabulan, told as a short by rules
- **7** [The dialectic, applied: the vote](#7-the-dialectic-applied-the-vote) — one question, every musician's answer by rules, unanimity or weakening
- **8** [Morphs: holomorphs, isomorphs, voice and readings](#8-morphs-holomorphs-isomorphs-voice-and-readings) — ten scales measured by rules; the holder's morph, private and shared; voice
- **9** [The knob lexicon](#9-the-knob-lexicon) — the closed list of factory inputs an agreement may name
- **10** [The moves](#10-the-moves) — eight moves declared for Thym, every one transcoding
- **11** [Checks](#11-checks) — the generic checks, the dialectic's, and seven of Popsniplish's own
- **12** [FEED on a Boll](#12-feed-on-a-boll) — the trimmed dictionary the image ships, and where the full one lives
- **13** [Conformance](#13-conformance) — what a reader of Popsniplish must do, and the evidence this edition ships
- **14** [Changes](#14-changes) — what each edition changed, newest first

### Glossary

| Term | Defined in | Definition |
| :--- | :--- | :--- |
| **holder** | [How to read this](#how-to-read-this) | A holder is who owns a personal sheet and speaks on the talkback… |
| **call** | [How to read this](#how-to-read-this) | A call is a musician's message before a take… |
| **Studio Cheat Sheet** | [How to read this](#how-to-read-this) | The Studio Cheat Sheet (SCS) is the band's sheet, a page per band day… |
| **entry** | [How to read this](#how-to-read-this); also [2](#2-the-model-on-one-page) | An entry is one item of a sheet: a constructed fabula file and its short |
| **knob** | [How to read this](#how-to-read-this) | A knob is a factory input an agreement may name, from a closed lexicon |
| **volume** | [2](#2-the-model-on-one-page) | A volume is a studio sheet, a personal sheet or one song's talkback |
| **vote** | [2](#2-the-model-on-one-page) | The vote is the core's dialectic with a bank of one question, answered by rules |
| **morph** | [2](#2-the-model-on-one-page) | A morph is Thym's, measured by rules on the seven statistics scales… |
| **The envelope** | [5](#5-the-modules-and-their-kinds) | The envelope is MacroCOSM's: id type name summary provenance required; status, visibility, pending… |
| **atem** | [6](#6-entries-constructed-fabulas-and-their-shorts) | The atem is constructed with the items: the line (15 to 25 words)… |
| **short** | [6](#6-entries-constructed-fabulas-and-their-shorts) | A short is compiled by rules: by weight for a standalone fabula |

## Colophon

*Popsniplish is © 2026 Graham Smith. This specification's text, as published on this page, is
licensed CC BY 4.0: it may be quoted and shared with credit. The name Popsniplish and the FEED data (§12) stay the
owner's. The reference implementation is closed today. A core subset of it that
needs no FEED is to be published under Apache-2.0 in the Bollard SDK, with a JavaScript twin; that is decided and
not done. Voice, morph and the FEED dictionary stay closed.*

This page is generated from the specification's one text (edition 0.1.0, revised 2026-11-10), which Pop Boll keeps, and a check holds the page in step with it. The text is given word for word, with its HTML comments removed and its Contents linked, but for 11 places where it names a file in Pop Boll's private repository: there the page says the same thing without the file's name. The reference, the outline and the glossary are made from the manifest, the programs and DocOES's rules, and nothing else is written here.
