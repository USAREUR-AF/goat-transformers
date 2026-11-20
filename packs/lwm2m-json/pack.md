# lwm2m-json

An OMA LwM2M JSON payload: content format 11543, media type `application/vnd.oma.lwm2m+json`,
as LwM2M 1.0 defines it (technical specification 1.0.2, section 6.4.4). A LwM2M client sends it
in a Read response or a notification. Wire `json`, no kinds. Written by hand from the section;
vectors are derived by `tools/gen/lwm2m-tcx-vectors.py`. Licence: `LicenseRef-OMA-Internal`
(PROVENANCE.md).

| Member | Line | Key |
|---|---|---|
| `bn`, base name | `string` | `lwm2m.base_name` |
| `bt`, base time in seconds | `float` | `lwm2m.base_time` |
| `e`, the entries | `group` | list `lwm2m.entries` |
| entry `n`, name | `string` | `lwm2m.name` |
| entry `t`, time relative to `bt` | `float` | `lwm2m.time` |
| entry `v`, numeric value | `float` | `lwm2m.value` |
| entry `bv`, boolean value | `bool` (1 or 0) | `lwm2m.boolean_value` |
| entry `ov`, object link | `string` | `lwm2m.objlnk_value` |
| entry `sv`, string value | `string` | `lwm2m.string_value` |

An entry's resource is the base name followed by its name: `/6/0/` and `0` name resource 0 of
instance 0 of object 6. What that resource is comes from the OMA LwM2M object registry, below.

## Shared-model keys: none, and why

The registry's Location object (6) states that resources 0 and 1 are latitude and longitude in
decimal degrees of WGS 84, and resource 5 the time of the measurement; object 3336 likewise has
numeric latitude and longitude (6051, 6052) and a timestamp (5518). So a payload of object 6
holds a position that `lat`, `lon` and `time_ms` mean. The pack language cannot reach it:

- Each resource is an entry of the array `e`, found by the value of its `n` (with `bn`), not by
  a member name or a position. On the `json` wire an array element is only a list item, and an
  item cannot be chosen by a value inside it (item kinds exist only on sequential `bits`
  layouts, Version 0.8); a shared key of the entity cannot be filled from one item.
- The time of an entry is `bt` plus `t`, in seconds, and `bt` is absolute only when above zero:
  no derive function adds two keys or tests a sign.

So every value stays a raw item key. A pack per registry object (Device, Location, Temperature,
...) would differ from this one only in documentation, and is not written until the language can
choose an entry by its name: the same addition SenML (RFC 8428) waits for.

## Not mapped

- The TLV content format (11542): its first byte holds the identifier type, the identifier's
  size and either the value's length or the size of a length field. The `tlv` wire reads a tag
  and a length of fixed encodings (Version 0.13), so this header cannot be stated.
- SenML JSON (110) and SenML CBOR (112) of LwM2M 1.1 and later: the message is a JSON array (or
  CBOR), which no wire reads as a message root. LwM2M CBOR (11544, LwM2M 1.2) needs a CBOR wire.
- Plain text and opaque: one bare resource value, with no structure to map.
- Members of an entry other than the six above: an item carries no residue, so they are dropped.
  Top-level scalar members other than `bn` and `bt` are residue and come back.

## The registry objects most used for devices and positions

From the OMA LwM2M registry (BSD-3-Clause, the notice is in PROVENANCE.md): the resource IDs, the
names, types and units as the registry gives them, and the member of the entry that carries each
type. IPSO sensor objects such as Illuminance (3301), Humidity (3304) and Barometer (3315) have
the same resources as Temperature (3303).

Object 3, Device (version 1.3, one instance):

