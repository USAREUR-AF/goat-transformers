# Pack: zwave-serial-frame

One frame of the Z-Wave Serial API, between a host and a Z-Wave controller (USB stick or module). Wire
`bits`, `layout sequential`, `bit_order msb`. Kinds by the first octet: `ack` (0x06), `nak` (0x15), `can`
(0x18), `data-frame` (SOF 0x01). Written by `tools/gen/smarthome-pack.py`.

## What is mapped

- **Data frame**: the length (a `length 8 bytes plus 1` block: the length counts the type, the function,
  the payload and the checksum, and the block holds all but the checksum), the message type (request or
  response), the function ID, the payload as octets, and the checksum as sent.
- **ACK, NAK, CAN**: the single octet.

## Shared keys

None.

## Not mapped

On encode with no recorded kind (engine-spec Encode step 2), each kind is chosen by the keys
it requires.
`ack`, `nak`, `can` have no `requires`, so an entity that fits no other kind is written as `ack`.
Choosing between them needs `requires` on a value or on an absent key, a language addition.

- **The checksum computed** (0xFF XOR the octets from the length to the payload's end): as sent.
- **Each function's payload** (node IDs, command class frames, the controller's capabilities):
  octets; the command class frame inside ApplicationCommand would be the next layer.
- The bootloader, Zniffer and CLI framings that zwave-js also parses.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one frame.

## Vectors

`tools/gen/smarthome-vectors.py`, without an engine: ACK; NAK; a GetControllerVersion request; an
ApplicationCommand; a SendData response; another first octet (`no-kind`); a cut frame (`malformed-wire`).

## Kind on encode from another format

The kind is the one whose value `zwave.start` holds (the first octet, `when ... as`), and
its `requires` line names the fields that kind always has.
An entity that fits no kind is `no-kind`.
