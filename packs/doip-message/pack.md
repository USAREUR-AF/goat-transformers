# Pack: doip-message

One DoIP (ISO 13400-2) message (UDP or TCP port 13400): the 8-octet generic header and the payload.
Wire `bits`, `layout sequential`, `bit_order msb`. No kinds. Written by `tools/gen/vehnet-pack.py`.

## What is mapped

- **Header**: version, inverse version, payload type, and the payload length (`length 32 bytes`).
- **By payload type**: generic NACK (the code); vehicle identification request (nothing), by EID (the
  EID), by VIN (the VIN); vehicle announcement (VIN, logical address, EID, GID, further action, sync
  status); routing activation request (source address, activation type of 16 bits in version 1 and 8
  later, the ISO reserved field, the optional OEM field as octets) and response (tester and entity
  addresses, response code, ISO reserved, OEM as octets); alive check (nothing; the response's source
  address); entity status (nothing; the response's node type, maximum and current sockets, maximum data
  size); power mode (nothing; the response's mode); diagnostic message (source, target, the UDS data as
  octets); diagnostic ACK and NACK (source, target, code, the previous message as octets). Other types:
  octets.

## Shared keys

None.

## Not mapped

- **The UDS message** inside a diagnostic message: octets here; `uds-message` reads it on its own.
- **Optional trailing fields as absent**: a vehicle announcement without the sync status (version 1)
  and an entity status response without the maximum data size re-encode with zeros for them (ruling 7
  of 0.8, vector 10).
- **A VIN or EID not yet configured** (0x00 or 0xFF fill): the VIN is `chars:ascii8`, which refuses 0xFF.
- DoIP over TLS (port 3496) and the payload types of later amendments.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one DoIP message.

## Vectors

`tools/gen/vehnet-vectors.py`, without an engine: a vehicle identification request; a vehicle
announcement; routing activation requests in versions 2 and 1 (with the OEM field) and a response; a
diagnostic message; a diagnostic ACK; an entity status response; a generic NACK; an announcement
without the sync status (a zero octet added); a cut payload (`malformed-wire`).
