## The message

One response of `GET https://api.open-meteo.com/v1/forecast` for one location (a request
with several comma-separated coordinates gets a JSON array of such objects; each element
is a message of this pack). The request chooses which variables come back; those not asked
for are absent.

`hourly`, `daily` and `minutely_15` are parallel arrays: `hourly.time` holds the times and
each variable, such as `hourly.temperature_2m`, the value at the same position. The pack
reads each array as its own list (`group` with `.` items), so the values keep their order
and the position ties a value to its time; the pack does not join them into records, as no
transform of the pack language zips lists. `current` is one object of scalars.
`hourly_units`, `daily_units` and `current_units` give the unit of each variable as text.

**Convention: timeformat.** The time stamps are ISO 8601 local times without an offset
(`2026-11-21T12:00`) by default, or UNIX seconds when the request sets
`timeformat=unixtime`; the document allows both types. The pack reads the default: the
time members are strings. A response with `timeformat=unixtime` fails on the time members.

## Evidence for the shared keys

- `lat`, `lon` (`latitude`, `longitude`): the document gives the request's coordinates as
  WGS 84; the response's are those of the grid cell the forecast was computed for, in the
  same terms. They can differ from the requested point by part of a grid cell.

## Not mapped

- `elevation` is in metres above sea level (the elevation used for downscaling): not `hae`.
- The times are local times without an offset (`utc_offset_seconds` gives the offset),
  which `iso8601_ms` refuses, and they are forecast times: nothing is `time_ms`.
