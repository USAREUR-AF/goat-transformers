# Pack: gtfs-routes

One data row of the GTFS Schedule file `routes.txt`. Public. Hand-written on the
`text` wire (engine-spec 0.10) from the GTFS Schedule Reference (google/transit,
Apache-2.0, commit `2ce6aa79e3fa7bdbaf19d2a12765cee5b9fdd699`). Uses the modules
`core` and `gtfs` (`model/gtfs.def`, one key per column name, shared by every
GTFS pack).

## Message convention

A message is one data row of `routes.txt`, without its line break: the values
separated by `,`. The pack has no start text, no checksum and no kinds.

### Column order

A GTFS file names its columns in its first line, and the order of the columns
and which optional columns appear are the producer's choice. A pack of the
`text` wire addresses a field by its position, fixed when the pack is written.
**Convention:** the columns are those the reference lists for the file, in the
reference's order, all of them. A row of a file whose header is exactly

    route_id,agency_id,route_short_name,route_long_name,route_desc,route_type,route_url,route_color,route_text_color,route_sort_order,continuous_pickup,continuous_drop_off,network_id,cemv_support

decodes and encodes as is. A row of a file with the same columns ending
earlier decodes (the missing trailing columns are absent) and encodes with all 14
columns. A row of a file whose columns are in another order, or that leaves out a
column before its last one, or adds a column, does not decode correctly: the
caller reorders it first. The header row itself is not a message (where a
column is numeric it fails with `transform-decode`).

Missing addition: **a header-defined column order**, a wire option by which a
pack names its columns and an input states their order once (a header record),
so each row is read by name. With it the same pack would read every GTFS file
of this type.

### Quoted values

GTFS allows a value that holds a comma or a quotation mark when the value is
enclosed in quotation marks, with each inner quotation mark doubled (the
reference's File Requirements, after RFC 4180). The `text` wire has no quoting:
it splits at every comma. A row with such a value is read with the columns after
it shifted, which the pack cannot detect when the shifted texts still parse.
Missing addition: **CSV quoting** on the `text` wire (a `quote` directive).

### Characters

GTFS text is UTF-8 and may begin with a byte-order mark. The `text` wire
accepts characters 0x20 to 0x7E only, so a row with any other character (an
accented stop name, for example) is `malformed-wire`. Missing addition:
**UTF-8 text fields** on the `text` wire.

### Required columns

The reference marks each column Required, Conditionally Required, Optional or
Recommended. The pack does not check it: on the `text` wire an empty value is an
absent key, so a row with a Required column empty decodes without an error.

## Columns

| Field | Column | Reference type |
|---|---|---|
| 0 | `route_id` | Unique ID |
| 1 | `agency_id` | Foreign ID |
| 2 | `route_short_name` | Text |
| 3 | `route_long_name` | Text |
| 4 | `route_desc` | Text |
| 5 | `route_type` | Enum |
| 6 | `route_url` | URL |
| 7 | `route_color` | Color |
| 8 | `route_text_color` | Color |
| 9 | `route_sort_order` | Non-negative integer |
| 10 | `continuous_pickup` | Enum |
| 11 | `continuous_drop_off` | Enum |
| 12 | `network_id` | ID |
| 13 | `cemv_support` | Enum |

Transforms: Latitude, Longitude and the float types `float`; Integer, the
signed integer types and Enum `int`; every other type `string` (IDs, text,
URL, time zone, language, phone, e-mail, colour, and Date and Time, which stay
text: a GTFS Time may pass 24:00:00 and is relative to the service day, which
no transform of the wire reads).

## Shared keys, with evidence

None. No column of this file has the meaning of a `core` or `track` key; every column is a raw key of `gtfs`.

## Not mapped

- The header row, column order, quoting and characters, as above.
- The relations between files (a `stop_times` row's `stop_id` names a row of
  `stops.txt`): each pack reads one row on its own.
- The dataset as a zip file of several files.

## Vectors

1 vector(s) under `vectors/`, written by `tools/gen/gtfs-vectors.py`
(standard library only; no pack read and no engine run; `--check` compares
them with the tree).
