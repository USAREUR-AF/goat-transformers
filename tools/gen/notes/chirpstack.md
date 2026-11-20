## About these ChirpStack messages

ChirpStack is an open-source LoRaWAN network server. Its gateway bridge sends a gateway's
frames and statistics to the server as `gw` messages (usually over MQTT), and the server
sends downlinks and configuration back. The integrations publish what happened to a device
as `integration` events: uplink, join, acknowledgement, transmit acknowledgement, log,
status and location. The `stream` messages are the records ChirpStack writes to its Redis
streams for frame and API logging. A message of this pack is one protobuf message. The
MQTT topic, or the stream key, that tells which message it is, is left to the caller.

Positions are not bound to `core` keys. `common.Location` (in `LocationEvent`, in a
gateway's `GetLocationResponse`, and in the receive metadata of an uplink) has latitude,
longitude and altitude as doubles. The schema names them, but it states no unit, no
datum and no height reference, and the repository states none elsewhere. They are raw
keys of the pack's module. A source that states degrees on WGS 84 would allow the binding
to `lat` and `lon`.

`bytes` fields (the PHY payload, EUIs and keys sent as bytes) are not carried, and neither
are the fixed-width integers; no protobuf transform reads them. `google.protobuf.Struct`
objects (the decoded application payload `object`) are maps, which no line addresses by
key.
