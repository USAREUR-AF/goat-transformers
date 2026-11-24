# Pack: mf-json

OGC Moving Features Encoding Extension - JSON (MF-JSON) 1.0 (OGC 19-045r3): one moving
feature. Written by hand from the standard's text; the MF-JSON schema files are not used
(`PROVENANCE.md`). Wire `json`.

## Message convention

A message is one moving feature: a JSON object whose `type` is `Feature` (a common `when`).
Two kinds, tried in this order, as the standard gives the Prism encoding priority over the
Trajectory encoding when a document has both (clause 7.2, requirement 2.3):

| Kind | Selected when | Encode requires |
|---|---|---|
| `MovingPoint` | `temporalGeometry.type` is `MovingPoint` (clause 7.2.1.1) | the list `mfjson.datetimes` |
| `Trajectory` | `geometry.type` is `LineString` and `properties.datetimes` is present (clause 7.1, requirement 1.4) | the list `mfjson.trajectory_datetimes` |

A MovingFeatureCollection (`type` `FeatureCollection`) is not one message (`no-kind`); its
features are messages one by one. The other temporal geometry types (MovingLineString,
MovingPolygon, MovingPointCloud, MovingGeometryCollection) are `no-kind`.

## Mapped

| Member | Key | Note |
|---|---|---|
| `id` | `uid` | Clause 7.2.4 (and 7.1, which maps the moving feature's identifier to the Feature's `id`): the commonly used identifier of the feature, the stable identifier of the entity. Read as a string; the standard also allows a number, which fails the decode (`transform-decode`) because a `json` line has one type |
| `temporalGeometry.datetimes` (MovingPoint), `properties.datetimes` (Trajectory) | lists of `mfjson.datetime_ms` | Clause 7.2.1.1 and requirement 1.5: each instant is an RFC 3339 string or a number of milliseconds since 1970-01-01T00:00:00Z UTC. Two lines read the two forms (`iso8601_short`, then `int`); encode writes the first, so a number comes back as an RFC 3339 instant in UTC |
| `temporalGeometry.interpolation` | `mfjson.interpolation` | the motion curve name or URL (clause 7.2.10) |
| `time` | list of `mfjson.instant` | the life span, two RFC 3339 instants (clause 7.2.6), kept as written |
| `bbox` | list of `mfjson.bound` | the bounding box (clause 7.2.7) |

No other shared key is bound. `time_ms` is not bound: a moving feature has one instant per
position, not one time of report, and list items cannot be shared keys.

## Not mapped

- **The positions.** `temporalGeometry.coordinates` of a MovingPoint is an array of
  positions, each an array of two or three numbers in longitude, latitude (and height)
  order for the default CRS (clause 7.2.1.1); a Trajectory's `geometry.coordinates` is the
  same. The `json` wire carries an array only as a group whose items are objects or
  scalars; an item that is itself an array has no locator. So the positions are not
  carried at all: a round trip drops them, and no position binds to `lat` and `lon`. The
  language needs an array-index locator inside a group item (`.0`, `.1`) or a transform
  that carries a JSON subtree as text. Until then this pack carries a moving feature's
  identity, times and metadata, not its movement.
- **`temporalProperties`** (clause 7.2.2): an array of objects whose member names are the
  property names, each holding a `values` array. Items carry no residue and their member
  names are data, so the member is not carried.
- **Arrays in `properties`** (the time-varying attributes of the Trajectory encoding) are
  not carried; scalar members of `properties` are residue.
- **`base` and `orientations`** (clause 7.2.1.1): `base` is an object whose members are
  residue; `orientations` is an array of objects holding arrays and is not carried.
- **Instants of reduced precision** (a year, a month, a time without seconds, which clause
  7.2.1.1 lists among the ISO 8601 forms) fail the decode: `iso8601_short` reads a full
  date-time only.
- **`crs` and `trs`** objects are residue: their scalar members round-trip.

## Vectors

Written by `tools/gen/mf-json-vectors.py`, which holds its own copy of these lines and
works out every expected output from the rules of `spec/engine-spec.md`; no engine is run.
Round trips of a MovingPoint (positions dropped), of epoch-millisecond instants, of a
Trajectory and of a feature with temporal properties; a conversion to `geojson` (the id
only); and four errors (a numeric id, a MovingPolygon, a FeatureCollection, an instant
without seconds). `packs/geojson/vectors/to-mf-json-is-no-kind.json`: a GeoJSON point has
no list of instants, so no kind qualifies.
