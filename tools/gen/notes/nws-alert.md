## Evidence for the shared keys

- The GeoJSON form of this response is read on the json wire: its geometry is a Polygon (or absent), which the geojson wire does not address, and the members under `properties` include objects and arrays that the json wire maps member by member.
- `uid` (`id`): the feature's identifier, a URI of the API that names this feature.
- `time_ms` (`properties.sent`): "The time of the origination of the alert message."
- `stale_ms` (`properties.expires`): "The expiry time of the information of the alert message."


`effective`, `onset` and `ends` are kept as raw keys. `properties.parameters` and the
geocode lists are objects whose member names are data (additionalProperties): not mapped.
The CAP form of an alert is the pack `cap`.
