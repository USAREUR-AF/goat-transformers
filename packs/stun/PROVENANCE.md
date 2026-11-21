# Provenance: stun pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 8489, Session Traversal Utilities for NAT (STUN), February 2020 | https://www.rfc-editor.org/rfc/rfc8489.txt | `3a1c97ec36576fda83b5f39fbe1d033c6c0b934e2209a29bb21b9ace57ef4289` |
| IETF RFC 8656, Traversal Using Relays around NAT (TURN), February 2020 | https://www.rfc-editor.org/rfc/rfc8656.txt | `271f4386bcf95cf94a31710dda6816a89cefdc2557581451e6a36d79b93b12b0` |

## Licence

The RFCs are IETF documents under the IETF Trust copyright, BCP 78 and the IETF Trust's Legal Provisions
Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default Apache-2.0 label.

This pack restates the layouts (field order, sizes, values) in its own words; no text, table, figure
or example of the sources is copied. The vectors are messages built by
`tools/gen/messaging-vectors.py` from values chosen there; their expected bytes are derived there,
without an engine.
