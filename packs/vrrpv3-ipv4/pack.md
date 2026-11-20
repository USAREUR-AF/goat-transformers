# Pack: vrrpv3-ipv4

A VRRPv3 advertisement for IPv4, as IETF RFC 9568 section 5 lays it out: the
8-octet fixed part and the counted list of IPv4 addresses. Public. Written by
hand from the RFC; the layout is stated in this repository's words. I/O is hex
text. Needs engine version 0.7 (a counted `bits` group).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the IP payload of a VRRP packet (protocol or next header 112). The
address family is that of the IP header, not on the VRRP wire: this pack reads
IPv4 addresses, and `vrrpv3-ipv6` the other family.

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-3 | version | `inet.vrrp_version` | `uint` |
| 0, bits 4-7 | type | `inet.vrrp_type` | `uint` |
| 1 | virtual router ID | `inet.vrrp_vrid` | `uint` |
| 2 | priority | `inet.vrrp_priority` | `uint` |
| 3 | address count | `inet.vrrp_addr_count` | `uint`; also the count of the list |
| 4, bits 0-3 | reserved | `inet.vrrp_reserved` | `uint` |
| 4 bits 4-7 and 5 | maximum advertisement interval | `inet.vrrp_max_adver_int` | `uint`, centiseconds |
| 6-7 | checksum | `inet.vrrp_checksum` | `uint` |
| 8 on | addresses | list `inet.vrrp_ipv4_addrs` | `item 32 count 0:24:8`; item keys `inet.vrrp_ipv4_addr`, the 32-bit integer |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The address count
is both a field and the count of the list (ruling 2 of 0.7): decode reads as
many addresses as it says, and a message cut inside them is `malformed-wire`;
encode writes the count from the number of items. The checksum is carried, not
computed or checked. The pack does not check the version or type, and reads a
count of 0, which RFC 9568 has a receiver ignore.

## Shared keys

None. The fixed-part keys are the same in both VRRPv3 packs.

## Not mapped, and why

Nothing in the VRRP message: the fixed part and the address list are the whole
advertisement.

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there.
An advertisement with two addresses, the address owner at the largest values,
priority 0 with no address, and one cut inside its addresses
(`malformed-wire`). Checksums computed there.
