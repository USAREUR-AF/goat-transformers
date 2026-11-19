# Provenance: ipv4-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `ipv4-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 791, Internet Protocol, DARPA Internet Program Protocol Specification, September 1981, STD 5 | https://www.rfc-editor.org/rfc/rfc791.txt | `6cfb387fcecfc1b72f2f69343c5b6951b5d263d708162e2b5c66ab8f394f6265` | section 3.1, the internet header format |
| RFC 8200, Internet Protocol, Version 6 (IPv6) Specification, July 2017, STD 86 | https://www.rfc-editor.org/rfc/rfc8200.txt | `371ae3f133d562db5d6385e6def4ca9914c4f831be228ea7779fd28799c2f490` | the meaning of the next header field, shared key `inet.ip_protocol` |

The pack follows the text of the RFC; its errata are listed at
https://www.rfc-editor.org/errata/rfc791.

## Licence

RFC 791 predates the IETF Trust and carries no copyright notice or licence
statement. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info)
cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
