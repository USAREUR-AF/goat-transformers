## About OpAMP

OpAMP (Open Agent Management Protocol) is the OpenTelemetry protocol by which a server
manages a fleet of telemetry agents. Two messages travel on the wire: AgentToServer, from
an agent, and ServerToAgent, from the server. Each message is one protobuf message. Over
WebSocket each is preceded by a header byte, and over plain HTTP it is the request or
response body. A message of this pack is the protobuf message alone; the header byte and
the HTTP exchange are left to the caller.

The `instance_uid` of an agent is a 16-byte `bytes` field. No transform reads `bytes`, so
it is not carried, and neither is any other `bytes` field (hashes, file bodies).
Attributes are `AnyValue` values, which can contain themselves through arrays and
key-value lists. The walk stops where a type would stand inside itself. Below that depth,
nested values are not carried.

No OpAMP message states a position or a time of report; every field is a raw key.
