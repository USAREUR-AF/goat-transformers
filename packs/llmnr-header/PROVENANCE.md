# Provenance: llmnr-header pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 4795, Link-Local Multicast Name Resolution (LLMNR), January 2007, section 2.1.1 | https://www.rfc-editor.org/rfc/rfc4795.txt | `84dc17ee8bf0d18c608a19318ce4b1d5b0fdded54732d098ed14cae98601d2df` |
| IETF RFC 1035, Domain Names - Implementation and Specification, section 4.1.1 (the DNS header of the shared keys, as dns-header reads it) | https://www.rfc-editor.org/rfc/rfc1035.txt | (as recorded for dns-header) |

## Licence

RFC 4795 states "Copyright (C) The IETF Trust (2007)." and is subject to BCP 78 and the IETF Trust's Legal
Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default
Apache-2.0 label.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure or table of
the sources is copied. The vectors are packets built by `tools/gen/dirnaming-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layout from IETF RFC 4795 (B. Aboba, D. Thaler, L. Esibov, 2007), restated.
