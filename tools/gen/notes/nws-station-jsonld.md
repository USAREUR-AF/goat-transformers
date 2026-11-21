## Evidence for the shared keys

- `uid` (`@id`): the station's identifier, a URI of the API.
- `callsign` (`name`): the station's name, as the GeoJSON form (`nws-station`) binds it.

## Not bound

The JSON-LD form gives the geometry as Well-Known Text in one string; no transform reads a position out of that text, so `lat` and `lon` are not bound (the GeoJSON form of the same resource binds them). The elevation is above mean sea level in the API's practice and is not `hae`.
