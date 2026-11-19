# Pack: gtfs-stops

One data row of the GTFS Schedule file `stops.txt`. Public. Hand-written on the
`text` wire (engine-spec 0.10) from the GTFS Schedule Reference (google/transit,
Apache-2.0, commit `2ce6aa79e3fa7bdbaf19d2a12765cee5b9fdd699`). Uses the modules
`core` and `gtfs` (`model/gtfs.def`, one key per column name, shared by every
GTFS pack).

## Message convention

A message is one data row of `stops.txt`, without its line break: the values
separated by `,`. The pack has no start text, no checksum and no kinds.

### Column order

A GTFS file names its columns in its first line, and the order of the columns
and which optional columns appear are the producer's choice. A pack of the
`text` wire addresses a field by its position, fixed when the pack is written.
**Convention:** the columns are those the reference lists for the file, in the
reference's order, all of them. A row of a file whose header is exactly

    stop_id,stop_code,stop_name,tts_stop_name,stop_desc,stop_lat,stop_lon,zone_id,stop_url,location_type,parent_station,stop_timezone,wheelchair_boarding,level_id,platform_code,stop_access

decodes and encodes as is. A row of a file with the same columns ending
earlier decodes (the missing trailing columns are absent) and encodes with all
16. A row of a file whose columns are in another order, or that leaves out a
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

## Columns

| Field | Column | Reference type |
|---|---|---|
| 0 | `stop_id` | Unique ID |
| 1 | `stop_code` | Text |
| 2 | `stop_name` | Text |
| 3 | `tts_stop_name` | Text |
| 4 | `stop_desc` | Text |
| 5 | `stop_lat` | Latitude |
| 6 | `stop_lon` | Longitude |
| 7 | `zone_id` | ID |
| 8 | `stop_url` | URL |
| 9 | `location_type` | Enum |
| 10 | `parent_station` | Foreign ID |
| 11 | `stop_timezone` | Timezone |
| 12 | `wheelchair_boarding` | Enum |
| 13 | `level_id` | Foreign ID |
| 14 | `platform_code` | Text |
| 15 | `stop_access` | Enum |

Transforms: Latitude, Longitude and the float types `float`; Integer, the
signed integer types and Enum `int`; every other type `string` (IDs, text,
URL, time zone, language, phone, e-mail, colour, and Date and Time, which stay
text: a GTFS Time may pass 24:00:00 and is relative to the service day, which
no transform of the wire reads).

## Shared keys, with evidence

| Column | Key | Evidence |
|---|---|---|
| 0 `stop_id` | `uid` | "Identifies a location", a unique ID of the file: a stable identifier of the stop |
| 2 `stop_name` | `callsign` | "Name of the location" as riders see it: a human-readable name |
| 5 `stop_lat` | `lat` | type Latitude: "WGS84 latitude in decimal degrees" (Field Types) |
| 6 `stop_lon` | `lon` | type Longitude: WGS 84 longitude in decimal degrees (Field Types) |

Each of these columns also has its raw key (`gtfs.<column>`), on the line after the shared key (engine-spec 0.5 ruling 16).

## Not mapped

- The header row, column order, quoting and characters, as above.
- The relations between files (a `stop_times` row's `stop_id` names a row of
  `stops.txt`): each pack reads one row on its own.
- The dataset as a zip file of several files.

## Vectors

7 vector(s) under `vectors/`, written by `tools/gen/gtfs-vectors.py`
(standard library only; no pack read and no engine run; `--check` compares
them with the tree).
