## What the message is

The pack's message is one bare `TakMessage`, the payload of TAK protocol version 1. The protocol
puts a header in front of that payload: on a mesh datagram the byte 0xbf, the protocol version as a
varint and 0xbf again; on a streaming connection 0xbf and the payload length as a varint. Neither
header is part of this pack, because the engine has no framing yet: a caller removes the header
before `decode` and adds it after `encode`. The negotiation that switches a streaming connection
from XML to this encoding is also outside the pack.

## Envelope and kinds

`TakMessage` holds two optional members, `takControl = 1` and `cotEvent = 2`, and a message may
hold either or both. The pack has two kinds:

- `cot_event`, `when 2 present`, first in the pack: every message that holds an event. It is the
  kind an entity from another format encodes as, and it requires `lat` and `lon`.
- `tak_control`, `when 1 present`: a message that holds a control member and no event. It has no
  line of its own and requires `takproto.tak_control_min_proto_version`.

The three fields of `TakControl` are common lines, so they are read and written in both kinds: a
message with both members decodes as `cot_event` with the control keys filled, and comes back with
both members (`03-full-message-roundtrip`). A control member with no field inside is kept as an
empty member (`08-control-empty-member`). A `TakMessage` with neither member is `no-kind`.

## Shared keys: the evidence

`CotEvent` is the XML `<event>` with its `<point>`, field for field, and each strongly typed
message under `Detail` is one child element of `<detail>`; the schema files tie each field to its
attribute by name. The bindings below follow that correspondence and match `packs/cot-xml`, so a
key leaves one pack and enters the other at the same place in the event.

| Key | Field | cot-xml locator | Unit |
|---|---|---|---|
| `type`, `uid`, `how` | `CotEvent.type`, `uid`, `how` | `@type`, `@uid`, `@how` | text |
| `track.scoped_id` | `CotEvent.uid`, a line before `uid` | `@uid`, a line before `uid` | text |
| `time_ms` | `CotEvent.sendTime`, then `startTime` | `@time`, then `@start` | uint64, milliseconds since 1970-01-01 00:00:00 UTC |
| `stale_ms` | `CotEvent.staleTime` | `@stale` | the same |
| `lat`, `lon`, `hae`, `ce`, `le` | `CotEvent.lat`, `lon`, `hae`, `ce`, `le` | `point/@lat` … `point/@le` | double; degrees and metres as in the XML |
| `callsign` | `Detail.contact.callsign` | `detail/contact/@callsign` | text |
| `speed_ms`, `course` | `Detail.track.speed`, `course` | `detail/track/@speed`, `@course` | double; metres per second, degrees true as in the XML |

The three times are integers of milliseconds since the Unix epoch in the schema, which is the unit
of `time_ms` and `stale_ms`: the transform is `pvarint` with no scaling.

## `track.scoped_id` and `uid`

`CotEvent.uid` has two shared lines, `track.scoped_id` first and `uid` second, as `@uid` has in
`cot-xml`. Decode fills both with the event's uid. Encode writes `track.scoped_id` when the entity
has it, else `uid`: a host that supplies its own scoped identity of a track (by context, or from a
format that maps it) sees that identity in the event, in this pack as in `cot-xml`.

## `sendTime` and `startTime`

`time_ms` has two lines, `sendTime` (2.6) first and `startTime` (2.7) second, as `cot-xml` has
`@time` first and `@start` second. Decode takes `sendTime`, and `startTime` only when `sendTime`
is not on the wire (`06-start-alone-fills-time`). Encode writes `time_ms` at both. Each path also
has its raw key, second on the path, so decode keeps both values as
`takproto.cot_event_send_time` and `takproto.cot_event_start_time`; on encode the shared line is
first on each path, so a `startTime` that differs from `sendTime` leaves with the value of
`sendTime` (`05-start-differs-time-is-written-at-both`).

## Numbers that are not written

The pack has no `default` line. A key the entity lacks is not written, and a proto3 reader takes a
number that is not on the wire as 0: an entity with no `hae`, `ce`, `le` or `stale_ms` becomes an
event whose reader sees 0 there. The other way, a proto3 writer leaves out a number equal to 0 and
an empty string, and decode reports a field that is not on the wire as an absent key, not as 0.
Encode writes every key the entity has, a 0 included.

## Left raw

- `CotEvent.access`, `qos`, `opex` (2.2 to 2.4): the shared model has no key for them.
- `Detail.xmlDetail` (2.15.1): the rest of `<detail>` as XML text, one string. It is carried as
  `takproto.detail_xml_detail` and not parsed.
