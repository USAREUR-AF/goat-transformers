# Pack: gre-header

The GRE header, as IETF RFC 2784 lays it out with the key and sequence number
of RFC 2890: four octets, then the checksum word when the C bit is 1, the key
when K is 1 and the sequence number when S is 1. Public. Written by hand from
the RFCs; the layout is stated in this repository's words. I/O is hex text.
Needs engine version 0.8 (sequential layout with presence).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the GRE packet. The pack reads 4 to 16 octets; the payload is
read over and not written (vector 08).

| Bits | Field | Key | Line |
|---|---|---|---|
| 0 | C, checksum present | | `presence c 1` |
| 1 | routing present in RFC 1701, reserved in RFC 2784 | `inet.gre_bit1` | `field … 1 uint` |
| 2 | K, key present | | `presence ks 2`, bit 1 |
| 3 | S, sequence number present | | `presence ks 2`, bit 2 |
| 4-12 | reserved | `inet.gre_reserved0` | `field … 9 uint` |
| 13-15 | version | `inet.gre_version` | `field … 3 uint` |
| 16-31 | protocol type (EtherType of the payload) | `inet.gre_protocol_type` | `field … 16 uint` |
| when C: 16 bits | checksum | `inet.gre_checksum` | `if c.1` |
| when C: 16 bits | reserved | `inet.gre_reserved1` | `if c.1` |
| when K: 32 bits | key | `inet.gre_key` | `if ks.1` |
| when S: 32 bits | sequence number | `inet.gre_sequence` | `if ks.2` |

`layout sequential`, `bit_order msb`; the fields are big-endian. The order of
the optional words is that of RFC 2890 section 2.

A presence bit is not a key. On encode C is 1 when the entity has
`inet.gre_checksum` or `inet.gre_reserved1`, K when it has `inet.gre_key`, S
when it has `inet.gre_sequence`; a checksum of 0 that is present keeps C set
(vector 05). Bit 1 is a plain field, not a presence bit: a presence bit that is
1 with no block naming it is `malformed-wire` (ruling 1 of 0.8),
and RFC 2784 has no field behind this bit. The routing field of RFC
1701 is not read.

The checksum is carried, not computed or checked.

## Shared keys

None.

## Not mapped, and why

- The RFC 1701 routing field (bit 1 set): RFC 2784 drops it, and a receiver
  that does not implement RFC 1701 discards such a packet.
- The payload.
- Version 1 (the enhanced GRE header of RFC 2637): another layout; it decodes
  here with version 1 and the RFC 2784 fields.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: the base
header, key only, sequence only, checksum with key and sequence, a checksum of
0, reserved and version bits all set, bit 1 set, a header followed by payload,
a K header cut before its key and 3 octets (both `malformed-wire`).
