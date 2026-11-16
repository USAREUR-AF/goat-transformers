## Why one kind

The schema file is proto2, has no `oneof` and no comments beyond its header. It has three candidate top-level messages. `Envelope` is `Header header = 1` plus `repeated Message body = 2`: a pack over it would hold every message as an item of one list, and an item is not decoded by kind (engine-spec 0.7 has no `when` inside a group). `Message` is a union written as seven optional fields (administrative 1, config 2, event 3, registration 4, request 5, response 6, status 7). `Event` is one of those seven. The hand-written pack this one replaces, and its two vectors, take the bytes to be a bare `Event` (position at path 25, velocity at 29), so the envelope here is `Event` and the pack has the single kind `event`, with no `when`. The generator can also write the seven-kind pack for `Message` (`--envelope Message --kinds-from-fields`); under that envelope every path gains a leading field number and the existing vectors no longer apply, so it is a different format and is not written here.

## Bindings to core keys

Kept exactly from the replaced pack: `lat`, `lon`, `hae` from `Event.position_observable` (`GeographicPosition.latitude`, `longitude`, `altitude`, paths 25.1 to 25.3); `course` from `Velocity.heading` (29.1.1, a `MeasuredDegrees.value`); `speed_ms` from `Velocity.speed` (29.3.1, a `MeasuredMpsec.value`). The file has no field comments: the field names and the `Measured<unit>` type names are the evidence for unit and meaning. The file does not say what `altitude` is measured from; binding it to `hae` (height above the WGS84 ellipsoid) is the replaced pack's reading. It does not say what `heading` is measured from either; `course` is degrees true.

## Left raw on purpose

- `Event.time` and `Event.stale` (`UTC.value`, a double): the file does not state the unit or epoch, and no transform turns a double into `time_ms`.
- `Event.event_id` and `Event.identifier` (sint64): `uid` is a string and no transform turns an integer into one. `Event.source` is a string but names the source, not the reported thing.
- Every other `GeographicPosition` and `Velocity` in the tree (`position_property`, `ground_intercept_property`, `velocity_property`, the area shapes).
- Every key of an item of a repeated field: no item key is bound to a shared key.
