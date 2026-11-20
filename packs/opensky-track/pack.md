# Pack: opensky-track

The response of the OpenSky Network REST API to `GET /tracks/all`: the trajectory of one
aircraft. Wire `json`. Written by hand from the response table of the API documentation
(PROVENANCE.md). Licence: `LicenseRef-OpenSky` (LICENSES/LicenseRef-OpenSky.txt). The
documentation marks the endpoint experimental.

## Mapped

| Member | Key | Transform | Evidence |
|---|---|---|---|
| `icao24` | `uid` | `string` | The unique ICAO 24-bit address of the aircraft's transponder, as lower-case hexadecimal text; it identifies the aircraft. |
| `startTime` | `opensky.start_time` | `int` | Time of the first waypoint, Unix seconds. |
| `endTime` | `opensky.end_time` | `int` | Time of the last waypoint, Unix seconds. |
| `callsign` | `callsign` | `string` | The callsign (8 characters) that holds for the whole track; may be null. |

`startTime` and `endTime` bound the track; neither is the time a report is valid, so
neither is `time_ms`.

The documentation spells the member `calllsign` (three l), in the response table and in
the Python client's docstring; the client copies whatever members the API returns, so it
does not settle the spelling. The three l's read as a typo, and the live API was not
checked (the tracks endpoint returned nothing to an anonymous request). The pack maps `callsign`, the spelling of the same member in
every other response of the API. A response that uses the documented spelling keeps the
value as residue, so it still round-trips.

## Not mapped

| Member | Why |
|---|---|
| `path` | The waypoints, each a JSON array of time, WGS 84 latitude and longitude in degrees, barometric altitude in metres, true track in degrees and an on-ground flag, told apart by position. As for the state vectors of `opensky-states`, the json wire cannot address an array item's elements by index, and arrays are not residue. |

The flight endpoints (`/flights/*`) answer with a JSON array of flight objects at the top
level; the json wire reads one object, so they have no pack.

## Message convention

Members are written in line order (`icao24`, `startTime`, `endTime`, `callsign`), then
residue scalars in input order.

## Vectors

`tools/gen/opensky-vectors.py`: a round trip with a path (not carried), a round trip with
a null callsign and a residue member, `icao24` as a number (`transform-decode`), and a
GeoJSON Feature to a track (its `id` is `icao24`, its `callsign` the callsign), under
`packs/geojson/vectors/`, the pack of its input.
