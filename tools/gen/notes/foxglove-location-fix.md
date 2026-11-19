## What the message is

The pack's message is one `foxglove.LocationFix`, the protobuf encoding of the Foxglove schema of
that name: a position fix from a satellite navigation receiver, as a robot or vehicle logs it on a
channel of an MCAP file or sends it over the Foxglove WebSocket protocol. The channel or the file
names the schema; the pack takes the bytes of one message.

## Shared keys: the evidence

| Keys | Field | What the schema states |
|---|---|---|
| `lat`, `lon` | `latitude`, `longitude` (1, 2, double) | the message is "A navigation satellite fix for any Global Navigation Satellite System"; the fields are "Latitude in degrees" and "Longitude in degrees" |
| `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` | `velocity.x`, `.y`, `.z` (11.1 to 11.3, double) | "Velocity in local East-North-Up (ENU) frame in m/s"; `Vector3` is `x`, `y`, `z` in that order, so `x` is east, `y` north, `z` up |

### `lat` and `lon`: an inference, stated so that it can be overturned

The schema gives the unit (degrees) and says what the message is (a satellite navigation fix),
but names no datum: neither the `.proto` file nor the JSON Schema, the ROS message files or the
documentation page of `LocationFix` at the commit read says WGS 84. The binding rests on one
inference: a fix from a satellite navigation receiver, in degrees, is reported in WGS 84 (or a
frame that agrees with it to the metre level), which is the datum `lat` and `lon` hold. A producer that fills the
fields with positions in another datum, or a reviewer who does not accept the inference,
removes the two `--map 1=lat --map 2=lon` arguments from `tools/gen/protobuf-2-run.sh` and runs
it again; the fields then stay raw keys as `foxglove.location_fix_latitude` and `_longitude`,
which the pack keeps on the same paths in any case.

`velocity` is an `optional` message: a fix without it has none of the three keys. Through
`model/track.def` the three velocities give `course` and `speed_ms` when a message is converted to
another format.

## Left raw on purpose

- `altitude` (3): metres, with no stated reference (ellipsoid or sea level): not `hae`.
- `heading` (10): a yaw angle in radians, clockwise from north. It is the direction the body
  points, not the direction of travel, and its unit is not degrees: not `course`.
- `position_covariance` (4): nine variances and covariances in square metres in the same frame. The
  model's sigmas are standard deviations, and no transform takes a square root; the list is
  carried as it is.
- `timestamp` (6): `google.protobuf.Timestamp`, seconds and nanoseconds as two raw keys; no
  transform joins them into `time_ms`.
- `color`, `metadata`, `frame_id`, `position_covariance_type`: display and bookkeeping fields.

## Hand-written vectors

`01-fix-roundtrip`; `02-fix-to-geojson` (the position arrives in geojson, and a velocity
of 5 m/s north as `course` 0 and `speed_ms` 5);
`packs/geojson/vectors/93-to-foxglove-location-fix` (the way in: the point's position
becomes latitude and longitude, its course and speed the velocity). All written field by field by `tools/gen/protobuf-2-vectors.py` (standard library only; no engine, no generator).
