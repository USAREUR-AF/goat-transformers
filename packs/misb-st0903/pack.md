# Pack: misb-st0903

The Video Moving Target Indicator (VMTI) Local Set of MISB ST 0903.6, in its
standalone form: the metadata packet that lists the targets a detection or
tracking system found in one frame of motion imagery. Public. Written from the
document only (PROVENANCE.md). I/O is hex text (`spec/engine-spec.md`, Version
0.13, the `tlv` wire). Needs engine version 0.13.

Uses the modules `core` and `misb0903` (`model/misb0903.def`).

This version maps the top-level items of the set that describe the frame and
the detecting system. The targets themselves, their algorithms and their
ontologies are in the series items 101, 102 and 103, which the pack language
cannot yet walk into (below); they are carried as residue. A VMTI packet
therefore converts to another format with none of its targets, and no
`core` key is bound in this version.

## Message convention

A message of this pack is one standalone VMTI Local Set (section 10.1):

1. the 16-byte Universal Label key of the set,
   `06 0E 2B 34 02 0B 01 01 0E 01 03 03 06 00 00 00` (`key`);
2. the length of the rest of the packet, BER short or long form (`length ber`);
3. the items, each a tag written as a BER object identifier, a BER length and
   the value (`tag ber-oid`);
4. last, the checksum item: tag 1, length 2, two value bytes
   (`checksum sum16 1`).

Byte 6 of the key, `0x0B`, is the SMPTE ST 336 code for BER-OID tags and BER
lengths. Section 9.2 of the document gives byte 6 of the VMTI key as 0x2B;
that is a slip in the document (0x2B is byte 3 of every SMPTE key),
and the key printed in section 10.1 has `0x0B` at byte 6. The pack follows the
key of section 10.1.

The checksum item is required in the standalone form and must be the last
item (requirements ST 0903.4-15 and -17). Section 10.1.1 and requirement
ST 0903.6-119 define it by reference to MISB ST 0601: a running 16-bit sum
over the packet from the first byte of the key up to and including the length
byte of the checksum item, keeping the low 16 bits. This is the wire's
`sum16` as the specification states it (bytes at even offsets from the start
of the key count as the high byte of a 16-bit word, at odd offsets as the low
byte); the same algorithm is used by the `misb-st0601` pack. A packet whose
checksum differs is `malformed-wire`.

Encode writes the items in `field`-line order: item 2 (precisionTimeStamp)
first, as requirement ST 0903.4-14 asks when the item is present, then the
other mapped items by tag, then any residue in input order, then the
checksum. When the entity has no `misb0903.ls_version`, item 4 is written as
6, the revision of the document this pack was written from; requirement
ST 0903.5-99 makes item 4 mandatory in every set.

### Sizes of variable-length integers

Items 4, 5, 6, 8 and 9 have a variable length in the document ("V2" or "V3":
at least one byte, at most two or three). Decode reads each at its own length
(`spec/engine-spec.md`, 0.13, "Transforms for `tlv`"), so every length the
document allows is accepted. Encode writes each at its largest allowed length
(`:2` for item 4, `:3` for items 5, 6, 8 and 9), so every value in the
document's range can be written and the output stays within the document's
lengths. The document's own examples use the shortest length (item 4 = 6 in
one byte, item 8 = 1920 in two); such a packet decodes to the same values but
does not round-trip byte for byte. The pack language has no "shortest length"
integer encoding; see "Candidate additions".

## Mapping

### Shared keys, with evidence

None in this version.

| Item | Candidate key | Why not bound |
|---|---|---|
| 2 precisionTimeStamp | `time_ms` | Section 10.1.2 and 9.2.2: microseconds since 1970-01-01 in MISP time (MISB ST 0603), counted without leap seconds, so not UTC. Converting needs the leap-second count, and the pack language has no integer division of a key and no leap-second derive. Kept raw in `misb0903.precision_time_us`, as `misb-st0601` keeps its item 2. |
| 10 vmtiSourceSensor | `track.source_id` | Section 10.1.10: a free-text label of the sensor, which changes whenever the source video changes. `track.source_id` is a stable identifier; the label is not stated to be stable or unique. |
| 13 miisId | `track.source_id`, `uid` | A MISB ST 1204 identifier of the source video, not of a target or sensor; ST 1204 was not read. |
| 101 vTargetSeries | `lat`, `lon`, `hae`, `uid`, `track.*` | Target positions (VTarget item 17, the Location pack), target ids, track velocities are all inside the series and IMAPB-coded (see "Not mapped"). |

