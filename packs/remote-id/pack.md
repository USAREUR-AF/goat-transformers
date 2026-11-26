# Pack: remote-id

Broadcast Remote ID for unmanned aircraft: the 25-byte messages of ASTM F3411 /
OpenDroneID. Public. Written from the packed structs and the encode and decode
functions of the Apache-2.0 reference implementation `opendroneid-core-c`
(`libopendroneid/opendroneid.h`, `opendroneid.c`), protocol version 2. I/O is
hex text (`spec/engine-spec.md`, bits wire). Needs engine version 0.7 (kinds,
`bit_order`, fields past their word, `uscale`, `sscale`, `ascii`, and a counted
group for the Message Pack).

Uses the modules `core` and `rid` (`model/rid.def`).

## Addressing

`word_bytes 1`, `bit_order lsb`. A locator is `0:<bit offset>:<len>`; byte *n*
starts at offset 8*n*.

The C structs declare bit-fields least significant bit first and hold
multi-byte integers little-endian. With `lsb` both come out as single fields:

- the low nibble of byte *n* is `0:<8n>:4`, the high nibble `0:<8n+4>:4`;
- a little-endian `int32` at byte *n* is `0:<8n>:32`, a `uint16` is `0:<8n>:16`.

With `msb` a little-endian integer would need one field per byte and could not
be scaled.

## Kinds

Byte 0 is `[message type : 4 high][protocol version : 4 low]`. The protocol
version is the common field `rid.proto_version`. The type nibble `0:4:4` is
both the common field `rid.msg_type` and a `when` in each kind: the `when`
selects the kind, the field puts the value in the model. On encode the kind's
`when` value is written after the fields, so the kind decides the type.

| Kind | Type | Fields | Mapped to `core` |
|---|---|---|---|
| `basic-id` | 0 | aircraft type, ID type, UAS ID, reserved | `uid` |
| `location` | 1 | status, flags, direction, speeds, position, three altitudes, accuracies, timestamp, reserved | `lat`, `lon`, `hae` |
| `auth-page0` | 2, page 0 | authentication type, last page index, length, timestamp, last data byte | none |
| `auth-page` | 2, pages 1-15 | page number, authentication type, last data byte | none |
| `self-id` | 3 | description type, text | none |
| `system` | 4 | operator location type and position, area count, radius, ceiling, floor, EU class and category, operator altitude, timestamp, reserved | none |
| `operator-id` | 5 | operator ID type, operator ID, reserved | none |
| `message-pack` | 15 | message size, and the list `rid.messages`: one item per contained message | none |

`auth-page0` is listed before `auth-page` and has a second `when` on the page
nibble, so page 0 selects it and every other page selects `auth-page`.

## Message Pack

A Message Pack (type 0xF) is byte 0 as in every message, byte 1 the size of one
message (25, `rid.pack_msg_size`, written as 25 when the entity has no value),
byte 2 the number of messages, then that many 25-byte messages. The kind
`message-pack` maps the messages with a counted group (engine-spec Version
0.7): `group rid.messages 0:24 item 200 count 0:16:8`. Byte 2 is the count; it
is read on decode and written with the number of items on encode. The kind
also needs byte 1 to be 25 (`when 0:8:8 25`): opendroneid.c (decodeMessagePack)
refuses another size, so a pack stating 26 is `no-kind` (vector 17). The source
also refuses a count of 0 or above 9; the pack reads such counts (vector 15
holds a count of 0), a limit.

Each item holds the fields every message type has in common, and the rest of
the message as raw integers:

| Item key | Bits of the message | Content |
|---|---|---|
| `rid.proto_version` | low nibble of byte 0 | protocol version |
| `rid.msg_type` | high nibble of byte 0 | message type, 0 to 5 |
| `rid.body_1_8`, `rid.body_9_16`, `rid.body_17_24` | bytes 1-8, 9-16, 17-24 | each a little-endian 64-bit integer; a value whose top bit is set is negative in the model (ruling 2 of 0.5) |

The five fields cover all 200 bits, so a pack round-trips byte for byte, and a
caller can read each message's type and rebuild its 25 bytes.

An item is not decoded by its own type: a Location message inside a pack does
not yield `lat` and `lon`, because the fields of a group are the same for every
item and the language has no group whose items are decoded by kind. What is
missing is exactly that: a group body that selects a kind per item (`when`
lines inside a group, which engine-spec Version 0.7 refuses). Until then the
caller converts each message on its own: message *i* is bytes `3 + 25 * i` to
`3 + 25 * i + 24` of the pack.

A pack whose count byte promises more messages than the input holds is
`malformed-wire`. The source limits a pack to 9 messages
(`ODID_PACK_MAX_MESSAGES`); the pack does not check the limit.

## Encodings, as the C source defines them

| Value | Wire | Transform | Key |
|---|---|---|---|
| Latitude, longitude | `int32`, degrees x 10^7 | `sscale:1/10000000` | `lat`, `lon` (operator: `rid.operator_lat`, `rid.operator_lon`) |
| Geodetic altitude (height above the WGS84 ellipsoid) | `uint16`, (meters + 1000) x 2 | `uscale:1/2:-1000` | `hae` |
| Pressure altitude, height, area ceiling and floor, operator altitude | same | `uscale:1/2:-1000` | `rid.alt_baro`, `rid.height`, `rid.area_ceiling`, `rid.area_floor`, `rid.operator_hae` |
| Vertical speed | `int8`, m/s x 2 | `sscale:1/2` | `rid.speed_v` |
| Area radius | `uint8`, meters / 10 | `uscale:10` | `rid.area_radius` |
| UAS ID, operator ID (20 bytes), Self-ID text (23 bytes) | NUL-padded text | `ascii` | `uid`, `rid.operator_id`, `rid.description` |
| Enumerations, counts, flags | unsigned integer | `uint` | `rid.*` |

