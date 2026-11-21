# Pack: diameter

A Diameter base protocol message (RFC 6733): the header and the AVPs. Wire `bits`, `layout
sequential`, most significant bit first, big-endian. One kind, `message`: version 1 is its `when`,
the message length a `length 24 whole` line. Input and output are hex. Written by
`tools/gen/telecom-pack.py`.

## What is mapped

The header: the command flags R, P, E and T and four reserved bits, the command code, the
application ID, and the hop-by-hop and end-to-end identifiers.

Each AVP is an item of `diameter.avps`: its code, the flags V, M and P and five reserved bits, its
length (a `length 24 bytes plus 8` block: the length counts the 8-octet header and the vendor ID,
not the padding), the vendor ID when V is 1, the data, then padding to a multiple of 4 octets
(`align 32`). The data of a base protocol AVP (vendor ID absent) is laid out by its type in RFC 6733
section 4.5:

| AVP codes | Type | Read as |
|---|---|---|
| 27, 85, 258, 259, 261, 262, 265-268, 270-274, 276-278, 285, 291, 295, 298, 299, 480, 483, 485 | Unsigned32, Enumerated | `diameter.unsigned32` |
| 287 | Unsigned64 | `diameter.unsigned64` |
| 55 | Time | `diameter.time` (NTP seconds) |
| 257 | Address | family, then an IPv4 address (integer) or IPv6 address (`hex`) |
| 260, 279, 284, 297 | Grouped | the AVPs inside, one level deep, as items of `diameter.grouped_avps` |
| any other, and every vendor AVP | OctetString, UTF8String, DiameterIdentity, DiameterURI, ... | the data as octets |

## Shared keys

None. Event-Timestamp is the time of an accounting event inside a list of AVPs, not the time of the
message, and the message names no entity a shared key holds.

## Not mapped

- **Strings and identities** are their octets: the `bits` wire has no text transform whose length a
  field gives.
- **Vendor AVPs** (V = 1) and the AVPs of Diameter applications (Credit-Control, S6a and others) are
  octets: their codes depend on the vendor and application dictionaries.
- **Grouped AVPs** are laid out one level deep; a Grouped AVP inside one (for example an
  Experimental-Result inside a Failed-AVP) keeps its data as octets. The pack language has no
  recursion.

## Vectors

`tools/gen/telecom-vectors.py`, without an engine: Capabilities-Exchange request and answer, a
Device-Watchdog request with a vendor AVP, an Accounting answer with a Failed-AVP two levels deep,
version 2 (`no-kind`) and a truncated message (`malformed-wire`).
