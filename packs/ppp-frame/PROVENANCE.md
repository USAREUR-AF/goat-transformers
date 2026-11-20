# Provenance: ppp-frame pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/link-headers-vectors.py` are built from that layout and
from values chosen there; no example of a document is used.

## Pack `ppp-frame`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 1661, The Point-to-Point Protocol (PPP), July 1994, STD 51 | https://www.rfc-editor.org/rfc/rfc1661.txt | `23f061fcdccf43f3016d3e896213f3f887ff07caa4d408e9125ce55cbdb1434b` | the protocol field and its value rules |
| RFC 1662, PPP in HDLC-like Framing, July 1994, STD 51 | https://www.rfc-editor.org/rfc/rfc1662.txt | `97fc11c5117461af5bdb8f3076f8d2e4d52c81935ab144cd4f50cb41e3aef2c1` | the address and control fields and their compression |

## Licence

RFC 1661 predates the IETF Trust and carries no copyright notice or licence statement. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

RFC 1662 predates the IETF Trust and carries no copyright notice or licence statement. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of a document is copied.
