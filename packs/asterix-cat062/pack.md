# Pack: asterix-cat062

ASTERIX Category 062, System Track Data: one data block holding one record.
Public. Written from EUROCONTROL-SPEC-0149-9, "EUROCONTROL Specification for
Surveillance Data Exchange ASTERIX Part 9 Category 062, SDPS Track Messages",
Edition 1.21, 5 June 2025
(https://www.eurocontrol.int/sites/default/files/2025-06/asterix-cat062-system-track-data-p9-ed1-21.pdf,
read on 2026-11-16, sha256 `37c3898824323e915c3bd83fdf20419939f3276d802733bae690a1875d29db96`). The items mapped are the ones the
CAT062 encoder of `USAREUR-AF/open-billie` writes
(`runtime/rust/translator/src/cat062.rs`, Apache-2.0, commit `19fccdb`); the
blocks that encoder produces are the pack's vectors. I/O is hex text. Needs
engine version 0.8 (`layout sequential`).

Uses the modules `core`, `track` and `cat062` (`model/cat062.def`).

## Layout

`layout sequential`, `bit_order msb`. One kind, `track`.

| Part | Lines | Model |
|---|---|---|
| CAT, one octet | `when 8 62` | selects the kind; another category is `no-kind` |
| LEN, two octets | `length 16 whole` | the block length in octets, CAT and LEN included; written on encode, and on decode input beyond it is not read |
| FSPEC | `presence fspec fx` | bit n is FRN n of the UAP (section 5.3, Table 1) |
| FRN 1, I062/010 | two 8-bit fields | `cat062.sac`, `cat062.sic` |
| FRN 4, I062/070 | 24 bits, `uscale:1/128` | `cat062.time_of_day_s`, seconds since UTC midnight |
| FRN 5, I062/105 | two signed 32-bit fields, `sscale:180/33554432` | `lat`, `lon`, degrees |
| FRN 7, I062/185 | two signed 16-bit fields, `sscale:1/4` | `track.vel_east_ms` (Vx), `track.vel_north_ms` (Vy; the y-axis points to geographical north) |
| FRN 12, I062/040 | 16 bits | `cat062.track_number` |
| FRN 13, I062/080 | a `chain`: the first part and six extents | below |
| FRN 18, I062/130 | signed 16 bits, `sscale:381/200` | `hae`, metres |

I062/130 is the "vertical distance between the target and the projection of
its position on the earth's ellipsoid, as defined by WGS84", in steps of
6.25 ft. 6.25 ft is 1.905 m exactly; the pack writes the factor as the
fraction `381/200`, so `hae` holds metres.

### Track status, I062/080

Each mapped bit is a `field` on its raw key; where `track` has a flag of the
same meaning an `also` line binds the flag to the same bit. Decode fills both.
Encode writes the raw key when the entity has it, else the flag, else the
flag's default.

| Bit | Raw key | Flag | Default |
|---|---|---|---|
| MON, first part | `cat062.mon` (1 = monosensor track) | none | 1 |
| MRH, first part | `cat062.mrh` (1 = geometric height more reliable) | none | 0 |
| CNF, first part | `cat062.cnf` (0 = confirmed, 1 = tentative) | `track.confirmed`, through the table `cnf`, which turns the value over | none: the kind requires `track.confirmed` |
| SIM, first extent | `cat062.sim` | `track.simulated` | 0 |
| TSE, first extent | `cat062.tse` | `track.final_update` | 0 |
| CST, third extent | `cat062.cst` | `track.coasting` | 0 |
| every other bit | `pad`: dropped on decode, written 0 | | |

A key with a default counts as present, so encode always writes the first
part and three extents.

MRH is written as `cat062.mrh` gives it, 0 when the entity does not have it.
The caller sets it as context (vector 39 of `canonical-track-v2`).
open-entity-gateway writes MRH 1 whenever it sends I062/130; the pack follows
that rule once a derive function can set an integer key from the presence of
`hae` ("Conditional output and flag tokens" in `docs/roadmap.md`, Designed). The fourth, fifth and sixth extents hold no mapped
bit; they are read, and not written.

