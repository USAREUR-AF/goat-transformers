# Pack: nmea-tag-block

An NMEA 4.x TAG block, as gpsd's AIVDM document describes it: the text between the opening and the
closing backslash that precede a sentence (`\g:1-2-73,s:r1,c:1241544035*hh\!AIVDM,...`), its
comma-separated parameters and its checksum. Wire `text`, delimiter `,`, `checksum nmea`, no start
text. No kind. Written by `tools/gen/maritime-pack.py`.

## What is mapped

The parameters, as a list of strings, each written as on the wire: a type letter, a colon and the
value (`c` UNIX time, `d` destination, `g` sentence group, `n` line count, `r` relative time, `s`
source, `t` text; IEC 62320-1 uses some other letters). The checksum is checked on decode and written on
encode.

## Shared keys

None. The `c` parameter is a time, but gpsd states that its unit (seconds or milliseconds) is not
known, so it does not bind `time_ms`.

## Not mapped

- **Each parameter by its letter**: the parameters come in any order, and the `text` wire addresses
  fields by position; a field cannot be chosen by its leading characters. Needed: keyed fields on the
  `text` wire (a field located by a prefix, in any order). So the letter and value are one string.
- **The line**: a whole line (`\...\` and the sentence after it) holds two checksums and two `*`;
  the caller splits it at the second backslash and passes the TAG block text here and the sentence to
  `nmea0183` or `ais`. Needed: a layered text wire (a framed prefix before a record).

## Vectors

`tools/gen/maritime-vectors.py`, without an engine: group, source and time parameters; source and line
count; a bad checksum (`malformed-wire`).
