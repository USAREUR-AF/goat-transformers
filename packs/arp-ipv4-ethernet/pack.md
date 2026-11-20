# Pack: arp-ipv4-ethernet

An ARP packet that resolves an IPv4 address to an Ethernet address, as IETF
RFC 826 lays it out, with 6-octet hardware and 4-octet protocol addresses: 28
octets. Public. Written by hand from the RFC; the layout is stated in this
repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the payload of an Ethernet frame of type ARP. The pack reads
octets 0-27; padding after them is read over and not written (vector 04).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0-1 | hardware type | common `when` 1 (Ethernet) | |
| 2-3 | protocol type | common `when` 0x0800 (IPv4) | |
| 4 | hardware address length | common `when` 6 | |
| 5 | protocol address length | common `when` 4 | |
| 6-7 | opcode | the `when` of the kinds | |
| 8-13 | sender hardware address | `inet.arp_sender_hw_addr` | `uint`, 48 bits |
| 14-17 | sender protocol address | `inet.arp_sender_ip_addr` | `uint`, 32 bits |
| 18-23 | target hardware address | `inet.arp_target_hw_addr` | `uint`, 48 bits |
| 24-27 | target protocol address | `inet.arp_target_ip_addr` | `uint`, 32 bits |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. An Ethernet address
is the 48-bit integer of its six octets in wire order; an IPv4 address the
32-bit integer.

The values of the common `when` lines: RFC 826 gives the Ethernet hardware type
as 1 and has the protocol type take its value from the Ethernet type field;
RFC 894 gives 0x0800 as the Ethernet type of IPv4. A packet with another type
or other lengths is `no-kind` (vector 06): its addresses do not have these
widths.

## Kinds

| Kind | `when` |
|---|---|
| `request` | opcode 1 |
| `reply` | opcode 2 |

RFC 826 defines these two opcodes; another opcode is `no-kind` (vector 05). On
encode from another format, a request is written.

## Shared keys

None. `inet.ipv4_src_addr` and `inet.ipv4_dst_addr` are the addresses of an IP
header, not the sender and target of an ARP packet.

## Not mapped, and why

- Hardware and protocol types other than Ethernet and IPv4: the address widths
  follow the length octets, which a fixed layout cannot follow.
- The Ethernet frame around the packet.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there (addresses from
RFC 5737 and RFC 7042 documentation ranges): a request, its reply, a reply with
all-ones addresses, the request with 18 octets of Ethernet padding, opcode 3
and hardware type 6 (`no-kind`), and 27 octets (`malformed-wire`).
