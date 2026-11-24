# Pack: bacnet-ip-bvlc

A BACnet/IPv4 virtual link layer message (BVLC), with the BACnet NPDU
header where the function carries an NPDU. Wire `bits`, `layout sequential`, `bit_order msb`. One kind,
`bvlc`, chosen by the type octet 0x81. Written by `tools/gen/indauto2-pack.py`.

## What is mapped

- **BVLC**: the function and the length of the whole message (`length 16 whole`).
- **By function**: result (the code); write BDT and read BDT ack (the entries: address, port, mask); read
  BDT and read FDT (nothing); forwarded NPDU (the original source address and port, then the NPDU);
  register foreign device (the TTL); read FDT ack (the entries: address, port, TTL, remaining); delete
  FDT entry (address, port); distribute broadcast, original unicast and original broadcast (the NPDU).
  Secure BVLL (12) and unknown functions: octets.
- **NPDU header**: version; the control bits (network message, destination present, source present,
  expecting reply, priority, and the two reserved bits); with a destination, DNET, the counted DADR and,
  after the source, the hop count; with a source, SNET and the counted SADR; with a network message, its
  type and, from 0x80, the vendor ID. The APDU or the network message's data follows as octets.

## Shared keys

None. Addresses are IPv4 integers of this module; nothing has a `core` or `track` meaning.

## Not mapped

- **The APDU** (confirmed and unconfirmed requests, ACKs, the BACnet services and their tagged
  application data): octets.
- **Network layer message bodies** (I-Am-Router-To-Network and the others): octets.
- Other BACnet data links.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one UDP payload.

## Vectors

`tools/gen/indauto2-vectors.py`, without an engine: an original broadcast Who-Is; a routed original
unicast; a forwarded NPDU with a source network; a proprietary network message with a vendor ID; a
result NAK; a register; a read BDT ack; a read FDT ack; another BVLL type (`no-kind`); a message shorter
than its length (`malformed-wire`).
