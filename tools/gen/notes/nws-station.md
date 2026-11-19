## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the document describes every feature as "A GeoJSON feature" and refers to IETF RFC 7946, whose section 4 makes the coordinates WGS 84 longitude and latitude in decimal degrees. A third coordinate is not defined by the schema, so `hae` is not bound.
- `uid` (`id`): the feature's identifier, a URI of the API that names this feature.
- `callsign` (`properties.name`): the station's name, the human-readable label of the station.

## What the geojson wire leaves out

`properties.elevation` (a quantitative-value object) and the station's zone links that are
objects are residue. The station elevation is above mean sea level in the API's practice
and is not `hae`.
