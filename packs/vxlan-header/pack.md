# Pack: vxlan-header

The VXLAN header, as IETF RFC 7348 section 5 lays it out: the 8 octets after the
outer UDP header. Public. Written by hand from the RFC; the layout is stated in
this repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of a VXLAN packet. The pack reads octets 0-7; the
inner Ethernet frame is read over and not written (vector 06).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bit 4 | I flag, VNI valid | `inet.vxlan_i_flag` | `uint` |
| 0, other bits | reserved flags | not mapped | |
| 1-3 | reserved | `inet.vxlan_reserved1` | `uint` |
| 4-6 | VNI | `inet.vxlan_vni` | `uint` |
| 7 | reserved | `inet.vxlan_reserved2` | `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian.

RFC 7348 has senders write the reserved bits 0 and receivers ignore them. The
seven reserved flag bits are not mapped: decode ignores them and encode writes
0 (vector 04). The reserved octets 1-3 and 7 are fields so that the message is
8 octets long (a fixed layout ends at its last mapped bit); they come back as
read (vector 05). The pack does not check the I flag (vector 03).

## Shared keys

None.

## Not mapped, and why

- The seven reserved flag bits: see above.
- The inner Ethernet frame and the outer headers.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: a valid VNI,
the largest VNI, eight zero octets, the reserved flag bits set (written 0), the
reserved octets set (carried), a header followed by an inner frame, and 7
octets (`malformed-wire`).
