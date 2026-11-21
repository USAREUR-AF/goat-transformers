# Pack: nts-ke-records

An NTS Key Establishment request or response (RFC 8915 section 4): the records exchanged in the TLS
application data before NTS-protected NTP. Wire `bits`, `layout sequential`. No kind. One message is
the whole request or response, its records to the end (the last is End of Message). Written by
`tools/gen/gnss-time-pack.py`.

## What is mapped

Each record: the critical bit, the record type, and the body in the extent of the body length: end of
message (empty), next protocol negotiation (a list of 16-bit protocol IDs), error and warning (a 16-bit
code), AEAD algorithm negotiation (a list of 16-bit algorithm IDs), new cookie (octets), NTPv4 server
negotiation (the address or name as ASCII octets), NTPv4 port negotiation (a 16-bit port), any other type
(octets).

## Shared keys

None.

## Not mapped

- **The server name as text**: the `bits` wire has no text transform whose length is the extent; it is
  the name's octets.
- **The TLS session** that carries the records, and the key extraction.

## Vectors

`tools/gen/gnss-time-vectors.py`, without an engine: a client request; a server response with two cookies;
an error response; an unknown record type; a cut record (`malformed-wire`).
