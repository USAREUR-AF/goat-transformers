# Pack: slp-message

An SLPv2 message (RFC 2608 section 8), over UDP or TCP port 427. Wire `bits`, `layout sequential`,
`bit_order msb`. One kind, `slpv2`, chosen by the version octet 2. Written by `tools/gen/dirnaming-pack.py`.

## What is mapped

- **Header**: function ID; the length of the whole message (`length 24 whole`); the O, F and R flags and
  the 13 reserved bits; the next extension offset; the XID; the language tag in its length block.
- **SrvRqst** (1): the previous responder list, service type, scope list, predicate and SPI, each in its
  16-bit length block.
- **SrvRply** (2): the error code and the URL entries (counted), each the reserved octet, lifetime, URL,
  and its authentication blocks (counted), each the descriptor, the block length (`length 16 bytes plus
  4`, since it counts the descriptor and itself), the timestamp, the SPI string and the authenticator.
- **SrvAck** (5): the error code.
- Any other function (SrvReg, SrvDeReg, AttrRqst, AttrRply, DAAdvert, SrvTypeRqst, SrvTypeRply,
  SAAdvert): the body as octets.

## Shared keys

None.

## Not mapped

- **Strings as text**: every string (language tag, scopes, service type, URL, predicate) is a list of
  octets, for want of a character field that fills its length block (as for `ipp-message`).
- **Extensions** (section 9.1): they follow the body at the next extension offset; in the three mapped
  functions they are not read and a re-encode leaves them out (and shortens the length); in the others
  they are part of the body octets.
- **The other functions' fields**: octets.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one message.

## Vectors

`tools/gen/dirnaming-vectors.py`, without an engine: a SrvRqst; a SrvRply with two URL entries, one with an
authentication block; a SrvAck; a DAAdvert as octets; version 1 (`no-kind`); a message shorter than its
length (`malformed-wire`).
