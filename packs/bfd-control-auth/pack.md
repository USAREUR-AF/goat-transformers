# Pack: bfd-control-auth

A BFD control packet (RFC 5880 section 4): the mandatory section and, when the A bit is set, the
authentication section. Wire `bits`, `layout sequential`, most significant bit first. No kind.
Input and output are hex.

## What is mapped

The mandatory section (section 4.1), field by field, to the same `inet` keys as the fixed
`bfd-control` pack, so the two convert: version, diagnostic, state, the flags P, F, C, A, D and M,
detect multiplier, length, my and your discriminator, and the three intervals in microseconds.
The length is kept as the packet states it (as in `bfd-control`), not computed.

Then a `switch` on the A bit. With A = 1, the authentication section: its type, its length (a
`length 8 bytes plus 2` block: the length counts the type and itself), and by type:

| Auth type | Read as |
|---|---|
| 1 simple password (4.2) | key ID, the password (1 to 16 octets) as octets |
| 2 keyed MD5, 3 meticulous keyed MD5 (4.3) | key ID, reserved octet, sequence number, the 16-octet digest as octets |
| 4 keyed SHA1, 5 meticulous keyed SHA1 (4.4) | key ID, reserved octet, sequence number, the 20-octet hash as octets |
| any other | the section as octets |

## Shared keys

None of `core` or `track`: a BFD packet carries no time, position or entity identity. The
mandatory section uses the `inet` keys of the IETF header packs; the authentication section the
`bfdauth` module.

## Not mapped

- The pack carries the digest or hash; it does not compute or check it.
- The A bit and the section are written as the entity holds them; an entity with A = 1 and no
  section, or the reverse, encodes a packet that does not decode the same.

## Vectors

`tools/gen/routing-vectors.py`, without an engine: no authentication; simple password;
meticulous keyed MD5; keyed SHA1; the SHA1 packet to `bfd-control` (its 24 octets); a packet
whose A bit promises a section that is not there (`malformed-wire`); and, under
`packs/bfd-control/vectors`, a packet from `bfd-control` to this pack.
