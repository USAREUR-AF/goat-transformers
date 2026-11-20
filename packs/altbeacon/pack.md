# altbeacon

AltBeacon BLE beacon advertisements (AltBeacon Protocol Specification v1.0) in one Bluetooth LE advertising payload. Wire `bits`, `layout sequential`, `bit_order msb`; I/O is hex text. Written by `tools/gen/beacons-pack.py`; vectors by `tools/gen/beacons-vectors.py`. Licence: CC-BY-SA-4.0, as altbeacon.org states (PROVENANCE.md).

## The AltBeacon advertisement

In the Manufacturer Specific Data, after the company identifier, the next two octets are read
as the beacon code (big-endian); when it is 0xBEAC (`switch altbeacon.beacon_code`, case 48812)
the 20-octet beacon ID (three keys: 8, 8 and 4 octets), the reference RSSI at 1 m (signed) and
the manufacturer's reserved octet follow. Manufacturer data of another kind keeps its first two
octets in `altbeacon.beacon_code` and the rest as octets, so it comes back unchanged.

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

- Apple iBeacon is not built (see the family report): its byte layout is published only in
  Apple's licensed specification.
- Characters and text (the local name, an SSID): kept as octets, as a sequential field of
  text needs a fixed length.

## Vectors

| File | Shows |
|---|---|
| `01-altbeacon-roundtrip.json` | Flags and an AltBeacon advertisement |
| `02-other-manufacturer-data-roundtrip.json` | manufacturer data that is not an AltBeacon |
