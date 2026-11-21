# Pack: rinex-obs-line

One line of a RINEX GNSS observation file, versions 3.05 and 4.01 (their observation columns are the
same). Wire `text`, `delimiter none`: the whole line is one field, read by column. One message is one
line. Written by `tools/gen/rinex-pack.py`. Labelled `LicenseRef-unstated` (PROVENANCE.md).

## Kinds

| Kind | Selected by | Fields |
|---|---|---|
| one per header label (`version-type`, `program`, `comment`, `marker-name`, ..., `end-of-header`) | the label in columns 61-80 | the line's columns as Table A2 lays them out (version and type, program, marker, observer, receiver, antenna, approximate position, antenna deltas and phase centre, the observation types with their system and count, interval, times of first and last observation with the time system, leap seconds, number of satellites, DOI, licence, station information); a few lines kept as their 60 columns (scale factor, phase shift, GLONASS slots and biases, PRN / # OF OBS) |
| `epoch` | `>` in column 1 | year, month, day, hour, minute, second, epoch flag, number of satellites, receiver clock offset |
| `observation-gps` ... `observation-sbas` (one per system letter) | the system letter in column 1 | satellite system and number, then up to 40 observations, each the value (14 columns) and its LLI and SSI digits |
| `header-other` | any other text in columns 61-80 | the first 60 columns and the label |

## Shared keys

None. The approximate position is geocentric (ECEF) X, Y, Z in metres, not latitude and longitude, and
is kept as written; the epoch is in GNSS system time (below).

## Not mapped

- **Numbers as numbers**: every value is its column text. RINEX right-justifies numbers in their
  columns with spaces, and the `text` wire's numeric transforms write zeros where a column is wider than
  the number, so a round trip would not be exact; its `float` does not read an exponent (`E+01`,
  `D-04`). Needed: right-justified numeric columns padded with spaces, and numbers with exponents
  (including Fortran `D`), on the `text` wire.
- **The file as a message**: one message is one line. Which observation types a value is (the
  system's `SYS / # / OBS TYPES` line), which epoch an observation line belongs to, and which line of a
  navigation record a values line is (BROADCAST ORBIT 1 to 7 by its place after the record's first
  line) are context across lines, which a pack does not hold. The caller groups the lines.
- **Times**: epochs are in the satellite system's time (GPS, GLONASS, Galileo, BeiDou time ...), not
  UTC, so they do not bind `time_ms`; they are kept as written.
- Header lines run to column 80 on encode (the label's column is 20 characters), and a line that a
  writer cut after its label's last character comes back with trailing spaces.
- Hatanaka-compressed (CRINEX) and meteorological files are not read.
- More than 40 observations on one line are not read (the 41st onward).

## Vectors

`tools/gen/rinex-vectors.py`, without an engine: the version line; approximate position; observation
types; time of first observation; end of header; an epoch line with and without the clock offset; a GPS
observation line with LLI and SSI; a GLONASS line with a blank observation; a header line kept whole;
an unknown label (`header-other`); a line of no kind (`no-kind`).
