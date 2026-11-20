## What the message is

The pack's message is one Gazebo message of the type named above (package `gz.msgs`), in its
protobuf encoding, as Gazebo's transport library publishes it on a topic or returns it from a
service. The topic names the type; the transport framing is not part of the pack. Each message
type is a pack of its own.

The schema files were read for names, field numbers and types only (`--no-comments`); the notes
here are this repository's own words.

## Frames

Gazebo states poses, positions, velocities and forces in the simulation's local Cartesian frames
(metres, radians, metres per second), relative to the world or to a named model, link or sensor
frame. Those are raw keys: the shared model's positions are geodetic. Only the navigation
satellite messages (`NavSat`, `NavSatWithCovariance`) report a latitude and longitude with their
unit stated; their packs bind them (see their pack.md).

`SphericalCoordinates` holds the latitude and longitude of the world origin, but for a surface
model that its enum chooses: Earth (WGS 84), the Moon, or a custom body. A value of the enum's
first member is not written on the wire in proto3, so no `when` can select the Earth case, and the
fields stay raw. `GPS` is deprecated, and its fields carry no stated units: raw keys.

## Times and the rest

`Time` and `Header.stamp` hold seconds and nanoseconds as two raw integer keys; no transform joins
them into `time_ms`. `bytes` fields (images, point clouds, serialized messages, the value of
`google.protobuf.Any`) have no transform and are not carried. Messages that contain themselves stop
the walk where the type would recur. A message whose `oneof` has members that are not messages is
one layout (`--one-layout`): `Any`, `EntityFactory`, `Packet`.
