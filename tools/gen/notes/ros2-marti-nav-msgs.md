The `wgs84` point of `marti_nav_msgs/msg/Wgs84Sample` is bound to `core` keys. The
evidence is the comment text of `Wgs84Sample.msg` at the commit in `PROVENANCE.md`,
in this project's words:

| Wire field | Model key | Evidence |
|---|---|---|
| `msg.wgs84.y` (float64) | `lat` (deg, WGS 84) | the file names the point a WGS-84 measurement and gives its y as latitude in decimal degrees |
| `msg.wgs84.x` (float64) | `lon` (deg, WGS 84) | the same comment gives x as longitude in decimal degrees |
| `msg.wgs84.z` (float64) | `hae` (m over the WGS 84 ellipsoid) | the same comment gives z as the altitude over the reference ellipsoid in metres |

The sample pairs that measurement with the vehicle's local odometry position, so the
point is where the vehicle was. Kind `wgs84_sample` requires `lat lon`.

Not bound: `odom` (a local frame), `wgs84_covariance` (a covariance, not an error
radius), and `header.stamp` (ROS time, which may be simulation time). No other
message of the package states a WGS 84 position: `RoutePoint` holds a pose and the
path messages hold points, all with no geodetic frame stated.
