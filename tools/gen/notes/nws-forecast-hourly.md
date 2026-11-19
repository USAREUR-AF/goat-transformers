## Evidence for the shared keys

- The GeoJSON form of this response is read on the json wire: its geometry is a Polygon (or absent), which the geojson wire does not address, and the members under `properties` include objects and arrays that the json wire maps member by member.
- `time_ms` (`properties.generatedAt`): "The time this forecast data was generated."
- The forecast periods are the group of `properties.periods`.