- `Contact.endpoint`, `Group` (`<__group>`), `PrecisionLocation`, `Status`, `Takv`: raw keys of
  module `takproto`.
- `TakControl`: raw keys; `contactUid` is not `uid` (it names the sender, not the reported thing).

## To and from `cot-xml`

`cot-xml` maps 14 keys and this pack maps the same 14, so every shared key of an event crosses in
both directions.

| Direction | Carried | Not carried |
|---|---|---|
| `cot-protobuf` to `cot-xml` | `track.scoped_id`, `uid`, `type`, `time_ms` (to `@time` and `@start`), `stale_ms`, `how`, `lat`, `lon`, `hae`, `ce`, `le`, `callsign`, `course`, `speed_ms` | every raw key: `takControl`, `access`, `qos`, `opex`, a `startTime` that differs from `sendTime`, `xmlDetail`, `Contact.endpoint`, `Group`, `PrecisionLocation`, `Status`, `Takv` |
| `cot-xml` to `cot-protobuf` | the same 14 keys; `time_ms` to `sendTime` and `startTime` | attributes of `<event>` that `cot-xml` does not map (`access`, `qos`, `opex`: residue of that format), and every child of `<detail>` other than `contact/@callsign` and `track`, which `cot-xml` does not read; `xmlDetail` is not written |

`cot-xml` writes `version="2.0"` on every event, and `type="a-u-X"` and `hae`, `ce`, `le`
`9999999` when the entity has no value: an event that left a proto3 writer with `hae` 0 (not on
the wire) arrives in XML with `hae="9999999"`.

The value for an unknown `hae`, `ce` and `le` is 9999999.0 (seven nines), the value CoT XML uses.
The comment in `cotevent.proto` says 999999 (six nines), but the TAK library in the same repository
at the same commit uses seven: `commoncommo/core/include/cotmessageio.h` defines its no-value point
constant as 9999999.0, `commoncommo/core/impl/cotmessage.cpp` copies `hae`, `ce` and `le` from the
XML event into the protobuf one unchanged and writes that constant back to XML as `9999999`, and
takproto 3.0.1 (github.com/snstac/takproto) also copies the XML value unchanged.
The three shared lines have 9999999.0 as `absent` (the unsigned integer of its 8 bytes,
4711630319185297408): such an event carries no height, `ce` or `le` into another format, the raw keys
keep the value, and an absent key writes 9999999.0 (vectors 09 and 10), as `cot-xml` writes
`9999999`. Before 27 November 2026 the lines had six nines, from the comment.

An XML event converted to this pack and back returns the canonical XML of `cot-xml`:
`01-event-to-cot-xml` takes the output of `gen-cot-xml-to-cot-protobuf` and returns the `expect`
of `packs/cot-xml/vectors/02-cot-roundtrip.json`; `04-full-message-to-cot-xml` returns that of
`05-full-event-roundtrip.json`, and `packs/cot-xml/vectors/19-full-event-to-cot-protobuf.json` is
the way in.

## Hand-written vectors

`vectors/01` to `08` are written by hand, field by field; their expected outputs were computed
with the codec of `tools/gen/proto2pack.py` by `tools/gen/cot-protobuf-vectors.py`. So are
`packs/cot-xml/vectors/19-full-event-to-cot-protobuf.json` and
`packs/geojson/vectors/90-to-cot-protobuf-no-position.json` (an entity with no `lat` and `lon`:
`no-kind`).

## Golden vectors

11 vectors `golden-pb-<n>.json`, written by `tools/gen/golden-takproto.py` from takproto
(PROVENANCE.md), a reference codec of TAK Protocol Version 1: takproto turns a CoT XML event into a
TakMessage and reads it back. The input is that message without its 3-byte mesh header, the expected
output its canonical form (an empty sub-message cleared: takproto marks a track present when it sets
speed and course to 0, decode reads no key from it), and the model values are takproto's, under the
`takproto` module's keys and the shared keys; a `hae`, `ce` or `le` of 9999999 is an absent shared
key. The events are takproto's own test event and ten written for the script, together setting every
field takproto maps: `takControl.contactUid` (a GeoChat event), `access`, `qos`, `opex`, the times,
the point, `xmlDetail` (detail elements takproto does not map), and each detail sub-message. Every
event has `time` and `start`, equal: an event with one of them, or two that differ, does not return
unchanged (above). `packs/cot-xml/vectors/golden-xml-<n>.json` hold the XML events of the same set
that carry only what both packs bind.
