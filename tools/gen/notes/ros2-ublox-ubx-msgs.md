The positions of three `ublox_ubx_msgs` navigation solutions are bound to `core` keys
with the json `scale` transform (engine-spec 0.15), and the raw integer keys stay at
the same places. The evidence is the comment text of the .msg files at the commit in
`PROVENANCE.md`, in this project's words:

| Kind | Wire fields | Model keys | Evidence |
|---|---|---|---|
| `ubx_nav_pvt` | `lat`, `lon` (int32); `height` (int32) | `lat`, `lon` with `scale:1/10000000`; `hae` with `scale:1/1000` | the file gives latitude and longitude in degrees scaled by 1e-7, and the height over the ellipsoid in millimetres, beside a separate height over mean sea level |
| `ubx_nav_pos_llh` | the same three | the same | the same field comments |
| `ubx_nav_hp_pos_llh` | the same three | the same | the same field comments; the high-precision parts (`lat_hp`, `lon_hp`, `height_hp`) refine each value and are raw keys, not added in |

None of these files names the datum. As for `ros2-ublox-msgs` (the KumarRobotics
package for the same receivers), the bindings take the receiver's configured datum,
WGS 84 by default; a receiver set to another datum reports positions that `lat`,
`lon` and `hae` do not hold.

Kind `ubx_nav_pvt` requires `lat lon`; `ubx_nav_hp_pos_llh` and `ubx_nav_pos_llh`
also require their own `itow`, so a position from another format becomes a
`ubx_nav_pvt`. `hmsl` is not `hae` and stays a raw key.
