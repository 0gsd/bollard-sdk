# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.popsnip: Pop Snip apps, the third-party apps that live at <name>.popsnip.app.

    from bollardeck.popsnip import records
    records.check(records.parse(text))          # the record, or records.RecordError with a code
    records.signed_message(record)              # the bytes an Ed25519 signature over it covers

`records` is the record forms and their canonical bytes (see its docstring); the conformance vectors are
conformance/popsnip/records.json, which the JavaScript twin (js/bollardeck.popsnip.js) passes too.
"""
from . import records
from .records import RecordError, canonical, check, parse, record_id, rekey_request, signed_message

__all__ = ["records", "RecordError", "canonical", "check", "parse", "record_id", "rekey_request", "signed_message"]
