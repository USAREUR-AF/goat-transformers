The horizontal position of `tier4_api_msgs/msg/AwapiVehicleStatus` is bound to `core`
keys. Nothing else in the package is.

| Wire field | Model key | Evidence | Note |
|---|---|---|---|
| `msg.geo_point.latitude` | `lat` (deg, WGS 84) | AwapiVehicleStatus.msg declares `geo_point` as a `geographic_msgs/GeoPoint`; GeoPoint.msg: "Geographic point, using the WGS 84 reference ellipsoid"; "Latitude [degrees]. Positive is north of equator" | same frame, unit and sign |
| `msg.geo_point.longitude` | `lon` (deg, WGS 84) | GeoPoint.msg: "Longitude [degrees]. Positive is east of prime meridian" | same frame, unit and sign |

Kind `awapi_vehicle_status` requires `lat lon`.

Not bound, and why:

- `msg.geo_point.altitude` is a raw key. GeoPoint.msg states the ellipsoid, but
  AwapiVehicleStatus.msg says nothing of where the value comes from, and the
  sibling message `tier4_map_msgs/MapProjectorInfo` warns that the altitude of its
  own GeoPoint may not be an ellipsoidal height. The binding is not shown.
- `msg.pose` is a `geometry_msgs/Pose` in the frame named by `msg.header.frame_id`,
  a local map frame; no shared key holds a local position.
- `tier4_map_msgs/MapProjectorInfo.map_origin` is the origin of a map projection,
  not the position of an entity.
