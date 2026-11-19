# Provenance: ntp-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `ntp-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 5905, Network Time Protocol Version 4: Protocol and Algorithms Specification, June 2010, Standards Track | https://www.rfc-editor.org/rfc/rfc5905.txt | `8b7abd903c60202e2953ee012fefa6916666c3b0c71825c748cdd262024fb268` | sections 6 (formats) and 7.3 (packet header variables) |

The pack follows the text of the RFC; its errata are listed at
https://www.rfc-editor.org/errata/rfc5905.

## Licence

The copyright notice of RFC 5905:

> Copyright (c) 2010 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on
> the date of publication of this document.

The notice goes on to say that code components extracted from the document must
carry the Simplified BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
