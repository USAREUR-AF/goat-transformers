# Pack: nmea2000

NMEA 2000 parameter groups (PGNs), generated from the CANboat PGN database
(`canboat/canboat` `docs/canboat.json` at commit `1111111111111111111111111111111111111111`, CANboat 0.0.1, Apache License 2.0) by
`tools/gen/canboat2pack.py`. Do not edit `pack.def`, `model/n2k.def` or the vectors by hand;
change the generator and run it again.

Status: Built. Generated from the database; every engine runs every vector in `vectors/` in
the conformance suite.

## Message convention

An NMEA 2000 payload travels in CAN frames whose 29-bit identifier carries the PGN, and the
pack language has no CAN framing. A message of this pack is therefore:

1. 3 bytes: the PGN, little-endian;
2. the payload: the 8 data bytes of a single-frame PGN, or the payload of a fast-packet PGN
   after reassembly (sequence and frame counters and the length byte removed).

Priority, source address and destination address are not part of the message. The pack is
`wire bits`, `bit_order lsb`, `word_bytes 1`; every locator is `0:<bit offset>:<len>` and a
payload field sits at CANboat's `BitOffset` + 24. Input and output are hex text.

## What is mapped

| | Count |
|---|---|
| PGN definitions in the source | 18 |
| kinds in `pack.def` | 9 |
| distinct PGNs with at least one kind | 8 |
| mapped by pack `nmea2000-seq` (a repeating field set with a count) | 3 |
| not mapped: repeating field sets | 1 |
| not mapped: variable-length or conditionally placed fields | 1 |
| not mapped: catch-all definitions for a range of PGNs | 1 |
| not mapped: not distinguishable from another definition of the same PGN | 2 |
| not mapped: no field the pack language can carry | 1 |
| keys in module `n2k` that this pack maps | 22 |
| vectors | 17 (9 same-format round trips, 5 to `geojson`) |

One kind per fixed-layout PGN definition, named `pgn<number>`, with the CANboat definition id
appended where the source holds several definitions for that PGN. Each kind has
`when 0:0:24 <pgn>` and one more `when` per CANboat field with a fixed `Match` value
(manufacturer code, industry code, function and message codes). Kinds of one PGN are ordered
with the most matched bits first, so the first kind that holds is the most specific one.
Two definitions of one PGN are told apart only by these values: a definition whose match
values also hold for another definition's messages, with no order that separates them, has
no kind.
A `Match` field is written by its `when` line and is not a model key.

Field rules:

| CANboat field | Transform | Model type |
|---|---|---|
| NUMBER, TIME, DURATION with `Resolution` other than 1 | `uscale:<resolution>` or, when `Signed`, `sscale:<resolution>`; a decimal resolution is written as a fraction in lowest terms (1e-7 is `1/10000000`, 0.002 is `1/500`); a resolution CANboat derived from pi and printed to 13 or more digits stays a decimal | float, CANboat's unit |
| any numeric field with `Offset` | `uscale:<resolution>:<offset>` (the raw value is unsigned; value = raw x resolution + offset) | float |
| NUMBER, DATE, MMSI, PGN, ISO_NAME, ADDRESS with resolution 1 | `uint`, or `twos` when `Signed` | int |
| LOOKUP, INDIRECT_LOOKUP, BITLOOKUP, FIELD_INDEX | `uint` (the wire integer, not the lookup name) | int |
| FLOAT | `f32` | float |
| STRING_FIX | `ascii` | string |
| BINARY of 64 bits or fewer | `uint` | int |
| RESERVED, SPARE | not mapped | |

Every raw value goes to module `n2k` (`model/n2k.def`). A field id that agrees across all its
uses on model type, unit, resolution, offset and lookup table is one key (`n2k.sid`,
`n2k.wind_speed`). Where uses disagree, each PGN gets its own key `n2k.pgn<number>_<id>`, and
where definitions of one PGN disagree, `n2k.<kind name>_<id>`.

`requires` of a kind lists up to six of its `n2k` keys, those used by the fewest kinds; a kind
with no `n2k` key lists its core keys. 0 kinds share their `requires` list with another kind;
for those, an encode from another format selects the first in pack order.

## Absent values

