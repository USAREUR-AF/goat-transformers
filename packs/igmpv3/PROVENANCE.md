# Provenance: igmpv3 pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `igmpv3`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 3376, Internet Group Management Protocol, Version 3, October 2002 | https://www.rfc-editor.org/rfc/rfc3376.txt | `0f28032de6034da1e13d85f2a34ff9f2956c0e7bb9ad9dd3be84c7ddcde780ed` | the version 3 query and report, sections 4.1 and 4.2 |

The pack follows the text of the RFC; its errata are listed at
https://www.rfc-editor.org/errata/rfc3376.

## Licence

The copyright notice of RFC 3376:

> Copyright (C) The Internet Society (2002). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
