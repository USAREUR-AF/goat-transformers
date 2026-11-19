## Evidence for the shared keys

- `lat`, `lon` (`location.lat`, `location.lng`, and the same members of
  `last_telemetry.location`): the MDS general information (mobility-data-specification
  2.0.2, `general-information.md`) states that geographic data in MDS are WGS 84
  (EPSG:4326) coordinates in decimal degrees, and the telemetry model of mds-openapi says
  the same of its latitude and longitude. That is `lat`/`lon` (WGS 84, degrees).
- `speed_ms` (`location.speed`): the GPS type gives the speed in metres per second as
  the GPS or GNSS receiver estimates it: a ground speed, as `speed_ms` is.
- `time_ms` (`timestamp`, `last_telemetry.timestamp`): the timestamp data type is an
  integer count of milliseconds since the Unix epoch, and the member is the time the
  telemetry point or event occurred. `time_ms` is epoch milliseconds UTC.
- `uid` (`device_id`): a UUID that identifies the device across messages; `uid` is the
  stable identifier of the entity.

Not bound, and why:

- `location.altitude` is above mean sea level; `hae` is above the WGS 84 ellipsoid.
- `location.heading` is an angle clockwise from true north, but the data type does not
  say it is the direction of travel (it may be where the vehicle points); `course` is the
  direction of travel.
- `location.horizontal_accuracy` and `vertical_accuracy` are metres with no stated
  confidence level; `ce` and `le` have one.
- `trip.start_location` and `trip.end_location` are two positions of one message; neither
  is "the" position of the entity.

## Kinds

An MDS object does not name its own type, so each kind is selected by a member only that
model has (`when <member> present`, ruling 27 of 0.5), in this order: vehicle status
(`last_telemetry`), trip (`trip_id`), event (`event_id`), telemetry (`telemetry_id`),
vehicle (`vehicle_type`). A vehicle status holds an event and a telemetry object, but not at
its top level, so the order is safe. Encode from another format selects a kind by its
`requires` key: an entity from geojson or cot-xml needs the context key
`mds.telemetry_id` to be written as telemetry (`packs/geojson/vectors/gen-geojson-to-mds.json`).
