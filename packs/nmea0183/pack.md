# Pack: nmea0183

NMEA 0183 sentences as GNSS receivers and marine instruments emit them. Public.
Written from the gpsd project's document "NMEA Revealed" (`www/NMEA.adoc` at
gpsd commit `c59fc6de479d06620c8b2ba395b728e10a71527b`, BSD-2-Clause), which
states that the NMEA 0183 standard was not consulted in writing it. The NMEA
standard itself (and IEC 61162-1) is a priced document and was not read.
`PROVENANCE.md` has the hashes and the license.

Needs engine version 0.10 (the `text` wire). Uses the modules `core` and
`nmea0183` (`model/nmea0183.def`).

Status: Built. 74 vectors (64 here, 10 from `geojson`), derived without an
engine. The sentences GNS, HDM, HDG, THS, ROT, VHW, MWV, MWD, DBT, DPT, MTW,
TTM, TLL, OSD and DTM were added later from two other sources (pynmea2 and the
gpsd driver); section "Added sentences".

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
| `gns` … `dtm` | `0:2:3 <id>` | a key of their own (section "Added sentences") | see there |

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
| Proprietary sentences (`$P...`) other than those of section "Proprietary sentences" | They decode as the kind `proprietary`: the tag is kept whole in `nmea0183.proprietary_tag` and the other fields as residue, so they round-trip; nothing of them is mapped |
| Other sentence ids | Not in scope of this pack: `no-kind`. RSD (radar system data) is not added: neither added source lays it out |
| `!` start (AIVDM, AIVDO) | A different payload (AIS); `start "$"` refuses it as `malformed-wire` |
| Tag blocks (`\...\` before `$`) | The source does not describe them. A sentence that begins with one does not begin with `$` and is `malformed-wire`; the caller strips the tag block first |
| Maximum length of 82 characters | Not checked on decode or encode |
| `^` hexadecimal escapes (NMEA 3.01) | Not decoded; text fields hold them as sent |
| Datum | Latitude and longitude are bound to WGS 84 keys. A receiver set to another datum announces it in a DTM sentence. The pack decodes DTM (kind `dtm`, raw keys) but does not apply it to other sentences' positions; such positions are then not WGS 84. The caller checks DTM where it matters |
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

## Added sentences

Fifteen kinds, added after the first edition, laid out from two sources that
are not the one above (`PROVENANCE.md`, "Added sentences"): the field order
from pynmea2 (`pynmea2/types/talker.py`, MIT) and the units and meanings from
gpsd's NMEA driver (`drivers/driver_nmea0183.c`, BSD-2-Clause) where it handles
the sentence (GNS, HDM, HDG, THS, ROT, MWV, MWD, DBT, DPT, MTW, DTM). For VHW,
TTM, TLL and OSD, which the driver does not handle, the meaning rests on
pynmea2's field names. They follow the conventions above: any talker, the
sentence id in columns 2-4, positions with five minute decimals, unit letters as
`const`, and the keys of the first edition where the meaning is the same
(`utc_s`, `status`, `sats_used`, `hdop`, `alt_msl_m`, `geoid_sep_m`,
`dgps_age_s`, `dgps_station`, `heading_true_deg`, `magvar_deg`, `magvar_dir`).

| Kind | Fields | Shared keys |
|---|---|---|
| `gns` | time, latitude, longitude, mode letters (one per constellation), satellites used, HDOP, MSL altitude, geoid separation, DGPS age, DGPS station | `lat`, `lon` |
| `hdm` | magnetic heading, `M` | none |
| `hdg` | sensor heading, deviation and its side, variation and its side | none |
| `ths` | true heading, mode letter | none |
| `rot` | rate of turn (degrees per minute, negative to port), status | none |
| `vhw` | true heading, `T`, magnetic heading, `M`, speed through water in knots, `N`, and in km/h, `K` | none |
| `mwv` | wind angle, reference (relative or true), speed, unit letter, status | none |
| `mwd` | wind direction true, `T`, magnetic, `M`, speed in knots, `N`, and in m/s, `M` | none |
| `dbt` | depth below the transducer in feet, `f`, metres, `M`, fathoms, `F` | none |
| `dpt` | depth relative to the transducer, transducer offset, range scale (optional) | none |
| `mtw` | water temperature, unit letter | none |
| `ttm` | number of the target, distance, bearing and its reference, speed, course and its reference, CPA distance and time, distance unit, name, status, reference flag, time, acquisition type | `callsign` (target name) |
| `tll` | number of the target, latitude, longitude, name, time, status, reference flag | `lat`, `lon`, `callsign` |
| `osd` | heading, status, course and reference, speed and reference, set, drift, speed unit | none |
| `dtm` | local datum, subdivision, latitude and longitude offsets in minutes, altitude offset, reference datum | none |

Evidence for the shared keys of these kinds: GNS and TLL positions are degrees
and minutes with a hemisphere letter, as in GGA (gpsd driver; pynmea2 names TLL
fields 2-5 as the latitude and longitude of the target and their directions), with the
datum as for the first edition. TTM 11 and TLL 6 are "Target Name" in pynmea2:
a human-readable name, `callsign`.

Not bound: headings (a heading is not the course over ground); speed through
the water (not over ground); TTM and OSD speed and course, whose unit and
true-or-relative reference are other fields of the sentence; the number of the target
(an integer, `uid` is a string). The `requires` of each added kind names one of
its own keys, so an entity from another format still becomes RMC or GGA.

Vectors 44-64 are written by `tools/gen/nmea0183-more-vectors.py` (standard
library only, no pack read, no engine run; `--check` compares them with the
tree): a round trip of every added kind, DPT without its optional field, GNS and
TLL to GeoJSON, TLL to CoT, TTM to GeoJSON (no position, name as callsign), and
60 minutes in a TLL position (`transform-decode`). Vectors 01-43 are not
written by it.

## Proprietary sentences

Version 0.2.0 of the pack adds the vendor sentences that gpsd's NMEA driver
parses, with layouts and meanings restated from `drivers/driver_nmea0183.c`
(gpsd, BSD-2-Clause, commit `c59fc6de479d06620c8b2ba395b728e10a71527b`): the
comment above each handler names the fields, and the code shows which field it
reads and how. Every sentence and value in the vectors is written for them.

### Tag and kinds

A proprietary sentence starts `$P`, then a three-letter manufacturer code
(`GRM` Garmin, `ASH` Ashtech, `MTK` MediaTek, `SRF` SiRF, `STI` SkyTraq, `TNT`
True North and iSync, `QTM` Quectel) and the vendor's sentence name; the tag is
4 to 7 characters (`PSTI`, `PGRME`, `PMTK001`, `PTNTHTM`, `PQTMGPS`). It has no
two-character talker id. Convention:

- Each vendor kind selects on the whole tag, `when 0 <tag>`, and also on field
  1 where the vendor writes a sentence number or type there (`PSTI,030`,
  `PASHR,POS`), or on a fixed field (`PTNTA` field 3 `T4`).
- Each maps the whole tag to `nmea0183.proprietary_tag` and lists it in
  `requires`: an entity from another format has no tag, so an encode from
  another format still selects RMC, GGA or VTG.
- After them the kind `proprietary` (`when 0:0:1 P`) takes every other `$P`
  sentence, keeping the tag and the other fields as residue.
- These kinds stand before the standard kinds. A standard kind selects on
  columns 2-4 of the tag, and a proprietary tag can hold one of its ids there
  (Garmin `PGRMC` holds `RMC`); taken first, a `$P` sentence never reaches a
  standard kind. A standard tag never begins with `P`, so the standard
  sentences decode as before (vectors 01-64 unchanged, but for vector 35, below).
- The common talker column `0:0:2` still reads the first two characters of a
  proprietary tag (`PG` for `PGRME`); it holds no talker there.

Vector 35 decoded `$PGRME` as `no-kind` before 0.2.0; it now decodes as
`pgrme`, and its `expect` is the sentence itself.

| Kind | `when` | Fields | Shared keys |
|---|---|---|---|
| `pashr-pos` | `0 PASHR`, `1 POS` | position type, satellites used, time, position, height, track, speed km/h, climb, PDOP, HDOP, VDOP, TDOP | `lat`, `lon`, `hae` |
| `pashr-sat` | `0 PASHR`, `1 SAT` | satellite count, then five fields per satellite (PRN, azimuth, elevation, signal, `U` if used) | none |
| `pashr-rid` | `0 PASHR`, `1 RID` | receiver type, firmware version | none |
| `pgrme` | `0 PGRME` | horizontal, vertical and spherical error estimates, each with the unit `M` | none |
| `pgrmf` | `0 PGRMF` | GPS week, GPS seconds, UTC date, UTC time, leap seconds, position, mode, fix type, speed km/h, course, PDOP, TDOP | `time_ms`, `lat`, `lon`, `course` |
| `pgrmm` | `0 PGRMM` | map datum name | none |
| `pgrmt` | `0 PGRMT` | product text and eight status fields | none |
| `pgrmv` | `0 PGRMV` | velocity east, north, up | `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` |
| `pgrmz` | `0 PGRMZ` | altitude in feet, the unit `f`, fix mode | none |
| `pmtk001` | `0 PMTK001` | command number, result flag | none |
| `pmtk424` | `0 PMTK424` | TSIP, antenna detect, PPS, PPS timing, duration of the PPS pulse | none |
| `psrfepe` | `0 PSRFEPE` | time, status, HDOP, four error estimates | none |
| `psti030` | `0 PSTI`, `1 030` | time, status, position, altitude above mean sea level, velocity east/north/up, date, mode, RTK age and ratio | `time_ms`, `lat`, `lon`, `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` |
| `psti032`, `psti035` | `0 PSTI`, `1 032` or `035` | time, date, status, RTK mode, baseline east/north/up, length, course; fields 11-15 are reserved and not mapped | `time_ms` |
| `psti036` | `0 PSTI`, `1 036` | time, date, heading, pitch, roll, mode | `time_ms` |
| `ptnta` | `0 PTNTA`, `3 T4` | date-time text, oscillator quality, PPS interval, fine phase, status, GPS message and transfer quality codes | none |
| `ptnthtm` | `0 PTNTHTM` | heading, pitch, roll, dip and horizontal field, each with a status letter where the driver names one | none |
| `pqtmgps` | `0 PQTMGPS` | uptime, time of week, latitude and longitude in degrees, height above the ellipsoid, altitude above mean sea level, ground speed, heading, accuracy, HDOP, PDOP, fix type, satellites | `lat`, `lon`, `hae`, `speed_ms` |
| `pqtmins` | `0 PQTMINS` | uptime, solution type, latitude and longitude in degrees, height, velocities, roll, pitch, heading | `lat`, `lon` |
| `pqtmimu` | `0 PQTMIMU` | uptime, three accelerations in g, three angular rates in degrees per second, wheel ticks, time of the last tick | none |
| `proprietary` | `0:0:1 P` | the tag; other fields as residue | none |

### Evidence for the shared keys

| Key | Where | Evidence in the driver |
|---|---|---|
| `lat`, `lon` | PASHR,POS 5-8; PGRMF 6-9; PSTI,030 4-7 | read with the driver's common latitude/longitude reading of degrees, minutes and hemisphere letter, as for GGA and RMC (the datum note of "Not mapped" applies) |
| `lat`, `lon` | PQTMGPS 3-4; PQTMINS 3-4 | the comments name them "Latitude. Degrees" and "Longitude. Degrees": decimal degrees, `float` |
| `hae` | PASHR,POS 9 | the driver stores it as the height above the ellipsoid, with the comment "altitude is already WGS 84" |
| `hae` | PQTMGPS 5 | the comment gives field 5 as the height relative to the ellipsoid, in metres |
| `time_ms` | PGRMF 4+3; PSTI,030 2+12; PSTI,032/035/036 2+3 | the comments name UTC time hhmmss and UTC date ddmmyy; the driver joins them into the fix time |
| `course` | PGRMF 13 | "Course over ground, 0 to 359 degrees true" |
| `speed_ms` | PQTMGPS 7 | "Ground speed (2D). Meters / sec" |
| `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` | PGRMV 1-3; PSTI,030 9-11 | "true east velocity, m/s", "true north velocity, m/s", "true up velocity, m/s"; PSTI,030 "East Velocity meters/sec" and the like, stored as the fix's east/north/up velocity |
| `nmea0183.sog_kmh` | PASHR,POS 12; PGRMF 12 | the driver divides by its km/h-per-m/s constant (PASHR) and the comment says "0 to 1151 km/hr" (PGRMF); the module derives `speed_ms` from it |

Not bound, on purpose: PASHR,POS track and the PSTI,036 and PQTM headings (the
driver does not say true or magnetic); PGRME and PSRFEPE error estimates (the
driver says the vendors do not state the confidence level, and `ce` / `le` are
not defined at an unknown one); PGRMZ altitude (feet, read by gpsd as above
mean sea level), PSTI,030 field 8 (above mean sea level) and PQTMINS height
(the comment asks "HAE?, MSL?"); PQTMINS velocities (no unit stated);
PTNTHTM angles (integers in the compass's own units, kept as text).

### Left out

| Sentence | Why |
|---|---|
| `PASHR` in the OxTS form (field 3 `T`) | the driver guesses it from field 3 being `T` and marks the decoding FIXME; its fields collide with the Ashtech sentence types. A `$PASHR` of this form decodes as `proprietary` |
| `PMGNST` (Magellan) | the comment numbers the mode as field 2 and the fix flag as field 3, the code reads fields 3 and 4: the layout is ambiguous |
| `PMTK705` | field 3 is a date code for one vendor and a product model for another, and field 4 is present for one only |
| `PSTI,033` | the comment and the code disagree on which field holds the L1 count and on the BDS fields |
| `PUBX` (u-blox) | the driver lists it with no handler: it gives no layout |
| `PGRMB`, `PGRMC`, `PGRMH`, `PGRMI`, `PGRMO`, `PMTK010`, `PMTK011`, `PSRF140`-`155`, `PSTI,000/001/005`, `PEMT`, `PERD...`, `PJLT...`, `PSSN`, `PSXN`, `PTNI`, `PTKM`, `PRWIZCH`, `PSTM`, `PTFTTXT`, `PTNLRHVR`, `PTNLRPT`, `PTNLRSVR`, `PTNLRZD` | listed by the driver with no handler, so no layout |
| `PERC...`, `PAIR...`, `PDTINFO`, `PGLOR`, `PGPSP`, `PSTMCPU`, `PSTMANTENNASTATUS`, `PSTMVER`, `PTNLRBA`, `PTNLRNM`, `PTNLRTP`, `PTNLRXO`, `PQTMVER`, `PQVERNO`, `PQTM...ERROR/OK`, `PRHS` | handled by the driver but not added here; candidates for a later addition |

All of these decode as `proprietary`.

Vectors `v01`-`v28` are written by `tools/gen/nmea0183-vendor-vectors.py`
(standard library only, no pack read, no engine run; `--check` compares them
with the tree): a round trip of every vendor kind, PASHR,SAT numbers rewritten
in the form `int` writes, PSTI,032 with its empty reserved fields dropped,
PASHR,POS, PGRMF, PGRMV and PQTMGPS to GeoJSON, and `$PGRMC`, `$PASHR,ACK` and
`$PUBX` as `proprietary`.
