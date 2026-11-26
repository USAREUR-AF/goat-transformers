# gpx

GPX 1.1, the GPS Exchange Format: an XML document of waypoints, routes and
tracks, published by TopoGrafix as an open standard. Wire `xml`, root `gpx`,
three kinds. Hand-written; vectors derived by
`tools/gen/aviation-xml-vectors.py` (standard library only, no engine).

## Message convention

One message is one GPX document. The pack reads one point of it:

| Kind | Holds when | The point read |
|---|---|---|
| `waypoint` | a `wpt` has `lat` | the first `wpt` |
| `route-point` | `rte/rtept` has `lat` | the first point of the first route, and the route's name |
| `track-point` | `trk/trkseg/trkpt` has `lat` | the first point of the first segment of the first track, and the track's name |

Kinds are tried in this order; a document with waypoints and tracks decodes as
`waypoint`. Encoding from another format picks `waypoint` (the first kind whose
`requires lat lon` holds).

Two common `when` lines check the root: the default namespace must be
`http://www.topografix.com/GPX/1/1` and `version` must be `1.1`. The encoder
writes both, so a converted message is a GPX 1.1 document. The schema requires
`creator`; when the entity has none the encoder writes `goat-transformers`.

Field lines of a point follow the element order of the schema's `wptType`
(ele, time, magvar, geoidheight, name, cmt, desc, src, sym, type, fix, sat,
hdop, vdop, pdop, ageofdgpsdata, dgpsid), and `rte/name` and `trk/name` come
before the points, as `rteType` and `trkType` order them.

## Shared-model keys and the evidence

| Wire | Key | Evidence (schema GPX 1.1, in our words) |
|---|---|---|
| `<pt>/@lat` | `lat` | the `lat` attribute of `wptType` is the latitude in decimal degrees, always on the WGS 84 datum; `latitudeType` is a decimal from -90 to 90 |
| `<pt>/@lon` | `lon` | the `lon` attribute is the longitude in decimal degrees on WGS 84; `longitudeType` runs from -180 inclusive to 180 exclusive |
| `<pt>/time` | `time_ms` | `time` is an `xsd:dateTime` that the schema says is in UTC, ISO 8601, with fractional seconds allowed; `iso8601_ms` reads it (an offset is converted to UTC, digits past milliseconds are truncated) |
| `<pt>/name` | `callsign` | `name` is the point's name as the receiver shows it, free text: the human-readable name of the point |

`<pt>` is `wpt`, `rte/rtept` or `trk/trkseg/trkpt` according to the kind.

## Raw keys (module `gpx`)

`gpx.creator`, `gpx.route_name`, `gpx.track_name`, and per point `gpx.ele`,
`gpx.magvar`, `gpx.geoidheight`, `gpx.cmt`, `gpx.desc`, `gpx.src`, `gpx.sym`,
`gpx.type`, `gpx.fix`, `gpx.sat`, `gpx.hdop`, `gpx.vdop`, `gpx.pdop`,
`gpx.ageofdgpsdata`, `gpx.dgpsid`. Why some are not shared keys:

- `ele` is not `hae`. The schema gives its unit (metres) and no height
  reference. The same type carries `geoidheight`, the geoid above the
  ellipsoid, which suggests `ele` is not ellipsoidal; in common use it is height
  above mean sea level. `hae` would be `ele + geoidheight` when both are
  present, but the derive functions add a constant (`offset:<n>`), not two keys.
- `type` is free-text classification, not a CoT type token.
- `magvar` is a magnetic variation, not a course.
- `hdop`, `vdop`, `pdop` are dilutions of precision, without unit; they are not
  the circular or linear error in metres (`ce`, `le`).
- Limit: a point whose `fix` is `none` still gives `lat` and `lon`. The schema
  (gpx.xsd, `fixType`) says `none` means the GPS had no fix, and that a fix not
  known is written by leaving `fix` out. The pack keeps `fix` as the raw key
  `gpx.fix` only; the xml wire has no condition that leaves a key out when a
  sibling element holds a given text, so the coordinates are read whatever
  `fix` says. A consumer should check `gpx.fix` before it trusts the position.

## Not mapped

- **Later points.** Only the first point of the kind is read. The second and
  later `wpt`, `rtept` and `trkpt`, later routes, tracks and segments are not
  carried (ruling 7 of 0.1.1). A `group` would read them as a list, but a
  `field` whose locator passes through a group's path is `bad-directive`
  (ruling 21 of 0.7), so one pack cannot both put the first point in `lat` and
  `lon` and list all points. A track as a list of points is a second pack or a
  pack-language addition.
- `link` (repeating, with `href` attribute and `text`, `type` children) and
  `extensions` (any element of another schema) under a point, route, track or
  the root.
- `metadata` (name, desc, author, copyright, link, time, keywords, bounds) of
  the document.
- `cmt`, `desc`, `src`, `link`, `number`, `type`, `extensions` of `rte` and
  `trk`; `extensions` of `trkseg`.
- Attributes of the root that no line maps (for example `xmlns:xsi`,
  `xsi:schemaLocation`) are residue and are written back on a GPX round trip;
  child elements no line maps are dropped (ruling 6 of 0.1.1).
- **Namespaces.** The xml wire compares element names as written. A GPX
  document written with a prefix (`<g:gpx xmlns:g="…GPX/1/1">`) has root
  `g:gpx` and matches no kind (`no-kind`, vector 11). GPX files in use declare
  the default namespace on the root, which this pack reads.
- GPX 1.0 (namespace `…/GPX/1/0`, version `1.0`) is another schema and is
  refused (`no-kind`, vector 09).

## Vectors

| File | Case |
|---|---|
| `01-waypoint-roundtrip` | every mapped point element, root residue, decimal and time canonical forms |
| `02-route-point-roundtrip` | route name and first route point |
| `03-track-point-roundtrip` | track name, first point; second point dropped; sub-millisecond time truncated |
| `04-waypoint-to-geojson` | lat, lon, time, name to GeoJSON; ele not carried |
| `05-track-point-to-cot-xml` | to CoT, with CoT's defaults |
| `06-time-offset-to-utc` | `+02:00` converted to UTC |
| `07-range-edges`, `08-range-upper-edges` | -90, -180, 90, 179.999999999; negative zero |
| `09-gpx-1-0-is-no-kind` | other namespace and version |
| `10-no-point-is-no-kind` | metadata only |
| `11-prefixed-root-is-no-kind` | the namespace limitation |
| `12-latitude-not-decimal` | `transform-decode` |
| `13-waypoint-before-track` | kind order |
| `packs/geojson/vectors/91-to-gpx-waypoint` | GeoJSON to GPX: namespace, version and creator written |
| `packs/cot-xml/vectors/20-to-gpx-waypoint` | CoT to GPX |
