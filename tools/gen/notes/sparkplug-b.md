## What the message is

The pack's message is one Sparkplug B `Payload`: the bytes of an MQTT PUBLISH payload under a
`spBv1.0/...` topic. The topic, which names the group, the message type (birth, death, data,
command) and the node or device, is not part of the payload and not part of the pack; a caller
keeps it beside the message.

## Everything raw

Sparkplug B carries industrial telemetry as named metrics. No field carries a position, an
identifier of a tracked thing or a velocity, so no field is bound to a shared key and the pack
converts to no other format. It decodes and re-encodes a payload: `timestamp` and `seq` as raw
keys, the metrics as items of the list `sparkplug.payload_metrics`.

- `Payload.timestamp` (1) and `Metric.timestamp` (2.3) are left raw. The schema says only that
  the first is the time of sending and the second the time of acquisition; it does not state the
  unit. The Sparkplug specification, a separate document, gives the unit; this pack does not bind
  a key from a statement outside the schema it is generated from.
- `Metric.value` is a `oneof` of typed values. Each member is a raw key of the item; which member
  is set follows from the keys present, and `Metric.datatype` keeps the declared type as its
  number. `bytes_value` (2.16) has no transform and is dropped.
- `Payload.uuid` (4) is a string and is carried; `Payload.body` (5) is bytes and is not.
- `Template` holds `repeated Metric`: a metric whose value is a template holds metrics of its own.
  The walk stops where a message type would stand inside itself, so the metrics of a template are
  not mapped.
- Extension ranges (`extensions ... to max`) have no line.

## Hand-written vector

`01-data-roundtrip-body-dropped`: a payload with two metrics (a float with a name, a boolean by
alias), a sequence number and a `body`; the `body` is not written back. Written field by field by
`tools/gen/protobuf-public-vectors.py` (standard library only; no engine, no generator).
