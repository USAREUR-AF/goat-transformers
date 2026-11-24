# Pack: ccsds-uslp-frame

The CCSDS USLP Transfer Frame (CCSDS 732.1-B-3, Unified Space Data Link
Protocol, section 4.1.2 and annex D): the primary header of a version-4 frame,
non-truncated (7 to 14 octets, by the length of its VC frame count) or
truncated (4 octets). Public. Hand-written from the Blue Book; I/O is hex text.
Needs engine version 0.17 (gate blocks).

Uses the modules `core` and `ccsdsuslp` (`model/ccsdsuslp.def`).

## Message convention

A message of this pack is a whole USLP Transfer Frame (4.1.1): primary header,
then the insert zone, the data field header, the data field, the optional
operational control field and the optional frame error control field. Decode
reads the primary header and ignores the rest; encode writes the primary header
only.

## Addressing

`word_bytes 1`, `bit_order msb`; the Blue Book's "bits *a*-*b*" (bit 0 first
transmitted, most significant) is `0:<a>:<b-a+1>`.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-3 | transfer frame version number | common `when 0:0:4 12` | `1100`; a TM, TC, AOS or Proximity-1 frame is `no-kind` here |
| 4-19 | spacecraft identifier | `ccsdsuslp.spacecraft_id` | 16 bits |
| 20 | source-or-destination identifier | `ccsdsuslp.source_dest_id` | |
| 21-26 | virtual channel identifier | `ccsdsuslp.virtual_channel_id` | |
| 27-30 | MAP identifier | `ccsdsuslp.map_id` | |
| 31 | end of frame primary header flag | the kind | |
| 32-47 | frame length | `ccsdsuslp.frame_length` | octets minus one (non-truncated) |
| 48 | bypass/sequence control flag | `ccsdsuslp.bypass_flag` | |
| 49 | protocol control command flag | `ccsdsuslp.protocol_control_command_flag` | |
| 50-51 | reserve spares | `ccsdsuslp.reserve_spares` | carried, not checked |
| 52 | OCF flag | `ccsdsuslp.ocf_flag` | |
| 53-55 | VC frame count length | `ccsdsuslp.vcf_count_length` | octets, 0-7 |
| 56 on | VC frame count | `ccsdsuslp.vcf_count` | 0 to 56 bits; gate blocks `if 0:53:3 <n>`, `n` from 1 to 7 |

The count field's width depends on bits 53-55, which come before it: seven gate
blocks (engine-spec 0.17), one per length, each mapping
`ccsdsuslp.vcf_count` at `0:56:<8n>`. With a length of 0 no block holds and the
header is 7 octets. Because the length is also a plain field, encode writes it
first and the block it selects follows it (0.17, Encode, step 2); an entity
with a count but no length gets the first block (1 octet), and a count that
does not fit it is `transform-encode`. A 7-octet count is at most 2^56 - 1, so
the integer key holds every value.

## Kinds

| Kind | `when` | `requires` | Header |
|---|---|---|---|
| `non-truncated` | bit 31 = 0 | `ccsdsuslp.frame_length` | 7 to 14 octets |
| `truncated` | bit 31 = 1 | the spacecraft, source/destination, virtual channel and MAP fields | 4 octets (annex D) |

An entity with no kind encodes as `non-truncated` when it holds the frame
length, as `truncated` when it holds what that kind requires, and is
`no-kind` otherwise.

## Shared keys

None. The spacecraft and virtual channel identifiers are raw keys of this
pack's module, as in the other CCSDS frame packs: USLP gives them 16 and 6 bits,
TM 10 and 3, and a shared key would lose the high bits in a conversion
(`ccsds-tm-frame` pack.md, Shared keys).

## Not mapped

| Part | Why |
|---|---|
| Insert zone | its length is fixed per physical channel by management, not stated in the frame |
| Transfer frame data field header and data field | the header's construction rule and the data follow it; needs "Layered wires and framing" (docs/roadmap.md, Designed) |
| Operational control field (4 octets, when the OCF flag is 1) | its place is the frame length minus the trailer; `ccsds-clcw` reads a CLCW |
| Frame error control field (2 octets) | a 16-bit CRC over the frame (4.1.6), its presence fixed by management; needs a checksum rule |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-2-vectors.py` from its own layout
table: non-truncated headers with a count of 0, 1, 4 and 7 octets (the last at
the largest values), a truncated header, a TM version number (`no-kind`), a
header cut inside its count and a non-truncated header of 6 octets (both
`malformed-wire`).
