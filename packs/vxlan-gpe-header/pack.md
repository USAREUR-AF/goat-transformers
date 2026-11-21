# Pack: vxlan-gpe-header

The VXLAN-GPE header (draft-ietf-nvo3-vxlan-gpe-13 section 3.1; the source is an expired Internet-Draft, not an RFC): the 8 octets after the outer UDP
header (port 4790). Wire `bits`, `layout sequential`, most significant bit first. No kind. Input and
output are hex. Written by `tools/gen/tunnels-pack.py`.

The draft expired in May 2024 without becoming an RFC; it is the published description that
implementations (Linux, Open vSwitch) follow, and its next protocol values are the IANA LISP-GPE
registry of RFC 9305.

## What is mapped

The two reserved flag bits, the version, the I bit, the P bit (next protocol present), the B bit
(ingress-replicated BUM traffic), the O bit (OAM), the 16 reserved bits, the next protocol, the VNI
and the last reserved octet.

## Shared keys

None of `core` or `track`. Three `inet` keys of `vxlan-header`: `inet.vxlan_i_flag` (the draft puts
the I bit where RFC 7348 does, bit 4, with the same meaning: the VNI is valid), `inet.vxlan_vni` (the
same 24-bit identifier) and `inet.vxlan_reserved2` (the reserved octet after the VNI in both). The
24 reserved bits of VXLAN are not the GPE layout (GPE uses the last 8 for the next protocol), so
GPE's 16 reserved bits and its flags are keys of `vxlangpe`. A VXLAN header converted to GPE has
P = 0 and next protocol 0; a GPE header converted to VXLAN loses the next protocol and the flags.

## Not mapped

- The inner packet after the header (Ethernet, IPv4, IPv6, NSH or MPLS by the next protocol).

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: next protocol IPv4; B and O set with NSH; GPE to
`vxlan-header`; `vxlan-header` to GPE (`packs/vxlan-header/vectors/to-vxlan-gpe-header-i-flag-and-vni.json`); a header of 7 octets
(`malformed-wire`).
