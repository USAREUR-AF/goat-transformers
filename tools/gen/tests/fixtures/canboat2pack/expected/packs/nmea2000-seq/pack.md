# Pack: nmea2000-seq

NMEA 2000 parameter groups (PGNs) that hold a repeating field set, generated from the CANboat
PGN database (`canboat/canboat` `docs/canboat.json` at commit `1111111111111111111111111111111111111111`, CANboat 0.0.1, Apache License 2.0) by
`tools/gen/canboat2pack.py`, the generator of pack `nmea2000`. Do not edit `pack.def`, `model/n2k.def`
or the vectors by hand; change the generator and run it again.

Status: Built. Generated from the database; the generator checks every vector with its own
codec, written from `spec/engine-spec.md` and not from an engine.

## Why a second pack

A repeating field set needs `group <list> count <len>` of the sequential layout (spec 0.8),
and `layout` holds for a whole pack. Pack `nmea2000` stays fixed-layout and byte-identical; this
pack holds the definitions the sequential layout can state. Both use module `n2k`.
The two packs accept disjoint messages: a kind here is generated only when its match
values conflict with those of every kind of the same PGN in `nmea2000`, so a reader may try
either pack first. A fixed-layout PGN is `no-kind` here (vector `e02`).

## Message convention

As pack `nmea2000`: 3 bytes of PGN, little-endian, then the payload after fast-packet
reassembly. The lines are read in order from the first bit, least significant bit first
(`bit_order lsb`). The message ends after the last item; it is as long as CANboat's fields
make it, trailing reserved bits included.

## What is mapped

| | Count |
|---|---|
| kinds | 3 |
| distinct PGNs | 3 |
| lists in module `n2k` | 3 |
| keys added to module `n2k` by this pack | 8 |
| vectors | 12 |

| Kind | PGN | CANboat id | Description | List (one item per) |
|---|---|---|---|---|
| `pgn65304` | 65304 | `labLogEntries` | Lab: log entries | `n2k.pgn65304_entries` (entries) |
| `pgn65309` | 65309 | `labCalibrationPairs` | Lab: calibration pairs | `n2k.pgn65309_pairs` (pairs) |
| `pgn129029` | 129029 | `gnssPositionData` | GNSS Position Data | `n2k.pgn129029_reference_stations` (referenceStations) |

Each kind is:

1. `when 24 <pgn>`, then a `when` for every leading CANboat field with a fixed `Match` value.
   A reserved field between two match fields is a `when` of all ones: CANboat states that
   reserved bits shall be 1, and spec 0.8 lets only `when` lines come before a kind's other
   lines. A message whose reserved bits there are not all ones is `no-kind`.
2. The fields before the repeating set, in order. A RESERVED field is `const <len> <all ones>`
   and a SPARE field `pad <len>`, so encode writes what NMEA 2000 requires (pack `nmea2000`
   writes zeros there).
3. `group n2k.<list> count <len>`: the CANboat count field is the group's count. It is not a
   model key; encode writes the number of items.

Field transforms, key naming and `when` ordering follow pack `nmea2000` (its `pack.md`). An item
field reuses a key of module `n2k` where the key's type, unit, resolution, offset and lookup
agree; otherwise it gets a new key under the same naming rule. No existing key is renamed or
retyped. `requires` lists up to five rare top-level keys and the kind's list.

## Core keys

| Kind | Core keys | Evidence |
|---|---|---|
| `pgn129029` | `lat` `sscale:1/10000000000000000`, `lon` `sscale:1/10000000000000000` | the rule and evidence of pack `nmea2000`: CANboat fields `latitude` and `longitude`, unit `deg`, signed, resolution 1e-16; NMEA 2000 states the datum in PGN 129044, which neither pack reads |

- `hae`: not mapped. PGN 129029 describes its altitude as "referenced to WGS-84" and carries
  a separate geoidal separation; the database does not say the height is above the
  ellipsoid, so it stays a key of module `n2k`.

## Not mapped, and what each needs

Every definition with a repeating field set or a variable-length field that has no kind in
either pack, with the addition to the pack language that would state it. Fast-packet and ISO
transport reassembly stay outside both packs (layered wires and framing: designed, not built).

| PGN | CANboat id | Description | Reason | Needs |
|---|---|---|---|---|
| 65280 | `labProprietaryRange` | Lab: catch-all for a proprietary range | catch-all definition for a range of PGNs | a `when` that holds for a range of values |
| 65305 | `labDeviceName` | Lab: device name | STRING_LAU | text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) |
| 65310 | `labRouteLimits` | Lab: route limits | repeating field set whose count (field 2) is not directly before the set (field 4) | a `count` taken from a field read earlier, not from the bits at the cursor |

By addition:

| Addition | Definitions |
|---|---|
| a `when` that holds for a range of values | 1 |
| text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset) | 1 |
| a `count` taken from a field read earlier, not from the bits at the cursor | 1 |

Pack `nmea2000` also lists definitions with no field the pack language can carry, and the
limits both packs share ("not available" values, lookup names, 64-bit unsigned values).

## Vectors

- `rt-<kind>.json`: a round trip with two items; `rt-<kind>-no-items.json`: the list present
  and empty. The generator packs the bytes from CANboat's field list, not from `pack.def`,
  with values inside each field's range that survive scaling exactly, and decodes them with
  its own codec of the `pack.def` text. `model` holds `@kind`, every key, `<list>.#` and every
  item value.
- `x01-pgn129029-to-geojson.json`: GNSS Position Data at 52.5 N, 4.5 E; `expect` written by
  hand (raw / 10^16, exact in doubles) and checked against the codec.
- `e01-pgn129029-count-beyond-the-input.json`: the count states one item more than the input
  holds: `malformed-wire` (spec 0.8 ruling 14 and Errors).
- `e02-fixed-layout-pgn-is-no-kind.json`: a PGN 129025 message is `no-kind` here.
- `s01-pgn129029-time-not-available-roundtrip.json`: the position of `x01` with the time of day
  at the value the database states for not available: no time key (`@absent`), same bytes back.
  The 64-bit latitude and longitude of PGN 129029 state no such value; the NUMBER rule gives them
  `absent` at the top of their range (`s02`, `s03`).

Fields carry `absent` as in pack `nmea2000` (its section "Absent values"); the option needs
engine version 0.9.

Vectors hold lowercase hex text in `input` / `expect`.
