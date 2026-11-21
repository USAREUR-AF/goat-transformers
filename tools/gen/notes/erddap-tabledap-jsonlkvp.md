## Evidence for the shared keys

- `time_ms` (`time`): ERDDAP keeps the name `time` for a variable that holds a full date and
  time and writes it as an ISO 8601 date-time in UTC in this format; `iso8601_ms` reads it.

## Not bound

- `latitude`, `longitude`: ERDDAP keeps these names for degrees north and east, but names no
  datum, so they are raw keys, not `lat` and `lon`. The .geoJson form of the same rows
  (`erddap-tabledap-geojson`) binds them through GeoJSON's WGS 84.
- `altitude` (metres, up) and `depth` (metres, down) refer to a vertical datum the dataset may
  or may not state; neither is `hae`.
- Every other member is a dataset variable: residue, carried back as it was.
