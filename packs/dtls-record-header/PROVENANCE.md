# Provenance: dtls-record-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `dtls-record-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 9147, DTLS Protocol Version 1.3, April 2022 | https://www.rfc-editor.org/rfc/rfc9147.txt | `04e2142333923e36268eb565ec44bdda4db06390114897b819c2f022cb351ebe` | the plaintext record header and the unified header, section 4 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc9147.

## Licence

The copyright notice of RFC 9147:

> Copyright (c) 2022 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Revised BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
