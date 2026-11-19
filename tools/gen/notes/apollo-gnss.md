## Shared keys: the evidence

| Keys | Field | What the schema states |
|---|---|---|
| `lon`, `lat`, `hae` | `position` (4) `.lon`, `.lat`, `.height` (4.1 to 4.3, double) | `position` is a `PointLLH`: longitude and latitude in degrees, a point in the global frame, and the height above the WGS-84 ellipsoid in metres |
| `track.sigma_east_m`, `track.sigma_north_m`, `track.sigma_up_m` | `position_std_dev` (5) `.x`, `.y`, `.z` | the standard deviation of the position, east, north and up, in metres |
| `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` | `linear_velocity` (6) `.x`, `.y`, `.z` | the velocity, east, north and up, in metres per second |

`PointLLH` names WGS-84 for the height; latitude and longitude on that ellipsoid are WGS-84
geodetic coordinates, which `lat` and `lon` are. The standard deviations are one-sigma values in
metres, the unit of the `track` sigmas; `model/track.def` derives `ce` and `le` from them, and
`course` and `speed_ms` from the velocity, when a message is converted.
