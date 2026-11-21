## The message

One response of Locationforecast 2.0 (`/compact` or `/complete`, JSON): a GeoJSON Feature
whose Point is the forecast location and whose `properties` hold `meta` (the update time and
the unit of each parameter) and `timeseries`, one item per forecast time. The two variants
share the schema; `compact` sends fewer parameters, which are absent here. The `/classic`
XML form is not this pack.

`properties.timeseries` is a list (`group`): each item has the time its values hold for
(`time`, ISO 8601 UTC, a raw string) and the parameters for that instant (`data.instant`)
and for the next 1, 6 and 12 hours (`data.next_1_hours` and so on), each with its
parameters and a weather symbol code. The units are in `properties.meta.units` (degrees
Celsius, hPa, m/s, mm, percent and so on), not repeated per value.

## Evidence for the shared keys

- `lon`, `lat`: the Point coordinates. The document gives them as longitude, latitude,
  altitude; GeoJSON (RFC 7946 section 4) makes them WGS 84 decimal degrees. They are the
  location the forecast was requested for.

## Not mapped

- The third coordinate is the altitude of the location in metres above sea level, not
  above the WGS 84 ellipsoid, so it is not `hae`; the geojson wire addresses a Point
  coordinate only through a shared key, so the altitude is not carried.
- `properties.meta` (the update time and units) is an object one level below
  `properties`, which the geojson wire does not address: it is residue and comes back as
  it was. Its `updated_at` is when the forecast was made, not a time a report is valid, so
  it would not be `time_ms` in any case.
- The forecast times are times in the future: no item time is `time_ms`.
- The `complete` variant sends parameters the document does not list (percentiles of
  temperature and wind speed, apparent temperature, a clear-sky UV index, a confidence of
  the weather symbol). They are inside list items, which carry no residue, so they are not
  carried.
