# Provenance: ipv6-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `ipv6-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 8200, Internet Protocol, Version 6 (IPv6) Specification, July 2017, STD 86 | https://www.rfc-editor.org/rfc/rfc8200.txt | `371ae3f133d562db5d6385e6def4ca9914c4f831be228ea7779fd28799c2f490` | section 3, the IPv6 header format |

The pack follows the text of the RFC; its errata are listed at
https://www.rfc-editor.org/errata/rfc8200.

## Licence

The copyright notice of RFC 8200:

> Copyright (c) 2017 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on
> the date of publication of this document.

The notice goes on to say that code components extracted from the document must
carry the Simplified BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
