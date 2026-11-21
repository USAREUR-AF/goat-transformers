## About the ESPHome native API

The ESPHome native API is the protocol Home Assistant and other clients use to talk to an
ESPHome device over TCP. Each message is a protobuf message with a numeric message ID.
On the connection, every message is framed with a preamble, its length and its ID (or sent
inside a Noise-encrypted frame). A message of this pack is the protobuf message alone. The
frame, and choosing the pack by its ID, are left to the caller.

Packs are generated one per message. Entity messages are named for the entity type
first, so the packs of one type sort together. For example, a light has
`esphome-light-list-entities-response`, `esphome-light-state-response` and
`esphome-light-command-request`.

The entity `key` is not carried. Every entity message starts with it: a `fixed32` hash
that ties a state or command to the entity its list-entities response announced. No
protobuf transform reads a fixed-width integer, so the field is not mapped. The same holds
for the other `fixed32`, `fixed64` and `bytes` fields of the schema.

No ESPHome message states a geographic position, a time of report or a tracked identity,
so every field is a raw key of the pack's module and converts to no other format.
