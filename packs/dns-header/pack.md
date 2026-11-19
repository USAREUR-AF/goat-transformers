# Pack: dns-header

The 12-octet header of a DNS message, IETF RFC 1035 section 4.1.1. Public.
Written by hand from the RFC; the layout is stated in this repository's words.
I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is a DNS message as sent over UDP, from its first octet (over TCP,
after the two-octet length that RFC 1035 section 4.2.2 puts before it). The pack
reads octets 0-11; the question, answer, authority and additional sections are
read over and not written (vector 01).

| Bits | Field | Key |
|---|---|---|
| 0-15 | ID | `inet.dns_id` |
| 16 | QR | `inet.dns_qr` |
| 17-20 | opcode | `inet.dns_opcode` |
| 21, 22, 23, 24 | AA, TC, RD, RA | `inet.dns_aa`, `inet.dns_tc`, `inet.dns_rd`, `inet.dns_ra` |
| 25-27 | Z | `inet.dns_z` |
| 28-31 | response code | `inet.dns_rcode` |
| 32-95 | the four section counts | `inet.dns_qdcount`, `inet.dns_ancount`, `inet.dns_nscount`, `inet.dns_arcount` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian.

## Shared keys

None. No field is bound to `core` or `track`.

## Not mapped, and why

- The four sections. A domain name is a chain of length-prefixed labels with
  compression pointers into earlier octets of the message, and the number of
  records comes from the counts; the pack language reads neither.
- The later meaning of two Z bits (AD and CD, RFC 4035) and the response codes
  above 5: the pack follows RFC 1035 and holds the bits and the code as numbers.

## Vectors

`tools/gen/ietf-headers-vectors.py`, from values chosen there: a query with its
question section, a name-error response, every field at its largest value, and
11 octets (`malformed-wire`).
