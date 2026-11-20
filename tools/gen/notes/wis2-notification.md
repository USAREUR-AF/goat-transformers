## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the standard requires the message to be a
  GeoJSON Feature (IETF RFC 7946), and its geometry requirement places the geometry in
  WGS 84 with longitude and latitude in decimal degrees. A third coordinate has no stated
  meaning, so `hae` is not bound.
- `uid` (`id`): a UUID that identifies the notification message.
- `time_ms` (`properties.datetime`): the date and time of the data the notification
  announces, RFC 3339; `iso8601_ms` reads it to epoch milliseconds UTC.

Not bound: `properties.pubtime` is when the notification was published, not the time of
the data; `start_datetime` and `end_datetime` bound a period, not one time.

## What the geojson wire leaves out

`links` (an array of link objects) and a Polygon geometry are residue of the geojson wire,
carried back as they were.
