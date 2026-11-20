# Provenance: vxlan-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `vxlan-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 7348, Virtual eXtensible Local Area Network (VXLAN), August 2014 (Informational) | https://www.rfc-editor.org/rfc/rfc7348.txt | `731475429b30bf4b29a102a0c9217cb0d3522c34fd546ba7b134fec931e83574` | the VXLAN header, section 5 |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc7348.

## Licence

The copyright notice of RFC 7348:

> Copyright (c) 2014 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (http://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
