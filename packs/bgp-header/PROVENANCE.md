# Provenance: bgp-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `bgp-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 4271, A Border Gateway Protocol 4 (BGP-4), January 2006 | https://www.rfc-editor.org/rfc/rfc4271.txt | `98b851146abcd56ecbb398dd1a818bcde2dcac6fde3d901c423d988f86eaab76` | the message header, OPEN, UPDATE, NOTIFICATION and KEEPALIVE, section 4 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc4271.

## Licence

The copyright notice of RFC 4271, with the first sentence of its Full Copyright Statement:

> Copyright (C) The Internet Society (2006).
>
> This document is subject to the rights, licenses and restrictions
> contained in BCP 78, and except as set forth therein, the authors
> retain all their rights.

The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover it.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
