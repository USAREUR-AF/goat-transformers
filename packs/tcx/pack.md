# tcx

A Garmin Training Center Database document (TCX, schema version 2): the activities recorded by a
fitness device, each with its laps, the tracks of a lap and the trackpoints of a track. Wire
`xml`, one kind, `database`. Written by hand from the XML schema; vectors are derived by
`tools/gen/lwm2m-tcx-vectors.py`. Licence: `LicenseRef-unstated` (PROVENANCE.md).

## Layout

| Lines | What |
|---|---|
| `root TrainingCenterDatabase`, `when @xmlns http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2` | the root element and its default namespace. As in the `kml` pack, the namespace is the root's `xmlns` attribute and the elements carry no prefix, so no namespace rule is needed; another namespace (TCX version 1) is `no-kind` |
| `group tcx.activities Activities/Activity` | each activity: `@Sport`, `Id`, its laps, `Notes` |
| `group tcx.laps Lap` | each lap: `@StartTime`, `TotalTimeSeconds`, `DistanceMeters`, `MaximumSpeed`, `Calories`, `AverageHeartRateBpm/Value`, `MaximumHeartRateBpm/Value`, `Intensity`, `Cadence`, `TriggerMethod`, its tracks, `Notes` |
| `group tcx.tracks Track` and `group tcx.trackpoints Trackpoint` | each trackpoint: `Time`, `Position/LatitudeDegrees`, `Position/LongitudeDegrees`, `AltitudeMeters`, `DistanceMeters`, `HeartRateBpm/Value`, `Cadence`, `SensorState` |

Lines are in the schema's element order, so a document written in that order comes back as it
was. Date-times (`Id`, `@StartTime`, `Time`) are `string`: the schema types them as XML
date-times, which may carry an offset or none, and `iso8601_ms` reads UTC with `Z` only.
Doubles are `float`, the unsigned short `Calories` and the byte-sized heart rates and cadences
`int`.

## Shared-model keys: none, and why

- A position is a trackpoint's, and a trackpoint is an item of a list several levels down. A
  shared key such as `lat` belongs to the entity, not to an item, and there is no single
  position of a document to bind: the language cannot pick one trackpoint (the first or the
  last) out of a list.
- The schema types `LatitudeDegrees` and `LongitudeDegrees` as doubles within -90..90 and
  -180..180 and states no datum; `AltitudeMeters` states no reference surface. `lat` and `lon`
  mean WGS 84 and `hae` the ellipsoid, so even a single point could not be bound on the
  schema's word alone.

## Not mapped

- `Folders`, `Workouts`, `Courses`, `Author`, `MultiSportSession` and the `Training` and
  `Creator` of an activity. They are not activity records. The root's own unmapped elements
  come back as residue; inside an item (an activity, lap, track or trackpoint) nothing unmapped
  comes back, as an item carries no residue.
- `Extensions` at every level: elements of other schemas (the Garmin activity extension with
  speed and power, for example). Inside an item they are dropped.
- Prefixed elements (`ns3:TPX`): XML namespaces are not ruled (spec, "Not ruled" in 0.11). The
  vectors write extensions with a default namespace, and those are dropped with their item's
  unmapped content.

## Vectors

| File | Shows |
|---|---|
| `01-run-roundtrip.json` | one run: an activity, one lap, one track, three trackpoints |
| `02-two-activities-roundtrip.json` | two activities, a lap with two tracks and a lap with none |
| `03-trackpoint-extensions-are-dropped.json` | an `Extensions` element inside a trackpoint is dropped |
| `04-version-1-namespace.json` | the TCX version 1 namespace: `no-kind` |
| `05-calories-not-an-integer.json` | `Calories` of 3.5: `transform-decode` |
