The latitude and longitude of `sbg_driver/msg/SbgGpsPos` and `SbgEkfNav` are bound
to `core` keys. The evidence is the comment text of the .msg files at the commit in
`PROVENANCE.md`, in this project's words:

| Kind | Wire fields | Model keys | Evidence |
|---|---|---|---|
| `sbg_ekf_nav` | `msg.latitude`, `msg.longitude` (float64) | `lat`, `lon` | the file gives latitude and longitude in degrees, north and east positive, and relates the reported altitude to the WGS-84 ellipsoid through the undulation field |
| `sbg_gps_pos` | `msg.latitude`, `msg.longitude` (float64) | `lat`, `lon` | the same comments |

Kind `sbg_ekf_nav` (the fused navigation solution) comes first in pack order, so a
position from another format becomes an `sbg_ekf_nav`.

Not bound: `altitude` is over mean sea level, not the ellipsoid; the height over the
ellipsoid is altitude plus undulation, which no transform adds. Velocities and
accuracies are raw keys. The time fields (`time_stamp`, the time of week of the satellite clock) are
not UTC epoch times.

## Validity flag not applied

sbg_ekf_nav: SbgEkfStatus `solution_mode` 0 (all data invalid) and `position_valid`; sbg_gps_pos: SbgGpsPosStatus `status` other than 0, `type` 0 (no solution), and `ifm` 4 (position invalid). The pack keeps the flag as a raw key and binds the position whatever it says: a message whose
flag says there is no fix converts with the coordinates it carries (often 0, 0), as if they were a
position. The pack language has no gate for a JSON or protobuf member yet (asked of gt-lang); until
it has, a consumer must read the flag. Bit-level packs of the same messages (PX4) read the shared
keys only when the flag says so.
