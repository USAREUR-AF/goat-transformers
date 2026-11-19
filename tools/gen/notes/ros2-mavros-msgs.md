The position of `mavros_msgs/msg/HomePosition` is bound to `core` keys. The other
position fields of the package are not, for the reasons below.

| Wire field | Model key | Evidence | Note |
|---|---|---|---|
| `msg.geo.latitude` | `lat` (deg, WGS 84) | HomePosition.msg: "geographic_msgs/GeoPoint geo # geodetic coordinates in WGS-84 datum"; GeoPoint.msg: "Latitude [degrees]" | same frame and unit |
| `msg.geo.longitude` | `lon` (deg, WGS 84) | as above; GeoPoint.msg: "Longitude [degrees]" | same frame and unit |
| `msg.geo.altitude` | `hae` (m above the WGS 84 ellipsoid) | GeoPoint.msg: "Altitude [m]. Positive is above the WGS 84 ellipsoid". mavros's `mavros/src/plugins/home_position.cpp` (listed in `PROVENANCE.md`) fills it from the MAVLink altitude in millimetres above mean sea level plus the geoid-to-ellipsoid height | ellipsoidal height |

Kind `home_position` requires `lat lon`.

Not bound, and why:

- `GPSRAW.lat`, `GPSRAW.lon`, `GPSRAW.alt_ellipsoid`, `GPSINPUT.lat` and `GPSINPUT.lon` are stated as
  WGS 84, but as integers in 1e-7 degrees and in millimetres. The `json` wire has no
  scale transform (`sscale` exists on `bits` only), so they cannot be bound to `lat`, `lon` and
  `hae`, which are degrees and metres. They are raw `int` keys. A scale transform on
  `json` would allow the binding.
- `GPSRAW.alt` and `GPSINPUT.alt` are above mean sea level, not the ellipsoid.
- `GlobalPositionTarget.latitude`/`longitude` and `ADSBVehicle.latitude`/`longitude`
  state no datum in the .msg, and their altitudes are "AMSL or above terrain" and
  "AMSL". Raw keys.
- `Waypoint.x_lat`/`y_long`/`z_alt` depend on the `frame` field (global, relative
  or local); one binding cannot hold for every frame. Raw keys.
- `OpenDroneIDSystem` operator position: integers in 1e-7 degrees, as for GPSRAW.
