# Pack: ccsds-aos-frame

The CCSDS AOS Transfer Frame (CCSDS 732.0-B-4, AOS Space Data Link Protocol,
section 4.1.2): the 6-octet primary header of an Advanced Orbiting Systems
frame. Public. Hand-written from the Blue Book; I/O is hex text. Needs engine
version 0.5.

Uses the modules `core` and `ccsdsaos` (`model/ccsdsaos.def`).

## Message convention

A message of this pack is a whole AOS Transfer Frame: primary header, optional
frame header error control, optional insert zone, data field, optional
operational control field and frame error control field. Decode reads the 6
header octets and ignores the rest; encode writes the 6 header octets only.

## Addressing

`word_bytes 1`, `bit_order msb`; "bits *a*-*b*" is `0:<a>:<b-a+1>`.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-1 | transfer frame version number | `when 0:0:2 1` | `01` (version 2); `00` (TM, TC) is `no-kind` |
| 2-9 | spacecraft identifier | `ccsdsaos.spacecraft_id` | |
| 10-15 | virtual channel identifier | `ccsdsaos.virtual_channel_id` | 63 only idle data |
| 16-39 | virtual channel frame count | `ccsdsaos.vc_frame_count` | |
| 40 | replay flag | `ccsdsaos.replay_flag` | |
| 41 | VC frame count cycle use flag | `ccsdsaos.vc_count_cycle_use_flag` | |
| 42-43 | reserved spare | not mapped | written as `00` (4.1.2.5.4.2) |
| 44-47 | VC frame count cycle | `ccsdsaos.vc_count_cycle` | |

One kind, `frame`, with no `when` and no `requires`, so that the version
number is checked (0.5 ruling 8).

## Shared keys

None (see `ccsds-tm-frame/pack.md`, Shared keys).

## Not mapped

| Part | Why |
|---|---|
| Frame header error control (bits 48-63, optional) | its presence is set by management, not signalled in the frame (4.1.2.6.2), and it is a Reed-Solomon code the pack cannot compute; a pack for a mission that uses it can map it as a further field |
| Insert zone, data field (M_PDU, B_PDU or VCA_SDU), operational control field, frame error control field | lengths fixed by management, content of other protocols; needs "Layered wires and framing" (docs/roadmap.md, Designed) |
| Reserved spare (bits 42-43) | reserved; written as `00` |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-vectors.py` from its own layout
table: a header round trip, an idle virtual channel at the largest values, a
whole frame with header error control whose other parts are not carried, spare
bits set on input and written as `00`, a version `00` frame (`no-kind`), and a
cut header (`malformed-wire`).
