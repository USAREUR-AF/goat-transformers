# Pack: misb-st0806

The Remote Video Terminal (RVT) Local Set of MISB ST 0806.4, in its
standalone form: metadata that an aircraft sends to a remote video terminal
on the ground (ROVER, OSRVT) beside its motion imagery, items that ST 0601
does not carry. Public. Written from the document only (PROVENANCE.md). I/O
is hex text (`spec/engine-spec.md`, Version 0.13, the `tlv` wire, with the
CRC-32 checksum of Version 0.27). Needs engine version 0.27.

Uses the modules `core` and `misb0806` (`model/misb0806.def`).

This version maps every top-level item of the set whose value is a plain
integer or a text. The three subordinate sets (User Defined, Point of
Interest, Area of Interest) are carried as residue. No `core` or `track` key
is bound (below), so a conversion from this pack to another format carries no
value, and a conversion into it writes only the key, the length and the
checksum.

## Message convention

A message of this pack is one standalone RVT Local Set:

1. the 16-byte Universal Label key of the set,
   `06 0E 2B 34 02 0B 01 01 0E 01 03 01 02 00 00 00` (requirement
   ST 0806.4-06; `key`);
2. the length of the rest of the set, BER short or long form (`length ber`);
3. the items, each a tag written as a BER object identifier, a BER length and
   the value (`tag ber-oid`);
4. last, the checksum item: tag 1, length 4, a four-byte CRC
   (`checksum crc32 1`).

Byte 6 of the key, `0x0B`, is the SMPTE ST 336 code for BER-OID tags and BER
lengths, as in the `misb-st0601` key. Every tag the document defines is below
128, so each tag is one byte. The document defers the construction of a local
set to MISB TRM 1006, which was not read; the encodings above are those the
key's byte 6 names.

### The checksum

Requirements ST 0806.4-03 and -04 make the checksum mandatory in a standalone
set and make it the last item. Table 8-1 (item 1) and the appendix define it
as the CRC-32 of ISO/IEC 13818-1, not the 16-bit sum of ST 0601; the
appendix's parameters are the polynomial 0x04C11DB7 and an initial register of
all ones, with the bytes taken most significant bit first and no final
inversion. This is the wire's `crc32` (`spec/engine-spec.md`, 0.27, "The
CRC").

