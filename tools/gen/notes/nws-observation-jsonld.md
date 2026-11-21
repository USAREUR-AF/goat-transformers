## Evidence for the shared keys

- `uid` (`@id`): the observation's identifier, a URI of the API: the same identifier the GeoJSON form (`nws-observation`) binds.
- `time_ms` (`timestamp`): the time of the observation, a date-time; `iso8601_ms` reads it. The GeoJSON form binds the same member.

## Not bound

The JSON-LD form gives the geometry as Well-Known Text in one string; no transform reads a position out of that text, so `lat` and `lon` are not bound (the GeoJSON form of the same resource binds them). Measurements are quantitative-value objects (`value`, `unitCode`, `qualityControl`), mapped member by member as raw keys.
