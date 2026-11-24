# pegelonline-current

PEGELONLINE REST API version 2 (WSV): the current measurement of one time series,
`/stations/{id}/{timeseries}/currentmeasurement.json`: its time, its value in the series' unit
and, for water levels, the two states. Wire `json`, no kinds. Written by hand; vectors by
`tools/gen/pegelonline-vectors.py`. Licence: `DL-DE-ZERO-2.0`.

## Shared-model keys

| Key | Member | Evidence |
|---|---|---|
| `time_ms` | `timestamp` | As in `pegelonline-timeseries`: ISO 8601 local legal time with an explicit offset from UTC, which `iso8601_ms` converts to UTC. |

The time is also kept as written (`pegelonline.current_time`, second line on the locator).

The states: `stateMnwMhw` sets the level against mean low and mean high water (low, normal, high),
`stateNswHsw` against the highest navigable water level (normal, high); either may also be
unknown, commented (a fault, see the series' comment) or out-dated (older than 25 hours). Both are
kept as text.

## Not mapped

- The unit: this response does not carry it; the series does (`pegelonline-timeseries`).

## Message convention

One response body of `currentmeasurement.json` is one message.

## Vectors

| File | Shows |
|---|---|
| `01-current-roundtrip.json` | a summer (+02:00) measurement above mean high water |
| `02-current-to-timeseries.json` | written as a series: under `currentMeasurement`, time in UTC |
| `03-value-as-text.json` | text in `value`: `transform-decode` |
