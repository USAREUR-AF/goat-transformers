# coops-data

One response of the NOAA CO-OPS Data Retrieval API (tides and currents) in JSON form
(`format=json`). Wire `json`, three kinds. Written by hand from the API documentation's
response columns; vectors are derived by `tools/gen/usgov2-vectors.py`.

| Kind | Holds when | What it is |
|---|---|---|
| `observations` | `data` is present | station `metadata` (id, name, lat, lon) and the list of observations |
| `predictions` | `predictions` is present | the list of tide predictions |
| `error` | `error.message` is present | the error of a refused request |

The observation list maps the union of the documented columns of the water level, air gap,
meteorological and water temperature products (`t`, `v`, `s`, `d`, `dr`, `g`, `ty`, `f`,
`q`); an observation has the columns of its product. Every value is a JSON string, as the
API sends it, so every line is `string`.

## Not bound to shared keys, and why

- `metadata.lat` and `metadata.lon` are text, and the documentation describes neither their
  unit nor their datum (the Metadata API shows station positions only in examples): raw
  keys `coops.station_lat`, `coops.station_lon`.
- `t` is a date and time written `yyyy-MM-dd HH:mm` in the time zone the request named
  (`gmt`, `lst` or `lst_ldt`); the response does not say which, so it is a raw key and not
  `time_ms`.
- `v` is in the units (`english` or `metric`) and the datum the request named; the response
  does not carry them.

## Not mapped

- The products whose responses have other columns: daily and monthly means, daily
  maximum and minimum, datums, current observations and current predictions (`b`, echo and
  correlation columns, `Velocity_Major`, ...), the one-minute water level with its six-minute
  and hourly columns.
- The `type` (H or L) that a high/low prediction carries: the documentation lists only `t`
  and `v` for predictions, so it is not a line, and an item carries no residue: it is lost on
  a round trip.
- The XML and CSV forms of the API: XML namespaces are not yet ruled, and CSV is not this
  wire.