| Resource | Name | Type | Unit | Entry member |
|---|---|---|---|---|
| 0 | Manufacturer | String | - | `sv` |
| 1 | Model Number | String | - | `sv` |
| 2 | Serial Number | String | - | `sv` |
| 3 | Firmware Version | String | - | `sv` |
| 4 | Reboot | - | - | none (an executable resource) |
| 5 | Factory Reset | - | - | none (an executable resource) |
| 6/<i> | Available Power Sources | Integer | - | `v` |
| 7/<i> | Power Source Voltage | Integer | - | `v` |
| 8/<i> | Power Source Current | Integer | - | `v` |
| 9 | Battery Level | Integer | /100 | `v` |
| 10 | Memory Free | Integer | - | `v` |
| 11/<i> | Error Code | Integer | - | `v` |
| 12 | Reset Error Code | - | - | none (an executable resource) |
| 13 | Current Time | Time | - | `v` (seconds since 1970-01-01 UTC) |
| 14 | UTC Offset | String | - | `sv` |
| 15 | Timezone | String | - | `sv` |
| 16 | Supported Binding and Modes | String | - | `sv` |
| 17 | Device Type | String | - | `sv` |
| 18 | Hardware Version | String | - | `sv` |
| 19 | Software Version | String | - | `sv` |
| 20 | Battery Status | Integer | - | `v` |
| 21 | Memory Total | Integer | - | `v` |
| 22/<i> | ExtDevInfo | Objlnk | - | `ov` |

Object 6, Location (version 1.0, one instance):

| Resource | Name | Type | Unit | Entry member |
|---|---|---|---|---|
| 0 | Latitude | Float | lat | `v` |
| 1 | Longitude | Float | lon | `v` |
| 2 | Altitude | Float | m | `v` |
| 3 | Radius | Float | m | `v` |
| 4 | Velocity | Opaque | - | `sv` (base64) |
| 5 | Timestamp | Time | - | `v` (seconds since 1970-01-01 UTC) |
| 6 | Speed | Float | m/s | `v` |

Object 3336, Location (version 2.0, several instances):

| Resource | Name | Type | Unit | Entry member |
|---|---|---|---|---|
| 6051 | Numeric Latitude | Float | lat | `v` |
| 6052 | Numeric Longitude | Float | lon | `v` |
| 6053 | Numeric Uncertainty | Float | m | `v` |
| 5705 | Compass Direction | Float | deg | `v` |
| 5517 | Velocity | Opaque | - | `sv` (base64) |
| 5518 | Timestamp | Time | - | `v` (seconds since 1970-01-01 UTC) |
| 5750 | Application Type | String | - | `sv` |
| 6050 | Fractional Timestamp | Float | s | `v` |
| 6042 | Measurement Quality Indicator | Integer | - | `v` |
| 6049 | Measurement Quality Level | Integer | - | `v` |

Object 3303, Temperature (version 1.1, several instances):

| Resource | Name | Type | Unit | Entry member |
|---|---|---|---|---|
| 5700 | Sensor Value | Float | - | `v` |
| 5601 | Min Measured Value | Float | - | `v` |
| 5602 | Max Measured Value | Float | - | `v` |
| 5603 | Min Range Value | Float | - | `v` |
| 5604 | Max Range Value | Float | - | `v` |
| 5701 | Sensor Units | String | - | `sv` |
| 5605 | Reset Min and Max Measured Values | - | - | none (an executable resource) |
| 5750 | Application Type | String | - | `sv` |
| 5518 | Timestamp | Time | - | `v` (seconds since 1970-01-01 UTC) |
| 6050 | Fractional Timestamp | Float | s | `v` |
| 6042 | Measurement Quality Indicator | Integer | - | `v` |
| 6049 | Measurement Quality Level | Integer | - | `v` |

## Vectors

| File | Shows |
|---|---|
| `01-device-instance-roundtrip.json` | instance 0 of the Device object with a base name |
| `02-location-notification-reordered.json` | a Location notification with a base time and entry times; `bt` and `t` are written in line order |
| `03-full-names-and-booleans-roundtrip.json` | no base name; Temperature value and unit, and two booleans held as 1 and 0 |
| `04-object-links-roundtrip.json` | a base name of `/` and object link values |
| `05-members-not-in-the-format.json` | a top-level member kept as residue, an entry member dropped |
| `06-value-as-text.json` | a string in `v`: `transform-decode` |
