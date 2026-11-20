# Pack: ccsds-cfdp-pdu

A CCSDS File Delivery Protocol PDU (CCSDS 727.0-B-5, CFDP, sections 5.1 and
5.2.1): the fixed PDU header with its source entity ID, transaction sequence
number and destination entity ID, each 1 to 8 octets, and the directive code of
a file directive PDU. Public. Hand-written from the Blue Book; I/O is hex text.
Needs engine version 0.17 (gate blocks).

Uses the modules `core` and `ccsdscfdp` (`model/ccsdscfdp.def`).

## Message convention

A message of this pack is one CFDP PDU: the PDU header, then the data field
(the directive code and its parameters, or file data), whose last 2 octets are
a CRC when the CRC flag is 1 (4.1.3; the data field length counts them). Decode reads the header and, in a file directive, the directive code;
it ignores the rest. Encode writes those octets only.

## Addressing

`word_bytes 1`, `bit_order msb`; bits count from 0 at the first transmitted
bit.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-2 | version | common `when 0:0:3 1` | `001` |
| 3 | PDU type | the kind | |
| 4 | direction | `ccsdscfdp.direction` | |
| 5 | transmission mode | `ccsdscfdp.transmission_mode` | |
| 6 | CRC flag | `ccsdscfdp.crc_flag` | |
| 7 | large file flag | `ccsdscfdp.large_file_flag` | |
| 8-23 | PDU data field length | `ccsdscfdp.data_field_length` | octets |
| 24 | segmentation control | `ccsdscfdp.segmentation_control` | |
| 25-27 | length of entity IDs | `ccsdscfdp.entity_id_length` | `a`: octets minus one |
| 28 | segment metadata flag | `ccsdscfdp.segment_metadata_flag` | |
| 29-31 | length of transaction sequence number | `ccsdscfdp.tsn_length` | `b`: octets minus one |
| 32, `8(a+1)` bits | source entity ID | `ccsdscfdp.source_entity_id` | gate `if 0:25:3 a` |
| next `8(b+1)` bits | transaction sequence number | `ccsdscfdp.transaction_seq_num` | nested gate `if 0:29:3 b` |
| next `8(a+1)` bits | destination entity ID | `ccsdscfdp.dest_entity_id` | nested gate `if 0:29:3 b` |
| next 8 bits (file directive) | directive code | `ccsdscfdp.directive_code` | the same nested gates, in kind `file-directive` |

The header is `4 + 2(a+1) + (b+1)` octets, 7 to 28. The places of the three
variable fields follow from both lengths, which come before them: eight gate
blocks on `a`, each holding the source ID at its width and eight nested blocks
on `b` that place the sequence number and the destination ID (engine-spec
0.17); kind `file-directive` repeats the 64 nested blocks to place the code
octet. Because both lengths are plain fields, encode writes them first and the
blocks they select follow them. An 8-octet ID or sequence number whose top bit
is set decodes to the negative model integer with the same bits and encodes
back to them (ruling 2 of 0.5).

The data field length and the CRC are carried, not computed or checked.

## Kinds

| Kind | `when` | `requires` |
|---|---|---|
| `file-directive` | bit 3 = 0 | `ccsdscfdp.directive_code` |
| `file-data` | bit 3 = 1 | none |

The directive codes (4 EOF, 5 Finished, 6 ACK, 7 Metadata, 8 NAK, 9 Prompt, 12
Keep Alive) are not kinds: the code octet's place depends on `a` and `b`, and a
kind's `when` reads a fixed locator, evaluated before any gate. The code is a
key; a reserved code is carried (vector 05). Candidate for the language: a
`when` inside a gate block, or a kind chosen by a gated field.

## Shared keys

None.

## Not mapped

| Part | Why |
|---|---|
| Directive parameters (EOF, Finished, ACK, Metadata, NAK, Prompt, Keep Alive) | fixed per directive, but at a place that depends on `a` and `b`; each directive's fields would need its own kind (see Kinds) and its file-size fields are 32 or 64 bits by the large file flag. Metadata, Finished and NAK also hold LV and TLV lists |
| File data (segment metadata, offset, file data) | the offset is 32 or 64 bits, the segment metadata has its own length octet, and the data runs to the data field length |
| CRC (the last 2 octets of the data field) | the CCSDS telecommand CRC over the PDU; needs a checksum rule and the data field length, "Layered wires and framing" (docs/roadmap.md, Designed) |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-2-vectors.py` from its own layout
table: an EOF directive with 1-octet fields and its parameters after it, a file
data PDU with 2- and 4-octet fields, a Metadata directive with 8-octet fields
(top bits set), a Keep Alive directive with 3- and 2-octet fields, a reserved
directive code, a header cut inside its destination ID and a directive without
its code (both `malformed-wire`), and version 0 (`no-kind`).
