# Pack: rpki-rtr

One PDU of the RPKI to Router protocol, version 1 (RFC 8210). Wire `bits`, `layout
sequential`, most significant bit first. The version (1) is a common `when`; each PDU type is a
kind chosen by its type octet; the PDU length is a `length 32 whole` line. Input and output are
hex. A TCP stream of PDUs is one message per PDU.

## What is mapped

| Kind | Type | Read as |
|---|---|---|
| `serial_notify` | 0 | session ID, serial number |
| `serial_query` | 1 | session ID, serial number |
| `reset_query` | 2 | nothing beyond the header |
| `cache_response` | 3 | session ID |
| `ipv4_prefix` | 4 | flags (the announce bit and the seven bits above it), prefix length, maximum length, the IPv4 prefix, AS number |
| `ipv6_prefix` | 6 | as IPv4, with the 128-bit prefix in two 64-bit halves |
| `end_of_data` | 7 | session ID, serial number, refresh, retry and expire intervals in seconds |
| `cache_reset` | 8 | nothing beyond the header |
| `router_key` | 9 | flags, the 20-octet subject key identifier (three integers: octets 1-8, 9-16, 17-20), AS number, the subject public key info as octets |
| `error_report` | 10 | error code, the erroneous PDU (its length, then its octets), the error text (its length, then its octets) |

The zero fields are `pad` lines: read over, written as zero.

## Shared keys

None: the protocol carries validated route origins, not a reported entity.

## Not mapped

- **Version 0** (RFC 6810): its End of Data has no intervals and it has no Router Key; a PDU of
  version 0 is `no-kind`.
- The erroneous PDU of an Error Report is kept as octets, not read as a PDU.
- The error text is its UTF-8 octets: the `bits` wire has no text transform whose length comes
  from a field.

## Vectors

`tools/gen/routing-vectors.py`, without an engine: one round trip per PDU type, version 0
(`no-kind`), type 5 (`no-kind`), and a truncated IPv4 Prefix PDU (`malformed-wire`).