The document says the CRC is computed over the whole packet including the
16-byte key, and that the item is the last of the set, but it does not say
where the covered range ends: a value cannot cover itself, and the document
does not say whether the checksum item's tag and length are included. Ruling 1
of 0.27 decides it: the CRC covers every byte from the first byte of the key
through the tag and length of the checksum item, the same range ST 0601's
checksum and the wire's `sum16` cover. A packet produced under another reading
(the CRC over the bytes before the checksum item's tag, for example) is
`malformed-wire` here.

A packet whose CRC differs, whose last item is not tag 1 with a four-byte
value, or which has no checksum item, is `malformed-wire`.

### Writing

Encode writes the items in `field`-line order: item 2 (Precision Time Stamp)
first, as requirement ST 0806.4-02 asks, then the other mapped items by tag,
then any residue in input order (the subordinate sets among it), then the
checksum. A packet whose items are in that order, with shortest-form lengths
and integer values of the sizes in Table 8-1, round-trips byte for byte.

Requirement ST 0806.4-01 makes item 2 mandatory in a standalone set. There is
no `default` for it: a time has no meaningful default, and an entity without
`misb0806.precision_time_us` is written without item 2.

## Mapping

Sizes `:<n>` are the lengths of Table 8-1. Integers are big-endian
(requirement ST 0806.4-05 points to MISB ST 0107, which was not read; the
wire reads every integer big-endian, as the `misb-st0601` pack does).

### Shared keys, with evidence

None in this version.

| Item | Candidate key | Why not bound |
|---|---|---|
| 2 User Defined Time Stamp (Precision Time Stamp) | `time_ms` | Table 8-1 states microseconds since 1970-01-01T00:00:00 and calls it UTC, and defines it as the Precision Time Stamp of MISB ST 0603. MISB ST 0601.19, a later document, describes the same ST 0603 time stamp as counted without leap seconds and so not UTC; ST 0603 itself was not read, so which reading holds is not shown. Either way the value is in microseconds and `time_ms` is in milliseconds: on `tlv` the integer scales of 0.15 are `bad-directive` (ruling 28 of 0.15), and `uint` cannot divide. Kept raw in `misb0806.precision_time_us`, as `misb-st0601` keeps its item 2. |
| 3 Platform True Airspeed, 4 Platform Indicated Airspeed | `speed_ms` | Speed through the air mass (true, or as indicated from pitot and static pressure), not speed over the ground, which `core.speed_ms` is. |
| 6 Frag Circle Radius | `ce` | The radius of a fragmentation circle the aircrew selects, not an error bound of a position. |
| 14 to 17 MGRS of the aircraft | `lat`, `lon` | The aircraft's position is given only as MGRS parts (zone, band and grid square, easting, northing, WGS 84). The pack language has no MGRS-to-latitude/longitude transform or derive, and the MGRS easting and northing within a 100 km square are not a linear mapping of latitude or longitude. |
| 18 to 21 MGRS of the frame center | none | The frame center is a point on the ground, not the reported entity; kept raw. |
| 12 Point of Interest LS, 13 Area of Interest LS | `lat`, `lon` | The POI and AOI latitudes and longitudes are WGS 84 with a stated linear mapping, but they locate points and areas of interest, not the aircraft; and the sets are repeatable residue (below). |

The set has no item that is a stable identifier or a name of the entity, so
there is no `uid` or `callsign`.

### Raw keys of `misb0806`

| Item | Key | Transform | Note |
|---|---|---|---|
| 2 User Defined Time Stamp | `precision_time_us` | `uint`, 8 bytes | microseconds since 1970-01-01; the time the set's metadata was created (section 6) |
| 3 Platform True Airspeed | `platform_true_airspeed` | `uint`, 2 bytes | whole m/s; two bytes here, where ST 0601's item 8 has one |
| 4 Platform Indicated Airspeed | `platform_indicated_airspeed` | `uint`, 2 bytes | whole m/s; two bytes here, where ST 0601's item 9 has one |
| 5 Telemetry Accuracy Indicator | `telemetry_accuracy_indicator` | `uint`, 1 byte | reserved for future use; the value has no defined meaning and is carried as a number |
| 6 Frag Circle Radius | `frag_circle_radius` | `uint`, 2 bytes | whole meters |
| 7 Frame Code | `frame_code` | `uint`, 4 bytes | a 60 Hz counter; the document gives its range as 0 to 2^32, one more than four bytes hold, and the pack writes at most 2^32-1 |
| 8 UAS LS Version Number | `ls_version` | `uint`, 1 byte | the ST 0806 revision the set was written to |
| 9 Video Data Rate | `video_data_rate` | `uint`, 4 bytes | bits per second for digital video, or the analog FM frequency in hertz; the unit depends on the video, so the key's unit is `-` |
| 10 Digital Video File Format | `video_format` | `utf8` | free text, ISO-7 (7-bit ASCII) in the document, at most 127 characters |
| 14 MGRS Zone | `mgrs_zone` | `uint`, 1 byte | UTM zone 1 to 60 of the aircraft |
| 15 MGRS Latitude Band and Grid Square | `mgrs_band_square` | `utf8` | three characters: band letter, then the two letters of the 100 km square |
| 16 MGRS Easting | `mgrs_easting` | `uint`, 3 bytes | 0 to 99999 m |
| 17 MGRS Northing | `mgrs_northing` | `uint`, 3 bytes | 0 to 99999 m |
| 18 MGRS Zone Second Value | `frame_center_mgrs_zone` | `uint`, 1 byte | as item 14, for the frame center |
| 19 MGRS Latitude Band and Grid Square Second Value | `frame_center_mgrs_band_square` | `utf8` | as item 15, for the frame center |
| 20 MGRS Easting Second Value | `frame_center_mgrs_easting` | `uint`, 3 bytes | as item 16, for the frame center |
| 21 MGRS Northing Second Value | `frame_center_mgrs_northing` | `uint`, 3 bytes | as item 17, for the frame center |

No item at the top level has a linear scale; every number is a whole count in
its unit.

## Not mapped, and why

- **Item 11, User Defined LS.** A subordinate set of two items: a one-byte
  identifier whose top two bits give the type of the data (text, signed,
  unsigned, experimental) and whose low six bits are a number from 0 to 63,
  and the data, whose size comes from its length. The meaning of each
  identifier is agreed outside the document, and the type of item 2 depends on
  the value of item 1, which a `field` line cannot state. Residue.
- **Item 12, Point of Interest LS.** A subordinate set: a POI number, a WGS 84
  latitude and longitude as 4-byte two's-complement integers mapped linearly
  to plus or minus 90 and 180 degrees, an altitude above mean sea level, a
  type, text, an icon name, a source id, a label and an operation id. Section
  7.4 lets it occur many times in one set, one per point. The wire's paths
  take the first occurrence of a tag and drop the later ones (0.13,
  "Locators"), and `group` is `bad-directive` on `tlv`, so a line on `12.2`
  would read the first point and silently lose the others. Residue: every
  occurrence is kept and written back in input order.
- **Item 13, Area of Interest LS.** A subordinate set with an AOI number, the
  north-west and south-east corners (WGS 84, the same mapping as the POI), a
  type and optional text items. Requirement ST 0806.4-25 and section 7.4
  exempt every subordinate set from the rule that an item occurs once, so an
  area may be repeated as a point may; the same objection holds as for item
  12. Residue.
- **Item 1.** The checksum is neither mapped nor residue (0.13, step 4).
- **The embedded form.** Section 5 lets the set stand alone or be embedded in
  another set (MISB ST 0601 item 73, for example). Requirements 01 and 03 ask
  for the time stamp and the checksum only in an independent set; an embedded
  set has no key or outer length. That is a different message convention from
  this pack's; such a value is `malformed-wire` here. In a `misb-st0601`
  message, item 73 is one residue item.
- **The earlier key.** Section 7.1 says an earlier RVT key was never
  registered and must not be used. A packet with any key other than the one
  above is `malformed-wire`.
- **Zero-length items.** On this wire an empty value is absent for the
  integer items and the empty string for the `utf8` items (ruling 1 of 0.13).
- **Repeated items.** Requirement ST 0806.4-25 forbids a top-level item other
  than a subordinate set twice in one set. Decode does not reject it: for a
  tag that a line names, only the first occurrence is read, and later ones are
  dropped (0.13, "Locators").
- **Item order.** Decode does not check that item 2 is first; encode writes it
  first.
- **Required lengths and limits.** Decode reads an integer at its own length,
  so an item 3 of one byte is accepted; it is written back in two. The
  127-character limit of item 10, the three characters of items 15 and 19,
  the range 1 to 60 of the zones and 0 to 99999 of easting and northing are
  not checked.
- **ISO-7 text.** Items 10, 15 and 19 are 7-bit ASCII in the document; they
  are read as UTF-8, of which ASCII is a part. A byte above 0x7F that is part
  of valid UTF-8 is accepted rather than rejected; invalid UTF-8 is
  `transform-decode`.
- **Item 8 for this revision.** The document's note on item 8 gives the value
  of "this version" as 2, while the document is revision 4. Because the
  number to write is not clear and the item is not required, there is no
  `default` line.

## Candidate additions to the pack language

1. **Groups on `tlv`**: a list of the model read from the repeated
   occurrences of one tag, each occurrence a nested set, so that every POI
   (item 12) and AOI (item 13) becomes one item of a list. With it, POI items
   2 and 3 could be mapped with `sscale:180/4294967294` and
   `sscale:360/4294967294` and POI item 4 with `uscale:19900/65535:-900`, as
   `misb-st0601` maps its items 13, 14 and 15, into keys of the point, not of
   the aircraft.
2. **A value whose type is chosen by another item** (User Defined LS, item 2
   read according to the top bits of item 1).
3. **An MGRS derive**: latitude and longitude from zone, band and square,
   easting and northing (WGS 84), so that items 14 to 17 could give `lat` and
   `lon`.
4. **Integer scales on `tlv`** (the `uiscale` of 0.15, now `bad-directive` on
   this wire) together with a stated time base, so that item 2 could give
   `time_ms`.
