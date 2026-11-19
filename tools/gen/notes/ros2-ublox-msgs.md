The positions of four `ublox_msgs` navigation solutions are bound to `core` keys with
the `scale` transform of engine-spec 0.15. The evidence is the comment text of the
.msg files at the commit in `PROVENANCE.md`, quoted in part:

| Kind | Wire fields | Model keys | Evidence |
|---|---|---|---|
| `nav_posllh` | `lat`, `lon` (int32); `height` (int32) | `lat`, `lon` with `scale:1/10000000`; `hae` with `scale:1/1000` | NavPOSLLH.msg: "Latitude [deg / 1e-7]", "Longitude [deg / 1e-7]", "Height above Ellipsoid [mm]"; the file header: the message gives the geodetic position "in the currently selected Ellipsoid. The default is the WGS84 Ellipsoid, but can be changed with the message CFG-DAT" |
| `nav_pvt`, `nav_pvt7` | `lat`, `lon`; `height` | as `nav_posllh` | NavPVT.msg, NavPVT7.msg: "Latitude [deg / 1e-7]", "Longitude [deg / 1e-7]", "Height above Ellipsoid [mm]"; these files name no datum, and the binding takes the receiver's selected ellipsoid as NavPOSLLH.msg states it |
| `hnr_pvt` | `lat`, `lon`; `height` | as `nav_posllh` | HnrPVT.msg: the same three field comments; no datum named, as for `nav_pvt` |

The bindings hold for a receiver left at its default datum, WGS 84. A receiver set to
another datum with CFG-DAT reports positions that `lat`, `lon` and `hae` do not hold.
Messages that carry that setting are in this pack (`cfg_dat`); a reader that cannot
rule out a change should not use the bound keys.

`h_msl` (height above mean sea level) is not `hae` and stays a raw key. The
high-precision components of NAV-HPPOSLLH are not in this version of the package.

Kind `nav_pvt` requires `lat lon`; `hnr_pvt`, `nav_posllh` and `nav_pvt7` also require
their own `i_tow`, so an entity from another format with a position is encoded as
`nav_pvt`.

A value decoded through `scale` is the nearest double to the integer times 1e-7 (or
1e-3); an encoder writes the quotient as a JSON number, which for a value that is not
exact can carry a fraction.

The padding fields of the u-blox layouts are not mapped (`--skip-field-re` in
`tools/gen/ros2-run.sh`).
