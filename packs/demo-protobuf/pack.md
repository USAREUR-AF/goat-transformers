# Pack: demo-protobuf

A synthetic protobuf message that exercises the `protobuf` wire: a string id
(field 1), two doubles for position (fields 2 and 3), a varint time (field 5),
and a nested submessage (field 4) holding a callsign (inner field 1). I/O is hex
text. The schema is invented; it stands in for real protobuf formats (SAPIENT,
ISA, CoT-protobuf) a pack would describe by field number.