NMEA 2000 reserves the top values of a field for "no value": all bits set for not available
and the values just below it for out of range and reserved. The database states them for each
field as raw wire integers: `UnknownValue`, `OutOfRangeValue`, `ReservedValue`. A field that
states them carries the option `absent <unknown>,<out of range>,<reserved>` (spec 0.9), in
that order, so:

- decode leaves the key absent when the raw value is one of them (an all-ones latitude is no
  latitude, not 214.7 degrees);
- encode writes the first, the not-available value, for a key the entity does not hold, where
  it wrote zero bits before.

An MMSI field also takes the raw value 0: the database's description of the MMSI field type
says devices send 0 for "none" and that it is treated as not available. A field the database
gives no such member keeps no option, whatever its type: a lookup of one or two bits uses every
value. The 64-bit numbers (the latitude and longitude of PGN 129029, for example) state no value,
since JSON cannot hold such integers exactly; for them the rule of the field type NUMBER applies
(Sentinels TopOfRange): the highest positive value is unknown and that minus one an error.
The pack uses only these statements of the database.

| Field type | Mapped fields with `absent` | Mapped fields without |
|---|---|---|
| BITLOOKUP | 0 | 1 |
| DATE | 0 | 1 |
| DURATION | 0 | 1 |
| FLOAT | 0 | 1 |
| LOOKUP | 0 | 7 |
| MMSI | 1 | 0 |
| NUMBER | 8 | 23 |
| STRING_FIX | 0 | 1 |
| TIME | 1 | 1 |

Types whose fields never carry `absent`:

| Field type | Why |
|---|---|
| FLOAT | the database names NaN for the type and no raw value; a NaN has many bit patterns |
| STRING_FIX | the database names the empty string for the type and no raw value, and allows 0x00, 0xff and `@` as padding; most such fields are longer than the 64 bits `absent` takes |
| BITLOOKUP | the database states no sentinel for the type: any combination of bits is a value |

The option needs engine version 0.9. A round trip of a message that holds an out-of-range or
reserved value returns the not-available value in its place (ruling 7 of 0.9).

## Core keys

| Kind | PGN | Core keys |
|---|---|---|
| `pgn65308` | Lab: course and height | `course` `uscale:0.005729577951308233`, `hae` `sscale:1/100` |
| `pgn129025` | Position, Rapid Update | `lat` `sscale:1/10000000`, `lon` `sscale:1/10000000` |
| `pgn129026` | COG and SOG, Rapid Update | `speed_ms` `uscale:1/100` |
| `pgn129038` | AIS Class A Position Report | `lon` `sscale:1/10000000`, `lat` `sscale:1/10000000`, `speed_ms` `uscale:1/100` |

- `lat` / `lon`: only a definition with exactly one latitude and one longitude field, ids
  `latitude` and `longitude`, in degrees at resolution 1e-7 or 1e-16. Waypoint, destination,
  station, corner and delta positions stay in `n2k`. NMEA 2000 states the datum in a separate
  PGN (129044); the pack does not read it.
- `speed_ms`: the field `sog` in m/s.
- `course`: no kind maps it. Every fixed-layout course-over-ground field either sits beside a
  reference selector (`cogReference`: true or magnetic) or has no stated reference in the
  database, so it stays `n2k.cog` in radians. The generator maps `course` with the factor
  resolution x 180/pi when a definition states a true-north reference and has no selector.
- `hae`: no kind maps it. No fixed-layout altitude field is stated to be above the WGS84
  ellipsoid (PGN 129029, in pack `nmea2000-seq`, says "referenced to WGS-84" and does not name
  the ellipsoid).

## What the pack language cannot express yet

- **"Not available" values where the database states none.** Section "Absent values"
  lists the field types whose fields carry no `absent` option, and why.
- **Reserved and spare bits.** NMEA 2000 sets them to 1; `encode` writes 0 in every bit no
  field covers. A real message with reserved bits set does not round-trip byte-identically.
- **Trailing bytes.** The message ends at the last mapped or `when` bit, rounded up to a
  byte. A definition that ends in reserved fields encodes shorter than its NMEA 2000 length
  (PGN 129026 encodes 3 + 6 bytes, not 3 + 8). Decode accepts the full length.
- **Repeating field sets and variable-length fields.** The layout of this pack is fixed
  (`layout` is pack-wide). A definition with one repeating field set whose count field stands
  directly before the set is in pack `nmea2000-seq` (spec 0.8 sequential layout). The others,
  listed below with the reason, need an addition named in `packs/nmea2000-seq/pack.md`.
