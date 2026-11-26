## Evidence for the shared keys

- `time_ms` (`time_measured.value`): the time the telemetry was measured, an RFC 3339
  date-time (the `Time` schema's `value`); `iso8601_ms` reads it.
- `lat`, `lon` (`position.latitude`, `.longitude`): degrees with reference to the WGS 84
  ellipsoid (`Latitude`, `Longitude` schemas).
- `hae` (`position.altitude.value`): height above the WGS 84 ellipsoid, the altitude whose `reference` the schema allows only
  as `W84` (WGS 84) and whose `units` only as metres.
- `speed_ms` (`velocity.speed`): ground speed in metres per second (`units_speed` is
  `MetersPerSecond` only).
- `course` (`velocity.track`): true-north ground track angle in degrees east of north; 360
  means unknown and is `absent`: no `course`, the raw key keeps it, an absent `course` writes 360.

## Licence and source

The source of record is InterUSS's Apache-2.0 api.py module for this interface in
interuss/uas_standards; the OpenAPI file, which states no licence, is read for convenience and
agrees with api.py (tools/gen/utm-crosscheck.py). The ASTM standards (paid documents) were not
used. PROVENANCE.md has the details.
