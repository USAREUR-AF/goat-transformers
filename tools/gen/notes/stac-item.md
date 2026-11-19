## Evidence for the shared keys

- `lon`, `lat`, `hae` (`geometry` of type Point): the Item specification says the geometry is
  formatted according to RFC 7946 and its coordinates are longitude, latitude and elevation
  on WGS 84. RFC 7946 section 4 gives decimal degrees and, for the third position, height in
  metres above or below the WGS 84 ellipsoid: `lon`, `lat` and `hae`.
- `time_ms` (`properties.datetime`): the date and time of the assets, in UTC, formatted per
  RFC 3339. The `iso8601_ms` transform reads it (an offset is converted to UTC) and writes
  it back with milliseconds and `Z`; the raw key `stac.properties_datetime` keeps the text
  as written. `datetime` may be `null` (with `start_datetime` and `end_datetime`): then
  `time_ms` is absent.
- `uid` (`id`): the provider's identifier of the Item, unique within its Collection.

## What the geojson wire leaves out of a STAC Item

- **A geometry other than a Point.** Most Items are footprints (Polygon). The geojson wire
  addresses the coordinates of a Point only; any other geometry is not carried, and encode
  writes `"geometry":null`.
- **Top-level members other than `id`:** `stac_version`, `stac_extensions`, `collection`,
  `bbox`, `links`, `assets`. Spec 0.1 lists `<name>` (a top-level member) as a geojson
  locator, and ruling 4 of 0.1.1 orders "top-level residue" after the mapped members; the
  Residue section of 0.1 names only `properties` members, and the reference engine refuses a
  top-level locator other than `id` (`bad geojson locator`) and drops top-level residue. The
  generator maps `id` only (`--top-level-members id`) until a ruling settles this.
- **Booleans in `properties`.** There is no `bool` transform on this wire, and no ruling
  says whether residue gives a boolean back as a boolean; the reference engine writes
  `"true"`.

## A defect of the schema set

`common.json` of STAC 1.1.0 declares `$id`
`https://schemas.stacspec.org/v1.1.0/item-spec/json-schema/commonjson` (no `.` before
`json`), while `item.json` refers to `common.json`. The run passes
`--alias .../common.json=<the file>` so the reference resolves to that file.
