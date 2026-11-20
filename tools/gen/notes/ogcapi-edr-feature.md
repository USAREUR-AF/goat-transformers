## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the feature is a GeoJSON Feature (IETF RFC 7946),
  whose section 4 makes coordinates WGS 84 longitude and latitude in decimal degrees. EDR
  allows a vertical coordinate in a CRS the collection names, so the third coordinate is not
  bound to `hae`.
- `callsign` (`properties.label`): EDR describes `label` as a text such as a site name, to
  show for the feature: a human-readable name.

## What is not carried

- **`id`.** A string or an integer; no transform reads either, so `uid` is not bound.
- **`properties.datetime`.** An instant or a period (`start/end`) in one string, so it is not
  bound to `time_ms`; it is a raw key. `properties.parameter-name` (an array) is residue.
- **`links`** (a top-level array): top-level residue is not settled on the geojson wire.
- **A geometry other than a Point**: encode writes `"geometry":null`.
