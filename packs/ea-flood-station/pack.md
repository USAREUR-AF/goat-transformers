# ea-flood-station

The Environment Agency's real-time flood-monitoring API (England): the response for one station,
`/id/stations/{id}`, whose `items` member is the station. Wire `json`, no kinds. Written by hand
from the API reference; vectors by `tools/gen/hydro-vectors.py`. Licence: `OGL-UK-3.0`.

| Members | Keys |
|---|---|
| `@context` | `eaflood.context` |
| `items`: `@id`, `notation`, `label`, `RLOIid`, `catchmentName`, `dateOpened`, `datumOffset`, `eaAreaName`, `eaRegionName`, `easting`, `northing`, `riverName`, `stationReference`, `town`, `wiskiID` | `eaflood.station_uri`, ... |
| `items.lat`, `items.long` | `lat`, `lon`, and the raw keys `eaflood.station_lat`, `eaflood.station_long` |
| `items.measures`, a list: `@id`, `label`, `parameter`, `parameterName`, `period`, `qualifier`, `unitName`, `datumType`, `latestReading.dateTime`, `latestReading.value` | list `eaflood.measures` |

## Shared-model keys

- `lat`, `lon`: the reference describes `lat` and `long` of a station as its latitude and
  longitude in the WGS84 coordinate reference system. The `lat` and `lon` lines come first on
  their locators (ruling 16 of 0.5); the raw keys hold the same values.
- No height: a station's levels are given against the datum its measure's `unitName` and
  `datumType` name (mAOD, the Ordnance datum, or mASD, a local stage datum), not the WGS 84
  ellipsoid; `datumOffset` is the offset between those two datums, a raw key.
- No time: the time of the latest reading is inside a measure, a list item, which a shared key
  of the entity cannot be filled from. It is kept as written (`eaflood.latest_reading_time`).

## Not mapped

- `meta` (publisher, licence, documentation, version): scalar residue, carried back; its arrays
  (`hasFormat`) are not carried on the json wire.
- Members inside a list item that the pack does not name: an item carries no residue.
- The JSON-LD meaning of the members (`@context`): the context URI is kept as text, not resolved.
- The CSV, RDF and Turtle forms of the API: other wires.
- The station's scales (`stageScale`, `downstageScale`): nested objects, carried as residue;
  their record times are written without a zone and are not read as times.
- The station list (`/id/stations`), whose `items` is an array: this pack reads one station.

## Vectors

| File | Shows |
|---|---|
| `01-station-roundtrip.json` | one station with one measure and its latest reading; meta and the stage scale as residue |
| `02-station-to-geojson.json` | the station's position reaches a GeoJSON Feature |
| `03-latitude-as-text.json` | `lat` as text: `transform-decode` |
