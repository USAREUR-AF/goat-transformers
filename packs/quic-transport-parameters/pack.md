# Pack: quic-transport-parameters

The QUIC transport parameters (RFC 9000 section 18): the data of the quic_transport_parameters TLS
extension, each parameter a variable-length ID, a variable-length value length and the value.
Wire `bits`, `layout sequential`. No kind. Written by `tools/gen/quic-pack.py`.

## Variable-length integers

A QUIC variable-length integer (RFC 9000 section 16) gives its size in its first two bits (1, 2, 4 or 8
octets). Each is a 2-bit `<name>_size` key and a `switch` on it reading the value in 6, 14, 30 or 62
bits; the size is kept, so a round trip writes the size it read, including a larger one than the value
needs. Where an integer counts what follows (a token, data, a reason phrase, ACK ranges, a parameter
value), each size case holds a `count` line of that width and the counted list, and the count is written
from the list.

## What is mapped

The parameters to the end: ID (with its size), and the value as octets counted by the value length.

## Shared keys

None.

## Not mapped

- **The values by ID**: most values are themselves a variable-length integer, some are connection IDs or
  a token, preferred_address is a structure. The value length is a count of octets, not an extent the
  value's layout could be read inside, so values stay octets. Needed: a variable-length integer usable as
  a length.

## Vectors

`tools/gen/quic-vectors.py`, without an engine: four client parameters, one with a reserved two-octet ID; a
cut value (`malformed-wire`).