A VMTI set is a report about a frame with zero or more targets, not about one
entity; even with series support, each target would be one entity of a list,
not the set itself.

### Raw keys of `misb0903`

Sizes `:<n>` are the document's required or largest length of each item
(section 10.1, the summary table, column Len).

| Item | Key | Transform | Note |
|---|---|---|---|
| 2 precisionTimeStamp | `precision_time_us` | `uint`, 8 bytes | microseconds since 1970-01-01, unsigned 64-bit, MISP time; the time of the source video frame (10.1.2) |
| 3 vmtiSystemName | `vmti_system_name` | `utf8` | free text, at most 32 characters (up to 128 bytes) |
| 4 vmtiLsVersionNum | `ls_version` | `uint`, 2 bytes | values 1 to 65535 are document revisions; default 6 on encode |
| 5 totalNumTargetsDetected | `total_num_targets_detected` | `uint`, 3 bytes | size of the producer's whole target list; 0 means none |
| 6 numTargetsReported | `num_targets_reported` | `uint`, 3 bytes | targets in this set after culling; required in every set (ST 0903.4-19), but a count has no meaningful default, so no `default` line |
| 8 frameWidth | `frame_width` | `uint`, 3 bytes | pixels per row of the source frame; the document forbids 0 |
| 9 frameHeight | `frame_height` | `uint`, 3 bytes | rows of the source frame; the summary table's format column reads "unit", taken as `uint` from the column of item 8 and the text of 10.1.9 |
| 10 vmtiSourceSensor | `vmti_source_sensor` | `utf8` | free text, at most 128 characters (up to 512 bytes) |
| 13 miisId | `miis_id` | `hex` | the value is binary (MISB ST 1204), kept as lowercase hex |

The document's length limits for items 3 and 10 are not checked on decode or
encode.

## Not mapped, and why

- **Items 11 and 12, vmtiHorizontalFov and vmtiVerticalFov.** Each is a
  2-byte value coded with IMAPB(0, 180, 2) from MISB ST 1201. The pack
  language has no IMAPB transform. The two examples of sections 10.1.11 and
  10.1.12 (12.5 degrees as `0x0640`, 10.0 degrees as `0x0500`) are consistent
  with a plain factor of 1/128, and `uscale:1/128` would decode them; but ST
  1201 also fixes how a value is rounded into the integer and sets aside bit
  patterns as out-of-range and user-defined signals (section 9.1.1 names
  IMAP_BELOW_MINIMUM, IMAP_ABOVE_MAXIMUM and an "Invalid" value starting
  `0xC1`). ST 1201 was not read, and a `uscale` line would decode those
  signals as angles. Both items are residue.
- **Item 101, vTargetSeries.** A series (section 9.1.3): the value is a run of
  elements, each a BER length and a VTarget Pack, with no tag per element.
  Each VTarget Pack begins with the target id as a BER-OID integer (up to 9
  bytes) and continues with VTarget items in tag-length-value form, among them
  further local sets (101 vMask, 104 vTracker, 105 vChip), further series (18
  geospatialContourSeries, 106 vChipSeries, 107 vObjectSeries), defined-length
  truncation packs of IMAPB values (17 targetLocation; vTracker's velocity and
  acceleration) and arrays. The `tlv` wire of 0.13 has no `group`, cannot read
  a value as a list of length-prefixed elements, and cannot read a leading
  untagged integer before the items of a set. The whole item is one residue
  item, carried back unchanged in a round trip.
- **Item 102, algorithmSeries, and item 103, ontologySeries.** Series of
  Algorithm and Ontology local sets (sections 10.8 and 10.9), each element a
  BER length and a local set. Not mapped for the same reason; each is one
  residue item.
