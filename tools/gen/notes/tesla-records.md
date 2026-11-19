## What the message is

The pack's message is one record of Tesla Fleet Telemetry of the type named above, as the
telemetry server publishes it beside the vehicle data (`tesla-fleet-telemetry`): alerts, errors,
connectivity events or metrics of one vehicle.

## Everything raw

No field carries a position; every field is a raw key of the pack's module, and the pack converts
to no other format. Times are `google.protobuf.Timestamp` (two raw integer keys). `map` fields (the
tags of an error or a metric) have no line.
