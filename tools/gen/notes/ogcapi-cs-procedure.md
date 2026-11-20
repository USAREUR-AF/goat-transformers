## Evidence for the shared keys

- `uid` (`properties.uid`): the GeoJSON encoding of Part 1 (requirement
  `/req/geojson/feature-attribute-mapping`) puts the feature's unique identifier in
  `properties.uid`, a URI that stays the same whatever the resource's address; the schema
  describes it as globally unique. The top-level `id` is the server's local identifier and
  states no JSON type, so it is not mapped.
- `callsign` (`properties.name`): the same requirement puts the feature's human-readable
  name in `properties.name`.
- A procedure has no location: the encoding maps no attribute of a procedure to `geometry`,
  so no position key is bound.

## What is not carried

- **`links`, `bbox`** and the other top-level members except `id`: top-level residue is
  not settled on the geojson wire.
- **`properties.validTime`** (an array of two date-times) and the `@link` members (objects)
  are residue, carried back as they were.
- **A geometry other than a Point**: encode writes `"geometry":null`.
