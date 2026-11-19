## What the message is

The pack's message is one gNMI message of the type named above: the request or the response of
the `Capabilities`, `Get`, `Set` or `Subscribe` method of the gNMI service, as it travels in a gRPC
call. The gRPC framing is not part of the pack.

## Everything raw

gNMI carries the configuration and state of network devices as paths and typed values. No field
is a shared key, and the packs convert to no other format.

- `map` fields (the keys of a path element) have no line: no line addresses a map entry by its
  key. `bytes` values (JSON and protobuf encoded values, `Any`'s value) are not carried.
- `TypedValue` holds a `ScalarArray` of `TypedValue`: the walk stops where a message type would
  stand inside itself.
- `SubscribeRequest` and `SubscribeResponse` are one layout (`--one-layout`): their `oneof` has a
  member that is a scalar or an empty message, which cannot be a kind of its own. Every member's
  fields are lines of the one kind; a `poll` request (an empty message) has no line.
- The `gnmi_ext` extensions of a message are carried as raw keys where the walk reaches them.
