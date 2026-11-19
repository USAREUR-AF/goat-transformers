## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the document describes every feature as "A GeoJSON feature" and refers to IETF RFC 7946, whose section 4 makes the coordinates WGS 84 longitude and latitude in decimal degrees. A third coordinate is not defined by the schema, so `hae` is not bound.
- `uid` (`id`): the feature's identifier, a URI of the API that names this feature.
- `time_ms` (`properties.timestamp`): the time of the observation, a `date-time`; `iso8601_ms` reads its offset and converts to UTC.

## What the geojson wire leaves out

Every measurement (`temperature`, `dewpoint`, `windSpeed`, `barometricPressure`, ...) is a
quantitative-value object (`value`, `unitCode`, `qualityControl`) inside `properties`; the
geojson wire maps one level of `properties`, so they are residue, carried back as they
were. The pack `nws-observation-collection` (json wire) maps them member by member.
The station elevation is such an object too, so `hae` is not bound.
