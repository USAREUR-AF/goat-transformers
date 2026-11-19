The position of `geographic_msgs/msg/GeoPoint` is bound to `core` keys wherever a
message holds exactly one such point for the whole message. The evidence is the
comment text of the .msg files at the commit in `PROVENANCE.md`, quoted in part:

| Wire field | Model key | Evidence | Note |
|---|---|---|---|
| `latitude` of the point | `lat` (deg, WGS 84) | GeoPoint.msg: "Geographic point, using the WGS 84 reference ellipsoid"; "Latitude [degrees]. Positive is north of equator" | same frame, unit and sign |
| `longitude` of the point | `lon` (deg, WGS 84) | GeoPoint.msg: "Longitude [degrees]. Positive is east of prime meridian" | same frame, unit and sign |
| `altitude` of the point | `hae` (m above the WGS 84 ellipsoid) | GeoPoint.msg: "Altitude [m]. Positive is above the WGS 84 ellipsoid (NaN if unspecified)" | ellipsoidal height; a NaN arrives as `null` and decodes to an absent `hae` |

The point is at these paths, one kind each:

| Kind | Path of the point |
|---|---|
| `geo_point` | `msg` |
| `geo_point_stamped` | `msg.position` |
| `geo_pose` | `msg.position` |
| `geo_pose_stamped` | `msg.pose.position` |
| `geo_pose_with_covariance` | `msg.pose.position` |
| `geo_pose_with_covariance_stamped` | `msg.pose.pose.position` |
| `way_point` | `msg.position` (WayPoint.msg: "Position relative to WGS 84 ellipsoid") |

Each of these kinds requires `lat lon`. An entity from another format with a
position is therefore encoded as `geo_point`, the first of them in pack order.

Not bound, and why:

- `BoundingBox` holds two corners, and `GeoPath`, `GeographicMap`, `RoutePath` and
  the like hold lists of points: none of them is the position of one entity.
- `orientation` of a GeoPose is a quaternion in East-North-Up axes; no shared key
  holds an attitude.
- `WayPoint.id` (`unique_identifier_msgs/UUID`, sixteen bytes in base64) names the
  way-point inside a map. It is not stated to identify a tracked entity, so it is
  not bound to `uid`.
- `header.stamp` is ROS time, which may be simulation time, so it is not bound to `time_ms`.
