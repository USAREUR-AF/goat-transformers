# Pack: quic-long-header

A QUIC long-header packet (RFC 9000 section 17.2), versions 1 and 2 (RFC 9369 section 3.2). Wire `bits`,
`layout sequential`. One kind, `long-header`, selected by the header form bit, as in `quic-invariant`. One
message is one UDP payload, starting with the packet. Written by `tools/gen/quic-pack.py`.

## Variable-length integers

A QUIC variable-length integer (RFC 9000 section 16) gives its size in its first two bits (1, 2, 4 or 8
octets). Each is a 2-bit `<name>_size` key and a `switch` on it reading the value in 6, 14, 30 or 62
bits; the size is kept, so a round trip writes the size it read, including a larger one than the value
needs. Where an integer counts what follows (a token, data, a reason phrase, ACK ranges, a parameter
value), each size case holds a `count` line of that width and the counted list, and the count is written
from the list.

## What is mapped

- **The invariant fields** on the `inet` keys of `quic-invariant`, unchanged: the 7 version-specific bits,
  the version, and the destination and source connection IDs.
- By the version:
  - **0, Version Negotiation**: the supported versions to the end.
  - **1 and 2**: by the long packet type (bits 5-4 of the version-specific bits; version 2 permutes the
    codes): **Initial** (token, then the length, then the protected octets), **0-RTT** and **Handshake**
    (the length, then the protected octets), **Retry** (the retry token and integrity tag as octets).
  - **another version**: the rest as octets.

The packet type is chosen by a `switch` on `inet.quic_version_specific` with the values of each type
listed, so the key of `quic-invariant` is kept whole rather than split into fixed bit, type and the
type-specific bits.

## Shared keys

None of `core` or `track`. The invariant fields are the `inet` keys of `quic-invariant`.

## Not mapped

- **The packet number and payload**: header protection masks the packet number length (the low two
  version-specific bits) and the packet number, and the payload is encrypted; with the keys, the
  decrypted payload is read by `quic-frames`. They are the `protected` octets.
- **The length as an extent**: the length is a variable-length integer read as a value, so the protected
  octets run to the end of the input; packets coalesced after the first are in them. Needed: a variable-
  length integer usable as a length.
- **The Retry integrity tag** is the last 16 octets, after a token that runs to them; it stays with the
  token. Needed: a trailer after a `rest` list.

## Vectors

`tools/gen/quic-vectors.py`, without an engine: an Initial; an Initial with a token; Handshake; 0-RTT; Retry;
Version Negotiation; a version 2 Initial; another version; a short header (`no-kind`); a cut connection
ID (`malformed-wire`).
