## Evidence for the shared keys

- `lon`, `lat`, `hae` (`geometry` of type Point): JSON-FG keeps `geometry` as in GeoJSON: the
  requirements class depends on IETF RFC 7946, and a geometry that is not in WGS 84 goes in
  `place`, not `geometry`. RFC 7946 section 4 gives WGS 84 longitude and latitude in decimal
  degrees and an optional height in metres above the WGS 84 ellipsoid.

## What is not carried

- **`time`, `place`, `measures`** are top-level objects, and `featureType` and `featureSchema`
  are top-level members other than `id`; the geojson wire addresses none of them (top-level
  residue is not settled). The instant of `time` is bound to `time_ms` in
  `ogc-jsonfg-feature-json`, which reads the same Feature on the json wire.
- **`id`** is a number or a string; no transform reads either, so `uid` is not bound.
- **`place`** is not bound to a position: it holds a geometry in the CRS that `coordRefSys`
  names, which the pack cannot check; only when that CRS is WGS 84 would it be the same
  meaning.
