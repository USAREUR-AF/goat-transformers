# Pack: ais

AIS (Automatic Identification System) message payloads, as an AIS receiver
reports them in `AIVDM` (other stations) and `AIVDO` (own station) sentences.
Public. Written from the gpsd document "AIVDM/AIVDO protocol decoding" v1.58
(`PROVENANCE.md`). The standard that document describes is ITU-R M.1371; it
was not used as a source (`PROVENANCE.md`, "What was not used").

Uses the modules `core` and `ais` (`model/ais.def`). Needs engine version
0.14: the `bits` wire with `armor sixbit`, `bit_order msb`, kinds, `optional`
fields, `default` lines and the `sixbit` transform.

## The message

A message of this pack is one whole AIS payload: the armored text of the
sixth comma-separated field of an `AIVDM` or `AIVDO` sentence. A payload sent
in several sentences is the text of their sixth fields joined in fragment
order. Not part of the message, and not read or written by the pack:

- the sentence around the payload: `!AIVDM`, the fragment count, fragment
  number and sequential message identifier, the radio channel, the checksum;
- the fill-bit count (the seventh field);
- the joining of fragments, and any NMEA 4.00 tag block.

These belong to a layered wire that does not exist yet (engine-spec 0.14,
ruling 1). A caller that holds sentences extracts and joins the payload
before calling the engine, and builds sentences around the text it gets back.

Each character of the text carries six bits, most significant first
(engine-spec 0.14, "Reading the armored text"). A message of N characters is
6N bits. Bits past what a kind reads, the fill bits included, are ignored on
decode (ruling 2 of 0.14). Encode writes as many characters as the kind's
fields reach, its last character padded with zero bits; the fill-bit count a
caller needs for the sentence is 6 times the characters minus the bits the
kind reaches, which the pack does not report.

## Addressing

`word_bytes 1`, `bit_order msb`: a locator is `0:<bit>:<len>`, bit 0 being the
first bit of the payload. The source numbers bits from 0 in the same order, so
each locator is the source's start bit and width.

## Kinds

Bits 0-5 are the message type. It is the common field `ais.msg_type` and a
`when` in every kind; on encode the kind's `when` value is written over the
field. Bits 6-7 (repeat indicator, `ais.repeat`) and 8-37 (MMSI, `ais.mmsi`)
are common to every type.

| Kind | Type | Bits | Mapped to `core` |
|---|---|---|---|
| `position-a1`, `position-a2`, `position-a3` | 1, 2, 3 | 168 | `lat`, `lon`, `speed_ms`, `course` |
| `base-station` | 4 | 168 | `lat`, `lon` |
| `static-voyage` | 5 | 424 | `callsign` |
| `binary-ack` | 7 | 72 to 168 | none |
| `sar-aircraft` | 9 | 168 | `lat`, `lon`, `speed_ms`, `course` |
| `utc-inquiry` | 10 | 72 | none |
| `utc-response` | 11 | 168 | `lat`, `lon` |
| `safety-ack` | 13 | 72 to 168 | none |
| `interrogation` | 15 | 88 to 160 | none |
| `assignment` | 16 | 96 or 144 | none |
| `position-b` | 18 | 168 | `lat`, `lon`, `speed_ms`, `course` |
| `position-b-ext` | 19 | 312 | `lat`, `lon`, `speed_ms`, `course` |
| `link-management` | 20 | 72 to 160 | none |
| `aid-to-nav` | 21 | 272, without the name extension | `lat`, `lon` |
| `channel-area` | 22, bit 139 = 0 | 168 | none |
| `channel-addressed` | 22, bit 139 = 1 | 168 | none |
| `group-assignment` | 23 | 160 | none |
| `static-a` | 24, part 0 | 160, or 168 | none |
| `static-b` | 24, part 1 | 168 | `callsign` |
| `long-range` | 27 | 96 | `lat`, `lon`, `speed_ms` |

Every other field of these types is a raw key of `ais`, in the wire's unit,
including the spare and regional bit ranges, so a same-format round trip
returns the bits it read. The exceptions are listed under "Not mapped".

Types 1, 2 and 3 share one layout and are three kinds, so that a round trip
keeps the type; the same holds for 4 and 11, and for 7 and 13. Type 22 is two
kinds because bit 139 decides whether bits 69-138 are the corners of an area
or two destination MMSIs. Type 24 is two kinds by the part number in bits
38-39; parts 2 and 3, which the source says are not allowed, select no kind
(`no-kind`).

### Variable length

The source gives some types several lengths. Where the longer forms only add
fields at the end, those fields are `optional`: a field any of whose bits lies
past the input is absent (engine-spec 0.6, field options), and encode stops
after the last present field (L of 0.14).

| Kind | Optional fields |
|---|---|
| `binary-ack`, `safety-ack` | the second, third and fourth MMSI and sequence number |
| `interrogation` | the second request to the first station; the second station and its request |
| `assignment` | the second station, its offset and increment |
| `link-management` | the second, third and fourth reservation |
| `static-a` | the spare byte at bits 160-167, which real senders often leave out |

