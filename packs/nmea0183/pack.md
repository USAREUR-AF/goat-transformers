# Pack: nmea0183

NMEA 0183 sentences as GNSS receivers and marine instruments emit them. Public.
Written from the gpsd project's document "NMEA Revealed" (`www/NMEA.adoc` at
gpsd commit `c59fc6de479d06620c8b2ba395b728e10a71527b`, BSD-2-Clause), which
states that the NMEA 0183 standard was not consulted in writing it. The NMEA
standard itself (and IEC 61162-1) is a priced document and was not read.
`PROVENANCE.md` has the hashes and the license.

Needs engine version 0.10 (the `text` wire). Uses the modules `core` and
`nmea0183` (`model/nmea0183.def`).

Status: Built. 53 vectors (43 here, 10 from `geojson`), derived without an
engine.

## Message convention

A message is one sentence, as text:

1. `$` (`start "$"`);
2. the fields, separated by `,`; field 0 is the tag;
3. `*` and the checksum: the XOR of every character between `$` and `*`, as
   two hexadecimal digits (`checksum nmea`).

Decode accepts one trailing CR LF or LF. Encode writes no line terminator and
writes the checksum digits in uppercase. A sentence without a checksum, with a
wrong one, or with any character outside 0x20 to 0x7E is `malformed-wire`: the
source states the checksum is mandatory.

Field numbers in this document are the wire's: field 0 is the tag, and field
*n* is the source's field *n* for every sentence here (the source numbers the
fields after the tag from 1).

## Kinds

The tag is two characters of talker id and a three-letter sentence id. The
sentence id (`0:2:3`) selects the kind; the talker id (`0:0:2`) is the common
field `nmea0183.talker`.

| Kind | `when` | `requires` (encode from another format) | Fields |
|---|---|---|---|
| `rmc` | `0:2:3 RMC` | `lat lon time_ms` | 13 |
| `gga` | `0:2:3 GGA` | `lat lon` | 14 (two of them `const`) |
| `gll` | `0:2:3 GLL` | `lat lon` | 7 |
| `vtg` | `0:2:3 VTG`, `2 T` | `course` | 9 (three `const`, one `when`) |
| `gsa` | `0:2:3 GSA` | `nmea0183.fix_mode` | 18 |
| `gsv` | `0:2:3 GSV` | `nmea0183.sats_in_view` | 3, then a group of 4 per satellite |
| `hdt` | `0:2:3 HDT` | `nmea0183.heading_true_deg` | 2 (one `const`) |
| `zda` | `0:2:3 ZDA` | `nmea0183.year` | 6 |

An entity from another format becomes RMC when it has a position and a time, GGA
when it has a position only, VTG when it has a course only. GLL, and every kind
after VTG, is reached by a same-format round trip, or by an entity that has the
`nmea0183` key its `requires` names.

### Talker ids

The talker id is read and written as the first two characters of the tag. A
sentence from any talker (GN, GL, GA, BD, II, ...) decodes to its kind, and a
same-format round trip writes the talker it read, because `nmea0183.talker`
holds it. A conversion to another format drops the key (no other format maps
it), and an entity that arrives without one is written with talker `GP`
(`default nmea0183.talker GP`). To write another talker from another format,
pass the key in the context: `--set nmea0183.talker=GN`.

## Shared keys: mapping and evidence

The source's statements, by section of "NMEA Revealed" and field number. The
datum for positions is stated in the section on the DTM sentence: the datum
GNSS receivers usually announce is WGS 84; GGA field 11 is defined against the
WGS 84 ellipsoid.

