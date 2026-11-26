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

## Validity flag not applied

Gnss `type` INVALID (0, insufficient observations or integrity warning) and PROPAGATED (1), for which gnss.proto recommends the solution not be used. The pack keeps the flag as a raw key and binds the position whatever it says: a message whose
flag says there is no fix converts with the coordinates it carries (often 0, 0), as if they were a
position. The pack language has no gate for a JSON or protobuf member yet (asked of gt-lang); until
it has, a consumer must read the flag. Bit-level packs of the same messages (PX4) read the shared
keys only when the flag says so.