`uid` is mapped only in `basic-id`. The operator position is not mapped to
`lat` / `lon`: those keys are the position of the reported aircraft.

## Kept raw, and what would convert it

| Value | Why it is raw | Addition that would map it |
|---|---|---|
| Horizontal speed: `rid.speed_h_raw` with flag `rid.speed_mult` | Two scales chosen by a bit in another field: raw x 0.25 m/s, or raw x 0.75 + 63.75 m/s. A transform reads one field. | A transform that takes a second locator as its selector, for example `uscale2:<flag locator>:<factor0>:<offset0>:<factor1>:<offset1>`, yielding `speed_ms`. |
| Track direction: `rid.direction_raw` with flag `rid.ew_direction` | The flag adds 180 degrees. Same limit. | The same two-field transform (`1:0` and `1:180`), yielding `course`. |
| Location timestamp `rid.timestamp_ds` | Tenths of a second after the full hour; the hour and date are not in the message. | Nothing in the pack can supply the hour. `time_ms` needs the receive time from outside the message. |
| System and authentication timestamps | Seconds since 2019-01-01T00:00:00Z. `uscale:1000:1546300800000` would give epoch milliseconds, but `uscale` yields `float` and `time_ms` is `int`. | An integer scale transform, for example `iscale:<factor>:<offset>` yielding `int`. These are also not the time of the aircraft position, so they would map to `rid` keys, not to `time_ms`. |
| Accuracy codes `rid.horiz_acc`, `rid.vert_acc`, `rid.baro_acc`, `rid.speed_acc` | Each code stands for a bound in meters or m/s from a table. | A lookup transform (`lookup:<table>`) with a per-pack table, yielding `ce` and `le`. |
| Aircraft type `rid.ua_type` | A code table; `typemap` maps to `type`, which is a string, and the wire value is an integer. | `typemap` usable on a `bits` field, or the lookup transform. |
| Vertical speed `rid.speed_v` | Converted to m/s, kept in `rid`. The source does not state the sign convention, so it is not mapped to `track.vel_up_ms`. | None: a mapping change once the convention is confirmed from the ASTM text. |

## Not mapped

- **The contents of the messages inside a Message Pack.** The pack is mapped
  (section Message Pack); each contained message is kept as raw bytes, not
  decoded by its type. Addition: a group whose items are decoded by kind.
- **Authentication data.** Bytes 8-24 of page 0 and bytes 2-24 of other pages
  are binary and longer than one 64-bit field. Only the header fields are
  mapped. The last data byte is mapped as `rid.auth_data_last` because a
  message's length is set by its furthest mapped bit: without it the page
  would encode as 8 or 2 bytes. An authentication message with data therefore
  does not round-trip byte-identically. Addition: a `hex` (or `bytes`)
  transform yielding a string, with the same length rule as `ascii`.
- **Binary UAS IDs.** For ID types 3 (UTM UUID) and 4 (specific session ID)
  the 20 bytes are binary. `ascii` refuses bytes outside 0x20-0x7E, so such a
  Basic ID message fails to decode with a transform error. The same `hex`
  transform, in a kind selected by `when` on the ID type, would carry them.
- **Reserved bits inside a message**: bit 3 of byte 1 and the high nibble of
  byte 23 in `location`; bits 5-7 of byte 1 in `system`. Zero in every defined
  protocol version. The trailing reserved bytes are mapped (`rid.reserved`) so
  that each kind's message is 25 bytes.
- **Wi-Fi and Bluetooth framing** (`odid_wifi.h`, `wifi.c`): transport, outside
  the message contents.

## Unknown values

The source defines a value for "invalid, no value, or unknown" in several
fields: latitude and longitude 0, altitudes -1000 m, vertical speed 63 m/s,
timestamp 65535. An altitude of raw 0 (-1000 m) in `rid.alt_baro`, `hae`,
`rid.height` and `rid.operator_hae` is absent (`absent 0`): the message
reaches GeoJSON without an altitude (vector
`location-unknown-values-to-geojson`), and an absent key is written as raw 0.
The others pass through as numbers; latitude and longitude both 0 (unknown)
decode as the point 0, 0, since either value alone is a real coordinate.

## Cross-format encode

Each kind has `requires` on keys only this pack produces, so an entity from
another format selects no kind and `encode` fails with `no-kind`. A GeoJSON
point cannot become a Location message: status, direction, speed and
timestamp have no source.

## Vectors

16 vectors under `vectors/`.

| Vectors | Content | Source |
|---|---|---|
| 01-07 | one same-format round trip per kind, byte-identical | input values of upstream `test/test_inout.c`, quantized as `opendroneid.c` encodes them |
| 08, 09 | the Basic ID message held as fixed bytes in upstream `test/unit_odid_wifi_beacon.cpp`: round trip, and to GeoJSON | `"source": "specification"` |
| 10-12 | Location to GeoJSON | 10: `test_inout.c` values; 11, 12: constructed |
| 13-17 | Message Pack: one message, two messages, no message (byte-identical round trips), a count beyond the input (`malformed-wire`), and a message size of 26 (`no-kind`) | constructed from the messages of vectors 01, 02 and 08 |

The upstream tests hold exactly one complete 25-byte message as fixed bytes
(the Basic ID in vector 08). The Location message in the same array is cut off
after two bytes.

The scale factors are written as fractions (`1/10000000`, `1/2`), so decode
divides as the C source does: the wire integer 455393090 decodes to 45.539309
(vector 10).
