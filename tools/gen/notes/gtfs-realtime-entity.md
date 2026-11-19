## What the message is

The pack's message is one `FeedEntity` of GTFS Realtime: one item of the `entity` list of a
`FeedMessage`, taken out of the feed by the caller. A feed on the wire is a `FeedMessage` (pack
`gtfs-realtime`); a caller that wants each vehicle as a shared-model entity splits the feed into its
entities and decodes each one with this pack, and does the reverse to build a feed. The pack does
not split or join a feed: one call converts one entity, because the shared model holds one entity
per message and an item of a list is not decoded by kind (engine-spec 0.7).

## Kinds

`FeedEntity` holds six optional members, `trip_update = 3`, `vehicle = 4`, `alert = 5`,
`shape = 6`, `stop = 7`, `trip_modifications = 8`; the file is proto2 and has no `oneof`. The
schema expects exactly one of them in an entity that is not being deleted. Each member is a kind,
selected by `when <number> present`. `id` (1) and `is_deleted` (2) are common lines. Kind
`vehicle` is last and is the kind an entity from another format encodes as; it requires `lat` and
`lon`.

## Shared keys: the evidence

The schema file states the unit and meaning of each bound field in its comment; the bindings use
those statements only.

| Key | Field | What the schema states |
|---|---|---|
| `lat` | `VehiclePosition.position.latitude` (4.2.1, float) | degrees north in the WGS-84 system |
| `lon` | `VehiclePosition.position.longitude` (4.2.2, float) | degrees east in the WGS-84 system |
| `speed_ms` | `VehiclePosition.position.speed` (4.2.5, float) | the speed the vehicle measures at that moment, in metres per second |
| `uid` | `VehiclePosition.vehicle.id` (4.8.1, string) | the vehicle's identification inside the system, unique per vehicle and usable to follow the vehicle over time |
| `callsign` | `VehiclePosition.vehicle.label` (4.8.2, string) | the label shown to passengers so that they recognise the vehicle: a human-readable name |

`latitude` and `longitude` are 32-bit floats on the wire. A value from another format is narrowed
to the nearest single-precision value on encode (about 1e-7 degrees at mid latitudes), so a
position that crosses into this pack and back can differ in the last digits.

## Left raw on purpose

- `Position.bearing` (4.2.3): degrees clockwise from north, but the schema allows it to be the
  compass bearing or the direction to the next stop, and does not say whether north is true or
  magnetic. `course` is the direction of travel in degrees true, so the field is not bound.
- `VehiclePosition.timestamp` (4.5) and `TripUpdate.timestamp` (3.4): seconds since 1970-01-01
  UTC. `time_ms` is milliseconds, and the protobuf wire has no transform that scales an integer.
- `Position.odometer` (4.2.4): metres travelled, no shared key.
- `FeedEntity.id` (1): the schema uses it to replace or delete an entity in a later feed and says
  it identifies the feed entity, not the vehicle, so it is not `uid`.
- `Stop.stop_lat`, `stop_lon` (kind `stop`): the position of a stop, not of a moving entity; the
  schema does not repeat the datum there. Raw keys.
- Every key of an item of a repeated field (stop time updates, informed entities, translations,
  carriage details, shapes of trip modifications).

## Encoding an entity from another format

`FeedEntity.id` is `required` in the schema. No shared key holds it, so an entity from another
format encodes with no `id`, which a proto2 reader that checks required fields rejects. A caller
supplies it as context: `--set gtfsrt.id=<text>` on the command line, or the `context` of
`convert`. `Position.latitude` and `longitude` are also `required`; kind `vehicle` requires `lat`
and `lon`, so they are always written.

## Extensions

The schema reserves extension ranges (1000 to 1999 and 9000 to 9999) in most messages. A field in
those ranges has no line and is dropped on decode: the protobuf wire keeps no residue, and encode
writes mapped fields only (engine-spec 0.3).

## Hand-written vectors

Written field by field, with expected outputs worked out from the specification by
`tools/gen/protobuf-public-vectors.py` (standard library only; it imports no engine and no
generator):

- `01-vehicle-to-geojson-single-precision`: a vehicle at 52.52 N, 13.405 E; the 32-bit floats
  reach geojson as the doubles they widen to (`52.52000045776367`, `13.404999732971191`).
- `02-vehicle-roundtrip`: the same entity, with `bearing` and `timestamp` kept as raw keys.
- `03-extension-field-dropped`: a field in the extension range of `Position` is not written back.
- `packs/geojson/vectors/91-to-gtfs-realtime-entity-id-from-context`: a point into kind `vehicle`,
  with `FeedEntity.id` from the context.
- `packs/geojson/vectors/92-to-gtfs-realtime-entity-no-position`: a feature with no geometry is
  `no-kind`.
