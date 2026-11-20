# Pack: quic-invariant

The parts of a QUIC packet header that every version keeps, as IETF RFC 8999
section 5 lays them out: the long header up to the end of the source
connection ID, and the first octet of a short header. Public. Written by hand
from the RFC; the layout is stated in this repository's words. I/O is hex text.
Needs engine version 0.8 (sequential layout, counted groups).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is a QUIC packet, the UDP payload or the first packet of it. The pack
reads the invariant fields; the version-specific rest is read over and not
written (vector 01).

| Bits | Field | Key | Line |
|---|---|---|---|
| 0 | header form | the kind | `when 1 1` (long) / `when 1 0` (short) |
| 1-7 | version-specific bits | `inet.quic_version_specific` | `field … 7 uint` |
| long: next 32 | version | `inet.quic_version` | `field … 32 uint` |
| long: next 8, then that many octets | destination connection ID | list `inet.quic_dcid`, item key `inet.quic_cid_octet` | `group … count 8` |
| long: next 8, then that many octets | source connection ID | list `inet.quic_scid` | `group … count 8` |

`layout sequential`, `bit_order msb`. Each connection ID is a group whose count
is the length octet before it (0.8), so the source ID follows the destination
ID wherever it ends. A connection ID is opaque: a list of octets, up to 255
(vector 03).

## Kinds

| Kind | `when` | Requires |
|---|---|---|
| `long-header` | bit 0 = 1 | `inet.quic_version` |
| `short-header` | bit 0 = 0 | none |

Version 0 marks a version negotiation packet; it is kind `long-header` with
version 0 (vector 02).

## Shared keys

None.

## Not mapped, and why

- The short header's destination connection ID: its length is not in the
  packet (RFC 8999 section 5.2), only the endpoint knows it.
- The version-specific rest: packet number, payload, the length fields of a
  version, which QUIC version 1 writes as variable-length integers.
- The list of supported versions in a version negotiation packet: it runs to
  the end of the datagram; a group needs a count.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: a version 1 long
header with an 8- and a 4-octet connection ID, a version negotiation packet
with an empty destination ID, a long header at its largest values (a 255-octet
source ID), a short header, and a long header cut inside its destination ID
(`malformed-wire`).
