# Provenance: vrrpv3-ipv4 pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `vrrpv3-ipv4`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 9568, VRRP Version 3 for IPv4 and IPv6, April 2024 | https://www.rfc-editor.org/rfc/rfc9568.txt | `c67e38b76eb5993be562b200facbf7ef23eebc9c8c785829d5db65e8b6785830` | the advertisement and its address list, section 5 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc9568.

## Licence

The copyright notice of RFC 9568:

> Copyright (c) 2024 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Revised BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
