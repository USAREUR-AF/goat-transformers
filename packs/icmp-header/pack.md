# Pack: icmp-header

The header of an ICMP message for IPv4, IETF RFC 792: type, code, checksum and
the fixed fields of the type, 8 octets (20 for the timestamp messages). Public.
Written by hand from the RFC; the layouts are stated in this repository's words.
I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the ICMP message, the data of the IP datagram that carries it, from
its first octet. Octets 0-3 are type, code and checksum in every message. What
follows the type's fixed fields (the original IP header and 64 bits of its data
in error messages, the data of an echo) is read over and not written. The
checksum is carried as a value; the pack does not compute or check it.

`word_bytes 1`, `bit_order msb`; the fields are big-endian.

## Kinds

The type octet is the common field `inet.icmp_type` and the `when` of each kind;
`inet.icmp_code` and `inet.icmp_checksum` are common.

| Kind | Type | Octets 4-7 (and on) | Keys |
|---|---|---|---|
| `echo-reply` | 0 | identifier, sequence number | `inet.icmp_identifier`, `inet.icmp_sequence` |
| `destination-unreachable` | 3 | unused | `inet.icmp_unused` |
| `source-quench` | 4 | unused | `inet.icmp_unused` |
| `redirect` | 5 | gateway address | `inet.icmp_gateway_addr` |
| `echo` | 8 | identifier, sequence number | as echo reply |
| `time-exceeded` | 11 | unused | `inet.icmp_unused` |
| `parameter-problem` | 12 | pointer (octet 4), unused (5-7) | `inet.icmp_pointer`, `inet.icmp_unused` |
| `timestamp` | 13 | identifier, sequence; octets 8-19 originate, receive and transmit timestamps | `inet.icmp_identifier`, `inet.icmp_sequence`, `inet.icmp_originate_ms`, `inet.icmp_receive_ms`, `inet.icmp_transmit_ms` |
| `timestamp-reply` | 14 | as timestamp | as timestamp |
| `information-request` | 15 | identifier, sequence number | as echo |
| `information-reply` | 16 | identifier, sequence number | as echo |
| `other` | any other | the 32 bits as one integer | `inet.icmp_rest` |

The unused bits are mapped, so a sender's non-zero value comes back. The kind
`other` has no `when` and stands last, so a type this pack has no kind for still
decodes (vector 12). A timestamp message cut to 8 octets is `malformed-wire`
(vector 13).

## Shared keys

None. No field is bound to `core` or `track`. The ICMP timestamps are
milliseconds since midnight UT with no date, so they are not `time_ms`. RFC 792 lets a sender that
cannot give that time send any time with the high-order bit set; the pack does not test that bit, so
such a value decodes as a number of milliseconds above 2^31, more than a day.

## Not mapped, and why

- The original datagram in error messages, and the data of echo messages.
- Types defined after RFC 792 (router advertisement and solicitation, address
  mask, extended echo) have no kind of their own; they decode as `other`.
- ICMPv6 (RFC 4443) is a different protocol with its own types.

## Vectors

`tools/gen/ietf-headers-vectors.py`, from values chosen there, with checksums
computed by the ones' complement sum: one round trip per kind, the error
messages with an original IPv4 header and data after them, and a timestamp
message cut short (`malformed-wire`).
