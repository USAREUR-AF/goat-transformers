## What the message is

The pack's message is one `ServiceEnvelope`: what a Meshtastic gateway publishes to an MQTT
broker for each packet it relays. It holds the mesh packet (field 1), the channel name (2) and
the gateway's node identifier as text (3). The schema files were read for names, field numbers and
types only (`--no-comments`): no comment of the files is in the pack, the module or this page.

## What the pack carries

Raw keys of module `meshtastic` for the fields whose types the protobuf wire can state: the
packet's channel index, hop counts, signal values, flags and, when the packet is not encrypted, the
`portnum` of its `Data` and its flags. No field is bound to a shared key, and the pack converts to
no other format.

## Not mapped, and why

- `MeshPacket.from`, `to`, `id`, `rx_time` and `Data.dest`, `source`, `request_id`, `reply_id`,
  `emoji`: `fixed32`. The protobuf wire has transforms for varints, zig-zag varints, `double`,
  `float` and strings only; a fixed-width integer has none, so these fields are not read. They
  include the sender and receiver node numbers and the packet identifier.
- `MeshPacket.encrypted` (1.5), `public_key` (1.16), `Data.payload` (1.4.2),
  `Data.xeddsa_signature`: `bytes`, no transform.
- The application message itself. A position, a node's user record, a text or telemetry is
  carried serialized inside `Data.payload`, and which message it is follows from `Data.portnum`
  (`POSITION_APP` holds a `Position`). The pack language cannot decode a `bytes` field as a nested
  message chosen by another field's value, so no position reaches the model.
- `Position.latitude_i` and `longitude_i` are `sfixed32` in units of 1e-7 degree. Even with the
  payload decoded, binding them to `lat` and `lon` would need a fixed-width transform and a scale
  on an integer, neither of which the protobuf wire has.

## Hand-written vector

`01-envelope-negative-rssi-fixed32-dropped`: an envelope whose packet has a `from` (fixed32), a
`Data` with `portnum` 1 and a payload, and `rx_rssi` -90, which an `int32` puts on the wire as a
ten-byte varint. `from` and the payload are not written back; -90 is. Written field by field by
`tools/gen/protobuf-public-vectors.py` (standard library only; no engine, no generator).
