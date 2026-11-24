## The message

One response of `GET https://api.open-meteo.com/v1/forecast` for one location. For several
locations the documentation page says the output becomes a list of structures; each element
is a message of this pack. The request chooses which variables come back; those not asked
for are absent.

`hourly`, `daily` and `minutely_15` are parallel arrays: `hourly.time` holds the times and
each variable, such as `hourly.temperature_2m`, the value at the same position. The pack
reads each array as its own list (`group` with `.` items), so the values keep their order
and the position ties a value to its time; the pack does not join them into records, as no
transform of the pack language zips lists. `current` is one object of scalars.
`hourly_units`, `daily_units` and `current_units` give the unit of each variable as text.

**Convention: timeformat.** By default the time stamps are ISO 8601, in the fixed
offset that `utc_offset_seconds` gives, or UNIX seconds when the request sets
`timeformat=unixtime` (documentation page); the OpenAPI document allows both types. The pack reads the default: the
time members are strings. A response with `timeformat=unixtime` fails on the time members.

## Evidence for the shared keys

- `lat`, `lon` (`latitude`, `longitude`): the Open-Meteo documentation page (https://open-meteo.com/en/docs, read 2026-11-24,
  SHA-256 `d8436072c9587c17bc418d10a00b55307e3493999cef57eed0cee3618e086a06`)
  gives the response members as the WGS 84 coordinates of the centre of the grid cell the
  forecast was made from, which can be a few kilometres from the requested point.

## Not mapped

- `elevation` comes from a 90 metre elevation model; the page states no vertical datum, so
  it is not `hae`.
- The ISO 8601 times of the response read carry no offset, which `iso8601_ms` refuses:
  nothing is `time_ms`.
