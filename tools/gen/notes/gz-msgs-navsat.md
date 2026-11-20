
## Shared keys: the evidence

| Keys | Field | What the schema states |
|---|---|---|
| `lat`, `lon` | `latitude_deg`, `longitude_deg` (double) | latitude and longitude, in degrees |
| `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms` | `velocity_east`, `velocity_north`, `velocity_up` (double) | the velocity toward east, north and up in the ENU frame, in metres per second |

The schema states the unit of latitude and longitude but names no datum. The binding to `lat`
and `lon`, which are WGS 84, rests on the reading that a navigation satellite fix is reported in
WGS 84 (the same schema set names WGS 84 as the Earth surface model of `SphericalCoordinates`).
A reviewer who does not accept the reading removes the `--map` lines of
these fields from `tools/gen/gz-msgs-run.sh`; the raw keys stay on the same paths.

`altitude` is in metres, with no stated reference (ellipsoid or sea level), so it is not `hae`: a
raw key. `model/track.def` derives `course` and `speed_ms` from the east and north velocity when a
message is converted.
