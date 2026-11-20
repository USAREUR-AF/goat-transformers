## What the message is

The body of one OTLP/HTTP request in its JSON encoding (`Content-Type: application/json`): an
export request for traces, metrics or logs. The OTLP specification's JSON encoding is the proto3
JSON mapping with its own rules, which the pack follows: trace and span identifiers are hex text
(not base64; the specification lets them be upper or lower case, and the pack keeps the text as
it is), enum values are numbers, and member names are the lowerCamelCase JSON names (the
specification does not allow the names as written in the .proto files). It also says a decoder
accepts a 64-bit integer as a number or as decimal text; this pack reads the text only, so a
64-bit integer sent as a number is `transform-decode`. Members a receiver does not know are
ignored by OTLP; here they are residue outside arrays and dropped inside them.

## Times stay raw

Every OTLP time (`timeUnixNano`, `startTimeUnixNano`, `observedTimeUnixNano`, ...) is a fixed64
count of nanoseconds since the Unix epoch, which the JSON mapping writes as decimal text. Core
`time_ms` is not bound: the `json` transforms that turn a number into an integer with a scale
(`iscale`) need a JSON number, not text, and the times sit inside arrays of spans, points and
records, where an item key is not the entity's time. The text is kept as a raw key.

## Everything raw

As in the protobuf `otlp-*` packs, no field is a shared key; the packs convert to no other format.
