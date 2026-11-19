## The form

One message is one CloudEvent in the JSON event format (`cloudevents/formats/json-format.md`
of the specification): one JSON object with the context attributes as members and the
payload in `data` or `data_base64`. A batch (a JSON array of events) is not a message of
this pack. Extension attributes are members the schema does not name; scalar ones are
residue and come back on a round trip.

## Evidence for the shared keys

- `time_ms` (`time`): in `cloudevents/spec.md` the `time` attribute is the time the
  occurrence happened; where a producer cannot know it, the producer may put another time
  there, chosen the same way for every event of one `source`. Its form is RFC 3339, and the
  schema states `format: date-time`. `iso8601_ms` reads it, converting an offset to UTC,
  and writes milliseconds with `Z`; the raw key keeps the text as written. RFC 3339 allows
  any number of fraction digits; digits beyond milliseconds are cut when the event is
  written from the shared key, so a same-format round trip of such a `time` is not exact.

Not bound:

- `id` identifies an event only together with `source` (the specification makes the pair
  unique); alone it is not a stable identifier of an entity, so it is a raw key, as are
  `source`, `type` and `subject`.
- `data` may be any JSON type (several JSON types), so no line maps it; an object or a
  string payload is residue only where it is a scalar.
