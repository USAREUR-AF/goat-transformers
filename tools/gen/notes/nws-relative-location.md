## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the document describes every feature as "A GeoJSON feature" and refers to IETF RFC 7946, whose section 4 makes the coordinates WGS 84 longitude and latitude in decimal degrees. A third coordinate is not defined by the schema, so `hae` is not bound.

## What the geojson wire leaves out

`properties.distance` and `properties.bearing` are quantitative-value objects: residue. The
feature has no `id` in the schema, so `uid` is not bound.
