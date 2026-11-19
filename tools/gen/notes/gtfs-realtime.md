## What the message is

The pack's message is one `FeedMessage` of GTFS Realtime, as a producer publishes it: a
`FeedHeader` (field 1) and a list of `FeedEntity` (field 2). Over HTTP a feed is usually served as
the bare serialized message; the pack takes those bytes as they are, with no framing.

## Everything raw

Every field of the feed is a raw key of module `gtfsrt`; no field is bound to a shared key. The
entities of a feed are items of the list `gtfsrt.feed_message_entity`, and the shared model has no
list of positions: a key of an item never carries `lat`, `lon` or another shared key
(engine-spec 0.7). The pack therefore converts to no other format. It decodes and re-encodes a
whole feed, header and entities, and keeps the module of `gtfs-realtime-entity`, which this run
extends (`--module-base`); the keys of an item are named by message type and differ from the
entity pack's keys, so a feed's entity does not convert to `gtfs-realtime-entity` through the
model. To work with vehicles as shared-model entities, split the feed into its entities and use
`gtfs-realtime-entity`.

## Left raw on purpose

- `FeedHeader.timestamp` (1.3): seconds since 1970-01-01 UTC; no protobuf transform scales an
  integer to `time_ms`.
- `FeedHeader.gtfs_realtime_version` (1.1) is `required`; the pack writes it only when the
  entity has the key.

## Extensions

The schema reserves extension ranges (1000 to 1999 and 9000 to 9999) in most messages. A field in
those ranges has no line and is dropped on decode: the protobuf wire keeps no residue, and encode
writes mapped fields only (engine-spec 0.3).

## Hand-written vector

`01-feed-two-vehicles-roundtrip`: a header and two vehicle entities, written field by field by
`tools/gen/protobuf-public-vectors.py` (standard library only; no engine, no generator).
