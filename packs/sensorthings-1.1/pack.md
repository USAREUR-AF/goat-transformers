# Pack: sensorthings-1.1

OGC SensorThings API Part 1: Sensing, version 1.1 (OGC 18-088): one entity as its JSON
object. Written by hand from the entity tables of clause 8.2. Wire `json`. The pack
`sensorthings-1.0` (OGC 15-078r6) has the same kinds and lines and adds the
MultiDatastream of its clause 12; this document covers both.

## Message convention

A message is one entity object: a response to a request for one entity, the body of a
create or update request, or the body of an MQTT message. Clause 14 of the standard sends
and receives the same entity JSON over MQTT (a publish to an Observations topic creates an
Observation; a subscription delivers the entity as the service returns it), so the pack
needs nothing of its own for MQTT: the topic names the entity set and is not part of the
message. A collection response (`value` array, `@iot.nextLink`) and the dataArray form of
clause 13 are not messages of this pack.

## Kinds

The standard gives an entity no type member, so the kind is chosen by a member that only
that entity has. Kinds are tried in this order; the first whose `when` lines hold is used.

| Kind | Selected when | Encode requires |
|---|---|---|
| `MultiDatastream` (1.0 only) | `multiObservationDataTypes` is present | the list of data types |
| `Datastream` | `unitOfMeasurement` is present | `sensorthings.observation_type` |
| `Observation` | `result` is present | `sensorthings.phenomenon_time` |
| `LocationPoint` | `location.type` is `Point` | the position list |
| `LocationFeaturePoint` | `location.geometry.type` is `Point` | the position list |
| `Location` | `location` is present (any other value) | `sensorthings.location_type` |
| `FeatureOfInterestPoint` | `feature.type` is `Point` | the position list |
| `FeatureOfInterestFeaturePoint` | `feature.geometry.type` is `Point` | the position list |
| `FeatureOfInterest` | `feature` is present (any other value) | `sensorthings.feature_type` |
| `Sensor` | `metadata` is present | `sensorthings.encoding_type` |
| `HistoricalLocation` | `time` is present | `time_ms` |
| `ObservedProperty` | `definition` is present | `sensorthings.definition` |
| `Thing` | `name` is present | `callsign` |

An object with none of these members is `no-kind`. An Observation whose `result` is `null`
is not selected as an Observation.

Within a kind the lines follow the order of the entity's table in the standard, so an
encoded entity lists its members in that order. The `when` of a kind stands after the
members its table lists first, so a `location` or `feature` object is written in its
table position. Members that no line maps follow, in input order.

## Mapped to shared keys

| Member | Kind | Key | Evidence |
|---|---|---|---|
| `name` | `Thing` | `callsign` | Table 3 of 1.1 (the Thing table of clause 8.2.1 in both versions) gives a Thing's name as a label for the Thing, usually a descriptive name: the human-readable name the shared key holds. The name of other entities labels a location, a stream, a sensor or a property, not the entity a report is about, and is the raw key `sensorthings.name` |
| `time` | `HistoricalLocation` | `time_ms` | Table 8 gives the time at which the Thing is known to be at its Locations, as a TM_Instant written as an ISO 8601 string: the time the report holds. Read with `iso8601_short`: an offset is converted to UTC; written in UTC with `Z`, without a fraction when the milliseconds are 0 |
| `resultTime` | `Observation` | `time_ms` | Table 18 gives the time the result was produced, a TM_Instant (an ISO 8601 instant, never an interval). It is the one time of an Observation that is always an instant, so it is the one bound |

Not bound, and why:

- **`@iot.id` to `uid`.** Clause 8.1 writes the identifier, the self link and the
  navigation links as annotations whose names hold a dot (`@iot.id`,
  `@iot.selfLink`, and for a navigation link the related set's name followed by
  `@iot.navigationLink`). A `json` locator splits at every dot, and a member
  whose name holds a dot is dropped on decode (engine-spec 0.5, ruling 12). So `uid` is not
  bound and the annotations do not round-trip; an output never holds them. The language
  needs a locator for a member name that holds a dot (an escape or a quoted member name).
- **Positions to `lat`, `lon`, `hae`.** A Location's `location` and a FeatureOfInterest's
  `feature` are GeoJSON when `encodingType` is `application/geo+json` (Table 7), so a Point
  position is the array `coordinates` in longitude, latitude, height order. The `json` wire
  addresses an array only as a group (a list), whose items cannot be shared keys. The pack
  keeps a Point's numbers as the list `sensorthings.location_coordinates` (and three like it)
  so they round-trip, but does not bind them. An array-index locator on `json`
  (`location.coordinates.1`) would bind them; the same need is recorded for the FIWARE Smart
  Data Models in `docs/coverage-roadmap.md`.
- **`phenomenonTime` to `time_ms`.** It is an instant or an interval (Table 18 for an
  Observation; always an interval for a Datastream). A line with `iso8601_short` would fail
  the decode of every Observation whose phenomenon time is an interval, and a `when` cannot
  tell the two forms apart, so it is the raw text `sensorthings.phenomenon_time`.
- **`validTime`** (an interval) and a Datastream's `resultTime` (an interval) are raw text.

## Raw keys (module `sensorthings`)

`name`, `description`, `encodingType`, `definition`, `observationType`, the three members of
`unitOfMeasurement`, `phenomenonTime`, a Datastream's `resultTime`, `validTime`, the `type`
member of a `location` or `feature` that is not a Point, and the Point positions as lists of
`sensorthings.coordinate`. For a MultiDatastream (1.0): `unitOfMeasurements` as the list
`sensorthings.units` and `multiObservationDataTypes` as the list
`sensorthings.multi_observation_data_types`.

## Not mapped (residue or not carried)

- **Carried as residue:** every scalar member no line maps, at any depth of objects:
  `properties` (Thing in 1.0; every entity but HistoricalLocation and Observation in 1.1),
  an Observation's `result` when it is a string, number, boolean or object, `parameters`,
  a Sensor's `metadata` (any JSON value: as residue a string or an object round-trips; a
  line with a fixed type would refuse the others), the `type` and `properties` of a GeoJSON
  Feature in `location` or `feature`.
- **Not carried:** the `@iot` annotations (above); an array no group maps: the coordinates
  of a geometry other than a Point, a Datastream's `observedArea` coordinates,
  `resultQuality` when it is an array, the array result of a MultiDatastream's Observation
  (its output has no `result` and does not decode as an Observation again), and the related
  entities a deep insert nests in arrays (`Locations`, `Observations`). A related entity
  nested as an object (`"Datastream": {"@iot.id": 1}`) holds only an annotation, which is
  dropped, and the empty object is not written.
- **`null` members** are absent: a Datastream's `unitOfMeasurement` whose members are `null`
  (a unitless stream) is not written, and a `null` `resultTime` is not written.

## Vectors

Written by `tools/gen/sensorthings-vectors.py`, which holds its own copy of these lines and
works out every expected output from the rules of `spec/engine-spec.md`; no engine is run.
Per pack: a round trip per kind (three for Location and FeatureOfInterest), an Observation
with offset times and an object result, an Observation create body, conversions to
`geojson` from a Thing, a HistoricalLocation and an Observation, and two errors (`no-kind`,
a `resultTime` that is a date alone). `packs/geojson/vectors/to-sensorthings-*` convert a
GeoJSON point into each pack: with `time_ms` it becomes a HistoricalLocation, without it a
Thing.