| Kind, field | Model key | Evidence and note |
|---|---|---|
| RMC 3+4, GGA 2+3, GLL 1+2 | `lat` | Latitude as degrees (two digits) and minutes, with N or S (section "NMEA Encoding Conventions"; each sentence's fields). WGS 84: see above and "Not mapped", datum. `dm:2:5:NS` |
| RMC 5+6, GGA 4+5, GLL 3+4 | `lon` | Longitude as degrees (three digits) and minutes, with E or W. `dm:3:5:EW` |
| RMC 1+9 | `time_ms` | Field 1 is the UTC time of the fix, field 9 the date as day, month, two-digit year; section "Dates and times" states that the sentences report UTC. `hms_dmy:2` reads years 80-99 as 19yy and 00-79 as 20yy |
| RMC 8 | `course` | Track made good, in degrees true: the direction of travel over the ground |
| VTG 1 | `course` | Course over ground in degrees true |
| RMC 7, VTG 5 | `nmea0183.sog_kn` | Speed over ground in knots. Not `speed_ms`: the unit differs and no `text` transform scales. `model/nmea0183.def` derives `speed_ms` from it (one knot is 1852 m per 3600 s, the definition of the international knot) and back |
| VTG 7 | `nmea0183.sog_kmh` | Speed over ground in km/h; derived to and from `speed_ms` likewise (1000 m per 3600 s) |

The derivations run in `convert` between formats (engine-spec 0.6), so a
conversion from RMC or VTG yields `speed_ms`, and a conversion to RMC or VTG
from an entity with `speed_ms` writes knots (and km/h in VTG). A same-format
round trip does not derive and keeps the sentence's digits. The capability
matrix does not count derivations, so it lists `speed_ms` as dropped in both
directions.

Not bound, on purpose:

| Field | Why not |
|---|---|
| GGA 9, antenna altitude | Above mean sea level (the geoid), not above the ellipsoid; `hae` is ellipsoidal height. Kept as `nmea0183.alt_msl_m`. The ellipsoidal height is GGA 9 + GGA 11, but no derive function adds two keys (see "Candidate additions") |
| GGA 8, GSA 16, HDOP | A dilution of precision, without unit; not a circular error in metres. Kept as `nmea0183.hdop` |
| HDT 1, heading true | The direction the vessel points, not the direction it moves; `course` is the direction of travel. Kept as `nmea0183.heading_true_deg` |
| VTG 3, course magnetic | Degrees magnetic; `course` is degrees true. Kept as `nmea0183.course_mag_deg` |
| GGA 1, GLL 5, ZDA 1, time of day | No date in GGA or GLL, so not an epoch time. ZDA has the date, in three separate fields with a four-digit year, and no `text` transform combines them. Kept as `nmea0183.utc_s` (seconds since midnight) and `nmea0183.day`, `month`, `year` |

## Raw keys

Every other field goes to a key of module `nmea0183`; the keys and their units
are in `model/nmea0183.def`. Letter codes (status, FAA mode, selection mode,
navigational status) are kept as the letter: the source gives their tables,
and no other format maps them, so no value table is used.

Numbers are written with the fraction digits the source's example sentences
show for that field: minutes of latitude and longitude 5 (`dm:<d>:5`), times 2
(`hms:2`, `hms_dmy:2`), course and heading 2 (`dec:2`), speed 3 (`dec:3`),
dilutions of precision 2, altitude, geoidal separation, magnetic variation and
correction age 1. The source states that the number of fraction digits of
time, latitude and longitude depends on the receiver; any number of digits
decodes, and a sentence with other digits re-encodes with the pack's. Fields
the source describes as sent with leading zeros are `int:<w>` at the width of
their layout: GGA 7 and 14, GSA 3 to 14, GSV 3 and the satellite fields, ZDA
2 to 6.

Fixed letters: GGA 10 and 12 (`M`, metres), VTG 4, 6 and 8 (`M`, `N`, `K`) and
HDT 2 (`T`) are `const`: decode does not check them and encode always writes
them. VTG 2 (`T`) is a `when`, because the source distinguishes the current
form of VTG from the older one by that letter.

Trailing fields that later NMEA versions added are `optional`, so encode leaves
them off when the entity has no value for them and decode reads the sentence
with or without them: GLL 7 and RMC 12 and VTG 9 (FAA mode, NMEA 2.3), RMC 13
(navigational status, NMEA 4.1), GSA 18 (system id, NMEA 4.11). GGA 13 and 14
(DGPS age and station) are not `optional`: the source lists them in the layout
and describes an empty field when DGPS is not used, so encode writes them empty.
A GGA without them decodes, and re-encodes with two empty fields.

### GSV satellites

Fields 4 onward are the list `nmea0183.satellites`, one item per four fields
(`group nmea0183.satellites 4 item 4`): `sv_id`, `elevation_deg`,
`azimuth_deg`, `snr_db`. The items run to the end of the sentence, so a
sentence with fewer than four satellites, or with a satellite whose SNR is empty
(not tracked), decodes; a missing field of an item is absent. A sentence whose
last satellite is four empty fields decodes to a last item with no keys and
re-encodes the same.

## Not mapped, and why

| What | Why |
|---|---|
| Multi-sentence GSV assembly | A satellites-in-view report is a group of GSV sentences (fields 1 and 2 give the count and the index). A message of this pack is one sentence; each decodes on its own with its own items. Joining a group is the caller's work |
| GSV signal id (NMEA 4.11) | One extra field after the last satellite. A group runs to the end of the record in fours, so the signal id is read as the `sv_id` of a last item with no other keys, and re-encodes as a four-field item. The pack language has no way to end a group one field before the end of the record. Decode a 4.11 GSV with this in mind |
| VTG, older form | Four values with no unit letters. Field 2 is not `T`, so it selects no kind (`no-kind`) rather than being misread |
| Sentences without a checksum | The source states the checksum is mandatory; `checksum nmea` makes such a sentence `malformed-wire` |
| Proprietary sentences (`$P...`) | Their tags are not `<talker><id>` with one of the eight ids, so they select no kind (`no-kind`). Their layouts are each vendor's |
| Other sentence ids | Not in scope of this pack: `no-kind` |
| `!` start (AIVDM, AIVDO) | A different payload (AIS); `start "$"` refuses it as `malformed-wire` |
| Tag blocks (`\...\` before `$`) | The source does not describe them. A sentence that begins with one does not begin with `$` and is `malformed-wire`; the caller strips the tag block first |
| Maximum length of 82 characters | Not checked on decode or encode |
| `^` hexadecimal escapes (NMEA 3.01) | Not decoded; text fields hold them as sent |
| Datum | Latitude and longitude are bound to WGS 84 keys. A receiver set to another datum announces it in a DTM sentence, which this pack does not read; such positions are then not WGS 84. The caller checks DTM where it matters |
| Signed magnetic variation | RMC 10 is unsigned degrees with an E or W letter in field 11; the `dm` pair transform takes degrees and minutes, not decimal degrees, so the two stay as `magvar_deg` and `magvar_dir` |
| GPS week rollover | A receiver may report a date one rollover period off (source, "Dates and times"). The pack decodes the date as sent |
| GGA quality from GPSDO devices | The source notes one vendor puts a GPSDO status in GGA 6; a non-integer there is `transform-decode` |

## Candidate additions to the pack language

1. A derive function that adds two keys, so `hae` follows from
   `nmea0183.alt_msl_m` and `nmea0183.geoid_sep_m` (GGA 9 + 11).
2. A transform, or a derive function, that makes epoch milliseconds from a time
   of day and a day, month and four-digit year in separate fields (ZDA 1 to 4),
   so ZDA yields `time_ms`.
3. A group that stops a fixed number of fields before the end of the record,
   with those fields in the enclosing scope, for the GSV signal id.

RMC with a time and no date decodes: the pair `1+9` is absent, and the second
line on field 1 carries the time of day in `nmea0183.utc_s`.
