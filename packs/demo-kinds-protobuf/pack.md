# Pack: demo-kinds-protobuf

A synthetic protobuf envelope that exercises message kinds on the `protobuf`
wire (`spec/engine-spec.md`, Version 0.5). The schema is invented. Field 1 (id)
and field 2 (time) are common to every message.

| Kind | Chosen when | Holds |
|---|---|---|
| `position` | submessage 10 is present | latitude, longitude, height (doubles 10.1 to 10.3) |
| `motion` | submessage 11 is present | course (double 11.1), speed (float 11.2) |
| `status` | varint field 3 equals 1 | callsign (string, field 4) |

Fields 10 and 11 stand for the arms of a oneof. A message with neither arm and
without field 3 equal to 1 is `no-kind`. On encode `status` writes field 3 as 1.
I/O is hex text.
