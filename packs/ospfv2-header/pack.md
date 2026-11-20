# Pack: ospfv2-header

An OSPFv2 packet, as IETF RFC 2328 appendix A.3 lays it out: the 24-octet
header and the fixed part of each of the five packet types. Public. Written by
hand from the RFC; the layout is stated in this repository's words. I/O is hex
text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the IP payload of an OSPF packet (IP protocol 89). Octets after
the mapped part are read over and not written.

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | version | `inet.ospf_version` | `uint` |
| 1 | type | the `when` of the kinds | |
| 2-3 | packet length | `inet.ospf_packet_length` | `uint` |
| 4-7 | router ID | `inet.ospf_router_id` | `uint` |
| 8-11 | area ID | `inet.ospf_area_id` | `uint` |
| 12-13 | checksum | `inet.ospf_checksum` | `uint` |
| 14-15 | authentication type | `inet.ospf_autype` | `uint` |
| 16-19 | authentication, first half | `inet.ospf_auth_hi` | `uint` |
| 20-23 | authentication, second half | `inet.ospf_auth_lo` | `uint` |

| Kind | `when` | Octets 24 on | Keys |
|---|---|---|---|
| `hello` | type 1 | 24-27 network mask, 28-29 hello interval, 30 options, 31 router priority, 32-35 router dead interval, 36-39 designated router, 40-43 backup designated router | `inet.ospf_network_mask`, `inet.ospf_hello_interval`, `inet.ospf_options`, `inet.ospf_router_priority`, `inet.ospf_router_dead_interval`, `inet.ospf_dr`, `inet.ospf_bdr` |
| `database-description` | type 2 | 24-25 interface MTU, 26 options, 27 bits 0-4 reserved, bit 5 I, bit 6 M, bit 7 MS, 28-31 DD sequence number | `inet.ospf_interface_mtu`, `inet.ospf_options`, `inet.ospf_dd_reserved`, `inet.ospf_dd_init`, `inet.ospf_dd_more`, `inet.ospf_dd_master`, `inet.ospf_dd_sequence` |
| `link-state-update` | type 4 | 24-27 number of LSAs | `inet.ospf_lsa_count` |
| `link-state-request` | type 3 | none | |
| `link-state-ack` | type 5 | none | |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The 64-bit
authentication field is two 32-bit keys: a key holds a signed 64-bit integer,
which a field with its top bit set would overflow. The checksum and the packet
length are carried, not computed or checked. Addresses and IDs are 32-bit
integers.

## Shared keys

None.

## Not mapped, and why

- Hello neighbors, request entries and LSA headers: lists whose number is the
  packet length less the fixed part, divided by the item size. The pack
  language counts a group by a field, not by a computed number.
- LSAs in a Link State Update: their count is on the wire, but each LSA has its
  own length and layout by type.
- Cryptographic authentication data appended after the packet (type 2).

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there, with lengths
and checksums computed there: a Hello with one neighbor, a Hello with a simple
password, a first Database Description, a Link State Update with one LSA, a
Link State Request with one entry, an empty Link State Acknowledgment, type 6
(`no-kind`) and a Hello cut short (`malformed-wire`).
