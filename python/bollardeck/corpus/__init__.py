# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus: call a corpus, and respect its settings.

A corpus is an artist's dataset: a manifest (corpus.json), a licence block inside it, and files
(the morpus the musicians study, recordings, cover art). This package is the one way a client
finds a corpus, asks what it may do with it, and reads it. Standard library only.


Using it
========

1. Find corpora
---------------

    from bollardeck.corpus import HubClient, Identity, discover

    hub = HubClient("https://bollawax.org", token=TOKEN, player="my-player",
                    cache_dir="/var/cache/corpora")
    found = discover(roots=["/media/sd/corpora"], hub=hub)

    for corpus in found.corpora:
        print(corpus.id, corpus.name, corpus.source)          # "local" or "hub"
    for where, reason, problems in found.refused:
        print("left out:", where, reason, problems)           # never dropped silently

A corpus in a local folder beats the same id on the hub (pass prefer_remote=True to turn that
round). A manifest that does not fit the corpus-manifest schema is refused whole, with its
problems; nothing is read from it.

One corpus by id, or from a folder, or from a manifest you already hold:

    corpus = hub.corpus("9001-PLACEHOLDERS")
    corpus = Corpus.load("/media/sd/corpora/9001-PLACEHOLDERS")
    corpus = Corpus.from_manifest(manifest_dict)

Pick a set. Ids that are not there are an error, not a quiet substitution:

    chosen = found.corpora.select(["9001-PLACEHOLDERS", "9002-STANDINS"])     # MissingCorpora
    chosen = found.corpora.select(ids, if_missing="skip")    # take what is there; .missing says what was not
    chosen = found.corpora.select(ids, if_missing="all")     # every corpus when none is there; .substituted

2. Ask the gate
---------------

    verdict = corpus.may("study", identity=Identity(email="ada@example.org"))
    if not verdict:
        show(verdict.reason, verdict.detail)                  # "revoked", "the licence was revoked at ..."

`may` never raises. It answers for the eight licence capabilities (transcode, store_audio,
stream_audio, store_art, store_morpus, musicians_may_study, export_morpus, device_copies; "study"
is short for musicians_may_study) and for "see" (may this identity know the corpus is there).
Every refusal has a reason from gate.REASONS:

    manifest_invalid  licence_ambiguous  unknown_scope  newer_version  withdrawn  not_visible
    licence_missing   licence_invalid    revoked        expired        not_granted
    unknown_capability  bad_clock

Things worth knowing:

  * A corpus with no licence block, or "licence": null, allows nothing (licence_missing).
  * A private corpus allows nothing to an identity that is not its owner and not on its access
    list, whatever the licence says. Identity(service=True) is the platform's own engine.
  * For a corpus from a hub, `may` first revalidates the licence block when the last check is
    older than the client's `revalidate_after`. A revocation or expiry the hub reports applies
    at once. When the hub cannot be reached the cached corpus keeps working on the block it
    holds, and the verdict says so: `verdict.unverified_since` is when the block was last
    revalidated. An `expires_at` the device already holds is honoured by its own clock, online
    or not; a revocation it has not heard of waits for the next contact. Setting the clock
    back does not reopen it: the gate reads no time earlier than the cache has witnessed.
  * A hub's read token alone is STUDY ONLY for a corpus that is not public. The
    hub gives a client that names nobody the morpus and a manifest with the people taken out,
    and answers 404 for tracks, audio, art and bundles. Say who the client acts for to reach
    those:

        hub = HubClient(url, token=TOKEN, acting_for="ada@example.org")     # or per call:
        corpus = hub.corpus("9002-PRIVATE", acting_for="ada@example.org")
        v = corpus.may("stream_audio", identity=Identity(email="ada@example.org"))

    The name is sent in the header X-Pop-For and never in a URL. It is self-declared until
    sign-in arrives in 0.2.5: it narrows what a token holder gets and proves nothing. A corpus
    fetched for a person is cached apart from the engine's copy.

3. Read content, with the verdict
---------------------------------

    v = corpus.may("study")
    if v:
        dna = corpus.dna(v)
        for notes, midi in corpus.study_pairs(v):
            text = corpus.read_morpus(notes, v)
            path = corpus.morpus_path(midi, v)                # a file on disk (cached if from a hub)

    v = corpus.may("stream_audio", identity=who)
    if v:
        for track in corpus.tracks(v):
            with corpus.open_audio(track, v, byte_range=(0, 65535)) as audio:
                play(audio.read())

    v = corpus.may("export_morpus", identity=who)
    if v:
        bundle = corpus.export_bundle("some-song", v)         # an MRPH5 bundle to hand to a person

A relay (a server that passes a recording on to its own caller) wants the source's status and
headers, and takes its caller's Range header as it came:

    with corpus.open_audio_ranged(track, v, range_header=request.headers.get("Range")) as upstream:
        respond(upstream.status, upstream.headers, upstream.read())     # 200, 206 or 416

