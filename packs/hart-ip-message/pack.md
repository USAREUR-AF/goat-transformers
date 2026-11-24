# Pack: hart-ip-message

A HART-IP message (TCP or UDP port 5094): the 8-octet header and the body. Wire `bits`, `layout
sequential`, `bit_order msb`. No kinds. Written by `tools/gen/indauto2-pack.py`.

## What is mapped

- **Header**: version, message type, message ID, status, sequence number, and the length of the whole
  message (`length 16 whole`).
- **Error and NAK** (types 3 and 15): the error code, anything after it as octets.
- **Session initiate** (ID 0): master type, inactivity close timer.
- **Pass through** (ID 3), the HART frame: the delimiter (address type, the expansion count as a count
  line, physical layer type, frame type); the short address (two high bits and the 6-bit polling
  address) or the 5-octet long address; the counted expansion octets; the command; the byte count as
  sent; in frame types 1 and 6 (responses) the response code and device status; then the data, whose
  last octet is the checksum.
- Other IDs (session close, keep alive): the body as octets.

## Shared keys

None.

## Not mapped

- **Preambles**: a pass-through frame that begins with 0xFF preamble octets is not read correctly; the
  pack takes the first octet as the delimiter. A run of octets of one value has no form in the pack
  language.
- **The checksum** as its own field and the byte count as a length: the data runs to the end of the
  message, and the checksum is its last octet; the source reads the data the same way (all but the last
  octet) and does not use the byte count to bound it.
- **The HART commands' data** (universal and common-practice commands): octets.
- Other message IDs: the body as octets.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one message.

## Vectors

`tools/gen/indauto2-vectors.py`, without an engine: a session initiate; a pass-through command 0 to a
short address; a command 3 response to a long address; expansion octets; an error; a keep alive; a
message shorter than its length (`malformed-wire`).
