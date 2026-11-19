# conformance/popsnip

`records.json` holds the vectors for Pop Snip records: the apps that live at `<name>.popsnip.app`, their launches,
releases, key changes and revocations. Every implementation gives the same answers:

- **`records`:** for each `record`, `check(record, signed)` refuses with `error` or accepts (`error: null`).
  - `signed` is true unless the vector says `"signed": false`, which is a record about to be signed.
  - For an accepted record that carries `canonical`, its canonical bytes are `canonical` (ASCII) and its id is
    `id` (sha256, hex).
  - Its signature is Ed25519 by the key named in `signed_by`, over `context` + `canonical`. `signed_by` is `null`
    for a rekey request, whose signature travels as its rotation's `old_key_sig`.
- **`texts`:** `parse()` of `text` refuses with `parse_error`, or gives a value whose canonical bytes are
  `canonical` or which is refused with `canonical_error`. A text read from UTF-8 bytes gets the same answer.
- **`rekey_requests`:** the request that a rotation's `old_key_sig` covers, and its canonical bytes.

The keys in `keys` are **test keys**. Their seeds are printed, so never use them for anything real.

The rules are written in `tools/popsnip_vectors.py`, which makes the file (`--check` compares). The refusal codes, in
the order they are tried:
1. `not_object`
2. `not_ascii`, `bad_number` or `bad_json` (nesting deeper than 32)
3. `unknown_kind`
4. `bad_version`
5. `unknown_field:<f>`
6. `missing_field:<f>`
7. `bad_field:<f>` (fields in sorted order)
8. `rule:<name>`

`parse()` adds `bad_json` and `duplicate_key`. It counts nesting over the text before anything else, so deep input
is `bad_json` whatever it holds.

`accept.json` holds the device check's cases (`accept()` in Python, `checkAccept()` in JavaScript): a signed history,
its variants, and each case's expected code. `ed25519.json` pins the one Ed25519 verify equation both twins use:
cofactorless, S below L, canonical points, and an A or R of small order refused. A verifier that is cofactored, or
that lets mixed-order points through differently, gives other answers on its mixed-order cases.
