## Position assumption

`lon`, `lat` and `hae` are bound to `Location.x` (field 1), `y` (field 2) and `z` (field 3) of `DetectionReport.location` (field 6 of `DetectionReport`, which is field 7 of `SapientMessage`: paths 7.6.1 to 7.6.3). This is the reading the `sapient` pack (BSI Flex 335 v2.0) takes, and `location.proto` of v1.0 declares the same message: `x = 1` 'X-coordinate (normally longitude)', `y = 2` 'Y-coordinate (normally latitude)', `z = 3` 'Z-coordinate (normally altitude)', `coordinate_system = 7`, `datum = 8`. The meaning of x, y, z is set by `Location.coordinate_system` (7.6.7), where 1 is latitude/longitude in decimal degrees and metres, 2 is radians and 5 is UTM, and by `Location.datum` (7.6.8), where 1 is the WGS84 ellipsoid and 2 the geoid. The binding holds only when 7.6.7 is 1, and `hae` is ellipsoid height only when 7.6.8 is 1. Kind `detection_report` therefore has `const 7.6.7 1` and `const 7.6.8 1`: every detection report this pack encodes states the units and datum its `lon`, `lat` and `hae` are in. A constant is written over any field, so a detection report that arrives with another coordinate system or datum leaves with 1 and 1 while its x, y, z are unchanged; decode still fills `sapient1.location_coordinate_system` and `sapient1.location_datum` with what the message said, for a consumer to check before it trusts the position. No other `Location` in the schema (`Alert.location` at 10.6, `StatusReport.node_location` at 6.7, the predicted location at 7.9.2) is bound to core keys; in kind `alert` the same fields are the raw keys `sapient1.location_x`, `location_y`, `location_z`.

## Bound to `track` keys

The same bindings as the `sapient` pack. `detection_report.proto`, `location.proto` and `velocity.proto` of v1.0 give every field below the number and type it has in v2.0.

- `Location.z_error` (7.6.6) is `track.sigma_up_m`: with coordinate system 1 the z error is in metres. `x_error` and `y_error` (7.6.4, 7.6.5) are in degrees there and stay raw.
- `DetectionReport.detection_confidence` (7.7) is `track.confidence`: the schema comment gives the range 0-1.
- `ENUVelocity.east_rate`, `north_rate`, `up_rate` (7.19.1 to 7.19.3) are `track.vel_east_ms`, `track.vel_north_ms`, `track.vel_up_ms`. The message carries no unit: the unit (metres per second or kilometres per hour) is declared in the node's Registration. The binding holds for a node that registered metres per second.
- `DetectionReportClassification.type` (7.11.1) is `track.class` through the table `sapient-class`, the table of the `sapient` pack. `classification` is a repeated field: one occurrence is carried, the last on decode. `unknown` and `other` both encode as `UNKNOWN`, and `UNKNOWN` decodes as `unknown`. The schema leaves the type a free string, so a name the table does not hold passes through unchanged in both directions.

## Differences from the `sapient` pack (v2.0)

The envelope, the nine kinds and their field numbers (4 to 12) are the same; v1.0 has no `additional_information` (field 13 of `SapientMessage`). The v1.0 files do not use the `is_mandatory` field option, so no field of this pack is known to be mandatory, and each kind but the default requires one key: the first raw key only that kind maps. The module is `sapient1`, separate from `sapient`: a v1.0 message and a v2.0 message share the core keys (`lat`, `lon`, `hae`) and the `track` keys above, and nothing else.

## Left raw on purpose

- `DetectionReport.object_id` (7.2): a ULID by the schema comment, allocated by the reporting node for the object. It is not `uid`: an identifier from another format is not a ULID, so nothing is bound to the path and it stays the raw key `sapient1.detection_report_object_id`. The same holds for `report_id` (7.1).
- `google.protobuf.Timestamp` (message timestamp 1, predicted time 7.9.3, task start and end 8.4 and 8.5): two integers, seconds and nanos. No transform joins two wire fields into `time_ms`.
- `DetectionReport.range_bearing` (7.5): position relative to the sensor; the shared model has no key for it.
