## What the message is

The pack's message is one Apollo message of the type named above, serialized as protobuf, as an
Apollo module publishes it on a channel of its Cyber RT middleware or writes it into a record
file. The channel or the record names the type; the pack takes the bytes of one message.

## Positions in Apollo messages

`modules/common_msgs/basic_msgs/geometry.proto` defines two kinds of point:

- `PointENU`: east, north and up in metres from the origin of the map. The map is a Universal
  Transverse Mercator projection; its zone and origin are part of the map, not of the message.
  Perception, prediction, planning and localization report positions this way.
- `PointLLH`: longitude and latitude in degrees and the height above the WGS-84 ellipsoid in
  metres: a point in the global frame.

Only a `PointLLH`, or a field whose own schema states degrees in WGS-84, is bound to `lat`,
`lon` and `hae`. A `PointENU` is a raw key: turning it into latitude and longitude needs the map's
projection, which the message does not carry, and its axes are grid axes, not true north.
Velocities in the map frame are left raw for the same reason.

## Times

`Header.timestamp_sec` is a double of seconds (publishing time) and `measurement_time` a double
of seconds since the GPS epoch (1980-01-06). `time_ms` is an integer of milliseconds since 1970
in UTC; no protobuf transform turns a double of seconds into it, and time counted from the
1980 epoch of the satellite system runs ahead of UTC by the leap seconds. Both are raw keys.
