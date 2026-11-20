# Provenance: arp-ipv4-ethernet pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-2-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `arp-ipv4-ethernet`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 826, An Ethernet Address Resolution Protocol, November 1982, STD 37 | https://www.rfc-editor.org/rfc/rfc826.txt | `01bc62fe6a37e90f1246ac43e8e145f1322b4ed1474836145c3da93d2bd3c8a6` | the ARP packet, its opcodes and the Ethernet hardware type |
| RFC 894, A Standard for the Transmission of IP Datagrams over Ethernet Networks, April 1984, STD 41 | https://www.rfc-editor.org/rfc/rfc894.txt | `be88b9301e53f986aca3a0e55e488d1d79bae3f88fe3f257640397bc089e7035` | the type value of IPv4 on Ethernet (0x0800) |

The pack follows the text of the RFCs; their errata are listed at
https://www.rfc-editor.org/errata/rfc826, https://www.rfc-editor.org/errata/rfc894.

## Licence

RFC 826 predates the IETF Trust and carries no copyright notice or licence statement. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

RFC 894 predates the IETF Trust and carries no copyright notice or licence statement. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover RFCs published before 10 November 2008 as well.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
