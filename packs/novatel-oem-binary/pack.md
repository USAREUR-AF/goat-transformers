# Pack: novatel-oem-binary

A NovAtel OEM binary log: the 28-octet header and, for BESTPOS (message ID 42),
the 72-octet body and the CRC. Wire `bits`, `layout sequential`, `bit_order lsb` (little-endian). One
kind, `oem-binary`, chosen by the sync octets AA 44 12. Written by `tools/gen/gnssbin-pack.py`.

## What is mapped

- **Header**: header length, message ID, message type, port address, message length (as sent), sequence,
  idle time, time status, GPS week, milliseconds of the week, receiver status, reserved, software
  version.
- **BESTPOS** (42): solution status, position type, latitude, longitude, height (doubles), undulation,
  datum identifier, the three standard deviations, the base station identifier, differential and
  solution age, the four satellite counts, the extended solution status and the signals-used mask, the
  two unnamed octets; then the 32-bit CRC.
- Any other log: the data and its CRC as octets.

## Shared keys

None, on purpose:

- **lat, lon**: BESTPOS reports latitude and longitude in the datum its `datum_id` names; the source does
  not state the unit, and passes the values to its fix message as they are. Binding `core.lat` (WGS84
  degrees) would need both the unit and a datum check, which a static binding cannot make.
- **hae**: the source names the field `height` and carries `undulation` beside it, but states neither the
  reference of `height` nor how the two combine; `hae` is not bound.
- **time_ms**: GPS week and milliseconds are kept; the epoch time needs a GPS-to-UTC step (leap seconds).

## Not mapped

- **The CRC computed** (CRC-32): kept as sent.
- **Other logs**: octets.
- **Data and CRC apart** for other logs: the CRC is the last four octets (the "all but the last N" gap);
  the message length is kept as sent.
- The ASCII form, which the source also reads.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one log, sync to CRC.

## Vectors

`tools/gen/gnssbin-vectors.py`, without an engine: BESTPOS; another log as octets; a wrong sync (`no-kind`);
a cut BESTPOS (`malformed-wire`).
