# aprs

APRS (Automatic Packet Reporting System) packets as the TNC2 monitor line shows
them, one packet per record. Hand-written from the APRS Protocol Reference,
Protocol Version 1.0, document version 1.0.1 (APRS101). The reference may be
copied for non-commercial purposes only, so this pack and its module carry the
label `LicenseRef-APRS-NC` (profile `everything`; `REUSE.toml`, `licences.toml`,
`LICENSING.md`). The vectors are written by `tools/gen/aprs-vectors.py`.

## Message convention

A record is the monitor line of one packet: the source call, `>`, the
destination, the path (calls separated by commas), `:`, and the information
field. The pack reads it on the `text` wire with the colon as the delimiter:

| Field | Holds | Key |
|---|---|---|
| 0 | the address part, `SOURCE>DEST,PATH`, whole | `aprs.header` |
| 1 | the information field up to any later colon, whole | `aprs.info` |
| 2 and later | what follows a later colon (in a comment, a status or a message text) | residue, written back unchanged |

The first character of the information field is the data type identifier
(chapter 5 of the reference), and it selects the kind. Every kind maps field 1
whole and its parts by column. A column and a whole-field line on one field are
both read; encode writes the whole field when `aprs.info` is present, so every
record round-trips exactly, and builds the field from the columns only when it
is absent (spec 0.10, ruling 3). A line terminator is removed on decode and not
written.

## Kinds

| Kind | Identifier | Layout of field 1 (columns from 0) |
|---|---|---|
| `position` | `!` | uncompressed position at 1 |
| `position-messaging` | `=` | as `position`, from a station that handles messages |
| `position-time` | `/` | time stamp at 1 (7 characters), uncompressed position at 8 |
| `position-time-messaging` | `@` | as `position-time`, messaging |
| `compressed` | `!` | compressed position at 1 |
| `compressed-messaging` | `=` | compressed position at 1 |
| `compressed-time` | `/` | time stamp at 1, compressed position at 8 |
| `compressed-time-messaging` | `@` | time stamp at 1, compressed position at 8 |
| `object` | `;` | name at 1 (9 characters), `*` live or `_` killed at 10, time stamp at 11, uncompressed position at 18 |
| `object-compressed` | `;` | as `object`, compressed position at 18 |
| `status` | `>` | free text: `aprs.info` |
| `message` | `:` | field 1 is empty (the identifier is the delimiter); field 2 is the addressee, padded to nine characters; field 3 is the text with any message number |

The uncompressed position (chapter 8) is 19 characters: latitude as degrees and
minutes `ddmm.mm` (7), `N` or `S`, the symbol table identifier, longitude
`dddmm.mm` (8), `E` or `W`, and the symbol code. The compressed position
(chapter 9) is 13 characters: the symbol table identifier, four base-91
characters of latitude, four of longitude, the symbol code, two characters of
course and speed (or radio range, or altitude) and the compression type. An
uncompressed and a compressed position share their identifiers; the uncompressed
kinds stand first and also require the decimal points of the two minutes fields
(columns 5 and 15, or 12 and 22 after a time stamp, or 22 and 32 in an object),
which the reference fixes and position ambiguity leaves in place. The `message`
kind stands last and selects on field 2 being present.

The pack escapes the identifier `=` as the `when` value `==` (one leading `=` of
a `when` value is stripped, spec 0.5).

## Shared keys

None.

- **Latitude and longitude** are kept as the text the packet holds
  (`aprs.lat_text`, `aprs.lat_hemisphere`, `aprs.lon_text`,
  `aprs.lon_hemisphere`). The `text` wire's `dm` transform reads degrees and
  minutes from a pair of whole fields, the digits in one and the hemisphere
  letter in the other. In APRS both are columns of one field, with the letter
  right after the digits, so `dm` cannot address them. A compressed position is
  base-91 text, which no transform reads. Candidate additions for gt-lang: a
  `dm` form over a column that ends in the hemisphere letter (or over a pair of
  columns), and a base-91 integer transform with the reference's scale.
- **Callsign.** The source call is the text before `>` in field 0. Its length
  varies, and the colon delimiter cannot split field 0 again, so `callsign`
  cannot be bound; `aprs.header` keeps the address part whole. Candidate
  addition: a field split by a second character (or a column ending at a
  character).
- **Time.** An APRS time stamp holds day, hour and minute, or hour, minute and
  second, with no month or year, so it stays raw (`aprs.timestamp`).

## Not mapped, and why

| What | Why |
|---|---|
| Mic-E (identifiers `` ` `` and `'`) | the latitude is in the destination call in field 0, and the information field carries bytes from 0x1C to 0x7F, outside the `text` wire's 0x20 to 0x7E, and may hold a colon |
| Items (`)`) | the item name is 3 to 9 characters, ended by `!` or `_`, so every later column moves with it |
| Weather, telemetry, queries, NMEA and the other identifiers | not asked for in this round; they decode as `no-kind` |
| Comments, PHG, course and speed and other data extensions | inside `aprs.info`, not parsed out |
| A colon in a comment or message text | it ends field 1 (or field 3); the text after it is residue, carried and written back, not part of `aprs.info` or `aprs.message_text` |
| Characters outside 0x20 to 0x7E | the `text` wire refuses them (`malformed-wire`) |
| The AX.25 frame | the pack reads the monitor line, not the frame |

## Vectors

`tools/gen/aprs-vectors.py` builds the records (invented for the vectors; no
example of the reference is copied) and derives the expected model values by
the reference's columns. Round trips expect the record back unchanged; one has
a CR LF that is not written back; `err-unknown-type` is a telemetry report
(`no-kind`) and `err-control-character` holds a control character
(`malformed-wire`). 18 vectors.

Independent check (not in the repository): the round-trip records were parsed
with aprslib 0.7.2 (GPL-2.0, used only as a checker; no code copied). Its
latitude, longitude, symbol, object name and state, and message fields agree
with the vectors' models. It differs where expected: it centres an ambiguous
position, it reads `BLN1` as a bulletin, and it keeps a colon inside message
text.

## Sources

See `PROVENANCE.md`.
