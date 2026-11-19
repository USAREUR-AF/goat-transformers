## Evidence for the shared keys

- The GeoJSON form of this response is read on the json wire: its geometry is a Polygon (or absent), which the geojson wire does not address, and the members under `properties` include objects and arrays that the json wire maps member by member.
- `time_ms` (`properties.updated`): "The time this zone forecast product was published."

