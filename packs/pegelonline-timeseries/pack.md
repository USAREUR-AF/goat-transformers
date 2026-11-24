# pegelonline-timeseries

PEGELONLINE REST API version 2 (WSV): one time series of a station,
`/stations/{id}/{timeseries}.json`, such as `W` (water level). With
`includeCurrentMeasurement=true` it holds the current measurement; the gauge zero is given for
water levels. Wire `json`, no kinds. Written by hand; vectors by
`tools/gen/pegelonline-vectors.py`. Licence: `DL-DE-ZERO-2.0`.

## Shared-model keys

| Key | Member | Evidence |
|---|---|---|
| `time_ms` | `currentMeasurement.timestamp` | The documentation says every time is local legal time (CET/CEST) and is written in JSON as ISO 8601 with an explicit offset from UTC; the `iso8601_ms` transform takes the offset and gives the instant in UTC. The current measurement is the newest value of the series, so its time is the time the report holds good for. |

The time is also kept as written (`pegelonline.current_time`, the same locator, second line), so
the local time and its offset survive in the model. On encode the shared line comes first
(ruling 16 of 0.5), so the time is written back in UTC with `Z`.

The gauge zero is a height above the German normal height zero, not the ellipsoid; see
`pegelonline-station`.

## Not mapped

- `characteristicValues` and `comment`: arrays or members the pack does not name; scalar residue
  of nested objects is carried back, arrays are not.

## Message convention

One response body of `/stations/{id}/{timeseries}.json` is one message.

## Vectors

| File | Shows |
|---|---|
| `01-timeseries-roundtrip.json` | a water-level series; its +01:00 time is written back in UTC |
| `02-timeseries-plain.json` | a series without its current measurement: `time_ms` absent |
