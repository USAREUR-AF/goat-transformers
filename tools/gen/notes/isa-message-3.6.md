## Seven kinds, one per member of `Message`

`Message` in IPL 3.6 is, as in 3.7, a union written as seven optional message fields (administrative 1, config 2, event 3, registration 4, request 5, response 6, status 7); the file is proto2 and has no `oneof`. Each member is a kind, selected by `when <number> present`. This pack has its own module, `isa36`: the IPL 3.6 file is a different schema from the 3.7 one that module `isa` follows, so their keys are not shared.

## Depth

The walk goes to path depth 14, as for `isa-message`. `Request` is a union of typed requests (`add_ip_address_request = 1`, `add_subscription_request = 2`, ...), each with its own header and parameters, and holds nearly every field of the pack; the generator's report counts the paths below depth 14 that are not read.

## Shared keys, with evidence

- `lat`, `lon` from `Event.position_observable` (`GeographicPosition.latitude`, `longitude`, both `double`, paths 3.25.1 and 3.25.2), the same field numbers as IPL 3.7.
- `course` from `Velocity.heading` (3.29.1.1, a `MeasuredDegrees.value`); `speed_ms` from `Velocity.speed` (3.29.3.1, a `MeasuredMpsec.value`).

The file has no field comments: the field names and the `Measured<unit>` type names are the evidence for unit and meaning.

## Left raw on purpose

- `GeographicPosition.altitude` (3.25.3): the file does not say what it is measured from, so it is not bound to `hae` (which is height above the WGS 84 ellipsoid); it stays the raw key. The `isa` and `isa-message` packs (IPL 3.7) bind it to `hae`, an exception listed in tools/model-checks-allow.txt; this pack does not repeat it.
- `time` and `stale` of every kind (`UTC.value`, a double): the file does not state the unit or epoch, and no transform turns a double into `time_ms`.
- `identifier` and `event_id` (sint64): `uid` is a string and no transform turns an integer into one. `source` is a string but names the source, not the reported thing.
- Every other `GeographicPosition` and `Velocity` in the tree, and every key of an item of a repeated field.
