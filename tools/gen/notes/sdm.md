## The form: NGSI key-values

A Smart Data Model's `schema.json` and `model.yaml` describe an entity in key-values form:
one JSON object with `id`, `type` and one member per attribute holding its value. That is
the NGSI-v2 `keyValues` representation and the NGSI-LD concise key-values form (without
`@context`). The pack reads that form. The NGSI-LD normalized form wraps every attribute in
an object (`{"type": "Property", "value": ...}`, `GeoProperty`, `Relationship`); the model
files do not describe that wrapping, so a pack of it would be this project's invention, not
the model's.

`type` is the entity type: the pack's common `when type <Model>` checks it on decode and
writes it on encode. Generated from the model's `model.yaml`, in which every reference of
`schema.json` is already resolved.

## Evidence for the shared keys

- `uid` (`id`): every model describes `id` as the unique identifier of the entity.
- `time_ms` (`dateObserved`), in six models only (DeviceMeasurement, AirQualityObserved,
  PhreaticObserved, WaterObserved, BikeLane, SeaConditions): there the member is a
  `date-time` string stated as the date and time of the observation in ISO 8601 UTC, one
  instant. In other models `dateObserved` may be an ISO 8601 interval, or its text does not
  say UTC, so it is a raw key only (an interval would fail the `iso8601_ms` transform).
- `course` (Vehicle `heading`): the direction of travel in degrees, clockwise from true
  north, in [0, 360).

Not bound: speeds are kilometres per hour (Vehicle, FleetVehicleStatus, Aircraft) and the
json wire has no scaling transform; `bearing` and the heading of aircraft and vessels are
not stated as the direction of travel.

## The location is not carried

`location` (and `previousLocation` and similar) is a GeoJSON geometry inside the JSON
object: `{"type": ..., "coordinates": ...}`. The json wire cannot bind it:

- there is no locator for an array element (`location.coordinates[1]`), so `lat` and `lon`
  cannot be bound;
- `coordinates` is a list of numbers for a Point and a list of lists for the other geometry
  types, so it is not a `group` either (an item is a scalar or an object), and arrays are
  not residue on the json wire (engine-spec 0.5).

So a converted or round-tripped entity keeps `location.type` and `location.bbox` and loses
the coordinates. Missing additions, in order of use: an array-index locator on the json wire,
or a transform that carries a JSON value (an object or array) as its canonical text.
