# defra-ukair-data

The UK-AIR Sensor Observation Service of Defra, REST API version 1 (the 52°North Timeseries
API): the values of one time series, `/timeseries/{id}/getData`. Its `values` hold each value with
its time, in time order. Wire `json`, no kinds. Written by hand; vectors by
`tools/gen/airq-vectors.py`. Licence: `OGL-UK-3.0`.

Each value is a list item of `defraukair.values`: `timestamp` (milliseconds since 1970-01-01
UTC, as `defra-ukair-timeseries` states the evidence) and `value` (in the series' unit, which
this response does not carry; `defra-ukair-timeseries` gives it as `uom`).

## Shared-model keys: none, and why

The times and values are list items, and a shared key of the entity cannot be filled from one
item; a response holds many values. The position and the pollutant are the series', which another
request gives.

## Not mapped

- Members inside an item that the pack does not name: an item carries no residue.
- The rendering outputs of the API (images, chart formats): other responses.

## Message convention

One response body of `/timeseries/{id}/getData` is one message.

## Vectors

| File | Shows |
|---|---|
| `01-data-roundtrip.json` | three hourly values |
| `02-data-empty.json` | a period with no values: an empty list, written back as `[]` |
