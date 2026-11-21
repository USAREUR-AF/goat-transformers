## What is not carried

No shared key is bound: a system event (a change of configuration, a calibration, ...) is a
record about a system, not a report of its position or state. The SensorML and SWE Common
structures inside an event are mapped to the third level only (`--max-depth 3`); members of
several JSON types are not mapped (see the table).
