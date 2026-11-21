# defra-ukair-timeseries

The UK-AIR Sensor Observation Service of Defra (UK air quality monitoring networks), REST API
version 1 (the 52°North Timeseries API): one time series, `/timeseries/{id}`. A series is one
pollutant at one station: its label and unit, the station's number and name, the first and latest
values with their times, and the service parameters (offering, feature, procedure, phenomenon,
category). Wire `json`, no kinds. Written by hand; vectors by `tools/gen/airq-vectors.py`.
Licence: `OGL-UK-3.0`.

## Shared-model keys

| Key | Member | Evidence |
|---|---|---|
| `time_ms` | `lastValue.timestamp` | The server writes a time either as the instant's milliseconds since 1970-01-01 UTC (its Joda-Time millisecond value) or, in its other setting, as ISO 8601 text (`TimeOutputConverter` in helgoland at the commit in PROVENANCE.md); UK-AIR answers with the number. `lastValue` is the newest value of the series, so its time is the time the report holds good for. |

The first value's time stays raw (`defraukair.first_time`, same unit): it is the start of the
record, not the time of the report.

## Not mapped

- The station's position: `station.geometry.coordinates` is an array of latitude, longitude and
  an altitude written as the text `"NaN"` (latitude first, unlike GeoJSON). Array elements cannot
  be addressed on the json wire, so `lat`/`lon` are not bound; the station lists of the API
  (`/stations`) are root arrays, which the json wire cannot read either.
- `extras` and `referenceValues`: arrays, not carried on the json wire.
- Labels and ids of parameters the pack does not name (`service.id`, `procedure.label`,
  `category.label`, the station's `type` and geometry `type`): scalar residue, carried back.
- Times as ISO text (the server's other form): an `int` line fails with `transform-decode`
  (vector 03).
- The SOS XML and SOS JSON (POST) bindings of the same service: SOS XML is namespaced, which the
  xml wire does not rule; the POST binding is a request protocol, not a message.

## Message convention

One response body of `/timeseries/{id}` is one message.

## Vectors

| File | Shows |
|---|---|
| `01-timeseries-roundtrip.json` | one series; mapped members in line order, then the residue |
| `02-series-without-values.json` | a series with no value yet: `time_ms` absent |
| `03-time-as-text.json` | ISO text in `lastValue.timestamp`: `transform-decode` |
