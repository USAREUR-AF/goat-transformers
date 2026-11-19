## What the message is

The pack's message is one `openxc.VehicleMessage`, the protobuf form of an OpenXC vehicle interface
message (the binary output format; the interface also writes JSON). A stream from the interface
puts a varint length before each message; that framing is not part of the pack.

## Everything raw

A simple message carries a signal by name (`vehicle_speed`, `latitude`, ...) and its value as a
dynamic field of type string, number or boolean. Which signal a value is follows from the name,
which is data, not a field of the schema, so no field is a shared key and the pack converts to no
other format. CAN messages carry their data as `bytes`, which no transform reads.
