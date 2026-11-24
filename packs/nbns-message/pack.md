# Pack: nbns-message

A NetBIOS Name Service packet (RFC 1002 section 4.2), as sent over UDP port 137. Wire `bits`, `layout
sequential`, `bit_order msb`. No kinds. One message is one packet (over TCP, without the 16-bit length
before it). Written by `tools/gen/dirnaming-pack.py`.

## What is mapped

- **Header**: transaction ID, R, opcode, AA, TC, RD, RA, the two reserved bits, B, rcode; the four counts
  are written from the lists.
- **Question entries**: name, type (NB, NBSTAT), class.
- **Answer, authority and additional records**: name, type, class, TTL, and in the RDLENGTH block the data
  by type: NB (each entry's G, owner node type, reserved bits, address), NBSTAT (the node name array of
  16-octet names with their flags, then the statistics), A (an address), NS (a name); any other type, NULL
  included (the WACK data), as octets.
- **Names** (section 4.1): up to four labels, then the end or a pointer. The first label is the NetBIOS
  name in its first-level encoding (32 letters); the next are the scope. A compression pointer (high bits
  11) is kept as its 14-bit offset; the reserved patterns 01 and 10 are `no-kind`.

## Shared keys

RFC 1002 section 4.2.1 says the Name Service packets follow the DNS packet structure and stay compatible
with it; its header descriptions of the transaction ID and of the R, AA, TC, RD and RA bits have the
meaning RFC 1035 gives ID, QR, AA, TC, RD and RA, at the same places. They are bound to `inet.dns_id`,
`inet.dns_qr`, `inet.dns_aa`, `inet.dns_tc`, `inet.dns_rd` and `inet.dns_ra` (vector 08 converts to
`dns-header`). The opcode (other values: 5 registration, 6 release, 7 WACK, 8 refresh) and rcode (two
codes more) have their own value sets and are `nbns` keys; B replaces a reserved DNS bit.

## Not mapped

- **The NetBIOS name itself**: the first label is the encoded text; turning the 32 letters into the 16
  octets needs a two-characters-to-one-octet transform the pack language does not have.
- **Names of more than four labels**: a fifth label is `no-kind`.
- **Pointers followed**: a pointer is its offset.
- **Statistics of another length**: the 46 octets of section 4.2.18 are read by field; fewer
  re-encode with zeros up to 46 (ruling 7 of 0.8), and octets beyond are
  skipped.
- **The TCP length prefix** and the Session Service (section 4.3).

## Message convention

`input` and `expect` are lowercase hexadecimal text of one packet.

## Vectors

`tools/gen/dirnaming-vectors.py`, without an engine: a broadcast name query; a positive query response
with two NB entries; a registration whose additional record names the question by a pointer; a node
status response; a redirect response with NS and A records; a WACK; a name with a three-label scope; a
conversion to `dns-header`; a cut record (`malformed-wire`); a reserved label tag (`no-kind`).