- **Everything inside the series.** All VTarget, VMask, VObject, VFeature,
  VTracker, VChip, Algorithm and Ontology items, the Location, Velocity and
  Acceleration packs, and the BoundarySeries. Residue inside items 101 to 103.
- **Item 7.** Deprecated in ST 0903.6 (section 10.1.7). Residue.
- **The embedded form.** A VMTI set inside a parent set (MISB ST 0601 item 74,
  for example) has no key, no outer length and no checksum item (requirement
  ST 0903.6-120), and may leave the fields of view and other items to the
  parent. That is a different message convention from this pack's; a packet
  without the key, or without a valid checksum as its last item, is
  `malformed-wire` here. Supporting it needs a second pack (no `key`, no
  `checksum`), or a way for the `misb-st0601` pack to walk into item 74; this
  version covers neither. In a `misb-st0601` message, item 74 is one residue
  item.
- **Zero-length items.** On this wire an empty value is absent for the
  integer items and the empty string for `utf8` and `hex` items (ruling 1 of
  0.13).
- **Repeated items.** Requirement ST 0903.5-98 forbids an item twice in one
  set. Decode does not reject it: for a tag that a line names, only the first
  occurrence is read, and later ones are dropped (0.13, "Locators").
- **Item order.** Decode does not check that item 2 is first; encode writes it
  first.
- **Values the document forbids** (a frame width or height of 0, a version of
  0) decode as numbers; the pack language has no range check or sentinel.

## Candidate additions to the pack language

What would let the rest of ST 0903.6 be mapped, in the order that unlocks the
most:

1. **Groups on `tlv`** (`group` is `bad-directive` on `tlv` in 0.13): a list
   of the model whose items are read from repeated elements of one value, so
   that each target of item 101 becomes one item of a list. ST 0903 needs this
   in three shapes:
   - a **series**: the value of an item is a sequence of elements, each a BER
     length followed by that many bytes, with no tag (items 101, 102, 103;
     VTarget 18, 106, 107; VObject 5; VTracker 5 and 9; VMask 2);
   - an element that is a **local set** (Algorithm, Ontology, VChip, VObject,
     VFeature elements), which the wire's nested-set locators already read;
   - an element that is a **pack with a leading untagged field**: the VTarget
     Pack's BER-OID target id, then tag-length-value items. This needs a
     locator for "the leading BER-OID integer of the element" (and a transform
     for a BER-OID integer as a value) besides the path into its items.
2. **An IMAPB transform** (MISB ST 1201) with the parameters minimum,
   maximum and length, including its rounding rule and its special values
   (below minimum, above maximum, user-defined such as the "Invalid" value of
   section 9.1.1) decoding as absent or as a named signal. This maps items 11
   and 12 at the top level, and inside the series the target's height (VTarget
   12, which would bind `hae`), the offset coordinates (10, 11, 13 to 16), and
   VObject and VFeature confidences.
3. **Defined-length truncation packs**: a value that is a fixed sequence of
   fixed-size sub-fields, of which trailing groups may be left out (the
   Location, Velocity and Acceleration packs of section 10.10). Location would
   bind `lat`, `lon`, `hae` and the `track.sigma_*` keys; Velocity would bind
   `track.vel_east_ms`, `track.vel_north_ms` and `track.vel_up_ms`, after the
   evidence for frame and units is read from section 10.10.
4. **Arrays**: a value that is a sequence of equal-size unsigned integers
   (VMask 1 pixelContour).
5. **A per-set tag size.** Section 9.2 says the sets nested in the VMTI set
   use 1-byte tags, while the VMTI set uses BER-OID tags; 0.13 uses the pack's
   tag encoding in every nested set. The two agree for every tag below 128,
   which covers every nested item ST 0903.6 defines, so this is needed only
   for strictness.
6. **A shortest-length integer encoding** for `uint` (write the fewest bytes
   from 1 up to `n`), so that encode matches the document's examples for
   items 4, 5, 6, 8 and 9 and the VTarget items marked V.
7. A time derive from microseconds without leap seconds to `time_ms` (UTC),
   as for `misb-st0601`.
