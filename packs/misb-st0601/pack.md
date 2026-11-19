# Pack: misb-st0601

The UAS Datalink Local Set of MISB ST 0601.19: the metadata packet that an
unmanned aircraft sends with its motion imagery. Public. Written from the
document only (PROVENANCE.md). I/O is hex text (`spec/engine-spec.md`, Version
0.13, the `tlv` wire). Needs engine version 0.13.

Uses the modules `core`, `track` and `misb0601` (`model/misb0601.def`).

## Message convention

A message of this pack is one UAS Datalink packet:

1. the 16-byte Universal Label key of the Local Set,
   `06 0E 2B 34 02 0B 01 01 0E 01 03 01 01 00 00 00` (`key`);
2. the length of the rest of the packet, BER short or long form (`length ber`);
3. the items, each a tag written as a BER object identifier (one byte for tags
   1 to 127, more above), a BER length and the value (`tag ber-oid`);
4. last, the checksum item: tag 1, length 2, two value bytes (`checksum sum16 1`).

The checksum is a 16-bit sum over the packet from the first byte of the key up
to and including the length byte of the checksum item. Bytes at even offsets
from the start of the key are added as the high byte of a 16-bit word, bytes
at odd offsets as the low byte, and the sum is kept modulo 65536. This is the
wire's `sum16` as the specification states it; a packet whose checksum
differs is `malformed-wire`, which matches the document's rule that such a
packet is discarded.

Encode writes the items in `field`-line order: item 2 (Precision Time Stamp)
first, as the document requires, then the other mapped items by tag, then any
residue, then the checksum. When the entity has no `misb0601.ls_version`, item
65 is written as 19, the version of the document this pack was written from;
the document requires item 65 in every packet.

## Mapping

Scales are the document's mapping of each item: the value range over the
integer range, written as a fraction (`spec/engine-spec.md`, ruling 1 of 0.5).
Sizes `:<n>` are the document's required length of each item.

### Shared keys, with evidence

| Item | Model key | Transform | Evidence in ST 0601.19 |
|---|---|---|---|
| 13 Sensor Latitude | `lat` | `sscale:180/4294967294`, 4 bytes | Item 13 summary: degrees; a 4-byte two's-complement integer from -(2^31-1) to 2^31-1 maps to -90..90; the note under the table says it is based on the WGS84 ellipsoid. Same meaning and unit as `core.lat` (degrees, WGS84). |
| 14 Sensor Longitude | `lon` | `sscale:360/4294967294`, 4 bytes | Item 14 summary: degrees; the same integer range maps to -180..180; based on the WGS84 ellipsoid. |
| 75 Sensor Ellipsoid Height | `hae` | `uscale:19900/65535:-900`, 2 bytes | Item 75 summary and 8.75.1: meters, the vertical distance between the sensor and the WGS84 reference ellipsoid; 0..65535 maps to -900..19000. Same as `core.hae` (meters above the WGS84 ellipsoid). |
| 56 Platform Ground Speed | `speed_ms` | `uscale:1`, 1 byte | Item 56 summary and 8.56.1: meters per second, 0..255, the aircraft's speed projected onto the ground. `core.speed_ms` is ground speed in m/s. `uscale:1` is used because the key is a float. |
| 59 Platform Call Sign | `callsign` | `utf8` | Item 59 summary: free text, the call sign of the platform or of its operating unit. `core.callsign` is a human-readable name. A reviewer may prefer a raw key because the document allows the unit's call sign as well as the platform's. |
| 79 Sensor North Velocity | `track.vel_north_ms` | `sscale:654/65534`, 2 bytes | Item 79 summary: meters per second, positive toward true north; -(2^15-1)..2^15-1 maps to -327..327. |
| 80 Sensor East Velocity | `track.vel_east_ms` | `sscale:654/65534`, 2 bytes | Item 80 summary: meters per second, positive toward east; same mapping as item 79. |

