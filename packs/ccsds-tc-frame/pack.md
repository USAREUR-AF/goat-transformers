# Pack: ccsds-tc-frame

The CCSDS TC Transfer Frame (CCSDS 232.0-B-4 with Technical Corrigendum 1, TC
Space Data Link Protocol, section 4.1.2): the 5-octet primary header of a
telecommand frame. Public. Hand-written from the Blue Book; I/O is hex text.
Needs engine version 0.5.

Uses the modules `core` and `ccsdstc` (`model/ccsdstc.def`).

## Message convention

A message of this pack is a whole TC Transfer Frame: the header, the data
field (up to 1019 octets) and an optional 2-octet frame error control field.
Decode reads the 5 header octets and ignores the rest; encode writes the 5
header octets only. The pack does not check the input length against
`frame_length + 1`.

## Addressing

`word_bytes 1`, `bit_order msb`; "bits *a*-*b*" is `0:<a>:<b-a+1>`.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-1 | transfer frame version number | `when 0:0:2 0` | `00`; other values are `no-kind` |
| 2 | bypass flag | `ccsdstc.bypass_flag` | 0 type-A, 1 type-B |
| 3 | control command flag | `ccsdstc.control_command_flag` | 0 type-D, 1 type-C |
| 4-5 | reserved spare | not mapped | decode ignores it, encode writes `00` as 4.1.2.4.2 requires |
| 6-15 | spacecraft identifier | `ccsdstc.spacecraft_id` | |
| 16-21 | virtual channel identifier | `ccsdstc.virtual_channel_id` | |
| 22-31 | frame length | `ccsdstc.frame_length` | octets in the whole frame minus one |
| 32-39 | frame sequence number | `ccsdstc.frame_sequence_number` | |

The pack has one kind, `frame`, with no `when` and no `requires`: a `kind` is
needed for the common `when` on the version number (0.5 ruling 8). The two
flags together name the frame type (type-AD 0/0, type-BD 1/0, type-BC 1/1;
0/1 is reserved). They are fields, not kinds: the layout is the same for all
four, and a kind per combination would force the flags on an entity that has
no kind.

## Shared keys

None (see `ccsds-tm-frame/pack.md`, Shared keys, for why the identifiers are
raw keys of each frame's own module).

## Not mapped

| Part | Why |
|---|---|
| Transfer frame data field (segment header and frame data unit, or control commands) | its length is `frame_length + 1` minus the header and the optional error control field, and whether that field is present is set by management, not stated in the frame; needs "Layered wires and framing" (docs/roadmap.md, Designed) |
| Frame error control field | a CRC; the same addition, with a checksum rule |
| Reserved spare (bits 4-5) | reserved; written as `00` |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-vectors.py` from its own layout
table: a type-AD header round trip, a type-BC header at the largest values, a
whole 27-octet frame whose data field and error control are not carried, spare
bits set on input and written as `00`, a version that is not `00` (`no-kind`),
and a cut header (`malformed-wire`).
