# Provenance: dns-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `dns-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 1035, Domain Names - Implementation and Specification, November 1987, STD 13 | https://www.rfc-editor.org/rfc/rfc1035.txt | `d14ae809fc9b41bbcae26bb38c937c9515808b944f3252b00de9fe0e95f4fdfb` | section 4.1.1, the header section format |

The pack follows the text of the RFC; its errata are listed at
https://www.rfc-editor.org/errata/rfc1035.

## Licence

RFC 1035 predates the IETF Trust and carries no copyright notice. Its status
section says:

> Distribution of this memo is unlimited.

The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover
RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