Section 7.2.1 names items 13, 14 and 75 as the location of the sensor, and
items 79 and 80 give the velocity "of the sensor or platform". The sensor is
carried by the aircraft (section 1: the Local Set is produced on board), so
these are read as the position and velocity of the reported entity, the
aircraft. With items 79 and 80, `convert` derives
`course` and `speed_ms` where the target needs them and the entity lacks them
(`model/track.def`, derived keys); item 56, when present, is the decoded
`speed_ms` and is not replaced.

### Raw keys of `misb0601`

| Item | Key | Transform | Note |
|---|---|---|---|
| 2 Precision Time Stamp | `precision_time_us` | `uint`, 8 bytes | microseconds since 1970-01-01, unsigned 64-bit; see "Not mapped" for `time_ms` |
| 3 Mission ID | `mission_id` | `utf8` | free text |
| 4 Platform Tail Number | `platform_tail_number` | `utf8` | free text |
| 5 Platform Heading Angle | `platform_heading` | `uscale:360/65535`, 2 bytes | true heading of the airframe, not direction of travel, so not `course` |
| 6 Platform Pitch Angle | `platform_pitch` | `sscale:40/65534`, 2 bytes | range-restricted to plus or minus 20 degrees |
| 7 Platform Roll Angle | `platform_roll` | `sscale:100/65534`, 2 bytes | range-restricted to plus or minus 50 degrees |
| 8 Platform True Airspeed | `platform_true_airspeed` | `uint`, 1 byte | m/s through the air mass, not ground speed |
| 9 Platform Indicated Airspeed | `platform_indicated_airspeed` | `uint`, 1 byte | m/s |
| 10 Platform Designation | `platform_designation` | `utf8` | free text |
| 11 Image Source Sensor | `image_source_sensor` | `utf8` | free text |
| 12 Image Coordinate System | `image_coordinate_system` | `utf8` | free text |
| 15 Sensor True Altitude | `sensor_true_altitude` | `uscale:19900/65535:-900`, 2 bytes | above mean sea level, so not `hae` |
| 16 Sensor Horizontal Field of View | `sensor_hfov` | `uscale:180/65535`, 2 bytes | |
| 17 Sensor Vertical Field of View | `sensor_vfov` | `uscale:180/65535`, 2 bytes | |
| 18 Sensor Relative Azimuth Angle | `sensor_rel_azimuth` | `uscale:360/4294967295`, 4 bytes | |
| 19 Sensor Relative Elevation Angle | `sensor_rel_elevation` | `sscale:360/4294967294`, 4 bytes | |
| 20 Sensor Relative Roll Angle | `sensor_rel_roll` | `uscale:360/4294967295`, 4 bytes | |
| 21 Slant Range | `slant_range` | `uscale:5000000/4294967295`, 4 bytes | meters |
| 22 Target Width | `target_width` | `uscale:10000/65535`, 2 bytes | meters |
| 23 Frame Center Latitude | `frame_center_lat` | `sscale:180/4294967294`, 4 bytes | a point on the ground, not the entity, so not `lat` |
| 24 Frame Center Longitude | `frame_center_lon` | `sscale:360/4294967294`, 4 bytes | as item 23 |
| 25 Frame Center Elevation | `frame_center_elevation` | `uscale:19900/65535:-900`, 2 bytes | above mean sea level |
| 65 UAS Datalink LS Version Number | `ls_version` | `uint`, 1 byte | default 19 on encode |
| 78 Frame Center Ellipsoid Height (HAE) | `frame_center_hae` | `uscale:19900/65535:-900`, 2 bytes | WGS84 ellipsoid height of the frame center, not of the entity |
| 90 Platform Pitch Angle (Full) | `platform_pitch_full` | `sscale:180/4294967294`, 4 bytes | plus or minus 90 degrees |
| 91 Platform Roll Angle (Full) | `platform_roll_full` | `sscale:180/4294967294`, 4 bytes | plus or minus 90 degrees |

Item 5 is stated in the document as a 2-byte unsigned integer; its formula
names the integer "KLVint", but the format column, the range 0..2^16-1 and the
mapping note are unsigned, so the pack uses `uscale`.

## Not mapped, and why