When something the gate allowed cannot be had, NotAvailable says why in `reason` (one of
model.NOT_AVAILABLE_REASONS, such as not_found, unreachable, not_licensed or bad_range) and
gives the hub's HTTP `status` when a hub answered.
CorpusUnavailable does the same for a corpus that cannot be had at all: `reason` is bad_id,
not_served or unreachable. Nobody needs to read the message text.

Each accessor takes the Verdict and raises GateRequired when it is missing, refused, for another
corpus or capability, older than fifteen minutes, or from before the corpus last changed. There
is no accessor without one, and the stores behind a Corpus accept nothing but a grant made from
an allowed Verdict. Metadata is free: id, name, artist, licence (on paper), visibility, form_cap,
attestation, manifest() (a copy, yours to change) and manifest_view() (read-only, the same
object each call, for code that only reads, such as a gate asked many times).

4. Show the notices
-------------------

    for line in corpus.notices()["lines"]:
        print(line)        # the edition label, the corpus's own notice, each MIDI source's attribution

5. Check the attestation
------------------------

    from bollardeck.corpus import attest
    record = attest.read_local_record(corpus.root, corpus.attestation["edition"])
    ed_pub, ml_pub = attest.read_public_keys("/etc/popboll/locker-keys", corpus.attestation["keyid"])
    result = attest.verify_attestation(corpus, ed25519_pub=ed_pub, mldsa65_pub=ml_pub, **record)
    result.status          # "verified" | "failed" | "partial" | "not_checked"
    result.mldsa65         # "not_checked" where no openssl knows ML-DSA-65; never "verified" by default

6. Self-hosted corpora
----------------------

    from bollardeck.corpus import fetch_origin
    origin = fetch_origin("https://files.example/popboll/", auth=("bearer", TOKEN))
    origin.live, origin.problems, origin.manifest()

7. A report-only window on the hub
---------------------------------

A hub states its rollout switch in /api/version as `corpus_gate`: "enforce", or "report" while it
still answers the old way for a manifest with no licence block and only counts what it would
refuse. `hub.corpus_gate()` reads it ("enforce", "report", or None when the hub states neither),
and `hub.listing().from_cache` says when a listing is the one from last time because the hub
could not be reached.

There is deliberately no way to read content the gate refuses, with a caller-supplied grace or
otherwise. The gate is the one place the licence is applied, and its promise to an artist is that
no SDK client reads a corpus the licence does not open; a switch that turns that off for "this
rollout" is the same switch for every later excuse, in every third-party client, and nothing on
the client can check that the grace it was handed is the hub's to give. A manifest with no
licence block is refused (licence_missing) whatever the hub's switch says. So during a
report-only window a host that must keep such a corpus playing does it outside the gate, in its
own code and on its own responsibility: it reads `hub.corpus_gate()`, and while that says
"report" it fetches those corpora the way it did before the gate, logs each one as a refusal
that is being waived, and deletes that path when the hub says "enforce". The lasting fix is on
the data: give the manifest its licence block, and the SDK reads it like any other.

Configuration
-------------

Everything is a constructor argument. `config_from_env()` reads the environment variables Pop
Boll's own programs use (POPBOLLARD_BOLLAWAX_URL and friends) and returns plain settings; it is
the only place this package looks at the environment:

    cfg = config_from_env()
    hub = HubClient(**cfg["hub"]) if cfg["hub"] else None
    found = discover(roots=cfg["roots"], hub=hub, prefer_remote=cfg["prefer_remote"])


Modules
=======

    licence     the licence block on paper: scopes, capabilities, UTC times
    gate        the decision, its reasons, Identity, Verdict
    model       Corpus and its accessors
    hub         HubClient, the cache, revalidation, config_from_env
    discovery   discover(), CorpusSet, select
    attest      attested editions: hashes, Ed25519, ML-DSA-65 through openssl
    origin      popboll.origin/1 discovery

Behaviour vectors for the gate are in conformance/corpus-gate/ (plain JSON, for any language).
"""

from . import attest
from .attest import AttestationResult, verify_attestation
from .discovery import CorpusSet, Discovery, MissingCorpora, discover
from .gate import ALL_CAPABILITIES, REASONS, GateRequired, Identity, Standing, Verdict, judge
from .hub import CorpusUnavailable, HubClient, HubError, HubUnreachable, Listing, config_from_env
from .licence import CAPABILITIES, Licence
from .model import NOT_AVAILABLE_REASONS, Corpus, ManifestRefused, NotAvailable, RangedAudio
from .origin import Origin, OriginError, fetch_origin

__all__ = [
    "Corpus", "Licence", "Identity", "Verdict", "Standing", "judge", "GateRequired", "ManifestRefused",
    "NotAvailable", "NOT_AVAILABLE_REASONS", "RangedAudio", "CAPABILITIES", "ALL_CAPABILITIES", "REASONS",
    "discover", "Discovery", "CorpusSet", "MissingCorpora",
    "HubClient", "HubError", "HubUnreachable", "CorpusUnavailable", "Listing", "config_from_env",
    "attest", "verify_attestation", "AttestationResult",
    "fetch_origin", "Origin", "OriginError",
]
