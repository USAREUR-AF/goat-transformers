# eonet-event

One natural event geometry of NASA's Earth Observatory Natural Event Tracker (EONET) v3,
GeoJSON form: a Feature of the `events/geojson` FeatureCollection. Each Feature pairs one
date with one location of an event; an event tracked over several days is several Features
with the same `id`. Wire `geojson`, no kinds. Written by hand from the documented member
list; vectors are derived by `tools/gen/usgov2-vectors.py` (standard library only, no
engine; `--check` compares).

## Shared-model keys and the evidence

| Member | Key | Evidence (EONET v3 documentation, in our words) |
|---|---|---|
| `geometry` (Point) | `lon`, `lat` | the event geometry is a GeoJSON object (RFC 7946: WGS 84 longitude and latitude in decimal degrees) |
| `properties.date` | `time_ms` | the date and time paired with the location, in UTC (the documentation notes it is usually 00:00Z when the source gives no time); ISO 8601 with `Z`, read by `iso8601_ms` |
| `properties.id` | `uid` | the unique identifier of the event; every Feature of one event carries it |
| `properties.title` | `callsign` | the title of the event, its human-readable name |

## Not mapped, and why

- `description`, `closed`, `magnitudeValue` and `magnitudeUnit` are often `null` (an open
  event has no `closed`; most have no description). On the geojson wire a `null` under a
  field fails its transform, so they are residue: a `null` is dropped, text comes back as
  it was, and a number (`magnitudeValue`) comes back as a string (ruling 13 of 0.6).
- `categories` and `sources` are arrays: residue, carried back as they were.
- **Polygon geometries.** The documentation allows a Point or a Polygon. The geojson wire
  addresses the coordinates of a Point only; with a Polygon the reference engine fails the
  decode on `geometry.lon` (`transform-decode`). The specification does not state the case,
  so no vector pins it; see the report on the geojson null rule. Point events decode.
- The JSON form of the Events API (an `events` array, each event with a `geometry` list of
  dated points) is not a pack: the json wire addresses no position inside an array, and a
  list item carries no residue, so its positions would be lost.

## Vectors

| File | Case |
|---|---|
| `01-event-roundtrip` | an open event; nulls dropped; arrays and a number as residue |
| `02-closed-event-roundtrip` | a closed event with a description |
| `03-event-to-geojson`, `04-event-to-cot-xml` | to the shared formats |
| `05-date-not-iso` | `transform-decode` |
| `packs/geojson/vectors/98-to-eonet-event` | GeoJSON to an event |
