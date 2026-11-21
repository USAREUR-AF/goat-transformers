## About these The Things Stack messages

The Things Stack (v3) is an open-source LoRaWAN network server. Its Application Server
hands every event of an end device to the application as one `ApplicationUp`: an uplink
(decoded, or normalized), a join accept, the fate of a queued downlink (acknowledged,
not acknowledged, sent, failed, queued, queue invalidated), a solved location, or data
from an application package. Each of those is one kind of `tts-application-up`. The
application sends downlinks back as one `ApplicationDownlink` (`tts-application-downlink`)
or a list of them (`tts-application-downlinks`), to push to or replace the queue.

A message of these packs is one protobuf message. The MQTT, webhook and Pub/Sub
integrations usually carry the same message as JSON in the protobuf JSON mapping; that
form is not a pack. The topic or path that names the event is left to the caller.

## Evidence for the shared keys

`lat` and `lon` are bound in the kind `location_solved` only, at field-number paths
11.2.1 and 11.2.2 (`ApplicationLocation.location`, a `Location`). In `metadata.proto`
the field comment of `Location.latitude` gives it in degrees from -90 to +90, zero at the
equator and positive to the north; the one of `Location.longitude` gives degrees from
-180 to +180, zero at the Greenwich meridian and positive to the east. The files name no
datum; the packs take these degrees as the WGS 84 latitude and longitude of `core`, as
the GNSS receivers and LoRa geolocation solvers that fill the field report them. A person
reviewing the pack may decide otherwise.

Not bound, and why:

- `Location.altitude` is an integer in metres above mean sea level, not above the
  ellipsoid: a raw key, not `hae`.
- The `location` of each gateway in the receive metadata (`rx_metadata`) and the
  `locations` map of an uplink are the gateways' or other sources' positions, not the
  device's, and stand in a list or a map: raw keys or not carried.
- `received_at` is when the server received the event, not when the device measured
  anything: a raw key.

`bytes` fields (the frame payload, keys and session key identifiers) are not carried,
and neither are the fixed-width integers; no protobuf transform reads them.
`google.protobuf.Struct` objects (the decoded payload) and other maps are not addressed
by key. Option imports (`validate`, `thethings/flags`, `thethings/json`,
`protoc-gen-openapiv2`) are given to the generator so that the schema resolves; they hold
field options only, and nothing of them reaches a pack.
