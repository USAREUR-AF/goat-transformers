# Pack: llmnr-header

The 12-octet LLMNR header (RFC 4795 section 2.1.1). Wire `bits`, fixed layout, one word per octet. The
rest of an LLMNR message (question and records) has the DNS format and is read by `dns-message`; LLMNR
differs from DNS only in the header bits, so no separate full-message pack is written. Written by
`tools/gen/dirnaming-pack.py`.

## What is mapped

ID, QR, opcode, C (conflict), TC, T (tentative), the four reserved Z bits, rcode, and the four counts.

## Shared keys

RFC 4795 says LLMNR uses the DNS header of RFC 1035 with the exceptions it lists; ID, QR, opcode, TC,
rcode and the four counts are not among them and keep their DNS meaning and places. They are bound to
`inet.dns_id`, `inet.dns_qr`, `inet.dns_opcode`, `inet.dns_tc`, `inet.dns_rcode` and the four
`inet.dns_*count` keys, as in `dns-header`. C, T and Z sit where DNS has AA, RD, RA and Z but mean
something else, so they are `llmnr` keys: a conversion to `dns-header` writes AA, RD and RA as 0, and one
from `dns-header` drops them (vectors).

## Not mapped

- The sections after the header (use `dns-message` on the whole message).
- A message longer than 12 octets is read as its header; the rest is not kept.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the 12 octets.

## Vectors

`tools/gen/dirnaming-vectors.py`, without an engine: a query; a response with C and T; every bit set; a
conversion to `dns-header`; eleven octets (`malformed-wire`); and, under `dns-header`, a conversion to
this pack.
