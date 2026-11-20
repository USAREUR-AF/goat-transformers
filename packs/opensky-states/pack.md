# Pack: opensky-states

The response of the OpenSky Network REST API to `GET /states/all` (and `/states/own`): a
JSON object with the time the state vectors belong to, `time`, and the state vectors,
`states`. Wire `json`. Written by hand from the response table of the API documentation
(PROVENANCE.md). Licence: `LicenseRef-OpenSky` (LICENSES/LicenseRef-OpenSky.txt).

## Mapped

| Member | Key | Transform | Evidence |
|---|---|---|---|
| `time` | `time_ms` | `iscale:1000` | The documentation gives `time` as an integer, the time with which every state vector of the response is associated (each holds the state within the second before it), in Unix seconds as the rest of the API states its times. `time_ms` is epoch milliseconds UTC, so the factor is 1000. |

## Not mapped

| Member | Why |
|---|---|
| `states` | A two-dimensional array: each state vector is a JSON array whose 17 or 18 values are told apart by their position (0 the ICAO 24-bit address, 1 the callsign, 5 and 6 the WGS 84 longitude and latitude in degrees, 9 the ground speed in m/s, 10 the true track in degrees, 13 the geometric altitude in metres, ...). The json wire addresses object members by name; a group item may be an object or a scalar (0.7), not an array addressed by index. Arrays are not residue, so a decoded response does not carry them. |

What the pack language would need: an item-relative locator that addresses an element of
an array item by its index (for example `[5]`), so that `states` is a group whose items
map to list keys; and, to give each state vector its own entity (the position of one
aircraft is `lat`/`lon` of that aircraft, not of the response), a rule that decodes each
item of a group as one entity. Both are candidate additions; until then the pack carries
`time` only and no conversion carries an aircraft position.

## Message convention

The member order of the encoded object is the line order (`time`), then residue scalars
in input order. A response whose `states` is `null` (no aircraft) reads as `time` alone.

## Vectors

`tools/gen/opensky-vectors.py` writes them from values chosen for them (none taken from the
API or the documentation): round trips with state vectors, with none and with `states`
`null`; `time` as text (`transform-decode`); and a GeoJSON Feature whose `time_ms` becomes
`time` in whole seconds (under `packs/geojson/vectors/`, the pack of its input).
