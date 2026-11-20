## What the message is

The pack's message is one ASAM Open Simulation Interface (OSI) message of the type named above,
in its protobuf encoding (package `osi3`), as a simulation component passes it to another through
the OSI interface (in an FMU, over a network socket, or in a trace file). A trace file puts a
length or a delimiter before each message; that framing is not part of the pack. Each top-level
OSI message is a pack of its own: they are separate interfaces, not members of one union message,
so they cannot be kinds of one pack.

The schema files were read for names, field numbers and types only (`--no-comments`); the notes
here are this repository's own words.

## Positions and frames

OSI states positions, velocities and orientations in its own Cartesian world frame, in metres,
radians and metres per second, or relative to a vehicle or sensor frame. Those are raw keys: the
shared model's `lat`, `lon` and `hae` are geodetic. `GroundTruth.proj_string` may describe the
world frame as a PROJ projection string, with `proj_frame_offset` relocating it; turning world
coordinates into a latitude and longitude needs that projection to be evaluated, which no pack
transform does, so `proj_string` is carried as text and nothing is derived from it.

The one geodetic position OSI states is `GeodeticPosition` (in `osi_common.proto`): longitude
and latitude in decimal degrees on WGS 84, and an altitude in metres above sea level by the
EGM96 geoid. It is used by the host vehicle's on-board localization,
`HostVehicleData.vehicle_localization.geodetic_position`.

## Times and identifiers

`Timestamp` is a signed count of seconds and a count of nanoseconds, two raw integer keys; no
transform joins them into `time_ms`. `Identifier` holds an unsigned integer; `uid` is a string,
and no transform turns an integer into text, so identifiers are raw keys.

## Not mapped

- `bytes` fields (image, point cloud and other sensor-specific data) have no transform.
- Messages that contain themselves stop the walk where the type would recur; paths below depth 6
  are not walked (pack.md counts them).
- `osi_version.proto`, which the release builds from `osi_version.proto.in` and the `VERSION`
  file, is made the same way by the run script; its file option `current_interface_version` is
  not a field of any message.
