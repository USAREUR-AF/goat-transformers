# Pack: stun

A STUN message (RFC 8489) with the attributes of STUN and TURN (RFC 8656), and the TURN
ChannelData message (RFC 8656 section 12.4). Wire `bits`, `layout sequential`, most significant bit
first. Two kinds, chosen by the first two bits: `message` (00) and `channel_data` (01). Input and
output are hex. Written by `tools/gen/messaging-pack.py`.

## What is mapped

**`message`**: the 14-bit message type as one integer (the method and class interleaved, as the
RFC numbers them: 0x0001 Binding request, 0x0101 its success response, 0x0111 its error response),
the message length (a `length 16 bytes plus -16` block: the length counts the attributes, not the
20-octet header), the magic cookie, the 96-bit transaction ID (`hex`), and each attribute: type,
length, value by type, padding to a multiple of 4 octets (`align 32`).

| Attribute | Read as |
|---|---|
| MAPPED-ADDRESS, ALTERNATE-SERVER, XOR-MAPPED-ADDRESS, XOR-PEER-ADDRESS, XOR-RELAYED-ADDRESS | family, port, IPv4 address (integer) or IPv6 address (`hex`); the XOR attributes as on the wire |
| ERROR-CODE | class, number, the reason phrase as octets |
| ADDRESS-ERROR-CODE | family, class, number, reason phrase |
| MESSAGE-INTEGRITY | the 20-octet HMAC (`hex`) |
| FINGERPRINT | the CRC value |
| UNKNOWN-ATTRIBUTES | the list of types |
| CHANNEL-NUMBER, LIFETIME, REQUESTED-ADDRESS-FAMILY, ADDITIONAL-ADDRESS-FAMILY, EVEN-PORT, REQUESTED-TRANSPORT, DONT-FRAGMENT, RESERVATION-TOKEN, ICMP | their fields |
| USERNAME, REALM, NONCE, SOFTWARE, DATA, MESSAGE-INTEGRITY-SHA256, USERHASH, PASSWORD-ALGORITHM(S), ALTERNATE-DOMAIN and any other | the value as octets |

**`channel_data`**: the channel number's 14 low bits (the two high bits, 01, are the kind's
`when`), the length, the data as octets.

## The XOR-encoded addresses

XOR-MAPPED-ADDRESS and the TURN XOR addresses carry the port XORed with the high 16 bits of the
magic cookie and the address XORed with the cookie (IPv4) or with the cookie and the transaction ID
(IPv6). The pack language has no transform that XORs a field with a constant or with another
field, so the pack keeps the values as they are on the wire, in the same keys as MAPPED-ADDRESS;
a consumer must XOR them itself. Needed: an `xor:<constant>` transform (enough for the IPv4 address
and the port).

## Shared keys

None.

## Not mapped

- String attribute values (USERNAME, REALM, NONCE, SOFTWARE, reason phrases) as octets.
- The ICMP attribute's figure in RFC 8656 draws the reserved field and the type and code with
  uneven widths; the pack reads 16 reserved bits, an 8-bit type and an 8-bit code, as the prose
  and the ICMP header give them.
- The padding of a ChannelData message over TCP is not read or written.
- MESSAGE-INTEGRITY and FINGERPRINT are carried, not computed or checked.

## Vectors

`tools/gen/messaging-vectors.py`, without an engine: Binding request, Binding success (with a
FINGERPRINT the program computes), Binding error 401, Allocate request and success, ChannelBind,
Data indication with the TURN attributes, ChannelData, and a truncated message (`malformed-wire`).
