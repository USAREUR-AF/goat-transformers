# Provenance: bfd-control pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `bfd-control`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 5880, Bidirectional Forwarding Detection (BFD), June 2010 | https://www.rfc-editor.org/rfc/rfc5880.txt | `45a7f8fcc04991c22d9efb1419aee4d9870cf1b7aa4b16a930e66a248146c61d` | the mandatory section of the control packet, section 4.1 |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc5880.

## Licence

The copyright notice of RFC 5880:

> Copyright (c) 2010 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (http://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Simplified BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
