## Evidence for the shared keys

- The GeoJSON form of this response is read on the json wire: its geometry is a Polygon (or absent), which the geojson wire does not address, and the members under `properties` include objects and arrays that the json wire maps member by member.
- `uid` (`id`): the feature's identifier, a URI of the API that names this feature.
- `issueTime`, `start` and `end` have no description in the schema, so they are raw keys and `time_ms` and `stale_ms` are not bound.

