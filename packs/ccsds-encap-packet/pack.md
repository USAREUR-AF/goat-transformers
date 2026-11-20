# Pack: ccsds-encap-packet

The CCSDS Encapsulation Packet header (CCSDS 133.1-B-3, Encapsulation Packet
Protocol, section 4.1.2): 1, 2, 4 or 8 octets as the length of length field
says. Public. Hand-written from the Blue Book; I/O is hex text. Needs engine
version 0.5.

Uses the modules `core` and `ccsdsep` (`model/ccsdsep.def`).

## Message convention

A message of this pack is one Encapsulation Packet: header and encapsulated
data field. Decode reads the header and ignores the data field; encode writes
the header only (vector 02).

## Addressing

`word_bytes 1`, `bit_order msb`; bit 0 is the first transmitted bit.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-2 | packet version number | common `when 0:0:3 7` | `111` (version 8) |
| 3-5 | encapsulation protocol ID | `ccsdsep.protocol_id` | |
| 6-7 | length of length | the kind | |
| 8-11 (4- and 8-octet headers) | user defined field | `ccsdsep.user_defined` | |
| 12-15 (4- and 8-octet headers) | protocol ID extension | `ccsdsep.protocol_id_extension` | |
| 16-31 (8-octet header) | CCSDS defined field | `ccsdsep.ccsds_defined` | carried, not checked |
| 8-15, 16-31 or 32-63 | packet length | `ccsdsep.packet_length` | octets, header included |

## Kinds

| Kind | `when` | Header | Requires |
|---|---|---|---|
| `length-4-octets` | bits 6-7 = 11 | 8 octets | `ccsdsep.ccsds_defined` |
| `length-2-octets` | bits 6-7 = 10 | 4 octets | `ccsdsep.user_defined` |
| `length-1-octet` | bits 6-7 = 01 | 2 octets | `ccsdsep.packet_length` |
| `idle` | bits 6-7 = 00 | 1 octet | none |

Each header form has fixed field places, so each is a kind and no gate block
is needed. On encode from another format, the kinds are tried in the order
above: an entity with the CCSDS defined field gets the 8-octet header, one with
the user defined field the 4-octet header, one with a length the 2-octet
header, and any other the idle packet. The pack does not check that an idle
packet has protocol ID 0 or that the length fits the data.

## Shared keys

None.

## Not mapped

| Part | Why |
|---|---|
| Encapsulated data field | the data of the protocol the ID names, to the packet length; needs "Layered wires and framing" (docs/roadmap.md, Designed) |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-3-vectors.py` from its own layout
table: the idle packet, a 2-octet header with its data, a 4-octet header with
an extended protocol ID, an 8-octet header at its largest values, an 8-octet
header cut short (`malformed-wire`) and a Space Packet version (`no-kind`).
