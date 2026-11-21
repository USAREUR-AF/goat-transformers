# remote-id-ble

ASTM F3411 broadcast Remote ID over Bluetooth LE: the advertising payload that carries a Remote ID message (Bluetooth 4 legacy advertising) or a message pack (Bluetooth 5 extended advertising). Wire `bits`, `layout sequential`, `bit_order msb`; I/O is hex text. Written by `tools/gen/beacons-pack.py` from opendroneid/transmitter-linux; vectors by `tools/gen/beacons-vectors.py`. Licence: Apache-2.0.

## The Remote ID service data

In the Service Data of UUID 0xFFFA (ASTM, case 65530) come the application code (0x0D for Open
Drone ID, `switch ridble.application_code`), a message counter, and the 25-octet message or the
message pack, kept as octets in `ridble.message`.

The messages themselves are read by the `remote-id` pack, which already covers every message
type and the message pack: this pack is only the Bluetooth wrapping. One message cannot be read
by two packs in one pass (a layered wire is not in the language), so a receiver takes the
octets of `ridble.message` and decodes them with `remote-id`.

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

- Wi-Fi NAN service discovery frames (the other Wi-Fi transport of Remote ID) are not built;
  the Wi-Fi beacon transport is in the `wifi-beacon` pack.
- Characters and text (the local name, an SSID): kept as octets, as a sequential field of
  text needs a fixed length.

## Vectors

| File | Shows |
|---|---|
| `01-bluetooth-4-message-roundtrip.json` | Bluetooth 4: one Basic ID message after the counter |
| `02-bluetooth-5-message-pack-roundtrip.json` | Bluetooth 5: a message pack of two messages |
| `03-other-application-code-roundtrip.json` | another application code: kept as octets |
