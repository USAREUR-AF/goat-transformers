# eddystone

Eddystone BLE beacon frames (google/eddystone) in one Bluetooth LE advertising payload. Wire `bits`, `layout sequential`, `bit_order msb`; I/O is hex text. Written by `tools/gen/beacons-pack.py`; vectors by `tools/gen/beacons-vectors.py`. Licence: Apache-2.0, as google/eddystone states.

## The Eddystone frame

In the Service Data of UUID 0xFEAA (`switch ble.service_data_uuid16`, case 65194) the first
octet is the frame type (`switch eddystone.frame_type`); the frame's fields are big-endian.

| Frame | Fields |
|---|---|
| UID (0x00) | Tx power at 0 m, namespace (10 octets, two keys), instance (6 octets), the two reserved octets (absent when the frame omits them; written back as zeros) |
| URL (0x10) | Tx power at 0 m, scheme code, the encoded URL as octets |
| TLM (0x20), version 0 | battery voltage (mV), temperature (signed 8.8 fixed point, `sscale:1/256`; `absent 32768` for 0x8000, no sensor), PDU count, time since power-on in tenths of a second |
| TLM, version 1 | encrypted data (12 octets, two keys), salt, integrity check |
| EID (0x30) | Tx power at 0 m, the ephemeral identifier (8 octets) |

Another frame type, and another TLM version, is kept as octets.

## The AD structures

The message is one advertising payload: AD structures to its end (`group ble.ad_structures rest`).
Each is a length octet counting the AD type and the data, the AD type, and the data (a `length 8
bytes` block). The AD type selects the reading (`switch ble.ad_type`): Flags (1), the 16-bit
service UUID lists (2, 3), Tx Power Level (10), Service Data with a 16-bit UUID (22) and
Manufacturer Specific Data (255); any other structure is kept as octets. 16-bit UUIDs and company
identifiers are little-endian on the wire (`swap`).

A zero octet after the last structure (padding to 31 octets) reads as a structure of length 0
and is written back as a structure of length 1 holding the AD type 0: on encode an absent key
writes zero bits (spec 0.8).

The keys of the AD framing are in the module `ble`, shared by the `eddystone`, `altbeacon` and
`remote-id-ble` packs.

## Shared-model keys: none

An advertising payload holds identifiers, signal strengths and telemetry, not a position or an
absolute time.

## Not mapped

- The URL is kept as its encoded octets: the expansion codes (0x00 to 0x0D for `.com/` and
  the others) need a table from octet to text that a list item cannot apply.
- Decrypting encrypted TLM, and resolving an EID, need keys held by a service.
- Characters and text (the local name, an SSID): kept as octets, as a sequential field of
  text needs a fixed length.

## Vectors

| File | Shows |
|---|---|
| `01-uid-roundtrip.json` | Flags, the UUID list and a UID frame with its reserved octets |
| `03-url-roundtrip.json` | a URL frame |
| `04-tlm-roundtrip.json` | a plain TLM frame |
| `05-tlm-temperature-not-supported-roundtrip.json` | 0x8000: the temperature is absent and written back |
| `06-tlm-encrypted-roundtrip.json` | an encrypted TLM frame |
| `07-eid-roundtrip.json` | an EID frame |
| `08-structure-longer-than-the-payload.json` | a structure longer than the payload: `malformed-wire` |
