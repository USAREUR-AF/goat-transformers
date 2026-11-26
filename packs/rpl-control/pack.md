# Pack: rpl-control

An RPL control message (RFC 6550 section 6): ICMPv6 type 155, the base object by code, and the
options. The message is the ICMPv6 message (from its type to the end). Wire `bits`, `layout
sequential`, most significant bit first. No kind: a `switch` on the type (155 only; any other type is
`no-kind`) and on the code chooses the layout. Input and output are hex. Written by
`tools/gen/mesh-pack.py`.

## What is mapped

The ICMPv6 type, code and checksum, then by code:

| Code | Base object |
|---|---|
| 0x00 DIS | flags, reserved |
| 0x01 DIO | RPLInstanceID, version, rank, G, the zero bit, MOP, preference, DTSN, flags, reserved, DODAGID |
| 0x02 DAO | RPLInstanceID, K, D, flags, reserved, DAO sequence, the DODAGID when D is 1 |
| 0x03 DAO-ACK | RPLInstanceID, D, reserved, DAO sequence, status, the DODAGID when D is 1 |
| any other (the secured forms 0x80-0x83, and 0x8A consistency check, which section 6.6 says is always sent secured) | the rest as octets |

Then the options to the end: the option type, and for any type but Pad1 (0, a single octet) the data
in the extent of the option length. Laid out: route information (3), DODAG configuration (4), RPL
target (5), transit information (6), solicited information (7), prefix information (8), target
descriptor (9); PadN (1), the DAG metric container (2) and other types as octets. Addresses that are
always 16 octets (DODAGID, prefix information) are `hex`; prefixes of a variable size (route
information, RPL target) and the optional parent address are octets.

## Shared keys

None of `core` or `track`. The ICMPv6 type, code and checksum are the `inet` keys of
`icmpv6-header` (same fields, same positions). The two do not convert in practice: `icmpv6-header`
has no kind for type 155, and its `other` kind requires `inet.icmpv6_rest`, which this pack does not
fill (the 32 bits after the checksum belong to different fields by code).

## Not mapped

- **Secured messages** (codes 0x80-0x83, RFC 6550 section 6.1): the security section's size depends
  on its own algorithm and key identifier mode fields, and the body after it is the unsecured layout;
  the whole is octets.
- **The DAG metric container** (RFC 6551) objects are octets.
- The checksum is carried, not computed (it covers an IPv6 pseudo-header).

## Vectors

`tools/gen/mesh-vectors.py`, without an engine: DIS; DIO with DODAG configuration and prefix information;
DAO with target and transit information; DAO-ACK with the DODAGID; Pad1, PadN and an unassigned option;
a consistency check as octets; a secure DIS as octets; DIS with solicited and route information; an echo request
(`no-kind`); a cut DIO (`malformed-wire`).
