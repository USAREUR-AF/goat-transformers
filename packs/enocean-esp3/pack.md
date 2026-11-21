# Pack: enocean-esp3

One EnOcean Serial Protocol 3 packet, between a host and an EnOcean transceiver (USB 300 and similar).
Wire `bits`, `layout sequential`, `bit_order msb`. One kind, `esp3`, chosen by the sync octet 0x55.
Written by `tools/gen/smarthome-pack.py`.

## What is mapped

- **Header**: the data length and the optional length (as `count` lines, so each region's length is
  written from its list), the packet type, the header CRC as sent.
- **Data** and **optional data**: each a counted list of octets.
- **Data CRC**: as sent.

## Shared keys

None.

## Not mapped

- **The CRC8s computed** (polynomial 0x07, over the header and over both data regions): as sent.
- **The data by packet type**: for radio ERP1 the RORG, the EEP payload, the sender ID and the status;
  the payload's length depends on the RORG and the region is a counted list, so the fields are not
  split. The EEP profiles (temperature sensors, switches and the rest) would be a further layer.
- **The optional data's fields** (subtelegram count, destination ID, dBm, security level): octets.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one packet, sync to data CRC.

## Vectors

`tools/gen/smarthome-vectors.py`, without an engine (CRCs computed there): a radio ERP1 telegram with optional
data; a response; a common command; no sync (`no-kind`); a cut packet (`malformed-wire`).