- **`time_ms` from item 2.** Item 2 counts microseconds, and the document
  states that it counts no leap seconds and therefore is not UTC; converting
  it needs the leap-second count (item 136 or a published table). The pack
  language has no integer division of a key and no leap-second derive, so
  `time_ms` is not derived. The raw count is kept in
  `misb0601.precision_time_us`.
- **Reserved and out-of-range values.** Several items set aside one integer as
  a signal: `0x8000` is "out of range" in items 6, 7, 79 and 80; `0x80000000`
  is "reserved" in items 13, 14 and 19, "N/A (off-earth)" in items 23 and 24,
  and "out of range" in items 90 and 91. The pack language has no sentinel
  value, so such an integer decodes as a number just beyond the lower end of
  the range (for item 13, slightly below -90 degrees) and is passed on as if
  it were a measurement. A consumer must check for these values until the
  language can state them.
- **Zero-length items.** The document lets most items be sent with length 0
  to say the value is no longer defined. On this wire an empty value is
  absent for numeric items and the empty string for `utf8` items (ruling 1 of
  0.13); the distinction "undefined now" versus "not sent" is not kept.
- **Required lengths.** The document requires each fixed-size item to use
  exactly its stated length. Decode accepts an integer value of any length up
  to 8 bytes and reads it at its own length; such a value is not rejected.
- **Item order.** The document requires item 2 to be the first item. Decode
  does not check the order; encode writes item 2 first.
- **Repeated items.** Items marked as allowing multiples (100, 101, 102, 115)
  are residue; for a tag that a line names, only the first occurrence is read.
- **Nested local sets.** Items 48 (Security, MISB ST 0102), 73 (RVT, ST 0806),
  74 (VMTI, ST 0903), 95 (SAR, ST 1206), 97 (Range Image, ST 1002), 98
  (Geo-Registration, ST 1601), 99 (Composite Imaging, ST 1602), 100 (Segment,
  ST 1607) and 101 (Amend, ST 1607) hold sets defined by other documents. No
  line walks into them, so each is one residue item and is carried back
  unchanged in a round trip.
- **Packs.** Items in defined-length, variable-length or floating-length pack
  form (81, 102, 115, 116, 121, 122, 127, 128, 130, 138, 140, 141, 142) have
  no tags inside and are residue.
- **IMAPB items.** Items encoded with the IMAPB float-to-integer mapping of
  MISB ST 1201 at a variable length (96, 103, 104, 105, 109, 112, 113, 114,
  117 to 120, 132, 134) are residue. The wire has no IMAPB transform; item 104 (sensor ellipsoid height, extended) and item 112
  (platform course angle) would otherwise bind to `hae` and `course`.
- **Variable-length integers.** Items whose integer length varies (110, 111,
  131, 133, 136, 137) are residue in this version. They could be mapped with
  `uint` or `twos` and a size, because decode reads an integer at its own
  length; their encode size is a choice the document leaves open. Items 123
  to 126 (one-byte counts and enumerations) and the byte strings 94, 139 and
  143 are residue in this version as well.
- **Other fixed-size items** (26 to 47, 49 to 55, 57, 58, 60 to 64, 67 to 72,
  76, 77, 82 to 89, 92, 93) are residue in this version. Each could be a raw
  key with a plain `uint`, `twos`, `uscale` or `sscale` line.
- **Range-restricted and full-range pairs.** The document asks a decoder that
  understands the full-range item (90, 91) or the ellipsoid item (75) to
  prefer it over the restricted or mean-sea-level item (6, 7, 15). Both are
  mapped to separate keys; only item 75 binds a shared key.
- **`uid`.** The document has no item that is a stable identifier of the
  entity in the sense of `core.uid`; mission ID, tail number and call sign are
  free text with mission-dependent content. A target that needs `uid` (Cursor
  on Target) needs it from the caller's context.

## Candidate additions to the pack language

- A sentinel or reserved value on a field (an integer that decodes as absent).
- A transform for MISB ST 1201 IMAPB.
- A time derive from microseconds without leap seconds to `time_ms` (UTC),
  with the leap-second count as an argument.
