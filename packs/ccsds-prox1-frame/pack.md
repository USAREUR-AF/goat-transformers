# Pack: ccsds-prox1-frame

The CCSDS Proximity-1 Version-3 Transfer Frame (CCSDS 211.0-B-6, Proximity-1
Space Link Protocol, Data Link Layer, section 3.2.2): the 5-octet transfer
frame header. Public. Hand-written from the Blue Book; I/O is hex text. Needs
engine version 0.5.

Uses the modules `core` and `ccsdsprox1` (`model/ccsdsprox1.def`).

## Message convention

A message of this pack is a whole Proximity-1 Transfer Frame: header and data
field. Decode reads the 5-octet header and ignores the data field; encode
writes the header only. The frame's attached synchronization marker and CRC
belong to the coding sublayer (the PLTU), not to the frame.

## Addressing

`word_bytes 1`, `bit_order msb`; the Blue Book's "bits *a*-*b*" is
`0:<a>:<b-a+1>`.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-1 | transfer frame version number | common `when 0:0:2 2` | `10`; a TM frame is `no-kind` here |
| 2 | quality of service indicator | `ccsdsprox1.qos_indicator` | |
| 3 | PDU type ID | the kind | |
| 4-5 | data field construction ID | `ccsdsprox1.dfc_id` | `00` in a P-frame |
| 6-15 | spacecraft identifier | `ccsdsprox1.spacecraft_id` | |
| 16 | physical channel identifier | `ccsdsprox1.physical_channel_id` | |
| 17-19 | port identifier | `ccsdsprox1.port_id` | `0` in a P-frame |
| 20 | source-or-destination identifier | `ccsdsprox1.source_dest_id` | |
| 21-31 | frame length | `ccsdsprox1.frame_length` | octets minus one |
| 32-39 | frame sequence number | `ccsdsprox1.frame_seq_number` | |

The pack carries the DFC ID and port ID of a P-frame as they are; it does not
check that they are 0.

## Kinds

| Kind | `when` | Frame |
|---|---|---|
| `u-frame` | bit 3 = 0 | user data |
| `p-frame` | bit 3 = 1 | supervisory protocol data units |

An entity with no kind encodes as `u-frame`.

## Shared keys

None, for the reason given in `ccsds-tm-frame` pack.md: the spacecraft ID here
is 10 bits, as in TM, but the frames are of different protocols and the keys of
each module stay apart.

## Not mapped

| Part | Why |
|---|---|
| Transfer frame data field | packets, segments or user data by the DFC ID, or SPDUs in a P-frame; needs "Layered wires and framing" (docs/roadmap.md, Designed) |
| SPDUs of a P-frame | each has its own header and length; the same addition |
| PLTU (attached synchronization marker and CRC-32) | the coding sublayer wraps the frame; a checksum rule is needed |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-2-vectors.py` from its own layout
table: a U-frame of packets with its data, an expedited P-frame, a U-frame at
the largest values, a TM version number (`no-kind`) and 4 octets
(`malformed-wire`).
