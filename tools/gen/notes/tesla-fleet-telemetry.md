## What the message is

The pack's message is one `telemetry.vehicle_data.Payload` of Tesla Fleet Telemetry: what the
telemetry server publishes for each batch of vehicle data it receives. It holds the time the
batch was created (2, a `google.protobuf.Timestamp`), the vehicle identification number (3), a
resend flag (4), and the data (1), a list of `Datum`. Each datum is a field name (an enum `Field`,
carried as its number) and a value, one member of the `oneof` of `Value`.

The server's other record types (alerts, errors, connectivity, metrics: `vehicle_alert.proto`,
`vehicle_error.proto`, `vehicle_connectivity.proto`, `vehicle_metric.proto`) are separate messages
and have no pack here.

## Everything raw

No field is bound to a shared key, and the pack converts to no other format.

- `LocationValue.latitude` and `longitude` (double): the schema states neither unit nor datum, and
  a location is one datum among many in the list `data`; a key of an item is never a shared key
  (engine-spec 0.7).
- `vin` is the vehicle's identifier, but the pack has no position to report with it; it is left raw
  rather than bound to `uid` alone.
- Which datum holds which value follows from `Datum.key` only: an item is not decoded by a
  discriminator, so every member of `Value` is a raw key of the item.

## Hand-written vector

One round trip, written field by field by `tools/gen/protobuf-2-vectors.py` (standard library only; no engine, no generator).
