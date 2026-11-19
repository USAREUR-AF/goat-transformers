Six kinds of `px4_msgs` state a position in WGS 84. They are bound to `core`
keys where the .msg file states the datum, and to `hae` only where it states the
ellipsoid. The evidence is the comment text of the .msg files at the commit in
`PROVENANCE.md`, quoted in part:

| Kind | Wire fields | Model keys | Evidence |
|---|---|---|---|
| `sensor_gnss` | `latitude`, `longitude`, `altitude_ellipsoid` | `lat`, `lon`, `hae` | "GNSS receiver report, position in WGS84"; "[deg] Latitude", "[deg] Longitude"; "[m] Altitude above the WGS84 ellipsoid" |
| `vehicle_global_position` | `lat`, `lon`, `alt_ellipsoid` | `lat`, `lon`, `hae` | "Fused global position in WGS84"; "Latitude, (degrees)", "Longitude, (degrees)"; "Altitude above ellipsoid, (meters)" |
| `home_position` | `lat`, `lon` | `lat`, `lon` | "GPS home position in WGS84 coordinates"; "Latitude in degrees", "Longitude in degrees" |
| `aux_global_position` | `lat`, `lon` | `lat`, `lon` | "[deg] Latitude in WGS84", "[deg] Longitude in WGS84" |
| `target_gnss` | `latitude_deg`, `longitude_deg` | `lat`, `lon` | "Landing target GNSS position in WGS84 coordinates"; "[deg] Latitude", "[deg] Longitude" |
| `camera_capture` | `lat`, `lon` | `lat`, `lon` | "Latitude in degrees (WGS84)", "Longitude in degrees (WGS84)" |

Each of these kinds requires `lat lon`. An entity from another format with a
position is encoded as `aux_global_position`, the first of them in pack order.

Not bound, and why:

- `altitude_msl`, `alt` (AMSL) and `altitude_msl_m` are above mean sea level, not the
  ellipsoid, so they are not bound to `hae`.
- `RangingBeacon.lat`/`lon` state no datum; only its altitude type names WGS 84.
- `PositionSetpointTriplet` holds three setpoints, not one position. `OrbitStatus`
  and `VehicleCommand` positions depend on a frame field or a command number.
- `timestamp` is microseconds since the system started, not UTC, so it is not
  bound to `time_ms`.
- `SensorGnss.vel_north` and `vel_east` ("[m/s] North velocity", "[m/s] East
  velocity") have the meaning of `track.vel_north_ms` and `track.vel_east_ms`, but
  this batch binds positions only, and the generator binds `core` keys only. They are
  raw keys. `vel_down` points down, against `track.vel_up_ms`, and the json wire has
  no transform that negates a value.
