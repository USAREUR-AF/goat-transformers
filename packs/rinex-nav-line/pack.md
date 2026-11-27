# Pack: rinex-nav-line

One line of a RINEX navigation file, version 4.01 (and version 3.05, whose records have no record
line). Wire `text`, `delimiter none`: the whole line is one field, read by column. One message is one
line. Written by `tools/gen/rinex-pack.py`. Labelled `LicenseRef-unstated` (PROVENANCE.md).

## Kinds

| Kind | Selected by | Fields |
|---|---|---|
| one per header label (`version-type`, `program`, `receiver`, `comment`, `merged-file`, `doi`, `license`, `station-information`, `leap-seconds`, `end-of-header`) | the label in columns 61-80 | the line's columns as Table A7 lays them out |
| `record` (version 4) | `>` in column 1 | record type (EPH, STO, EOP, ION), satellite system and number, message type |
| `satellite-epoch-gps` ... `satellite-epoch-sbas` | the system letter in column 1 | satellite system and number, the epoch (Toc), and three values in columns 24-80 (the clock bias, drift and drift rate for an ephemeris) |
| `epoch-19xx`, `epoch-20xx` | four spaces and a year in columns 5-8 | the epoch of an STO, EOP or ION record, and the text of columns 24-80 as three columns (the STO identifiers, or the EOP and ION values) |
| `values` | any other line | the four values of columns 5-80 |

The `values` kind holds when no other does, so this pack has no `no-kind` line; a line with a
character outside 0x20-0x7E is `malformed-wire`.

## Shared keys

None. The ephemeris parameters (orbit, clock, health) are values of a line whose meaning depends on its
place in the record and on the message type; they are kept as written.

## Not mapped

On encode with no recorded kind (engine-spec Encode step 2), each kind is chosen by the keys
it requires.
`satellite-epoch-gps`, `satellite-epoch-glonass`, `satellite-epoch-galileo`, `satellite-epoch-beidou`, `satellite-epoch-qzss`, `satellite-epoch-navic`, `satellite-epoch-sbas` require the same keys, so an entity with them is written as `satellite-epoch-gps`.
`epoch-19xx`, `epoch-20xx` require the same keys, so an entity with them is written as `epoch-19xx`.
`end-of-header`, `values` have no `requires`, so an entity that fits no other kind is written as `end-of-header`.
Choosing between them needs `requires` on a value or on an absent key, a language addition.
`end-of-header` maps no key and must stand before `values` for decode, so a kind-less entity
that fits no other kind is written as END OF HEADER and `values` is not reached.

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
- An STO record's identifiers are left-justified in 18 columns starting one column after the
  values' columns; the pack keeps them in the values' columns, with the leading space.

## Vectors

`tools/gen/rinex-vectors.py`, without an engine: the version line; leap seconds; a record line; a GPS
satellite-epoch line; a four-value line; a two-value line; an STO epoch line; a line with a tab
(`malformed-wire`).
