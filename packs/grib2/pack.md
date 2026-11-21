# grib2

One GRIB edition 2 message (WMO FM 92 GRIB, Manual on Codes WMO-No. 306 Volume I.2). Wire `bits`,
`layout sequential`, `bit_order msb`; I/O is hex text. Written by hand from WMO's machine-readable
GRIB2 templates (wmo-im/GRIB2, MIT) and the ecCodes section definitions (Apache-2.0); vectors by
`tools/gen/wmo-vectors.py`. Licence: Apache-2.0 (PROVENANCE.md).

## Layout

| Part | Lines |
|---|---|
| section 0 | common lines: `when` "GRIB", reserved, discipline, `when` edition 2, `length 64 whole` (the total length) |
| sections 1 to 7 | `group grib2.sections rest`, one item per section: `length 32 bytes plus 4` (the length counts itself), the section number, then `switch grib2.section_number` |
| section 8 | the item kind `end`: `when 32` "7777" |

Kind `grib2` holds the list. A section is an item of kind `section`; sections 3 to 7 may repeat
for further fields of one message, each a new item.

| Section | Read field by field | Kept as octets |
|---|---|---|
| 1 identification | centre, sub-centre, table versions, significance of the reference time, the reference time as year, month, day, hour, minute, second, production status, type of data | octets after them (identification templates of later tables) |
| 2 local use | | all |
| 3 grid definition | source, number of data points, the optional-list size and interpretation, the template number; template 3.0 (latitude/longitude): shape of the Earth and its radius or axes, Ni, Nj, basic angle and subdivisions, La1, Lo1, resolution flags, La2, Lo2, Di, Dj, scanning mode | the optional list of points (quasi-regular grids); every other template |
| 4 product definition | number of coordinate values, template number; template 4.0: parameter category and number, generating process, cut-off, unit of time range, forecast time, the two fixed surfaces (type, scale factor, scaled value) | the coordinate values; every other template |
| 5 data representation | number of values, template number; template 5.0 (simple packing): reference value (IEEE single, `f32`), binary and decimal scale factors, bits per value, type of original values | every other template |
| 6 bitmap | the bitmap indicator | the bitmap |
| 7 data | | the packed data |

Signed fields (La1, Lo1, La2, Lo2, forecast time, the surfaces' scale factors, E and D) are sign
and magnitude, the most significant bit being the sign (WMO regulation 92.1.5, as the WMO template
notes cite it): `smag`.

## Shared-model keys: none, and why

- **The reference time** is six fields. A `derive` that composes a date and a time of day from
  their parts into `time_ms` does not exist (candidate addition), so they stay raw keys.
- **Positions**: La1, Lo1, La2, Lo2 are the corners of a grid, not the position of one object,
  and their unit is the basic angle divided by its subdivisions (1e-6 degree only in the usual
  case, octets 39 to 46), on an Earth whose shape octet 15 states (often a sphere). They stay raw
  integers in that unit.

## Not mapped

- Grid templates other than 3.0, product templates other than 4.0, data representation templates
  other than 5.0: kept as octets in `grib2.section_octets`, so a message comes back unchanged.
- Unpacking the data (the packed values with R, E, D and the bitmap): the pack keeps the octets.
- Missing values (all bits set) are carried as the integers they are.
- A file of several messages: one vector is one message.
- GRIB edition 1: `no-kind`.

## Vectors

| File | Shows |
|---|---|
| `01-temperature-field-roundtrip.json` | a 2 x 2 latitude/longitude grid of 2 m temperature, templates 3.0, 4.0, 5.0 |
| `02-negative-values-roundtrip.json` | sign and magnitude in latitudes, longitudes, forecast time, scale factors; a negative reference value |
| `03-other-templates-as-octets-roundtrip.json` | a local use section, grid template 30, product template 8, data template 40 and a bitmap kept as octets |
| `04-two-fields-roundtrip.json` | sections 4 to 7 repeated for a second field |
| `05-edition-1-is-no-kind.json` | edition 1: `no-kind` |
| `06-input-shorter-than-total-length.json` | `malformed-wire` |
