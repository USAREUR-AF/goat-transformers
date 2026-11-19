## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the WZDx 4.1 specification at tag v4.1 (commit 5952f210026c091bca1e4082c0c4e43cf16eb519)
  (`spec-content/objects/FieldDeviceFeature.md`) makes the geometry a GeoJSON Point per
  RFC 7946, whose section 4 gives WGS 84 longitude and latitude in decimal degrees. No third
  coordinate is defined for a field device, so `hae` is not bound.
- `uid` (`id`): the feed provider's identifier of the field device (a UUID is recommended).

Not bound: `core_details.update_date` (the time the device information was last updated)
is inside an object in `properties`; the geojson wire addresses one level of `properties`
only, so it is residue and `time_ms` is not bound.

## What the geojson wire leaves out

- `properties.core_details` (device type, status, road names, ...) is an object: residue,
  carried back as it was.
- Booleans in `properties` (`is_moving`, `is_flashing`, ...): no `bool` transform on this
  wire, and no ruling on the type of boolean residue; the reference engine writes `"true"`.
- Top-level `bbox`: see the `stac-item` pack (top-level members other than `id`).
- The device type is `core_details.device_type`, inside an object: a kind cannot be selected
  by it, so the pack has one kind whose lines are the members of every device type.
