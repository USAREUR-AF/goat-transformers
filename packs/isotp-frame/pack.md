# Pack: isotp-frame

One ISO-TP (ISO 15765-2) frame: the data field of one CAN frame (8 octets, or up to 64 in the source's longer frames),
with normal addressing (no address extension octet). Wire `bits`, `layout sequential`, `bit_order msb`.
Kinds by the protocol control information, in this order: `single-frame-escape` (first octet 0x00),
`single-frame` (high half 0), `first-frame-escape` (first two octets 0x1000), `first-frame` (high half
1), `consecutive-frame` (2), `flow-control` (3). Written by `tools/gen/vehnet-pack.py`.

## What is mapped

- **Single frame**: the length (the low half of the first octet, or the next octet after the escape
  value 0) as the count of `isotp.data`, then the padding octets.
- **First frame**: the message length (12 bits, or 32 bits after the escape value 0), then the data to
  the end of the frame.
- **Consecutive frame**: the sequence number, then the data to the end of the frame (the last frame of
  a message carries padding there too).
- **Flow control**: flow status, block size, STmin, then the padding.

## Shared keys

None.

## Not mapped

- **Reassembly** of a message from its first and consecutive frames: one message is one frame.
- **Extended and mixed addressing** (an address octet before the control information): use a pack per
  addressing mode; not written.
- **The CAN identifier** and DLC: the frame's data field only.
- **STmin reserved values** are kept as sent; the source reads them as 0x7F.
- **Padding inside a consecutive frame** cannot be told from data; the message length in the first frame
  says where the message ends.
- **Frames the source refuses are read.** python-can-isotp (`isotp/protocol.py`, class `PDU`) raises an
  error for a flow-control frame whose flow status is 3 or more ("Unknown flow status") and for an
  escaped single frame of length 0. The pack reads both: `34 00 00` gives `isotp.flow_status` 4, and an escaped
  single frame with length 0 gives an empty `single-frame-escape`. The pack language has no line that
  refuses a value in range, so a consumer should check `isotp.flow_status` (0 to 2) and that an escaped single frame has data.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the CAN frame's data field.

## Vectors

`tools/gen/vehnet-vectors.py`, without an engine: a padded single frame; a CAN FD single frame with the
escape length; a first frame; a first frame with the 32-bit length; a consecutive frame; a flow control;
frame type 4 (`no-kind`); a single frame longer than its data (`malformed-wire`).
