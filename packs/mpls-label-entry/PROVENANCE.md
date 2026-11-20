# Provenance: mpls-label-entry pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `mpls-label-entry`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 3032, MPLS Label Stack Encoding, January 2001 | https://www.rfc-editor.org/rfc/rfc3032.txt | `c611103bf720c643a40e128159aabb1607eab97977d0f3483d468a620cd86180` | the label stack entry, section 2.1 |
| RFC 5462, MPLS Label Stack Entry: EXP Field Renamed to Traffic Class Field, February 2009 | https://www.rfc-editor.org/rfc/rfc5462.txt | `4e6154ec58f83fa5a7c1a14584ad87804fecc69092ea8e87b57027bf9246cc58` | the name of the 3-bit field (traffic class) |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc3032, https://www.rfc-editor.org/errata/rfc5462.

## Licence

The copyright notice of RFC 3032:

> Copyright (C) The Internet Society (2001). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The copyright notice of RFC 5462:

> Copyright (c) 2009 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (http://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
