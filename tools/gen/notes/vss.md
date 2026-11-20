## The form, and why one pack

VSS is a tree of signals, not a set of messages. The pack is one JSON document of the whole
tree, `vss-vehicle`: each branch is an object, each signal its value, the shape a vss-tools
JSON export of values has (`{"Vehicle": {"Speed": 12.5, "CurrentLocation": {...}}}`). A
producer sends whatever part of the tree it has; members it leaves out are absent. The
tree, expanded, has about 1,400 signals, which fit in one pack, so it is not split.

`tools/gen/vss2pack.py` reads the root `spec/VehicleSignalSpecification.vspec` and every
file it includes, and expands `instances` the way the specification describes (a range
`Row[1,2]` is `Row1` and `Row2`; a list of lists is one level per list; a child marked
`instantiate: false` stays beside the instances). The `VehicleDataTypes` branch defines
types, not signals, and is left out. Overlays (vendor additions to the tree) are not read.

## Relation to the KUKSA.val packs

The `kuksa-val-*` packs carry VSS values one datapoint at a time, the signal named by its
path as data; they bind no shared key, because which signal a value belongs to is not a
field of their schema. This pack is the other form: the tree as one document, where the
path is the member's place. The two do not contradict: a KUKSA datapoint for
`Vehicle.Speed` and this pack's `Vehicle.Speed` are the same signal; converting between
them needs a step from datapoints to a document, which the pack language does not have.

## Evidence for the shared keys

- `lat`, `lon` (`Vehicle.CurrentLocation.Latitude`, `.Longitude`): `spec/Vehicle/Vehicle.vspec`
  gives them in degrees, in WGS 84 geodetic coordinates, at the GNSS antenna.
- `hae` (`.Altitude`): metres relative to the WGS 84 reference ellipsoid, at the antenna.
- `time_ms` (`.Timestamp`): the time of the current location from the GNSS system, a string
  in ISO 8601 with the UTC time zone. The schema states that form in the node's text, not as
  a JSON Schema `format`, so the generator is told (`--date-time`). `iso8601_ms` reads it
  and writes milliseconds with `Z`; the raw key keeps the text. A timestamp without a time
  zone designator fails the decode.
- `speed_ms` (`Vehicle.Speed`): the vehicle's speed in km/h, read with `scale:5/18`
  (1 km/h is 5/18 m/s exactly). The raw key's line comes first, so a same-format round trip
  writes the speed as read; a speed from another format is written in km/h.

Not bound:

- `course`: `Vehicle.CurrentLocation.Heading` is relative to geographic (true) north, but it
  is the vehicle's heading, where it points, not its direction of travel, which is what
  `course` means (the same distinction the `sdm` and `sds-tms` packs keep). Raw key.
- `HorizontalAccuracy` and `VerticalAccuracy` are accuracies in metres whose confidence
  level the specification does not state, so not `ce` or `le`.
- The other speeds, positions and times of the tree (wheel speeds, the speed of the
  powertrain, timestamps of other branches) are not the vehicle's own report.