## Items not mapped

No `if` block names these FSPEC bits. A record with one of them set fails to
decode with `malformed-wire`, and encode never sets them.

| FRN | Item |
|---|---|
| 2 | spare |
| 3 | I062/015 Service Identification |
| 6 | I062/100 Calculated Track Position (Cartesian) |
| 8 | I062/210 Calculated Acceleration (Cartesian) |
| 9 | I062/060 Track Mode 3/A Code |
| 10 | I062/245 Target Identification |
| 11 | I062/380 Aircraft Derived Data |
| 14 | I062/290 System Track Update Ages |
| 15 | I062/200 Mode of Movement |
| 16 | I062/295 Track Data Ages |
| 17 | I062/136 Measured Flight Level |
| 19 | I062/135 Calculated Track Barometric Altitude |
| 20 | I062/220 Calculated Rate Of Climb/Descent |
| 21 | I062/390 Flight Plan Related Data |
| 22 | I062/270 Target Size & Orientation |
| 23 | I062/300 Vehicle Fleet Identification |
| 24 | I062/110 Mode 5 Data reports & Extended Mode 1 Code |
| 25 | I062/120 Track Mode 2 Code |
| 26 | I062/510 Composed Track Number |
| 27 | I062/500 Estimated Accuracies |
| 28 | I062/340 Measured Information |
| 29 to 33 | spare |

I062/RE (FRN 34) and I062/SP (FRN 35) are explicit-length items: the first
octet is the length of the item, itself included. The pack reads them over by
that length, so a record that carries them decodes; their content is not
mapped and encode does not write them (vectors 15 and 16). A record that sets
any FRN of the table above still fails; `asterix-cat062-full` decodes every
item of the category and is the pack to read such records with.

A data block that holds more than one record: the first record is read and
the rest of the block is not.

## Converting to this pack

The kind requires `cat062.sac`, `cat062.sic`, `cat062.time_of_day_s`,
`cat062.track_number` and `track.confirmed`: the specification requires
I062/010, I062/040, I062/070 and I062/080 in every record. An entity without
them fails with `no-kind`.

| Key | Where it comes from |
|---|---|
| `cat062.sac`, `cat062.sic` | the caller, as context (`--set`, a vector's `context`): the operator of the sending system assigns them |
| `cat062.time_of_day_s` | derived from `time_ms` (`day_seconds`) |
| `cat062.track_number` | derived from `uid` when it is a decimal number (`parse_int`); another `uid` leaves it absent |
| `cat062.sim` | derived: 1 when any of `track.simulated`, `track.header_simulated` and `track.test_data` that is present is not 0 (`any`) |

The derive lines are in `model/cat062.def`, which uses the module `track`.

## Compared with the open-billie encoder

Vectors 24 to 29 of `canonical-track-v2` convert the track of the encoder's
tests, and variants of it, to this pack, with SAC and SIC as the only context.
Each gives the block the encoder writes, byte for byte.

| Track | Octets |
|---|---|
| the `sample()` track (vector 24) | 31 |
| simulated, not confirmed, coasting, final update (25) | 31 |
| no velocity, no altitude (26) | 24 |
| track 4095 at 23:59:59.250, position 56.9496 24.1052, altitude -100 m, velocity 250.75 east -3.5 north (27) | 31 |
| `headerSimulated` true, `simulated` false, southern and western position (28) | 27 |
| every optional flag absent (29) | 24 |

Where the two differ:

- The encoder refuses a track number above 4095, a longitude of 180 and an
  altitude outside -1500 to 150000 ft. The pack writes any value its field
  holds: a track number to 65535, a longitude of 180 as 2^25, an altitude to
  the 16-bit limit.
- A time within 1/256 s before midnight rounds to 86400 s. The encoder wraps
  it to 0; the pack writes 11059200.
- Position: the pack computes `x * 2^25 / 180` and the encoder
  `x * (2^25 / 180)`; a value that lies on a rounding boundary can differ by
  one unit.
