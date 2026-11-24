# Provenance: icmpv6-nd pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 4861, Neighbor Discovery for IP version 6 (IPv6), September 2007; sections 4.1-4.6 | https://www.rfc-editor.org/rfc/rfc4861.txt | `1a4309c117d765a7c0edfcb2297fc90c3c09f0fcae255f15e53b20748bcc09fb` |
| IETF RFC 8106, IPv6 Router Advertisement Options for DNS Configuration, March 2017; section 5 | https://www.rfc-editor.org/rfc/rfc8106.txt | `9a44a5e06d36506da358fa0d62d02f484dd76b4e6ca75920ebda2cfed315ef2f` |
| IETF RFC 6275, Mobility Support in IPv6, July 2011; section 7.2 (the prefix information option); read 2026-11-24, after the pack was written | https://www.rfc-editor.org/rfc/rfc6275.txt | `5773ab98e91a06be49ac9f3821836dca6372227e2126db81c414f938c03fe20a` |

## Licence

These are IETF documents, each under the copyright notice of its time (the IETF Trust, or for the older
ones the Internet Society; RFC 1035, of 1987, carries no copyright notice), subject to BCP 78 and the IETF
Trust's Legal Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps
the default Apache-2.0 label. It restates the layouts (field order, sizes, codes) in this project's own
words; no text or figure is copied.

The vectors are built by `tools/gen/inet-more-vectors.py` from values chosen there; their expected bytes are
derived there, without an engine.

## Attribution

From RFC 4861 and RFC 8106. Copyright IETF Trust and the persons identified as the document authors; BCP 78
and the IETF Trust's Legal Provisions Relating to IETF Documents. Layouts restated, no text copied.
