## Evidence for the shared keys

- `lon`, `lat`, `hae` (`geometry` of type Point): Part 1 requires that, when the client asks
  for no other coordinate reference system, every geometry is in WGS 84 longitude/latitude
  (CRS84) for two coordinates, or WGS 84 longitude/latitude/ellipsoidal height (CRS84h) for
  three (abstract test `ATS_crs84`; the `bbox` parameter text of `ogcapi-features-1.yaml`
  names both CRS). Degrees and metres above the ellipsoid: `lon`, `lat`, `hae`. A response in
  another CRS (Part 2, `crs` parameter, stated in the `Content-Crs` header) is not WGS 84; the
  pack cannot see the header, so such a response must not be read with this pack.

## What is not carried

- **`id`.** The schema allows a string or an integer. No transform of the pack language reads
  a JSON value that may be either, so `id` is not mapped and `uid` is not bound. The
  `geojson` pack, which maps `id` as a string, reads string identifiers.
- **A geometry other than a Point.** The geojson wire addresses the coordinates of a Point
  only; encode writes `"geometry":null` for any other.
- **`links`** (a top-level array): top-level residue is not settled on the geojson wire.
- **`properties`.** The schema leaves the feature's properties open (no named members); every
  member is residue, carried back as it was.
