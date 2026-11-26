# Pack: ah-header

The IPsec Authentication Header, as IETF RFC 4302 section 2 lays it out: the
12 fixed octets before the ICV. Public. Written by hand from the RFC; the
layout is stated in this repository's words. I/O is hex text. Needs engine
version 0.2.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the AH header and what follows it. The pack reads octets 0-11; the
ICV and the payload are read over and not written (vector 01).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | next header | `inet.ah_next_header` | `uint` |
| 1 | payload length | `inet.ah_payload_len` | `uint`: 32-bit words, minus 2 |
| 2-3 | reserved | `inet.ah_reserved` | `uint` |
| 4-7 | security parameters index | `inet.ipsec_spi` | `uint` |
| 8-11 | sequence number | `inet.ipsec_seq` | `uint` |

## Shared keys

- `inet.ipsec_spi` and `inet.ipsec_seq`, with `esp-header` (its pack.md).

## Not mapped, and why

- `inet.ip_protocol` is not bound. That key is the protocol after the IP
  header, which for an AH packet is 51 (RFC 4302 section 2); the next header
  field names the payload after AH, so it is `inet.ah_next_header`, from the
  same IANA registry.

- The ICV: its length is `(payload length + 2) × 4 - 12` octets, a count the
  header gives only through that sum; a `bits` group counts items by a field's
  value. Candidate for the language: a count with an offset.
- The payload.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: a header before
TCP with a 12-octet ICV, the largest values, and 11 octets (`malformed-wire`).