A type 27 payload of 168 bits, which the source says occurs, decodes from its
first 96 bits; the rest is ignored and not written back.

### Encode from another format

When the entity does not come from this pack (`convert` from another format
clears the kind), the first kind whose `requires` keys are all present is
written. `position-a1` is first and requires `ais.mmsi`, `lat` and `lon`;
`static-voyage` requires `ais.mmsi` and `callsign`. The other kinds require a
raw key of their own type and so are written only for an entity that carries
it. An entity from GeoJSON or CoT with a decimal `uid` and a position becomes
a type 1 report; with a call sign and no position, a type 5.

Fields the entity lacks are written as the source's not-available or default
code where the source states one, through `default` lines:

| Field | Written when absent | Kinds |
|---|---|---|
| speed over ground | 1023 (types 1-3, 18, 19: tenths of a knot; type 9: knots); 63 knots (type 27) | as listed |
| course over ground | 3600 tenths of a degree | 1-3, 9, 18, 19 |
| rate of turn | -128 | 1-3 |
| navigation status | 15, undefined | 1-3, 27 |
| true heading | 511 | 1-3, 18, 19 |
| UTC second | 60 | 1-4, 9, 11, 18, 19, 21 |
| hour, minute | 24, 60 | 4, 11 |
| ETA hour, ETA minute | 24, 60 | 5 |
| DTE | 1, not ready | 5, 9, 19 |
| altitude | 4095 | 9 |
| course (type 27) | 511 | 27 |
| GNSS position status | 1, not a GNSS position | 27 |

The defaults on `speed_ms` are the model value that encodes to the code:
1023 x 1852/36000 = 52.627666... m/s, 1023 x 1852/3600 = 526.27666... m/s, and
63 x 1852/3600 = 32.41 m/s. Every other absent field is written as zero bits.

## Shared keys and their evidence

Each binding below rests on a sentence of the source; the sentence is cited
by section, and its content is stated here in this project's words.

| Wire field | Model key | Transform | Evidence |
|---|---|---|---|
| MMSI, bits 8-37 | `ais.mmsi`, and `uid` by derivation | `uint` | Common Navigation Block and every type table: a 30-bit unsigned MMSI of nine decimal digits. `model/ais.def` derives `uid` as the decimal text of `ais.mmsi` (`text_of`) and `ais.mmsi` from a `uid` that is a decimal integer (`parse_int`), as `model/cat062.def` does for the track number. `uid` is the stable identifier of the entity; the source calls the MMSI the unique ID of the ship's radio. |
| Longitude, types 1-3, 4, 9, 11, 18, 19, 21 | `lon` | `sscale:1/600000` | Types 1, 2 and 3: a signed field in 1/10000 minute, divided by 600000 to give degrees, east positive, west negative, up to 180 degrees. The other types state "as in the Common Navigation Block". |
| Latitude, the same types | `lat` | `sscale:1/600000` | The same section: 1/10000 minute, divided by 600000, north positive, up to 90 degrees. |
| Longitude and latitude, type 27 | `lon`, `lat` | `sscale:1/600` | Type 27: signed, in 1/10 minute, east and north positive. |
| Speed over ground, types 1-3, 18, 19 | `speed_ms` | `uscale:1852/36000` | Types 1, 2 and 3: speed over ground in steps of 0.1 knot. One knot is 1852 m per 3600 s, so one step is 1852/36000 m/s. Types 18 and 19 state "as in the common navigation block". |
| Speed over ground, type 9 | `speed_ms` | `uscale:1852/3600` | Type 9: speed over ground in whole knots, not tenths. |
| Speed over ground, type 27 | `speed_ms` | `uscale:1852/3600` | Type 27: speed over ground in knots, 0 to 62. |
| Course over ground, types 1-3, 18, 19 | `course` | `uscale:1/10` | Types 1, 2 and 3: course over ground relative to true north in 0.1 degree. Type 18: 0.1 degrees from true north. Type 19: relative to true north, units of 0.1 degrees. |
| Course over ground, type 9 | `course` | `uscale:1/10` | Type 9: true bearing in 0.1 degree units. |
| Call sign, type 5 bits 70-111; type 24 part B bits 90-131 | `callsign` | `sixbit`, `trim` | Type 5: the call sign, 7 six-bit characters; type 24 part B: "as in message type 5". The vessel name is a separate field and is not a call sign: it is `ais.shipname`. |

What the evidence does not show:

- **Datum.** The gpsd document does not name the datum of the positions.
  Recommendation ITU-R M.1371-6 (02/2026), section A7-3, says that all
  positions should be sent in WGS 84 (read 2026-11-24,
  https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.1371-6-202602-I!!PDF-E.pdf,
  sha256 `126025db40f545454bbfc192c85353bd24bded48016f853ec184ef46f704a1dd`).
  Nothing else in the pack is taken from it.
- **Type 27 course.** The source gives the type 27 course in whole degrees, 0
  to 359, without saying it is relative to true north. It is the raw key
  `ais.course_lr`, not `course`.
- **Heading.** True heading (types 1-3, 18, 19) is the direction the vessel
  points, not its direction of travel; it is `ais.heading`, not `course`.
