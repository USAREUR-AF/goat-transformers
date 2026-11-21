## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): ERDDAP writes the row's longitude and latitude as
  a GeoJSON Point; GeoJSON (IETF RFC 7946, section 4) makes them WGS 84 decimal degrees.
  ERDDAP's own variables name no datum: the binding rests on the GeoJSON form.
- `time_ms` (`properties.time`): the row's time, written as an ISO 8601 date-time in UTC (the
  collection's `propertyUnits` give `UTC`); `iso8601_ms` reads it.

## What is not carried

The other properties of a row are the dataset's own variables; they are residue, carried
back as they were. The collection's `propertyNames`, `propertyUnits` and `bbox` belong to the
collection, not to one Feature. ERDDAP has no altitude in the geometry: `altitude` or `depth`,
when the dataset has them, are properties.
