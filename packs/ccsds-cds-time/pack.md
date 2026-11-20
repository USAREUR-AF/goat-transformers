# Pack: ccsds-cds-time

The CCSDS Day Segmented Time Code (CCSDS 301.0-B-4, Time Code Formats, sections
3.1 and 3.3) with an explicit P-field: a 16- or 24-bit day count, 32-bit
milliseconds of day and an optional 16- or 32-bit submillisecond segment.
Public. Hand-written from the Blue Book; I/O is hex text. Needs engine version
0.17 (gate blocks) and 0.16 (the `add` derive).

Uses the modules `core` and `ccsdstime` (`model/ccsdstime.def`).

## Message convention

A message of this pack is one time code: the P-field octet and the T-field.
Octets after the T-field are read over and not written (vector 07).

## Addressing

`word_bytes 1`, `bit_order msb`; bit 0 is the first transmitted bit.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0 | P-field extension | common `when 0:0:1 0` | |
| 1-3 | time code identification | common `when 0:1:3 4` | `100` |
| 4 | epoch identification | the kind | |
| 5 | day segment length | `ccsdstime.cds_day_segment_24` | 0: 16 bits, 1: 24 bits |
| 6-7 | submillisecond segment length | `ccsdstime.cds_submillisecond_length` | 0 none, 1: 16 bits, 2: 32 bits, 3 reserved |
| 8, 16 or 24 bits | day | `ccsdstime.cds_day` | gate `if 0:5:1 0` / `if 0:5:1 1` |
| next 32 bits | milliseconds of day | `ccsdstime.cds_ms_of_day` | |
| next 16 or 32 bits | submilliseconds | `ccsdstime.cds_submillisecond` | nested gates `if 0:6:2 1` / `if 0:6:2 2` |
| the day's bits (kind `level-1`) | the day's start since 1970 | `ccsdstime.cds_day_unix_ms` | `uiscale:86400000:-378691200000` |

With length code 3 (reserved) no submillisecond segment is read (vector 07).

## Kinds

| Kind | `when` | Epoch |
|---|---|---|
| `level-1` | bit 4 = 0 | 1958 January 1 |
| `level-2` | bit 4 = 1 | defined by the agency |

Both require `ccsdstime.cds_day`, so an entity without the day count (one from
another format that holds only `time_ms`) is `no-kind` here (vector
`packs/geojson/vectors/ccsds-cds-time-01-*.json`).

## Shared keys

`time_ms`, for kind `level-1` only, by a derivation:

- Evidence: section 3.3.1 makes the level 1 day count a continuous count of
  days from 1958 January 1, day 0 first, and states that the code is
  UTC-based, with the leap-second correction made. So the day count and the
  milliseconds of day are a UTC calendar day and a time in it, the same scale
  as `time_ms`. (The CUC level 1 code, by contrast, is TAI; see
  `ccsds-cuc-time`.)
- The day's bits also give `ccsdstime.cds_day_unix_ms`: `uiscale` multiplies
  the day count by 86400000 and subtracts 378691200000, the milliseconds of
  the 4383 days from 1958-01-01 to 1970-01-01. The factor and offset are
  integers, so the result is exact (engine-spec 0.15).
- `model/ccsdstime.def` derives `time_ms` as `add(cds_day_unix_ms,
  cds_ms_of_day)` (engine-spec 0.16, integer addition). Derivations run in a
  conversion, so `time_ms` reaches another format (vector 02); a same-format
  round trip keeps the raw segments.
- Leap seconds: during a positive leap second the milliseconds of day run from
  86400000 to 86400999. The sum then equals `time_ms` of the first second of
  the next day (vector 04): milliseconds since 1970 count no leap second, so
  the two instants share a value. The submillisecond segment is not added.
- The other direction is not stated: from `time_ms` the day count is
  `floor(time_ms / 86400000) + 4383` and the milliseconds the remainder, and
  the language has no integer division or remainder derive (`sec_of` divides
  by 1000 only). Candidate for the language: `div:<n>` and `mod:<n>` derives.
- A level 2 code's epoch is the agency's; no `time_ms` (vector 06).

## Not mapped

| Part | Why |
|---|---|
| An implicit P-field | the code's form is agreed outside the message |
| `time_ms` to a CDS code | needs integer division and remainder derives (see above) |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-3-vectors.py` from its own layout
table: a level 1 code with a 16-bit day, the same to GeoJSON with `time_ms`, a
24-bit day with microseconds, a leap-second code to GeoJSON, a level 2 code at
its largest values with picoseconds, a level 2 code to GeoJSON (no `time_ms`),
the reserved submillisecond length, a code cut inside its milliseconds
(`malformed-wire`) and a CUC code ID (`no-kind`); and from GeoJSON, `time_ms`
alone (`no-kind`).
