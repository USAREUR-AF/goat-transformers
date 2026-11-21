## Evidence for the shared keys

- `uid` (`@id`): the zone's identifier, a URI of the API.

## Not bound

The JSON-LD form gives the geometry as Well-Known Text in one string; no transform reads a position out of that text, so `lat` and `lon` are not bound (the GeoJSON form of the same resource binds them).
