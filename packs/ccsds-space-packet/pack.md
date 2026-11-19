# Pack: ccsds-space-packet

The CCSDS Space Packet (CCSDS 133.0-B-2, Space Packet Protocol, section 4.1.3):
the 6-octet primary header that every packet on a CCSDS space link or ground
network starts with. Public. Hand-written from the Blue Book; I/O is hex text
(`spec/engine-spec.md`, bits wire). Needs engine version 0.5 (kinds,
`bit_order msb`, fields past their word).

Uses the modules `core` and `ccsdssp` (`model/ccsdssp.def`).

## Message convention

A message of this pack is a whole Space Packet: the primary header, then the
packet data field (1 to 65536 octets). Decode reads the 6 header octets and
ignores the rest of the input (engine-spec 0.5, fields that run past their
word: longer input is accepted). Encode writes the 6 header octets only; a
producer appends the data field. An input shorter than 6 octets is
`malformed-wire`. The pack does not check that the input holds
`data_length + 1` octets after the header.

## Addressing

`word_bytes 1`, `bit_order msb`. The Blue Book numbers bits from 0 at the
first transmitted bit, the most significant bit of the first octet (section
1.6), so its "bits *a*-*b*" is the locator `0:<a>:<b-a+1>`.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-2 | packet version number | `when 0:0:3 0` | `000` is the only version this standard defines; any other value is `no-kind` |
| 3 | packet type | `ccsdssp.packet_type`, and the kind | 0 telemetry, 1 telecommand |
| 4 | secondary header flag | `ccsdssp.secondary_header_flag` | |
| 5-15 | application process identifier | `ccsdssp.apid` | 2047 is an idle packet |
| 16-17 | sequence flags | `ccsdssp.sequence_flags` | 0 continuation, 1 first, 2 last, 3 unsegmented |
| 18-31 | sequence count, or packet name | `ccsdssp.sequence_count` (kind `telemetry`), `ccsdssp.sequence_count_or_name` (kind `telecommand`) | |
| 32-47 | packet data length | `ccsdssp.data_length` | octets in the data field minus one |

## Kinds

| Kind | `when` | `requires` | Why |
|---|---|---|---|
| `telemetry` | bit 3 = 0 | `ccsdssp.sequence_count` | bits 18-31 of a telemetry packet are always the sequence count (4.1.3.4.3.2) |
| `telecommand` | bit 3 = 1 | `ccsdssp.sequence_count_or_name` | in a telecommand packet the same bits are either the count or a name the mission chooses, so they are a different key |

The packet type is also a common field, so the model holds it; on encode the
kind's `when` value is written over it (0.5 ruling 5).

## Shared keys

None. The primary header has no field whose meaning is a `core` or `track`
key: no position, no time, no name. Every field is a raw key of `ccsdssp`, so
a packet converts to no other format, and an entity from another format
selects no kind (`no-kind`).

## Not mapped

| Part | Why |
|---|---|
| Packet data field: secondary header (time code, ancillary data) and user data | its length is `data_length + 1` octets and its content is defined by the mission, not by this standard (4.1.4.2.1.4). A bits pack cannot hold a byte string whose length a header field states and that no field describes; this needs "Layered wires and framing" (docs/roadmap.md, Designed): the data field as the payload of another pack, its length from `data_length` |
| Consistency of `data_length` with the input | the same addition |
| Packet version other than `000` | not a packet of this standard; `no-kind` |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-vectors.py` (standard library
only, imports no engine) from its own table of the header layout. Round trips
of a telemetry and a telecommand header, a whole packet whose data field is not
carried, an idle packet, the largest count and length, a version that is not
`000` (`no-kind`), and an input shorter than the header (`malformed-wire`).
