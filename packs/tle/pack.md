# Pack: tle

One line of a NORAD two-line element set: line 1 or line 2, or the name line (line 0) of
the three-line form CelesTrak serves. Public. Hand-written on the `text` wire (engine-spec
0.10) with `delimiter none`; every field is a column. Uses the modules `core` and `tle`
(`model/tle.def`).

## Message convention

A message is one line, without its line break (CelesTrak ends lines with CR LF; decode
removes one terminator). A two-line element set is two messages; the pack does not join
them. Kinds:

| Kind | Selected when | Fields |
|---|---|---|
| `line1` | columns 1-2 read `1` (the column's trailing space removed) | satellite number, classification, the three parts of the international designator, epoch year and day, the two mean-motion derivatives, BSTAR, ephemeris type, element number, checksum |
| `line2` | columns 1-2 read `2` | satellite number, inclination, right ascension of the ascending node, eccentricity digits, argument of perigee, mean anomaly, mean motion, revolution number, checksum |
| `name` | any other line | the name, columns 1-24 |

The kinds are taken in that order, and `name` has no `when`: any line that is not line 1
or line 2 reads as a name (its first 24 characters). A name line whose text begins with
`1 ` or `2 ` would be read as a line of elements and fail.

## Columns and numbers

Columns as CelesTrak's format page numbers them from 1 (a locator counts from 0):

- Line 1: satellite number 3-7 (`int`), classification 8, designator year 10-11 (`int`),
  launch number 12-14 (`int`), piece 15-17 (text), epoch year 19-20 (`int`), epoch day
  21-32 (`dec:8:12`), first derivative 34-43, second derivative 45-52, BSTAR 54-61 (the
  three as text), ephemeris type 63, element number 65-68 and checksum 69 (`int`).
- Line 2: satellite number 3-7, inclination 9-16, right ascension 18-25, eccentricity 27-33
  (`int`: the seven digits after the assumed decimal point), argument of perigee 35-42,
  mean anomaly 44-51 (the four angles `dec:4:8`, degrees), mean motion 53-63 (`dec:8:11`,
  revolutions per day), revolution number 64-68 and checksum 69.

Encode writes numeric columns padded with `0` where producers pad with spaces (`051.6319`
for ` 51.6319`, `0999` for ` 999`). Both count 0 in the checksum, so the checksum digit
still holds, and readers that parse each column as a number read the same values.

The two derivatives and BSTAR are kept as text, sign column included (a space or `-`): the
first derivative is a decimal with no digit before the point, which `dec` does not write
in that width, and the second derivative and BSTAR use an assumed decimal point and a
power of ten, which no transform reads. The eccentricity is the integer of its seven
digits for the same reason: the `text` wire has no scale.

## Not mapped, and why

- **Checksum.** The modulo-10 checksum is carried as written and not verified; a line
  written from values of another source carries no checksum unless the model has one.
  Missing addition: a TLE checksum (digits, and 1 for each minus sign, modulo 10) on the
  `text` wire.
- **Epoch.** The epoch is a two-digit year (57 to 99 are 19xx, 00 to 56 are 20xx) and a
  day of the year with its fraction; no transform turns these into epoch milliseconds, so
  `time_ms` is not bound.
- **Shared keys.** None: the international designator is split into three columns without
  the century, so it is not the `uid` value the OMM packs give (`1998-067A`), and the
  elements are a mean orbit, not a position.
- **Six-digit catalogue numbers.** The satellite number has five columns. CelesTrak says
  objects numbered 100000 and up get no TLE; a letter in the first column (a scheme some
  producers use) is not an `int` and is refused.

## Vectors

`tools/gen/space-text-vectors.py` writes them (no engine is run): a round trip of each
line kind, space-padded columns written with zeros, a negative derivative, the name line
padded and unpadded, a five-character number with a letter (an error) and a line with its
CR LF terminator. Every line is constructed, and its checksum computed by the script.
