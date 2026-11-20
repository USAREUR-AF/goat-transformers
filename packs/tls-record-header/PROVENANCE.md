# Provenance: tls-record-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `tls-record-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 8446, TLS Protocol Version 1.3, August 2018 | https://www.rfc-editor.org/rfc/rfc8446.txt | `47871bc8820a2c3b6ea89f061055577058862cf543686b82d10131239702b3bd` | the record header, section 5.1; the alert and handshake message headers, sections 6 and 4 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc8446.

## Licence

The copyright notice of RFC 8446:

> Copyright (c) 2018 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Simplified BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
