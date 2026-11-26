# Pack: enip-encapsulation

An EtherNet/IP encapsulation message (TCP or UDP port 44818): the 24-octet
header and the command data. Wire `bits`, `layout sequential`, `bit_order lsb` (EtherNet/IP is
little-endian); the socket address item's fields are big-endian (`swap`). No kinds. Written by
`tools/gen/indauto2-pack.py`.

## What is mapped

- **Header**: command, the data length (a `length 16 bytes plus -20` block: the length counts the data
  after the 24-octet header, and the 20 header octets after the length field sit inside the block),
  session handle, status, sender context (`hex`), options.
- **RegisterSession** (0x65): protocol version, option flags.
- **SendRRData and SendUnitData** (0x6F, 0x70): interface handle, timeout, and the common packet format:
  the counted items, each a type and its length block holding, by type, the connection ID (connected
  address 0xA1), the connection ID and sequence number (sequenced address 0x8002), or the socket address
  (0x8000, 0x8001: family, port, IPv4 address, 8 zero octets). Other items (null address, unconnected
  and connected data, identity) as octets.
- Any other command's data (ListIdentity, ListServices and ListInterfaces replies included): octets.

The sender context under `bit_order lsb` gives each octet's low digit first (as for `smb2-message`); it
round-trips exactly.

## Shared keys

None.

## Not mapped

- In a ListIdentity request (command 0x63, length 0), Wireshark's dissector (packet-enip.c) reads
  octets 12-13 as a response delay and only 14-19 as the sender context. The pack reads octets
  12-19 as `enip.sender_context` for every command, so for that request the key holds the delay
  as its first two octets. The bytes round-trip; choosing the layout by the command and the length
  together is a two-field condition the language has no form for.
- **The CIP message** inside unconnected and connected data items (service, request path, status,
  data): octets. The CIP specification: not read.
- **ListIdentity, ListServices and ListInterfaces replies**: octets (their item list is the same CPF,
  but a request has no data at all, and a count line at the end of an empty block re-encodes as two
  zero octets under ruling 7 of 0.8, so the commands are left to octets).
- The class 3 sequence count inside connected data, the CIP Security and DTLS items.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one encapsulation message.

## Vectors

`tools/gen/indauto2-vectors.py`, without an engine: RegisterSession; SendRRData with an unconnected CIP
request; SendUnitData with a connected address; a reply with a socket address item; a sequenced address
item; a ListIdentity request; UnRegisterSession with a status; a cut header (`malformed-wire`).
