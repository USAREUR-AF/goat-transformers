## Evidence for the shared keys

- `time_ms` (`validTime`): GeoPose 1.0 states time as UNIX time with the intended precision of
  one millisecond, encoded as an integer number of milliseconds (annex on time); the valid
  time is the instant at which the pose holds. That is `time_ms`, read with `int`.

## What is not carried

The position of an Advanced GeoPose is given by its frame specification (an authority, an
identifier and parameters as text, for example a PROJ string): no position key is bound, as
the pack cannot read a CRS from text. The quaternion is a raw key.
