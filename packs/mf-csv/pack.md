# mf-csv

OGC Moving Features Encoding Extension: Simple Comma Separated Values (CSV),
OGC 14-084r2, version 1.0: a text file of header lines and trajectory lines
that state the movement of points over time. Wire `text` (engine-spec 0.10),
delimiter `,`, five kinds. Hand-written; vectors derived by
`tools/gen/ogc-mf-kml-vectors.py` (standard library only, no engine). Module
`mfcsv` (`model/mfcsv.def`).

This pack includes modifications that have not been approved or adopted by the
Open Geospatial Consortium: it is an implementation written for this
repository, not a part of the standard.

## Message convention

One message is one line of the file, without its line break. The caller splits
the file into lines and decodes each; the pack keeps no state from one line to
the next, so the meaning a header gives to later lines (the time unit, the
attribute names and types, the coordinate reference system) is not applied to
them (below).

| Kind | Holds when | The line |
|---|---|---|
| `stboundedby` | column 0 is `@stboundedby` | the spatio-temporal bounding box of the file (8.2.1) |
| `columns` | column 0 is `@columns` | the attribute definitions (8.2.2) |
| `foliation` | column 0 is `@foliation` | the order of the trajectory lines (8.2.3) |
| `header` | the first character is `@` | any other header line (8.1); its value columns are residue |
| `trajectory` | no other kind holds | a trajectory line (9) |

Kinds are tried in this order, so a header line never decodes as a trajectory.

## Shared-model keys and the evidence

| Column | Key | Evidence (OGC 14-084r2, in our words) |
|---|---|---|
| trajectory line, column 0 (`mfidref`) | `uid` | 8.2.2 and 9.2: the first column names the moving feature the line belongs to (a person or a vehicle identifier); every line of one feature carries the same text |

No other shared key is bound:

- **Position.** 9.2: the points of a line are one column holding the x, y (and
  in 3D z) values of every point, all separated by whitespace. The `text` wire
  splits a record at the delimiter only and has no transform that takes the
  n-th number of a whitespace-separated text, so the column is carried whole as
  `mfcsv.points` and `lat` and `lon` stay absent. A conversion to GeoJSON has
  `geometry: null` (vector 10) and a conversion from a format without
  `mfcsv.points` fails with `no-kind` (geojson vector
  `to-mf-csv-geojson-to-trajectory-without-points-is-no-kind`).
- **Reference system and axis order.** 8.2.1: the coordinate reference system
  is named once, in the `@stboundedby` line, and may be any system. 9.2 says x
  is the longitude, while an EPSG 4326 system orders latitude first, and the
  bounding-box corners of the standard's own example are written latitude
  first. So even with a split transform a line alone does not say whether its
  first number is a longitude, nor that it is WGS 84; binding `lat` and `lon`
  would need the header.
- **Time.** 8.2.1: the start and end times of a trajectory line are offsets in
  seconds or minutes from the file's start time, or absolute date-times, as
  the header's time-encode column says. A line alone cannot be read as an
  instant, so both are carried as text (`mfcsv.start_time`, `mfcsv.end_time`)
  and `time_ms` is not bound. The `@stboundedby` times are date-times that may
  lack a zone and state the file's period, not the time of a report; they are
  text too (`mfcsv.period_start`, `mfcsv.period_end`).

## Raw keys (module `mfcsv`)

| Kind | Column | Key |
|---|---|---|
| `stboundedby` | 1 to 7 | `srid`, `dim`, `upper_left`, `lower_right`, `period_start`, `period_end`, `time_encode` (`optional`: a line without it is written without it) |
| `columns` | 1, 2 | the fixed texts `mfidref` and `trajectory`, written by `const` lines |
| `columns` | 3 on, two per item | list `attribute_defs`: `attribute_name`, `attribute_type` |
| `foliation` | 1 | `order` |
| `header` | 0 | `header_name`, the `@` included |
| `trajectory` | 1, 2, 3 | `start_time`, `end_time`, `points` |
| `trajectory` | 4 on, one per item | list `attributes`: `value` |

Every value is a string carried as written. An empty column is absent and is
written back empty; an empty attribute column (9.2: a value equal to the
previous line's) is an item with no value.

## Not mapped

- **Header context.** The time unit, attribute names and types, and reference
  system that header lines give to later lines are not applied; attribute
  values are a list of text, not typed keys named after their definitions.
  Missing addition: a header-defined column layout (the same addition the GTFS
  packs name).
- **Quoted columns.** 7.1 follows RFC 4180: a column may be enclosed in double
  quotation marks, with inner ones doubled, and may then hold a comma. The
  `text` wire splits at every comma and has no quoting, so such a line is read
  with its later columns shifted. The `@columns` fixed names written in quotes
  (`"mfidref"`) decode, because `const` columns are not checked on decode, but
  are written back without quotes. Missing addition: CSV quoting on `text`.
- **Characters.** 7.1: lines are UTF-8. The `text` wire accepts 0x20 to 0x7E
  only, so a line with any other character is `malformed-wire` (vector 11).
  Missing addition: UTF-8 text fields on `text`.
- **Escapes.** 9.2: attribute values escape XML-special characters as entity
  references and space, tab and comma as `\s`, `\t`, `\b`. Values are carried
  as written, escapes included; no transform decodes them.
- **Trailing empty columns** after the last mapped column of a header line
  (7.2 shows one) are not written back.
- Multiple lines as one message, and the order and non-overlap requirements
  between trajectory lines of one feature (9.1), which concern the file.

## Candidate pack-language additions

1. A split transform or derive function: the n-th part of a text split at a
   separator (here whitespace, in KML a comma), and its inverse. With it, a
   point list could become a group of `lat`/`lon` items once the axis order is
   known.
2. Stateful decode: a header record whose values (column names, a time unit,
   an epoch) apply to later records of the same stream.
3. CSV quoting and UTF-8 on the `text` wire.

## Vectors

| File | Case |
|---|---|
| `01-stboundedby-roundtrip` | every column of the bounding-box line |
| `02-stboundedby-omitted-columns-roundtrip` | empty `dim`, no time encode (`optional`) |
| `03-columns-roundtrip` | two attribute definitions as items |
| `04-columns-without-attributes-roundtrip` | no attribute: the list is absent |
| `05-foliation-roundtrip` | the order line |
| `06-other-header-roundtrip` | a header line with no kind of its own; residue |
| `07-trajectory-roundtrip` | `uid`, offsets, points, two attribute values |
| `08-trajectory-omitted-attribute-roundtrip` | an empty attribute column |
| `09-trajectory-absolute-3d-roundtrip` | absolute times, 3D points, no attributes |
| `10-trajectory-to-geojson` | `uid` carries as the Feature id; geometry null |
| `11-non-ascii-is-malformed-wire` | a UTF-8 character outside the `text` wire's range |
| `packs/geojson/vectors/to-mf-csv-geojson-to-trajectory-without-points-is-no-kind` | GeoJSON to mf-csv cannot write the points |
