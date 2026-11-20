# Provenance: icmpv6-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `icmpv6-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 4443, the ICMPv6 specification for IPv6, March 2006 | https://www.rfc-editor.org/rfc/rfc4443.txt | `f20d1de8878e1142000bfeaa3ad1b0540fab7653a395cf7b07e81d2da2f650bf` | the message header, the error messages and echo, sections 2.1, 3 and 4 |
| RFC 4861, Neighbor Discovery for IP version 6 (IPv6), September 2007 | https://www.rfc-editor.org/rfc/rfc4861.txt | `1a4309c117d765a7c0edfcb2297fc90c3c09f0fcae255f15e53b20748bcc09fb` | the router solicitation and router advertisement, sections 4.1 and 4.2 |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc4443, https://www.rfc-editor.org/errata/rfc4861.

## Licence

The copyright notice of RFC 4443, with the first sentence of its Full Copyright Statement:

> Copyright (C) The Internet Society (2006).
>
> This document is subject to the rights, licenses and restrictions
> contained in BCP 78, and except as set forth therein, the authors
> retain all their rights.

The copyright notice of RFC 4861, with the first sentence of its Full Copyright Statement:

> Copyright (C) The IETF Trust (2007).
>
> This document is subject to the rights, licenses and restrictions
> contained in BCP 78, and except as set forth therein, the authors
> retain all their rights.

The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover
both documents.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
