## The form

One message is one MISP event in the MISP core format: a JSON object whose `Event` member
holds the event, its `Org` and `Orgc`, its attributes (`Attribute`), objects (`Object`, each
with its own attributes and object references) and tags (`Tag`). The pack is generated from
`tools/gen/misp-core-schema.json`, this repository's restatement of the members the format
document names, since the document is prose with samples and has no machine-readable schema.
Most values are JSON strings, numbers included, as the document states.

## Shared keys

- `uid` (`Event.uuid`): the event's UUID, which the document says must be preserved for
  every update or transfer of the same event.

Not bound: `time_ms`. `Event.timestamp` is the time the event or one of its attributes was
created or last changed, written as epoch seconds in a JSON string; the `json` wire's `int`
transform reads JSON numbers only. `date` is a date without a time.

Not mapped: `ShadowAttribute`, `RelatedEvent`, `Sighting`, `Galaxy`, `EventReport` and the
analyst data; their scalars are residue and their arrays are not carried.
