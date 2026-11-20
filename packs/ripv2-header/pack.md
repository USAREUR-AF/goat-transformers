# Pack: ripv2-header

The header of a RIP message, as IETF RFC 2453 section 3.6 lays it out: the 4
octets before the route entries. Public. Written by hand from the RFC; the
layout is stated in this repository's words. I/O is hex text. Needs engine
version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of a RIP message (port 520). The pack reads octets
0-3; the route entries are read over and not written (vector 01).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | command | `inet.rip_command` | `uint` |
| 1 | version | `inet.rip_version` | `uint` |
| 2-3 | unused, zero | `inet.rip_zero` | `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The unused field is
a key so that the message is 4 octets long (a fixed layout ends at its last
mapped bit).

## Shared keys

None.

## Not mapped, and why

- The route entries, 1 to 25 of 20 octets each. Their number is not on the
  wire: the entries run to the end of the datagram. A `bits` group needs a
  count (engine-spec 0.7), so the list cannot be stated. Candidate for the
  language: a group whose items run to the end of the message. The first
  entry alone could be mapped, with gate blocks (0.17) for the authentication
  entry (family 0xFFFF); it is left out as a partial list.

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there: a version 2
whole-table request with its entry, a version 1 response header, the largest
values, and 3 octets (`malformed-wire`).
