## What the message is

The pack's message is one Eclipse uProtocol message of the type named above, in its protobuf
encoding: a `UMessage` with its `UAttributes` and payload as a uProtocol transport carries it, one
of the types it addresses and reports with (`UUri`, `UStatus`, `File`), or the request or response
of a uProtocol core service (uDiscovery, uSubscription, uTwin) as it travels in the payload of a
`UMessage`. The transport binding (MQTT, SOME/IP, Zenoh and others) and its framing are not part
of the pack. Each message type is a pack of its own.

The schema files were read for names, field numbers and types only (`--no-comments`); the notes
here are this repository's own words.

## Everything raw

uProtocol carries the addressing, identity and delivery state of messages between software
entities in a vehicle and the cloud: URIs of entities and resources, message ids, priorities,
time-to-live values, subscription states. None is a position, a track identity or a time in the
shared model's sense, so no field is bound to a shared key and the packs convert to no other
format. Every field the protobuf wire can state is a raw key of the pack's own module.

- `UUID` is two `fixed64` halves (`msb`, `lsb`): no transform on this wire reads a fixed-width
  integer, so a message id is not carried (every `UUID` field of every pack) and `UUID` has no pack.
- The payload of a `UMessage` is `bytes`: not carried. Its format follows from `UAttributes`.
- `google.protobuf.Timestamp` fields are two raw integer keys.
- `UServiceTopic` describes a topic as a protobuf option of a service declaration, not a
  message on the wire; and `SetServiceTopicsResponse`, `UnsubscribeResponse`,
  `NotificationsResponse` and `ResetResponse` have no field: none of them has a pack.