- **PGN ranges.** A `when` compares for equality, so CANboat's catch-all definitions for a
  range of PGNs (proprietary ranges) have no kind.
- **CAN framing**: identifier, priority, addresses, fast-packet and ISO transport reassembly.
- **Opaque fields over 64 bits and DECIMAL fields.** 1 kinds leave such a field unmapped:

| Kind | Field | Reason |
|---|---|---|
| `pgn65303` | `signature` | BINARY of 72 bits (no transform carries more than 64 opaque bits) |
| `pgn65303` | `partNumber` | DECIMAL (two decimal digits per byte; no transform) |

- **String padding.** `ascii` strips trailing NUL bytes only and refuses bytes above 0x7E.
  NMEA 2000 devices also pad fixed strings with 0xFF or `@`; 0xFF padding is a decode error.
- **Lookup names.** Lookups are carried as integers; the pack language has no value table for
  a `bits` field.
- **64-bit unsigned values.** `uint` on a 64-bit field (ISO NAME) with the top bit set
  decodes to the negative integer with the same bit pattern.

## Kinds from definitions CANboat marks incomplete

1 of the 9 kinds come from definitions with `Complete: false` (CANboat states fields, field
lengths, resolutions or lookups may be missing or wrong). They carry `[CANboat: incomplete]`
in the comment above the kind in `pack.def`.

## Vectors

- `rt-<kind>.json`: one same-format round trip per kind. The generator packs the bytes itself
  from values inside each field's range that survive scaling exactly; unmapped bits are 0 and
  the message has the encoded length, so the round trip is byte-identical. `model` holds
  `@kind` and every decoded key.
- `x01-pgn129025-to-geojson.json`, `x02-pgn129025-south-west-to-geojson.json`, `x03-pgn129026-to-geojson.json`, `x04-pgn129026-magnetic-cog-to-geojson.json`, `x05-pgn129038-ais-class-a-to-geojson.json`: conversions to `geojson`, with the expected text
  written by hand from the canonical GeoJSON rules and checked by the generator against its
  own codec. PGN 129029 (GNSS Position Data) is in pack `nmea2000-seq`, with its own vector to
  `geojson`.
- `s01-pgn129025-latitude-not-available-roundtrip.json`, `s02-pgn129025-latitude-out-of-range-reencodes-as-not-available.json`, `s03-pgn129025-latitude-not-available-to-geojson.json`: a latitude that holds its not-available or its out-of-range value decodes to no
  `lat` (`@absent`); the out-of-range value re-encodes as the not-available one, and the
  position without a latitude has no GeoJSON geometry. The raw values are those the database
  states for the field; the expected bytes are packed by hand from them.
- `packs/geojson/vectors/gen-to-nmea2000-position-not-given.json`: the other way, a key the entity does not hold is written as its
  not-available value: a Feature with no geometry, with the `requires` keys of the AIS Class A
  position report as context, encodes latitude and longitude as all-but-the-sign-bit ones.
  The vector belongs to the pack that owns its input.

Vectors hold lowercase hex text in `input` / `expect`.

## Definitions not mapped

### Repeating field sets (1)

The Detail column names what the pack language cannot state; `packs/nmea2000-seq/pack.md`
names the addition each needs.

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 65310 | `labRouteLimits` | Lab: route limits | repeating field set whose count (field 2) is not directly before the set (field 4) |

### Variable-length or conditionally placed fields (1)

The Detail column names what the pack language cannot state; `packs/nmea2000-seq/pack.md`
names the addition each needs.

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 65305 | `labDeviceName` | Lab: device name | STRING_LAU |

### Catch-all definitions for a range of PGNs (1)

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 65280 | `labProprietaryRange` | Lab: catch-all for a proprietary range | catch-all definition for a range of PGNs |

### Not distinguishable from another definition of the same PGN (2)

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 65307 | `labAlphaReport` | Lab: report, first reading of the layout | same match values as definition labBetaReport |
| 65307 | `labBetaReport` | Lab: report, second reading of the layout | same match values as definition labAlphaReport |

### No field the pack language can carry (1)

| PGN | CANboat id | Description | Detail |
|---|---|---|---|
| 65306 | `labHeartbeatMarker` | Lab: marker with no value | fields: LOOKUP (match), RESERVED |
