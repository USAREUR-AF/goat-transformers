# Pack: nbdgm-message

A NetBIOS Datagram Service packet (RFC 1002 section 4.4), as sent over UDP port 138. Wire `bits`, `layout
sequential`, `bit_order msb`. No kinds; the message type chooses the layout (`switch`). Written by
`tools/gen/dirnaming-pack.py`.

## What is mapped

- **Header**: message type; the flags (four reserved bits, source node type, F, M); datagram ID; source
  address and port.
- **Direct unique, direct group, broadcast** (0x10 to 0x12): datagram length and packet offset as sent,
  the source and destination names, the user data as octets.
- **Error** (0x13): the error code.
- **Query request and responses** (0x14 to 0x16): the destination name.
- **Names** as in `nbns-message`, without pointers (section 4.1 allows them in Name Service packets
  only): a pointer is `no-kind`.

## Shared keys

None. The datagram header has no DNS or core meaning.

## Not mapped

- **The datagram length computed**: it is kept as sent, not checked against the names and data.
- **Fragment reassembly** (F, M and the offset across packets).
- **The NetBIOS name decoded** from its first-level encoding (see `nbns-message`).
- **An undefined message type**: `no-kind`.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one packet.

## Vectors

`tools/gen/dirnaming-vectors.py`, without an engine: a direct unique datagram; a broadcast fragment with
scoped names; an error packet; a query request; a pointer in a datagram name and type 0x17 (`no-kind`); a
cut header (`malformed-wire`).
