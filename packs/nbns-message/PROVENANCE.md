# Provenance: nbns-message pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 1002, Protocol Standard for a NetBIOS Service on a TCP/UDP Transport: Detailed Specifications, March 1987, sections 4.1, 4.2 and 4.4 | https://www.rfc-editor.org/rfc/rfc1002.txt | `af52f2f4df7b6d11358e4a87e673842e7b78203e289dbeccd18906b21a7837b2` |
| IETF RFC 1035, Domain Names - Implementation and Specification, section 4.1.1 (the DNS header of the shared keys, as dns-header reads it) | https://www.rfc-editor.org/rfc/rfc1035.txt | (as recorded for dns-header) |

## Licence

RFC 1002 is from before the IETF Trust; it carries no copyright line, and its status section states that
its distribution is unlimited. RFCs are covered by BCP 78 and the IETF Trust's Legal Provisions Relating to
IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default Apache-2.0 label. RFC 1035 is used only for the
meaning of the shared header keys.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure or table of
the sources is copied. The vectors are packets built by `tools/gen/dirnaming-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layouts from IETF RFC 1002 (NetBIOS Working Group, 1987), restated.
