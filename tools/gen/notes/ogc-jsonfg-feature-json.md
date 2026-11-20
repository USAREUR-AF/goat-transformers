## Evidence for the shared keys

- `time_ms` (`time.timestamp`): JSON-FG's `time` member holds the feature's primary temporal
  information, the instant or interval its publisher considers the most important temporal
  characteristic of the feature; a timestamp is an RFC 3339 instant in UTC (the core
  requirements fix the `Z` time zone, and the schema gives the pattern). That is the time the
  feature's description holds for: `time_ms`. The schema states a pattern, not
  `format: date-time`, so the run passes `--date-time`; `iso8601_ms` reads it. A `date` or an
  `interval` is a raw key, and `time_ms` is then absent.

## What is not carried

The same Feature as `ogc-jsonfg-feature`, read on the json wire so that `time` and the JSON-FG
members are addressable. Positions are not bound here: `geometry.coordinates` and
`place.coordinates` are arrays (numbers for a Point, arrays for other types), which the json
wire reads only as lists. `id`, `featureSchema` and `coordRefSys` take several JSON types and
are not mapped; `properties` is open.
