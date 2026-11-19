## What the message is

The pack's message is one message of the KUKSA.val gRPC API (Eclipse KUKSA databroker), of the type
named above, as it travels in a gRPC call: the request or the response of one method of
`kuksa.val.v1.VAL` or `kuksa.val.v2.VAL`. The gRPC framing (a compressed flag and a 4-byte length
before each message) is not part of the pack.

## Everything raw

A KUKSA message carries values of Vehicle Signal Specification signals: a signal is named by its
path text (`Vehicle.Speed`, v1) or its numeric id (v2), and its value is one member of a `oneof` of
typed values. Which signal a value belongs to is data, not a field of the schema, so no field is a
shared key: a position or speed reaches the model only as the value of a datapoint whose path a
consumer reads. Every field is a raw key of the pack's module, and the pack converts to no other
format.

- Timestamps are `google.protobuf.Timestamp`: two raw integer keys.
- `map` fields (v2 `SubscribeResponse.entries`, `PublishValuesRequest.data_points`, ...) have no
  line: no line addresses a map entry by its key.
