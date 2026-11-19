## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the document describes every feature as "A GeoJSON feature" and refers to IETF RFC 7946, whose section 4 makes the coordinates WGS 84 longitude and latitude in decimal degrees. A third coordinate is not defined by the schema, so `hae` is not bound.
- `uid` (`id`): the feature's identifier, a URI of the API that names this feature.

## What the geojson wire leaves out

`properties.relativeLocation` (the nearest city, itself a feature) and
`properties.astronomicalData` are objects inside `properties`: residue, carried back as
they were. The JSON-LD form of the response (`application/ld+json`) is not this pack.
