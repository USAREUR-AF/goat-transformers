# Provenance: gre-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `gre-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 2784, Generic Routing Encapsulation (GRE), March 2000 | https://www.rfc-editor.org/rfc/rfc2784.txt | `dad757f9b5eb51478e768295eb39df4b54c1f299eeb6e5c7bea080eb45556d58` | the GRE header and its checksum word |
| RFC 2890, Key and Sequence Number Extensions to GRE, September 2000 | https://www.rfc-editor.org/rfc/rfc2890.txt | `96bdafc03219df215342d9b9d127ba87d7aaf2f2130797035ac3c17f07115455` | the K and S bits, the key and the sequence number |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc2784, https://www.rfc-editor.org/errata/rfc2890.

## Licence

The copyright notice of RFC 2784:

> Copyright (C) The Internet Society (2000). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The copyright notice of RFC 2890:

> Copyright (C) The Internet Society (2000). All Rights Reserved.

Its Full Copyright Statement permits derivative works that explain the document or assist in its implementation. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
