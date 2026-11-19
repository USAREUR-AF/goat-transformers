## Shared keys: the evidence

| Keys | Field | What the schema states |
|---|---|---|
| `lon`, `lat`, `hae` | `position` (4) `.lon`, `.lat`, `.height` (4.1 to 4.3, double) | the position of the inertial unit, a `PointLLH`: longitude and latitude in degrees, a point in the global frame, and the height above the WGS-84 ellipsoid in metres |
| `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` | `linear_velocity` (6) `.x`, `.y`, `.z` | the velocity, east, north and up, in metres per second |

`PointLLH` names WGS-84 for the height; latitude and longitude on that ellipsoid are WGS-84
geodetic coordinates. `euler_angles` (roll, pitch, yaw in radians, in Apollo's own convention),
the angular velocity and the acceleration (vehicle axes) and the covariance lists (squared units)
are raw keys.
