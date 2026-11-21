## Evidence for the shared keys

- `time_ms` (`telemetry.time_measured.value`): the time the telemetry was measured, an RFC 3339
  date-time (the `Time` schema's `value`); `iso8601_ms` reads it.
- `lat`, `lon` (`telemetry.position.latitude`, `.longitude`): degrees with reference to the WGS 84
  ellipsoid (`Latitude`, `Longitude` schemas).
- `hae` (`telemetry.position.altitude.value`): height above the WGS 84 ellipsoid, the altitude whose `reference` the schema allows only
  as `W84` (WGS 84) and whose `units` only as metres.
- `speed_ms` (`telemetry.velocity.speed`): ground speed in metres per second (`units_speed` is
  `MetersPerSecond` only).
- `course` (`telemetry.velocity.track`): true-north ground track angle in degrees east of north; 360
  means unknown and passes through as a number.
- `uid` (`operational_intent_id`): the identifier of the operational intent whose vehicle the
  telemetry describes.

## Licence and source

The source of record is InterUSS's Apache-2.0 api.py module for this interface in
interuss/uas_standards; the OpenAPI file, which states no licence, is read for convenience and
agrees with api.py (tools/gen/utm-crosscheck.py). The ASTM standards (paid documents) were not
used. PROVENANCE.md has the details.
