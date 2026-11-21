# wifi-beacon

The body of an IEEE 802.11 beacon frame: the three fixed fields and the information elements to
its end, as google/gopacket decodes them, with the ASTM Remote ID vendor element as
opendroneid-core-c writes it. Wire `bits`, `layout sequential`, `bit_order msb`; I/O is hex text.
Written by `tools/gen/beacons-pack.py`; vectors by `tools/gen/beacons-vectors.py`. Licence:
Apache-2.0: the layouts are restated from google/gopacket (BSD-3-Clause) and opendroneid-core-c
(Apache-2.0), and no code is copied (PROVENANCE.md). The IEEE 802.11 standard was not used.

| Part | Lines | Keys |
|---|---|---|
| timestamp (8 octets), beacon interval (2), capability (2), little-endian | `uint` with `swap` | `wifi.timestamp` (microseconds; `uint` at 64 bits reads a set top bit as negative), `wifi.beacon_interval` (time units of 1024 microseconds), `wifi.capability` |
| elements to the end | `group wifi.elements rest`: ID, then a `length 8 bytes` block | `wifi.element_id` |
| SSID (0), Supported Rates (1) | octets | `wifi.ssid`, `wifi.rates` |
| DS Parameter Set (3) | the channel | `wifi.channel` |
| TIM (5) | DTIM count, DTIM period, bitmap control, the partial virtual bitmap as octets | `wifi.dtim_count`, ... |
| Vendor Specific (221) | the OUI (24 bits); for FA-0B-BC (ASTM) the type, and for type 0x0D (Remote ID) the message counter and the message pack as octets; another vendor's data as octets | `wifi.oui`, `wifi.oui_type`, `wifi.rid_message_counter`, `wifi.rid_message_pack` |
| any other element | octets | `wifi.element_data` |

## Remote ID over a Wi-Fi beacon

A Remote ID beacon is an ordinary beacon whose body holds the ASTM vendor element: this pack reads
it. The message pack is kept as octets in `wifi.rid_message_pack`, which the `remote-id` pack's
`message-pack` kind reads; the language has no layered wire to read both in one pass.

## Shared-model keys: none

The timestamp is the transmitter's free-running timer, not an absolute time; a beacon holds no
position.

## Not mapped

- The MAC header (frame control, addresses, sequence control) and the frame check sequence: the
  message is the frame body.
- Elements whose layout only the IEEE standard gives (RSN, HT and VHT capabilities and others):
  kept as octets.
- The SSID as text: kept as octets.

## Vectors

| File | Shows |
|---|---|
| `01-remote-id-beacon-roundtrip.json` | a Remote ID beacon body: SSID, rate, channel, the ASTM element with a message pack |
| `02-access-point-beacon-roundtrip.json` | a hidden SSID, a TIM, another vendor's element, an element kept as octets |
| `03-element-longer-than-the-body.json` | an element that states more octets than the body holds: `malformed-wire` |
