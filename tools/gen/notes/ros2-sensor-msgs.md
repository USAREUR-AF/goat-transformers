Three fields of `sensor_msgs/msg/NavSatFix` are bound to `core` keys. The
evidence is the comment text of `sensor_msgs/msg/NavSatFix.msg` at the commit in
`PROVENANCE.md` (Apache License 2.0), quoted in part:

| Wire field | Model key | Evidence in NavSatFix.msg | Note |
|---|---|---|---|
| `msg.latitude` (float64) | `lat` (deg, WGS 84) | file header: "Specified using the WGS 84 reference ellipsoid"; field: "Latitude [degrees]. Positive is north of equator" | same frame, unit and sign |
| `msg.longitude` (float64) | `lon` (deg, WGS 84) | "Longitude [degrees]. Positive is east of prime meridian" | same frame, unit and sign |
| `msg.altitude` (float64) | `hae` (m above the WGS 84 ellipsoid) | "Altitude [m]. Positive is above the WGS 84 ellipsoid (quiet NaN if no altitude is available)" | ellipsoidal height, not mean sea level; rosbridge writes the NaN as `null`, which decodes to an absent `hae` |

Kind `nav_sat_fix` requires `lat lon`, so an entity from another format with a
position is encoded as a NavSatFix.

Not bound, and why:

- `header.stamp` (`sec`, `nanosec`): the file says it is "the ROS time for this
  measurement", which may be simulation time and is not stated as UTC; it is
  also two fields where `time_ms` is one. Raw keys.
- `position_covariance` (ENU, m^2, row-major 3 by 3) and
  `position_covariance_type`: `ce` and `le` are circular and linear errors, a
  different quantity from a covariance matrix; deriving them would need a
  confidence level the message does not state. Raw keys.
- `status.status`, `status.service`: no shared key holds a fix quality or a
  constellation set. Raw keys.
- `header.frame_id`: the antenna's frame on the vehicle, not an identity of the
  vehicle; not `uid`. Raw key.
- No other message of the package states a geodetic frame. `sensor_msgs/msg/TimeReference`
  carries a time from an external source with no stated time base; raw keys.
