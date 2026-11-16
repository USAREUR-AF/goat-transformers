## Seven kinds, one per member of `Message`

`Message` is a union written as seven optional message fields (administrative 1, config 2, event 3, registration 4, request 5, response 6, status 7); the file is proto2 and has no `oneof`. Each member is a kind, selected by `when <number> present`. The `isa` pack reads the same schema with `Event` as the whole message; this pack reads a `Message`, so an `Event` here sits under field 3 and every `isa` path gains the prefix `3.`. `Envelope` (`Header header = 1`, `repeated Message body = 2`) is not the envelope here: a pack over it would hold every message as an item of one list, and an item is not decoded by kind (engine-spec 0.7 has no `when` inside a group).

## One module with the `isa` pack

This pack uses module `isa`, the module of the `isa` pack, extended. The 285 paths the `isa` pack maps outside groups keep their key names under the prefix `3.` (`--names-from names/isa.json=3`), and the key and list lines the `isa` run wrote are unchanged; this run adds the keys and lists of the other six kinds. Outside groups, kind `event` maps exactly those 285 paths: `Event` has no single value deeper than the `isa` pack already walks. Every list of the `isa` pack has the same name here, and the keys of an item are named by message type, so they are the same keys in both packs. Inside an item this pack maps paths up to three field numbers long (the run lowered the limit to keep pack.def within its line budget) and the `isa` pack maps as far as its depth 6 allows; an item converted between the two keeps the keys both map. So a bare `Event` (`isa`) converts into a `Message` holding it (`isa-message`, kind `event`) and back with every field outside groups and with its lists, not only the five shared keys; the vectors `gen-isa-to-isa-message` and `gen-isa-message-to-isa` pin both directions. Kind `event` requires `lat` and `lon`, so that an entity from a format without module `isa` can encode as it; the cost is that an `Event` with no `position_observable` does not convert from `isa` into this pack (`no-kind`).

## Depth

The walk goes to path depth 14, where no value is cut off for depth. Six kinds are complete by depth 6. `Request` alone is deeper: in IPL 3.7 it is itself a union of typed requests (`add_ip_address_request = 1`, `add_subscription_request = 2`, ...), each carrying its own header and parameters, and those parameters nest selectors and areas.

Counted outside groups:

| `--max-depth` | Keys in the module | `field` lines of `request` | Fields of `request` cut for depth |
|---|---|---|---|
| 6 | 1,700 | 1,354 | 341 |
| 7 | 2,115 | 1,769 | 340 |
| 8 | 2,393 | 2,047 | 215 |
| 10 | 4,671 | 4,325 | 1,911 |
| 12 | 8,497 | 8,151 | 924 |
| 13 | 8,905 | 8,559 | 60 |
| 14 | 9,025 | 8,679 | 0 |

The count of cut fields rises before it falls because each level opened exposes the message fields of the next. At depth 14, 8,679 of the pack's 9,165 `field` lines outside groups belong to `request`.

Kind `request` has no mandatory field of its own (every typed request is optional), so it requires the first key only it maps, `isa.add_ip_address_request_source`. Its round-trip vector sets every typed request at once: valid protobuf for this schema, not a message a component would send.

## Bindings to core keys

The bindings of the `isa` pack, under field 3: `lat`, `lon`, `hae` from `Event.position_observable` (`GeographicPosition.latitude`, `longitude`, `altitude`, paths 3.25.1 to 3.25.3); `course` from `Velocity.heading` (3.29.1.1, a `MeasuredDegrees.value`); `speed_ms` from `Velocity.speed` (3.29.3.1, a `MeasuredMpsec.value`). The file has no field comments: the field names and the `Measured<unit>` type names are the evidence for unit and meaning. The file does not say what `altitude` is measured from; binding it to `hae` is the `isa` pack's reading. No field of the other six kinds is bound to a shared key.

## Left raw on purpose

- `time` and `stale` of every kind (`UTC.value`, a double): the file does not state the unit or epoch, and no transform turns a double into `time_ms`.
- `identifier` and `event_id` (sint64): `uid` is a string and no transform turns an integer into one. `source` is a string but names the source, not the reported thing.
- Every other `GeographicPosition` and `Velocity` in the tree, and every key of an item of a repeated field.