- **Altitude, type 9.** Metres, with no stated reference (ellipsoid or sea
  level); it is `ais.altitude`, not `hae`.

## Not-available codes on decode

The source gives not-available codes, and each is `absent` on its line: in the
common navigation block (types 1, 2, 3, 9, 18, 19) and in types 4, 11 and 21,
longitude 181 degrees (raw 108600000), latitude 91 degrees (54600000), speed
1023 and course 3600. A message with them decodes without `lon`, `lat`,
`speed_ms` or `course`, so no conversion carries them as values, and an absent
key writes the code: the message comes back byte for byte. Heading 511 and the
other raw keys (`ais.heading`, `ais.second`, `ais.turn` and the rest) still hold
the code, which the key's description in `model/ais.def` names.

Type 27: the source prints 181000 and 91000 in a unit of 1/10 minute, which do
not fit its signed 18- and 17-bit fields; the pack takes 181 and 91 degrees in
that unit, 108600 and 54600, as the source does for type 17, and speed 63. The
course of type 27 is the raw key `ais.course_lr` (511 not available). Every code
lies outside the range of a real value, so no real value is lost.

## Not mapped

| What | Why |
|---|---|
| The `AIVDM`/`AIVDO` sentence, fill-bit count, fragments, tag blocks | A layered wire (ruling 1 of 0.14); see "The message" |
| Types 6 and 8 (binary addressed and broadcast) | The data after the application identifier runs to the end of the message, up to 920 or 952 bits, and its length is the message length less the header. The fixed layout cannot read a field whose length is the rest of the input; a header-only kind would drop the data silently. The many DAC/FID subtypes are not mapped either. |
| Types 12 and 14 (safety-related text) | The text runs to the end of the message, 1 to 156 or 161 characters. The same limit: `sixbit` needs a fixed length. |
| Type 17 (DGNSS broadcast) | The correction data after bit 79 runs to the end of the message, up to 736 bits. |
| Types 25 and 26 (single- and multiple-slot binary) | The destination MMSI and the application identifier are present or absent by two flags, and the data runs to the end (type 26: followed by 20 bits of radio status). The sequential layout can state the flags; it cannot state a data field whose length is what remains before a trailing field, or the end of the input. |
| Type 21 name extension, bits 272 and on | Up to 14 six-bit characters, as many as the message length allows, then padding. Its length is the rest of the input, as above. A payload with an extension decodes; the extension is ignored and a round trip drops it. |
| Type 15 spare bits 88-89, 108-109, 158-159; type 16 bits 92-95 of the 96-bit form | Trailing spares of variable-length forms: mapping them as optional would read the fill bits of a shorter form as a value, or overlap the fields of the longer form. |
| Type 22 addressed form, bits 99-103 and 134-138 | The source does not describe the bits between and after the two MMSIs. Encode writes zero. |
| Rate of turn in degrees per minute | The wire code is the signed square-root form 4.733 x sqrt(rate). The language has no transform for it; `ais.turn` holds the code. |
| A time instant (`time_ms`) | Position reports carry only the UTC second. Types 4 and 11 carry year to second, but no derive function builds an instant from date and time parts. They are raw keys. |
| Type 24 part B, bits 132-161 | Not left out, but read twice: as the four dimensions and as `ais.mothership_mmsi`. The source says the second reading holds when the MMSI has the form 98xxxxxxx (auxiliary craft). That is a range of the MMSI, not a value a `when` can test, so both are decoded and the consumer chooses. Bits 48-89 are likewise read both as vendor ID, model and serial, and as the 7-character `ais.vendor_text`, as the source advises. On encode the earlier line wins (ruling 5 of 0.5). |

## Behaviour to know

- **Six-bit text.** Ship name, destination, aid name and call sign are read
  with `sixbit` and `trim`: trailing `@` and spaces are removed, as the source
  advises. A name padded with spaces comes back padded with `@`, so a round
  trip of such a name is not byte-exact. Characters after a first `@` that is
  followed by other characters are kept; the source says they are garbage. The
  two overlapping vendor fields of type 24 part B are read without `trim`, so
  both write back the same bits.
- **Short type 5.** The source says type 5 is often received with 420 or 422
  bits. 422 bits arrive as 71 characters and decode. 420 bits arrive as 70
  characters, too short for the destination field, and are `malformed-wire`.
- **Length checks.** The source advises rejecting payloads of the wrong length
  for their type. The pack rejects a payload too short for its kind's
  non-optional fields (`malformed-wire`) and ignores anything longer.
- **MMSI from `uid`.** `parse_int` accepts any 64-bit decimal integer, and
  a value that does not fit the 30-bit MMSI is `transform-encode` (ruling 4b
  of 0.11), so a `uid` such as `"1234567890"` is refused, not written as a
  different MMSI. A `uid` that is not a decimal
  integer leaves `ais.mmsi` absent, so no kind's `requires` holds and encode is
  `no-kind`.
- **Capability matrix.** The matrix lists `uid` as dropped between this pack
  and others, because it does not count derived keys; `convert` carries it.
