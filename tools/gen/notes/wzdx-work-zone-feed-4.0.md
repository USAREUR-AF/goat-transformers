## Evidence for the shared keys

- `time_ms` (`road_event_feed_info.update_date`; in 4.0 the work zone feed names its feed information so): "The UTC date and time when the GeoJSON file (representing the instance of the feed) was generated".


The road events or field devices of the feed are the group `features`; their members are
raw keys of the item, and their geometry (a LineString or MultiPoint for a road event, a
Point for a device) is a coordinate array that the json wire does not map
(several JSON types). The feature form with a Point geometry, for a device, is the pack
`wzdx-device` (4.2) and `wzdx-device-4.1`, `wzdx-device-4.0`.
