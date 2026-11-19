## What the message is

The pack's message is one Meshtastic application payload of the type named above: the bytes that
stand in `Data.payload` of a mesh packet (pack `meshtastic`, path 1.4.2) when `Data.portnum`
names this type. The port numbers are those of `portnums.proto`: `Position` 3, `User` 4,
`Routing` 5, `Waypoint` 8, `Paxcount` 34, `StoreAndForward` 65, `Telemetry` 67,
`RouteDiscovery` 70, `NeighborInfo` 71, `TAKPacket` 72, `MapReport` 73. The pack language cannot
decode a `bytes` field as a message chosen by another field, so a caller takes the payload out of
the packet and hands it to this pack.

The schema files were read for names, field numbers and types only (`--no-comments`): no comment
of the files is in the pack, the module or this page.

## Not mapped, and why

- Every `fixed32`, `sfixed32` and `bytes` field: the protobuf wire has transforms for varints,
  zig-zag varints, `double`, `float` and strings only. That includes `latitude_i` and
  `longitude_i` of `Position`, `Waypoint` and `MapReport` (`sfixed32` in units of 1e-7 degree;
  there is also no scale for an integer on this wire), the times in seconds (`fixed32`), node
  numbers and public keys. So no latitude or longitude of a Meshtastic payload reaches `lat` and
  `lon`.
- `Position.altitude_hae` is a whole number of metres (`sint32`): `hae` is a float, and a
  transform that yields an integer cannot fill it.
- A `oneof` whose members are not all messages (`Routing`, `StoreAndForward`, `TAKPacket`) is one
  layout (`--one-layout`): every member's fields are lines of the one kind, and which member is
  set follows from the keys present.
