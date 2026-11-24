# pegelonline-station

PEGELONLINE, the gauge service of the German Federal Waterways and Shipping Administration (WSV),
REST API version 2: one station, `/stations/{id}.json`. With `includeTimeseries=true` (and
`includeCurrentMeasurement=true`) it holds the station's time series, each with its current
measurement and gauge zero. Wire `json`, no kinds. Written by hand; vectors by
`tools/gen/pegelonline-vectors.py`. Licence: `DL-DE-ZERO-2.0`.

## Shared-model keys

| Key | Member | Evidence |
|---|---|---|
| `lon` | `longitude` | The documentation of the Station resource defines `longitude` as the longitude in WGS84, decimal notation. |
| `lat` | `latitude` | Likewise `latitude`: the latitude in WGS84, decimal notation. |

No height of the station is given. The gauge zero (`gaugeZero.value`, raw
`pegelonline.gauge_zero_value`) is a height in metres above the German normal height zero (the
documentation says its unit is always metres above a Normalhöhennull: a national levelling datum,
NHN in DHHN, or the older NN), not above the WGS84 ellipsoid, so it is not `hae`.

## Not mapped, and why

- The current measurement's time is not `time_ms` here: it is a list item, and a shared key of the
  entity cannot be filled from one item (a station holds several series). It stays raw, as
  written (`current_time`); `pegelonline-timeseries` and `pegelonline-current` map it.
- `characteristicValues` and `comment` of a series (with `includeCharacteristicValues=true`), and
  other members inside an item the pack does not name: an item carries no residue.
- The station lists (`/stations.json`), the waters list (`/waters.json`) and the measurements of a
  series (`/measurements.json`): root JSON arrays, which the json wire cannot read.
- The CSV and PNG outputs: other wires.

## Message convention

One response body of `/stations/{id}.json` is one message.

## Vectors

| File | Shows |
|---|---|
| `01-station-roundtrip.json` | a station with two series; mapped members in line order, then residue |
| `02-station-to-geojson.json` | the position reaches a GeoJSON Feature |
| `03-latitude-as-text.json` | text in `latitude`: `transform-decode` |

The conversion the other way, a GeoJSON point written as a station, is
`packs/geojson/vectors/pegelonline-geojson-to-station.json` (a vector lives under its `from` pack).
