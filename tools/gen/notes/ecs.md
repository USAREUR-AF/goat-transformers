## The form, and why one pack

ECS is not a set of message classes: it is one document, an event, made of field sets
(`base`, `event`, `host`, `source`, `process` and some forty more) that any event may carry
together. So the pack is one document, `ecs-event`, holding every field of
`generated/ecs/ecs_flat.yml` at its dotted place as nested JSON objects (the form an ECS
document has in JSON). A pack per field set would split one event across packs that all
need `@timestamp`.

`tools/gen/ecs2pack.py` reads only the type, array and object-type keys of each field and
builds a JSON Schema of structure, which is the "Sources" file above. ECS does not say that
any field is required to be present in the JSON form beyond `@timestamp`, and Elasticsearch
accepts some fields in other forms; the pack reads the form `ecs_flat.yml` describes:

- a field whose `normalize` has `array` is an array of its type (`tags`, `related.ip`, ...);
  any other field is a single value. A producer that sends an array where ECS expects one
  value has that member dropped (arrays are not residue);
- `date` fields are strings. Elasticsearch also accepts a number of epoch milliseconds for
  a date; such a member fails the decode of a string line;
- `unsigned_long` fields are integers; a value above 2^63 - 1 fails the decode;
- `geo_point` is the object form `{"lat": ..., "lon": ...}` that ECS gives as its example.
  The other forms Elasticsearch accepts (a `"lat,lon"` string, a `[lon, lat]` array, a
  geohash, WKT) are not mapped: a string is residue, an array is dropped;
- `object` and `flattened` fields whose member names are data (`labels`, the
  `*.attributes` maps) are not mapped; `nested` fields are arrays of objects (groups).

## Evidence for the shared keys

- `time_ms` (`@timestamp`): `schemas/base.yml` gives it as the date and time the event
  originated (falling back, where the source has none, to when the pipeline first received
  it); it is the one field ECS requires. Its type is `date`, which ECS writes in its
  examples as ISO 8601 with `Z`. `iso8601_ms` reads it (an offset is converted to UTC) and
  writes milliseconds with `Z`; the raw key keeps the text as written. A fraction beyond
  milliseconds (ECS allows nanoseconds in `date_nanos`-mapped indices) is cut when the
  event is written from the shared key.
- `uid` (`event.id`): `schemas/event.yml` gives it as an identifier unique to the event.
- `lat`, `lon` (`host.geo.location.lat`, `.lon`): `schemas/geo.yml` makes `location` a
  geo_point of longitude and latitude in degrees, and `schemas/host.yml` makes `host` the
  computing instance the event happened on. Of the nine geo_points of the document
  (`client`, `destination`, `host`, `host.target`, `observer`, `server`, `source` and two
  under `threat`), only the host's is the event's own place; the others are raw keys.

Not bound: `event.created`, `event.ingested`, `event.start`, `event.end` (other times of
the event's handling or an interval), the `*.geo.location` of the other field sets, and
`*.id` of other field sets (each identifies its own thing).
