# Pack: dhcpv6-message

A DHCPv6 message (RFC 9915, which obsoletes RFC 8415): the message type, the transaction ID (or for
RELAY-FORW and RELAY-REPL the hop count and link and peer addresses), and the options, with the options of
IAs and of their addresses and prefixes nested. Wire `bits`, `layout sequential`. No kind. One message is
one UDP payload. Written by `tools/gen/inet-more-pack.py`.

`dhcpv6-options` (on main) reads an options area as a TLV wire, each option as hex; this pack reads the
whole message and lays out the common options.

## What is mapped

- **Header**: message type; transaction ID, or hop count, link address and peer address for relay
  messages.
- **Options** (code, then the body in the extent of the length): client and server ID (the DUID by type:
  link-layer plus time, enterprise number, link-layer, UUID); IA_NA and IA_PD (IAID, T1, T2, options);
  IA_TA (IAID, options); ORO (the requested codes); preference; elapsed time; status code (code,
  message octets); rapid commit; DNS servers; information refresh time, SOL_MAX_RT and INF_MAX_RT; other
  codes as octets.
- **IA options**: IA address (address, lifetimes, options), IA prefix (lifetimes, length, prefix,
  options), status code; their own options: status code; others as octets.

## Shared keys

None.

## Not mapped

- **The relayed message** (option 9) is octets: an option holding a whole message would need the layout
  to recur. Run the pack again on the octets.
- **Deeper nesting** than an IA address's or prefix's options, and the options whose bodies are DNS names
  (domain list, FQDN) or vendor-defined (vendor options, authentication): octets.

## Vectors

`tools/gen/inet-more-vectors.py`, without an engine: a SOLICIT; a REPLY with an IA address and its status;
an IA_PD prefix; a RELAY-FORW; a DUID-UUID and an option kept as octets; a cut option (`malformed-wire`).
