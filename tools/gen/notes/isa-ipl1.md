## Envelope and kinds

IPL 1.6 has the same three candidate top-level messages as IPL 3.7. `Envelope` is `Header header = 1` plus `repeated Message body = 2`: a pack over it would hold every message as an item of one list, and an item is not decoded by kind (engine-spec 0.7 has no `when` inside a group). `Message` is a union written as seven optional message fields (administrative 1, config 2, event 3, registration 4, request 5, response 6, status 7), so `Message` is the envelope and each member is a kind, selected by `when <number> present`. The file is proto2 and has no `oneof`.

## No shared key

IPL 1.6 carries the content of every message as name-value lists: `Event.observables = 9` and `Event.detector_properties = 10` are `repeated NameValuePair`, and a `NameValuePair` is `name = 1` plus a `Wildcard value = 2` whose `geographic_position = 19` and `velocity = 38` hold what IPL 3.7 gives fixed fields (`Event.position_observable = 25`, `velocity_observable = 29`). Each of those lists is a `group`: an item holds the pair's name (`isa1.name_value_pair_name`) and the fields of its `Wildcard` value as raw keys (`isa1.name_value_pair_value_geographic_position_latitude`, ...). Which pair holds the position of the event is said by the pair's name, and an item is not selected by a value (engine-spec 0.7 has no `when` inside a group), so no position, course or speed is bound to a shared key. Outside the lists a message has its header: `source`, `identifier`, `priority`, `time`, `stale` and the kind's own scalars.

No kind maps a shared key, there is no default kind, and an entity from a format that does not use module `isa1` does not encode into this pack: `gen-geojson-to-isa-ipl1` pins the error `no-kind`. In the other direction an `isa-ipl1` message converts to a format's empty shell: `gen-isa-ipl1-to-geojson` pins a GeoJSON Feature with `null` geometry and no properties.

## Module

Module `isa1`, separate from `isa`: IPL 1.6 and IPL 3.7 are different declaration files with different field numbers below the message headers.

## Left raw on purpose

- `time` and `stale` of every kind (`UTC.value`, a double): the file does not state the unit or epoch.
- `identifier`, `event_id`, `request_id` (sint64): `uid` is a string and no transform turns an integer into one.
