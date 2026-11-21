## Evidence for the shared keys

- `uid` (`id`): the record's identifier, a string the schema requires.
- `lon`, `lat`, `hae` (`geometry` of type Point): the JSON requirements class of Records makes
  a record a GeoJSON Feature (IETF RFC 7946); RFC 7946 section 4 makes coordinates WGS 84
  longitude and latitude in decimal degrees and an optional third value the height in metres
  above or below the WGS 84 ellipsoid.

## What is not carried

- **`time`** (a top-level object: an instant, an interval and a resolution of the resource):
  top-level objects are not addressable on the geojson wire, so `time_ms` is not bound.
  `properties.created` and `properties.updated` are dates of the record itself, not the
  time the resource is valid; they are raw keys only.
- **`conformsTo`, `links`, `linkTemplates`** (top-level arrays): top-level residue is not
  settled on the geojson wire.
- **A geometry other than a Point**, or `null`: encode writes `"geometry":null`.
