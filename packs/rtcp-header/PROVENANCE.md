# Provenance: rtcp-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `rtcp-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 3550, RTP: A Transport Protocol for Real-Time Applications, July 2003, STD 64 | https://www.rfc-editor.org/rfc/rfc3550.txt | `4c210e9434b5b4c029e8536ad8991f3709bc3cbfa0999e951bcb4c2143c539e8` | the RTCP sender and receiver report with their report blocks, the source description header, the goodbye packet and the application-defined packet, sections 6.4 to 6.7 |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc3550.

## Licence

The copyright notice of RFC 3550:

> Copyright (C) The Internet Society (2003). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
