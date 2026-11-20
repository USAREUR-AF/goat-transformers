## Evidence for the shared keys

- `uid` (`uuid`, both kinds): the identity report gives the robot an RFC 4122 UUID that
  every later message names; the status report repeats it.
- `time_ms` (`timestamp`, both kinds): sections 4.1.2 and 5.1.2 of the standard (the PDF
  in the same repository) make it the time of the report in UTC; the schema types it as a
  date-time. `iso8601_ms` reads it to epoch milliseconds.

Not bound, and why:

- `location.x`, `.y`, `.z` are metres in a local planar datum that a site defines
  (section 3 of the standard), not WGS 84 latitude and longitude; no conversion vector to
  geojson or cot-xml is written for that reason.
- `location.angle` is a quaternion in the same local frame, not a course in degrees true.
- `velocity.linear` is the speed along the robot's heading, signed (forward positive), not
  a ground speed over the earth.

## Kinds

The two reports do not name their type. The identity report is selected by
`manufacturerName` (required there, absent from the status report), the status report by
`operationalState` (required there).
