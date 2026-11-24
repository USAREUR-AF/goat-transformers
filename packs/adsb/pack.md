# Pack: adsb

ADS-B on Mode S Extended Squitter: the 112-bit downlink format 17 message.
Public. Field layouts are from "The 1090 Megahertz Riddle" (Junzi Sun, second
edition, https://mode-s.org/1090mhz/), which documents ICAO Annex 10 Volume IV,
ICAO Doc 9871 and RTCA DO-260B. I/O is hex text (`spec/engine-spec.md`, bits
wire). Needs engine version 0.15 (`chars:icao6`; 0.9 `absent`; kinds, `bit_order`, fields past their word).

Uses the modules `core` and `adsb` (`model/adsb.def`). `pack.def` is maintained
by hand.

## The one `core` key: `callsign`

Every field decodes to a raw unsigned integer in the `adsb` module, and the
identification message's characters also give `callsign` (below). Position,
altitude, speed and course each need a decoding step the pack language does
not have, listed under "Kept raw" below. A conversion from `adsb` to
`geojson` therefore produces a feature with `null` geometry and, for an
identification message, the callsign.

The 24-bit ICAO address is `adsb.icao`, an integer. It is not mapped to `uid`,
which is a string.

## Addressing

`word_bytes 1`, `bit_order msb`. A locator is `0:<bit offset>:<len>`; offset 0
is the first transmitted bit and a value is read most significant bit first.
The source tables number bits from 1: message bit *n* is offset *n* - 1, and
bit *n* of the 56-bit ME field is offset 31 + *n*.

## Frame (common lines)

| Bits | Field | Line |
|---|---|---|
| 1-5 | downlink format | `when 0:0:5 17` and `adsb.df` |
| 6-8 | capability | `adsb.ca` |
| 9-32 | ICAO address | `adsb.icao` |
| 33-88 | ME, starting with the 5-bit type code (`when` and `adsb.tc` in every kind) | per kind |
| 89-112 | parity / interrogator ID | `adsb.parity` |

`adsb.parity` is carried as received so that a real message round-trips
byte-identically. The pack does not compute or check parity: an entity whose
fields were changed encodes with a stale parity value. Addition: a checksum
directive (`crc <locator> <polynomial> over <range>`) written on encode and
checked on decode.

Downlink format 18 (ADS-B from equipment that cannot be interrogated, TIS-B)
uses the same ME layouts but fails the common `when`: `no-kind` (vector
`df18-no-kind`). It is the pack `adsb-df18`, with the same layouts and the
module `adsb`.

## Kinds

32 kinds. Every kind maps all 112 bits, reserved bits included, so every
message of a mapped kind round-trips byte-identically.

| Kinds | Type code | Second `when` | Content |
|---|---|---|---|
| `identification-tc1` ... `-tc4` | 1-4 | | category, eight 6-bit callsign characters |
| `surface-position-tc5` ... `-tc8` | 5-8 | | movement code, track status, track, time bit, CPR format, CPR latitude and longitude |
| `airborne-position-baro-tc9` ... `-tc18` | 9-18 | | surveillance status, single antenna flag, 12-bit altitude code, time bit, CPR format, CPR latitude and longitude |
| `airborne-velocity-ground-st1`, `-st2` | 19 | subtype 1, 2 | east-west and north-south sign and magnitude, vertical rate, GNSS-barometric altitude difference |
| `airborne-velocity-air-st3`, `-st4` | 19 | subtype 3, 4 | magnetic heading, airspeed type and airspeed, vertical rate, altitude difference |
| `airborne-position-gnss-tc20` ... `-tc22` | 20-22 | | as airborne position, with 12-bit GNSS height in meters |
| `aircraft-status-emergency` | 28 | subtype 1 | emergency state, 13-bit Mode A code |
| `target-state` | 29 | subtype 1 (2 bits) | selected altitude, barometric setting, selected heading, accuracy and integrity indicators, autopilot mode bits |
| `operational-status-airborne` | 31 | subtype 0 | capability class, operational mode, version, accuracy and integrity indicators |
| `operational-status-surface` | 31 | subtype 1 | surface capability class, length/width code, operational mode, version, indicators |
| `acas-ra-no-threat-identity` | 28 | subtype 2, threat type 0 | ACAS resolution advisory: seven advisory flags, the ACAS III bits, four complement flags, terminated, multiple threat, threat type indicator, the 26 unused identity bits |
| `acas-ra-threat-address` | 28 | subtype 2, threat type 1 | the same, then the threat's 24-bit address and 2 reserved bits |
| `acas-ra-threat-position` | 28 | subtype 2, threat type 2 | the same, then the threat's 13-bit altitude code, 7-bit range and 6-bit bearing |

The three `acas-ra-*` kinds are laid out from pyModeS alone
(`decoder/bds/bds61.py`: subtype 2 carries bits 8-55 of the BDS 3,0 register;
`decoder/bds/bds30.py`: the place of each flag and of the threat identity for
each indicator). The threat type indicator is a third `when` and the field
`adsb.tti`. Indicator 3, which pyModeS names reserved, is `no-kind` (vector
`acas-ra-threat-type-3-no-kind`). pyModeS has no published message of this
subtype; the vectors are constructed, and what `tools/gen/adsb-vectors.py` writes was compared
with pyModeS's own decoding of the same messages (`PROVENANCE.md`).

**One kind per type code.** `when` compares for equality, and a type code
range (9-18) is ten values, so each value is its own kind with the same field
lines. The type code is also the model key `adsb.tc`, a field over the same
bits as the `when`. On encode the `when` value is written after the fields, so
the selected kind decides the type code on the wire, not `adsb.tc`.
Consequence: kinds that share a layout share their `requires`, so a
cross-format encode would select the lowest type code of the group whatever
`adsb.tc` holds. No other pack produces `adsb` keys, so this does not occur
today. Addition that removes both the repetition and the ambiguity:
`when <locator> <low>..<high>` (or a value list), giving one kind per layout
in which the `adsb.tc` field alone sets the type code.

The operational status kinds use the ADS-B version 2 field names. A version 1
message has the same bit boundaries: `adsb.gva` then holds the barometric
altitude quality and `adsb.sil_supp` a reserved bit. The meaning of the
indicator fields depends on `adsb.version`, a value in the same message. A version 0
message has other fields at these bits (the book's first operational status table: capability and status codes by
phase of flight, then reserved bits), and the pack does not choose by version: its names do not apply to it.

Type code 29 subtype 1 and type code 28 subtype 1 are not laid out bit by bit
in the book. Their layouts are RTCA DO-260B's, checked here against published
messages with published decoded values (vectors 41-43).

## Kept raw, and what would convert it

| Value | Keys | Why it is raw | Addition that would map it |
|---|---|---|---|
| Position | `adsb.cpr_lat`, `adsb.cpr_lon`, `adsb.cpr_odd` | Compact Position Reporting: 17-bit fractions of a latitude or longitude zone. A position needs an even and an odd message from the same aircraft within about ten seconds, or one message and a reference position within 180 NM (45 NM on the surface). One message alone has no position. | Not a pack-language feature: a stateful stage outside the pack that pairs messages by `adsb.icao` and emits `lat` / `lon`. The pack gives that stage its inputs. |
| Barometric altitude | `adsb.alt_baro_raw` | 12 bits with the Q bit in the middle. Q = 1: remove it, the 11 remaining bits x 25 ft - 1000 ft. Q = 0: a Gray code in 100 ft steps. Barometric altitude is also not `hae`. | A transform that removes a bit and scales (`bitdrop:<index>` then `uscale`), a Gray-code transform for Q = 0, and a `when` on the Q bit to choose. The result belongs in a pressure-altitude key, not `hae`. |
| GNSS height | `adsb.gnss_height_m` | Whole meters, linear. The source says "the height of aircraft in meters" from GNSS and does not name the datum, so it is not mapped to `hae`. | None: `uscale:1` to `hae` once the datum is confirmed from DO-260B. Without `lat` / `lon` the GeoJSON geometry stays `null` either way. |
| Ground velocity | `adsb.ew_sign`, `adsb.ew_raw`, `adsb.ns_sign`, `adsb.ns_raw` | Sign bit and magnitude, magnitude offset by one (speed = raw - 1 kt, raw 0 = no information), scale x 4 in subtype 2. | A sign-magnitude transform with factor and offset, for example `smscale:<factor>:<offset>` over the 11 bits, plus an "absent value" argument: gives `track.vel_east_ms` and `track.vel_north_ms` (factor 0.514444, x 4 in the subtype 2 kinds). `speed_ms` and `course` need a two-field polar conversion on top. |
| Vertical rate | `adsb.vr_sign`, `adsb.vr_raw` | Sign-magnitude, 64 x (raw - 1) ft/min. | The same sign-magnitude transform (factor 0.32512 m/s): `track.vel_up_ms`. |
| Surface ground speed | `adsb.movement_raw` | A piecewise table: seven ranges with steps from 0.125 kt to 5 kt. | A lookup or piecewise-linear transform (`lookup:<table>`), yielding `speed_ms`. |
| Surface track | `adsb.track_raw`, `adsb.track_valid` | Linear (x 360/128 degrees) but only meaningful when the status bit is 1. | `uscale:2.8125` to `course` works today; it is held back because the language cannot make a field absent on another field's value. Addition: a field condition (`field ... if <locator> <value>`). |
| Magnetic heading | `adsb.heading_raw`, `adsb.heading_valid` | Linear (x 360/1024) with a status bit; magnetic, and `course` is degrees true. | The field condition above, and a magnetic-heading key. |
| Mode A code | `adsb.squawk_raw` | 13 bits in the order C1 A1 C2 A2 C4 A4 X B1 D1 B2 D2 B4 D4; the four octal digits are interleaved. | A bit-permutation transform, or a named `squawk` transform yielding a string. |
| Aircraft category | type code and `adsb.category` | The category is the pair (type code, 3-bit code). | `typemap` or a lookup keyed on two values, yielding `type`. |
| Selected altitude, barometric setting, selected heading | `adsb.sel_alt_raw`, `adsb.baro_setting_raw`, `adsb.sel_heading_*` | Linear with an offset of one and zero meaning "no information": 32 x (raw - 1) ft, 800 + 0.8 x (raw - 1) hPa, raw x 180/256 degrees plus a sign bit. | `uscale` with an "absent value" argument covers the first two (`uscale:32:-32`, `uscale:0.8:799.2`) into new `adsb` float keys; no `core` key exists for them. |

## Not mapped

- Type code 0 (no position information), 23-27 (reserved, test), 30:
  `no-kind` (vector `type-code-0-no-kind`).
- Type code 28 subtypes 0 and 3-7.
- Type code 29 subtype 0 (ADS-B version 1 target state). pyModeS
  (`decoder/bds/bds62.py`) parses subtype 0 with the subtype 1 layout as a
  fallback and says a caller can ignore the result; that is not a statement of
  the subtype 0 layout, and no other public source with a usable license lays
  it out, so it is not mapped.
- Type code 31 subtypes 2-7 (reserved).
- Type code 19 subtypes 0 and 5-7 (reserved).
- Downlink formats other than 17 (18 is the pack `adsb-df18`).

## "Not available" values (engine-spec 0.9)

Version 0.2 of the pack marks the raw values pyModeS's decoders read as not
available with the field option `absent`: decode gives no key, and an entity
without the key writes the first value listed.

| Keys | `absent` | pyModeS |
|---|---|---|
| `adsb.movement_raw` | 0, 125, 126, 127 | `decoder/bds/bds06.py`: movement 0 or above 124 |
| `adsb.ew_raw`, `adsb.ns_raw`, `adsb.vr_raw`, `adsb.airspeed_raw` | 0 | `decoder/bds/bds09.py`: a magnitude of 0 |
| `adsb.galt_diff_raw` | 0, 127 | `decoder/bds/bds09.py`: difference 0 or 127 |
| `adsb.sel_alt_raw`, `adsb.baro_setting_raw` | 0 | `decoder/bds/bds62.py`: N/A |
| `adsb.threat_range_raw`, `adsb.threat_bearing_raw` | 0 | `decoder/bds/bds30.py`: range or bearing 0 |

A message holding 127 or 125-126 in such a field is written back with the
first value, 0 (engine-spec 0.9 ruling 7); no vector of version 0.1 holds one.
The keys stay raw: the sign-and-magnitude and piecewise values still need the
transforms listed under "Kept raw".

## `callsign` (engine-spec 0.15)

In the four identification kinds (type codes 1-4) the eight 6-bit characters,
ME bits 9-56 (`0:40:48`), are also read as the core key `callsign` with
`chars:icao6`, on a line before the eight raw keys `adsb.cs_c1` ... `adsb.cs_c8`,
which stay. Evidence: pyModeS `_callsign.py` builds the alphabet of the field:
codes 1-26 are `A`-`Z`, 32 is space, 48-57 are `0`-`9`, and every other code is
invalid; `callsign` is a human-readable name. Decode removes trailing spaces
(the transform's rule for `icao6`); encode pads with spaces. A character code
outside the set is `transform-decode`, so such a message no longer decodes at
all (vector `identification-character-outside-the-set`).

The callsign line comes first, so on encode it wins over the raw characters
where both are present (ruling 5 of 0.5). `identification-tc4` now requires
`adsb.icao` and `callsign`, so an entity from another format that has a
callsign, with the 24-bit address supplied as context (`--set
adsb.icao=<integer>`), is written as type code 4 with category 0. The pack
does not compute the parity: such a message carries parity 0 and is not
valid on the air; the caller computes it.

## Vectors

53 vectors under `vectors/`, and one under `packs/geojson/vectors/to-adsb-*`.
Vectors 01-04 and 46 on are written by `tools/gen/adsb-vectors.py` (`--check`
compares them with the tree); 05-45 are maintained by hand.

| Vectors | Content | Source |
|---|---|---|
| 01-29 | one same-format round trip per kind, byte-identical; parity computed by the generator with the Mode S generator polynomial so each frame is self-consistent | constructed |
| 30-43 | 14 published messages: the kind selected, raw values pinned, byte-identical round trip | `"source": "specification"`; each `reference` names the book chapter or the pyModeS test file |
| 44 | published DF18 message, `expect_error: no-kind` | pyModeS `tests/test_adsb.py` |
| 45 | type code 0, `expect_error: no-kind` | constructed |
| 46-48 | one same-format round trip per `acas-ra-*` kind, parity computed as for 01-29 | constructed |
| 49 | threat type indicator 3, `expect_error: no-kind` | constructed |
| 50 | airborne velocity with east-west and vertical-rate magnitude 0 and GNSS-baro difference 127: no keys for them; 127 written back as 0 | constructed |
| 51, 52 | the published KLM1023 identification to GeoJSON and to CoT: the callsign carried | book, chapter 2 |
| 53 | the identification round trip of version 0.2, whose characters lie outside the ICAO set: `transform-decode` | constructed |
| `geojson/vectors/to-adsb-callsign-to-identification-geojson` | a GeoJSON callsign with the address in the context, written as type code 4 | constructed |

Vectors 01-04 were rewritten for version 0.3: their characters were any
6-bit numbers and are now letters and digits, with the parity recomputed.

Before writing vectors 30-43 the generator decodes each published message
with the pack and checks the raw values against the published decoded values
(callsign `KLM1023` and `EZY85MH`, altitude 38000 ft and 39000 ft, CPR values
93000 / 51372 and 74158 / 50194, ground speed 159 kt on track 182.88 with
vertical rate -832 ft/min, airspeed 375 kt on heading 243.98, squawk `6513`,
selected altitude 16992 ft, barometric setting 1012.8 hPa, selected heading
66.8 and 246.8), using decoders that exist only in the generator. For 13 of
the 14 it also checks that the parity field equals the remainder of the first
88 bits. Vector 43 is a published one-bit variant of vector 42 whose parity
the source leaves unchanged.
