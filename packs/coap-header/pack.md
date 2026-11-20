# Pack: coap-header

The CoAP message header, as IETF RFC 7252 section 3 lays it out: the 4-octet
fixed header and the token after it. Public. Written by hand from the RFC; the
layout is stated in this repository's words. I/O is hex text. Needs engine
version 0.7 (a counted `bits` group).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of a CoAP message. The pack reads the fixed header
and the token; options and the payload are read over and not written (vector
01).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-1 | version | `inet.coap_version` | `uint` |
| 0, bits 2-3 | type | `inet.coap_type` | `uint` |
| 0, bits 4-7 | token length | `inet.coap_token_length` | `uint`; also the count of the token |
| 1, bits 0-2 | code class | `inet.coap_code_class` | `uint` |
| 1, bits 3-7 | code detail | `inet.coap_code_detail` | `uint` |
| 2-3 | message ID | `inet.coap_message_id` | `uint` |
| 4 on | token | list `inet.coap_token`, item key `inet.coap_token_octet` | `group … 0:32 item 8 count 0:4:4`, `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The code is two
keys, class and detail, as RFC 7252 writes it (`c.dd`). The token is a list of
octets: up to 8 octets is up to 64 bits, which a signed 64-bit integer key
cannot hold in full.

The token length is both a field and the count of the token (ruling 2 of
0.7). Decode reads as many octets as it says; a message cut inside the token
is `malformed-wire` (vector 05). Encode writes the length from the number of
items. RFC 7252 makes a token length of 9 to 15 a format error; the pack does
not check it and reads that many octets.

## Shared keys

None.

## Not mapped, and why

- Options: each begins with a 4-bit delta from the previous option number and
  a 4-bit length, either of which may be extended by one or two octets; the
  option number is the running sum of the deltas. No transform or group of the
  pack language states a running sum.
- The payload marker (0xFF) and the payload.

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there: a confirmable
GET with a 4-octet token and an option and payload after it, a piggybacked
2.05 response, a reset with an 8-octet token at the largest values, an empty
message, a message cut inside its token and 3 octets (both `malformed-wire`).
