# Provenance: ospfv2-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `ospfv2-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 2328, OSPF Version 2, April 1998, STD 54 | https://www.rfc-editor.org/rfc/rfc2328.txt | `981690e297fbba9e8ef655802552b5529cb17f1ffe790ad2d55706cc522ff50c` | the packet header and the fixed part of each packet type, appendix A.3 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc2328.

## Licence

The copyright notice of RFC 2328:

> Copyright (C) The Internet Society (1998). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
