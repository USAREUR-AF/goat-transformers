The positions of `mavros_msgs/msg/HomePosition`, `GPSRAW` and `GPSINPUT` are bound to
`core` keys. The other position fields of the package are not, for the reasons below.

| Wire field | Model key | Evidence | Note |
|---|---|---|---|
| `msg.geo.latitude` | `lat` (deg, WGS 84) | HomePosition.msg: "geographic_msgs/GeoPoint geo # geodetic coordinates in WGS-84 datum"; GeoPoint.msg: "Latitude [degrees]" | same frame and unit |
| `msg.geo.longitude` | `lon` (deg, WGS 84) | as above; GeoPoint.msg: "Longitude [degrees]" | same frame and unit |
| `msg.geo.altitude` | `hae` (m above the WGS 84 ellipsoid) | GeoPoint.msg: "Altitude [m]. Positive is above the WGS 84 ellipsoid". mavros's `mavros/src/plugins/home_position.cpp` (listed in `PROVENANCE.md`) fills it from the MAVLink altitude in millimetres above mean sea level plus the geoid-to-ellipsoid height | ellipsoidal height |

| `GPSRAW` `msg.lat`, `msg.lon` (int32) | `lat`, `lon` with `scale:1/10000000` | GPSRAW.msg: "[degE7] Latitude (WGS84, EGM96 ellipsoid)", "[degE7] Longitude (WGS84, EGM96 ellipsoid)" | degrees times 10^7; `scale` (engine-spec 0.15) turns the integer into degrees |
| `GPSRAW` `msg.alt_ellipsoid` (int32) | `hae` with `scale:1/1000` | GPSRAW.msg: "[mm] Altitude (above WGS84, EGM96 ellipsoid). Positive for up." | millimetres to metres |
| `GPSINPUT` `msg.lat`, `msg.lon` (int32) | `lat`, `lon` with `scale:1/10000000` | GPSINPUT.msg: "[degE7] Latitude (WGS84, EGM96 ellipsoid)", "[degE7] Longitude (WGS84, EGM96 ellipsoid)" | as GPSRAW |

Kind `home_position` requires `lat lon`. Kinds `gpsinput` and `gpsraw` also require
their own `fix_type`, so an entity from another format with only a position is still
encoded as `home_position`, as before these bindings.

A value decoded through `scale` is the nearest double to the integer times 1e-7; it
encodes back to the same integer for most values, and an encoder writes the quotient
as a JSON number, which for a value that is not exact can carry a fraction (a reader
that wants an integer rounds it).

Not bound, and why:

- `GPSRAW.alt` and `GPSINPUT.alt` are above mean sea level, not the ellipsoid.
- `GlobalPositionTarget.latitude`/`longitude` and `ADSBVehicle.latitude`/`longitude`
  state no datum in the .msg, and their altitudes are "AMSL or above terrain" and
  "AMSL". Raw keys.
- `Waypoint.x_lat`/`y_long`/`z_alt` depend on the `frame` field (global, relative
  or local); one binding cannot hold for every frame. Raw keys.
- `OpenDroneIDSystem` operator position: integers in 1e-7 degrees with no datum stated
  in the .msg. Raw keys.
