## Evidence for the shared keys

- `time_ms` (`last_updated`), in GBFS 3.0 and 3.1-RC3 only: the schema states it is the last
  time the data in the feed was updated, as an RFC 3339 `date-time`. The `iso8601_ms`
  transform reads it (an offset is converted to UTC) and writes it with milliseconds and
  `Z`; the raw key keeps the text as written.
- `time_ms` (`last_updated`), before 3.0: the schema states it is the last time the data in
  the feed was updated, in POSIX time, an integer: seconds since 1970-01-01 UTC. The
  `iscale:1000` transform (engine-spec 0.15) reads it as milliseconds and writes
  milliseconds divided by 1000 exactly, so a whole second comes back as written; the raw
  key keeps the integer as written.

## What is not bound

- **Positions in lists.** Every GBFS file is one object whose `data` holds arrays: the
  stations of `station_information`, the bikes of `free_bike_status`, the vehicles of
  `vehicle_status`. Their `lat` and `lon` are WGS 84 degrees, but they are members of list
  items, and a list item's keys never become the entity's `lat` and `lon`; so they are raw
  keys of the item. The same gap stands for any message that carries many positions in one
  object (NeTEx too): a conversion to a one-position format would need a message-per-item
  step that the pack language does not have.
- **Geometries.** `geofencing_zones` and `system_regions` carry GeoJSON geometries
  (coordinate arrays of arrays); the json wire addresses no array element, so they are not
  mapped.
- **Seconds and durations.** `ttl` and the other second counts stay raw keys.

The files have no member that names the file's own type, so each pack has one message and
no `kind` lines; the caller chooses the pack by the feed file it reads.
