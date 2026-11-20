# Pack: ethernet-ii

The Ethernet II frame header, as IETF RFC 894, RFC 7042 section 3 and the
outer header of RFC 7348 section 5 lay it out: destination and source MAC
addresses and the EtherType, with or without one 802.1Q C-tag. Public. Written
by hand from the RFCs; the layout is stated in this repository's words. I/O is
hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is an Ethernet frame from its destination address, without preamble
and start delimiter. The pack reads the header (14 octets, 18 with a C-tag);
the payload, padding and FCS are read over and not written (vector 01).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0-5 | destination address | `inet.eth_dst_addr` | `uint`, the 48-bit integer |
| 6-11 | source address | `inet.eth_src_addr` | `uint` |
| 12-13 | EtherType, or 0x8100 for a C-tag | `inet.eth_type`, or the `when` of kind `c-tagged` | `uint` |
| 14-15 (C-tag) | VLAN tag information | `inet.vlan_tag_info` | `uint`, one 16-bit integer |
| 14-15 (C-tag), the same bits | priority (3 bits), C bit (1), VLAN ID (12), RFC 6325 section 4.1.1 Figure 8 | `inet.vlan_pcp`, `inet.vlan_dei`, `inet.vlan_vid` | `uint` each |
| 16-17 (C-tag) | inner EtherType | `inet.eth_type` | `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. RFC 7042 gives
EtherTypes as values of 0x0600 and above; a smaller value is an IEEE 802.3
length, which the pack carries in the same key (vector 04).

## Kinds

| Kind | `when` | Requires |
|---|---|---|
| `c-tagged` | octets 12-13 = 0x8100 | `inet.vlan_tag_info` |
| `untagged` | none | none |

An S-tag (0x88A8) or a second tag is read as kind `untagged` with that
EtherType.

## Shared keys

None. The EtherType has the meaning of `inet.gre_protocol_type` and
`inet.geneve_protocol_type`, but those keys belong to their headers.

## Not mapped, and why

- S-tags (802.1ad) and stacked tags; IEEE 802.3 LLC/SNAP after a length.
- The payload, padding and the FCS.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there (addresses from
RFC 7042's documentation block): an untagged IPv4 frame with payload, a
C-tagged IPv6 frame, a C-tagged frame at its largest values, an 802.3 length,
a C-tagged header cut short and 13 octets (both `malformed-wire`).
Vectors 07 and 08 check the split of the tag information (priority 5, VLAN ID
100; and every bit set) against `inet.vlan_tag_info`.

The tag information is mapped twice: as one 16-bit key, and split into
priority, the C bit (IEEE 802.1Q's later editions call it the drop eligible
indicator) and the VLAN ID, as RFC 6325 section 4.1.1 draws it. Both are
decoded. On encode the whole-word line comes first and wins where both are
present; an entity with only the split keys selects kind `c-tagged` only if
it also has `inet.vlan_tag_info` (the kind's `requires`, unchanged).
