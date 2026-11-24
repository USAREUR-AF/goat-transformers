# Pack: icmpv6-nd

The ICMPv6 Neighbor Discovery messages (RFC 4861): Router Solicitation (133), Router Advertisement (134),
Neighbor Solicitation (135), Neighbor Advertisement (136) and Redirect (137), with their options. Wire
`bits`, `layout sequential`. No kind: a `switch` on the type chooses the body; another type is `no-kind`.
One message is the ICMPv6 message. Written by `tools/gen/inet-more-pack.py`.

`icmpv6-header` (on main) reads RS and RA without options and has no NS, NA or Redirect.

## What is mapped

- Type, code and checksum, the RS reserved field and the RA fields on the `inet` keys of `icmpv6-header`;
  NS (target), NA (R, S, O, target), Redirect (target, destination).
- **Options** to the end: type, length (in 8-octet units), and the body by type and length: source and
  target link-layer address (hex; 6 octets for length 1); prefix information (length, L, A, R, lifetimes,
  prefix); redirected header (the packet's start as hex); MTU; RDNSS (lifetime, the addresses as hex);
  DNSSL (lifetime, the names as hex); other types as hex.

## Shared keys

None of `core` or `track`. Type, code, checksum, the RS reserved field and the RA fields are the `inet`
keys of `icmpv6-header`.

## Not mapped

- **Option bodies by their length**: an option's length counts 8-octet units, which a `length` block does
  not count, so the body's size is chosen by a `switch` on the length (up to 32 units, 256 octets); RDNSS
  addresses and DNSSL names are therefore one hex field each. Needed: a length in n-octet units.
- **The prefix information bit after A** is its own key (`icmpnd.router_address`), named beyond what the source
  states: RFC 4861 has a 6-bit reserved field there.
- The checksum is carried, not computed (it covers an IPv6 pseudo-header).

## Vectors

`tools/gen/inet-more-vectors.py`, without an engine: RS; RA with prefix, MTU, link-layer address and RDNSS;
NS; NA; Redirect; a nonce option as hex; a cut option (`malformed-wire`).
