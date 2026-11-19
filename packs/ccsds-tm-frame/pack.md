# Pack: ccsds-tm-frame

The CCSDS TM Transfer Frame (CCSDS 132.0-B-3, TM Space Data Link Protocol,
sections 4.1.2 and 4.1.3.2): the 6-octet primary header of a telemetry frame,
and the identification octet of the secondary header when the frame has one.
Public. Hand-written from the Blue Book; I/O is hex text. Needs engine version
0.5.

Uses the modules `core` and `ccsdstm` (`model/ccsdstm.def`).

## Message convention

A message of this pack is a whole TM Transfer Frame (4.1.1.1): primary header,
optional secondary header, data field, optional operational control field,
optional frame error control field. The frame length is fixed per mission
phase and is not stated in the frame. Decode reads the mapped octets (6, or 7
with a secondary header) and ignores the rest; encode writes the mapped octets
only. A frame whose secondary header flag is 1 and that ends after 6 octets is
`malformed-wire`.

## Addressing

`word_bytes 1`, `bit_order msb`; the Blue Book's "bits *a*-*b*" (bit 0 first
transmitted, most significant) is `0:<a>:<b-a+1>`.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0-1 | transfer frame version number | `when 0:0:2 0` | `00`; `01` is an AOS frame (`ccsds-aos-frame`) and is `no-kind` here |
| 2-11 | spacecraft identifier | `ccsdstm.spacecraft_id` | |
| 12-14 | virtual channel identifier | `ccsdstm.virtual_channel_id` | |
| 15 | operational control field flag | `ccsdstm.ocf_flag` | |
| 16-23 | master channel frame count | `ccsdstm.mc_frame_count` | |
| 24-31 | virtual channel frame count | `ccsdstm.vc_frame_count` | |
| 32 | secondary header flag | `ccsdstm.secondary_header_flag`, and the kind | |
| 33 | synchronization flag | `ccsdstm.sync_flag` | |
| 34 | packet order flag | `ccsdstm.packet_order_flag` | |
| 35-36 | segment length identifier | `ccsdstm.segment_length_id` | |
| 37-47 | first header pointer | `ccsdstm.first_header_pointer` | 2047 no packet starts, 2046 only idle data |
| 48-49 | secondary header version (kind `with-secondary-header`) | `ccsdstm.secondary_header_version` | |
| 50-55 | length of the secondary header (kind `with-secondary-header`) | `ccsdstm.secondary_header_length` | octets minus one |

## Kinds

| Kind | `when` | `requires` |
|---|---|---|
| `with-secondary-header` | bit 32 = 1 | `ccsdstm.secondary_header_length` |
| `primary-header` | bit 32 = 0 | none |

An entity with no kind encodes as `with-secondary-header` when it holds the
length of the secondary header and as `primary-header` otherwise.

## Shared keys

None. No field of the header means what a `core` or `track` key means. The
spacecraft and virtual channel identifiers are raw keys of this pack's module,
not shared with `ccsds-aos-frame` or `ccsds-tc-frame`: the three frames give
them different widths (10, 8 and 10 bits for the spacecraft; 3, 6 and 6 for
the channel), and `uint` encode keeps the low bits of a value that does not
fit, so a shared key would corrupt values in a conversion between them.

## Not mapped

| Part | Why |
|---|---|
| Secondary header data field (up to 63 octets) | mission-defined content whose length the identification octet states; needs "Layered wires and framing" (docs/roadmap.md, Designed) |
| Transfer frame data field | packets or a VCA_SDU, located by the first header pointer and the frame length the mission fixes; the same addition |
| Operational control field (4 octets) | its place is the frame length minus the trailer, which the frame does not state. When it holds a CLCW, `ccsds-clcw` reads those 4 octets |
| Frame error control field (2 octets) | a CRC over the frame; needs a checksum rule (same roadmap row) and the frame length |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-vectors.py` from its own layout
table: round trips with and without a secondary header, a whole frame whose
data field and trailer are not carried, the largest values with the "no packet
starts" pointer, an only-idle-data frame, a frame with sync flag 1 whose
undefined fields are carried as they are, an AOS version number (`no-kind`), a
secondary header flag with no secondary header (`malformed-wire`) and a cut
header (`malformed-wire`).
