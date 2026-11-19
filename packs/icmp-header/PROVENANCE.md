# Provenance: icmp-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `icmp-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 792, Internet Control Message Protocol, September 1981, STD 5 | https://www.rfc-editor.org/rfc/rfc792.txt | `58714393ded142bacf188d7e8977eef98f4110c4c87ac94595f750df5664c2c6` | the message formats of every type it defines |

The pack follows the text of the RFC; its errata are listed at
https://www.rfc-editor.org/errata/rfc792.

## Licence

RFC 792 predates the IETF Trust and carries no copyright notice or licence
statement. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info)
cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
