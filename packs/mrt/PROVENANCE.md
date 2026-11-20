# Provenance of the mrt pack

The pack and the module `mrt` are written by `tools/gen/mrt-pack.py`, which states each layout
once, read from the RFCs below; the vectors by `tools/gen/logs-vectors.py`, which encodes records
written for them. No RFC text is kept in this repository. Read on 2026-11-20.

| Source | Address | SHA-256 | Sections read |
|---|---|---|---|
| RFC 6396, Multi-Threaded Routing Toolkit (MRT) Routing Information Export Format | https://www.rfc-editor.org/rfc/rfc6396.txt | `415c96368320e94eaed7dd17d024a83c516beb0ac98653ec80ddcc1921d22ef7` | 2, 3, 4.3, 4.4 |
| RFC 8050, MRT Routing Information Export Format with BGP Additional Path Extensions | https://www.rfc-editor.org/rfc/rfc8050.txt | `aa3ea773846495e292749a13a5306dfbc6da8e37d80ddbf92fddc827a71b5821` | 3, 4 |
| RFC 4271, A Border Gateway Protocol 4 (BGP-4) | https://www.rfc-editor.org/rfc/rfc4271.txt | `98b851146abcd56ecbb398dd1a818bcde2dcac6fde3d901c423d988f86eaab76` | 4.1 to 4.5 (the message header, OPEN, UPDATE, KEEPALIVE, NOTIFICATION) |

Each RFC's notice:

> This document is subject to BCP 78 and the IETF Trust's Legal Provisions Relating to IETF
> Documents (http://trustee.ietf.org/license-info) in effect on the date of publication of
> this document.

The pack restates the record layouts in this repository's words and copies no text, figure or
example of the RFCs; it is labelled Apache-2.0, as the other packs written from RFCs are.
