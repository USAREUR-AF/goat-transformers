# Provenance: ripv2-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `ripv2-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 2453, RIP Version 2, November 1998, STD 56 | https://www.rfc-editor.org/rfc/rfc2453.txt | `0ea7c77b8883220c13003fe0cc31ee628478864dac5919aada0497bd9e9e2127` | the message header, sections 3.6 and 4 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc2453.

## Licence

The copyright notice of RFC 2453:

> Copyright (C) The Internet Society (1998). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
