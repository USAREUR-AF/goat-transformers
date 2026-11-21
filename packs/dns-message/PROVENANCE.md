# Provenance: dns-message pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 1035, Domain Names - Implementation and Specification, November 1987; sections 3.1-3.4 and 4.1 | https://www.rfc-editor.org/rfc/rfc1035.txt | `d14ae809fc9b41bbcae26bb38c937c9515808b944f3252b00de9fe0e95f4fdfb` |
| IETF RFC 3596, DNS Extensions to Support IP Version 6, October 2003; section 2.2 | https://www.rfc-editor.org/rfc/rfc3596.txt | `2a3d44744086f66a7ba00e7d282dc1f740a3e0b63b4b6f7c763ffc0e61ee1dbb` |
| IETF RFC 2782, A DNS RR for specifying the location of services (DNS SRV), February 2000; the RR format | https://www.rfc-editor.org/rfc/rfc2782.txt | `bacc8972b55f30eb47d7bb07662905ba3a3a7cdefb148174d0d9fbbb313735ac` |
| IETF RFC 6891, Extension Mechanisms for DNS (EDNS(0)), April 2013; section 6 | https://www.rfc-editor.org/rfc/rfc6891.txt | `626d2d3a8febe5c92fb90a84b0891ec2f6c983a681ab5d06040c75ef2119491f` |
| IETF RFC 8659, DNS Certification Authority Authorization (CAA) Resource Record, November 2019; section 4.1 | https://www.rfc-editor.org/rfc/rfc8659.txt | `5f0e193e3bfad5273fe8dd1086d060bdec951505d61bfd0111ae832c1f3e293d` |

## Licence

These are IETF documents, each under the copyright notice of its time (the IETF Trust, or for the older
ones the Internet Society; RFC 1035, of 1987, carries no copyright notice), subject to BCP 78 and the IETF
Trust's Legal Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps
the default Apache-2.0 label. It restates the layouts (field order, sizes, codes) in this project's own
words; no text or figure is copied.

The vectors are built by `tools/gen/inet-more-vectors.py` from values chosen there; their expected bytes are
derived there, without an engine.

## Attribution

From RFC 1035, RFC 3596, RFC 2782, RFC 6891 and RFC 8659. Copyright IETF Trust (or the Internet Society) and the
persons identified as the document authors; BCP 78 and the IETF Trust's Legal Provisions Relating to IETF
Documents. Layouts restated, no text copied.
