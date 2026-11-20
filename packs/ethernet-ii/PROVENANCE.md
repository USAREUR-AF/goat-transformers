# Provenance: ethernet-ii pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/link-headers-vectors.py` are built from that layout and
from values chosen there; no example of a document is used.

## Pack `ethernet-ii`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 894, A Standard for the Transmission of IP Datagrams over Ethernet Networks, April 1984, STD 41 | https://www.rfc-editor.org/rfc/rfc894.txt | `be88b9301e53f986aca3a0e55e488d1d79bae3f88fe3f257640397bc089e7035` | the EtherType field and the IPv4 type |
| RFC 7042, IANA Considerations and IETF Protocol and Documentation Usage for IEEE 802 Parameters, October 2013, BCP 141 | https://www.rfc-editor.org/rfc/rfc7042.txt | `8ad7b042253d1204cef2a5eddd6682072a5d4f9edc3b749df15df7bccdeca1df` | the MAC-48 addresses, the EtherType range and the C-tag EtherType 0x8100 |
| RFC 7348, Virtual eXtensible Local Area Network (VXLAN), August 2014 | https://www.rfc-editor.org/rfc/rfc7348.txt | `731475429b30bf4b29a102a0c9217cb0d3522c34fd546ba7b134fec931e83574` | the order of the header fields and the 16 bits of tag information after a C-tag |

## Licence

RFC 894 predates the IETF Trust and carries no copyright notice or licence statement. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The copyright notice of RFC 7042:

> Copyright (c) 2013 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (http://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Simplified BSD License text. No code component is extracted here.

The copyright notice of RFC 7348:

> Copyright (c) 2014 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (http://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Simplified BSD License text. No code component is extracted here.

RFC 6325 restates the inner layout of the tag information, but carries the
notice that material from before 10 November 2008 in it may not be modified or
used for derivative works outside the IETF Standards Process; it is not used
here (pack.md, Not mapped).

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of a document is copied.
