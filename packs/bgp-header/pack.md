# Pack: bgp-header

A BGP-4 message, as IETF RFC 4271 section 4 lays it out: the 19-octet header,
the fixed part of OPEN, the first field of UPDATE, the codes of NOTIFICATION,
and KEEPALIVE. Public. Written by hand from the RFC; the layout is stated in
this repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is one BGP message, from its marker. Octets after the mapped part are
read over and not written.

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0-15 | marker, all ones | four common `when` lines of 32 bits | |
| 16-17 | length | `inet.bgp_length` | `uint` |
| 18 | type | the `when` of the kinds | |

| Kind | `when` | Octets 19 on | Keys |
|---|---|---|---|
| `open` | type 1 | 19 version, 20-21 my AS, 22-23 hold time, 24-27 BGP identifier, 28 optional parameters length | `inet.bgp_version`, `inet.bgp_my_as`, `inet.bgp_hold_time`, `inet.bgp_identifier`, `inet.bgp_opt_param_length` |
| `update` | type 2 | 19-20 withdrawn routes length | `inet.bgp_withdrawn_routes_length` |
| `notification` | type 3 | 19 error code, 20 error subcode | `inet.bgp_error_code`, `inet.bgp_error_subcode` |
| `keepalive` | type 4 | none | `inet.bgp_type` (octet 18); `requires inet.bgp_type=4 inet.bgp_length` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The marker is four
`when` lines because RFC 4271 requires it to be all ones; a message with
another marker is `no-kind` (vector 07), and encode writes it. The length is
carried, not computed or checked. A message too short to hold the type octet is
`no-kind`, since a `when` beyond the input does not hold (vector 09).

On encode from another format: OPEN when the entity holds the BGP identifier,
UPDATE when it holds the withdrawn routes length, NOTIFICATION when it holds
the error code, else KEEPALIVE.

## Shared keys

None. The BGP identifier is an IPv4 address by form only; it is not the
address of an IP header.

## Not mapped, and why

- OPEN optional parameters: a list of type, length and value whose total
  length, not count, is on the wire. A `bits` group needs a count of items.
- UPDATE after its first field: withdrawn routes and NLRI are prefixes of
  varying length; the path attribute length comes after the withdrawn routes,
  at a place no fixed locator gives.
- NOTIFICATION data: its form depends on the error code.
- ROUTE-REFRESH (type 5) and the messages of later RFCs: `no-kind` (vector 08).

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there (AS numbers
from RFC 5398): an OPEN, an OPEN with an optional parameter, a KEEPALIVE, a
NOTIFICATION with and without data, an UPDATE with no route, a marker that is
not all ones and type 5 (both `no-kind`), 18 octets (`no-kind`) and an OPEN
cut to 28 octets (`malformed-wire`).
