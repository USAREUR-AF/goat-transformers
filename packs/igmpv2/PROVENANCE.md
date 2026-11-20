# Provenance: igmpv2 pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `igmpv2`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 2236, Internet Group Management Protocol, Version 2, November 1997 | https://www.rfc-editor.org/rfc/rfc2236.txt | `0c8fc75ffb7251cad7452b31b43333ccbc3a53e0541069c47c571933fca46862` | the IGMPv2 message, section 2 |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc2236.

## Licence

The copyright notice of RFC 2236:

> Copyright (C) The Internet Society (1997). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
