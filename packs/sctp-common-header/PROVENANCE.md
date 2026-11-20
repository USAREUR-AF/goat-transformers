# Provenance: sctp-common-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `sctp-common-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 9260, Stream Control Transmission Protocol, June 2022 | https://www.rfc-editor.org/rfc/rfc9260.txt | `04bdd3255e9e5ddf1e401e9d5d726ec2750e5269cb52485db3f7f4fe77500354` | the SCTP common header, section 3.1, and the meaning of its port fields |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc9260.

## Licence

The copyright notice of RFC 9260:

> Copyright (c) 2022 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Revised BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
