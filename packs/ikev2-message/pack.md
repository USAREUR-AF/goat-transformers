# Pack: ikev2-message

An IKEv2 message (RFC 7296 sections 3.1 and 3.2): the IKE header and the chain of payloads, each read
as its generic header and its body octets. The message is one UDP payload on port 500; on port 4500
the four zero octets before it are not part of it. Wire `bits`, `layout sequential`, most significant
bit first. No kind. Input and output are hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The header: initiator's and responder's SPIs (hex), the type of the first payload, major and minor
version, exchange type, the flags (two reserved bits, R, V, I, three reserved bits), the message ID,
and the length of the whole message (`length 32 whole`: written on encode). Then the payloads to the
end of the message: next payload type, critical bit, seven reserved bits, and the body as octets in
the extent of the payload length (which counts the 4-octet generic header).

The bodies are laid out by the payload packs `ikev2-sa`, `ikev2-ke`, `ikev2-id`, `ikev2-cert`,
`ikev2-auth`, `ikev2-notify`, `ikev2-delete`, `ikev2-ts`, `ikev2-cp` and `ikev2-eap`, each of whose
messages is one payload with its generic header.

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- **The bodies, in this pack.** A payload's type is not in the payload: it is in the header of the
  payload before it (or, for the first, in the IKE header). A `switch` in a list item can only test
  a field of the same item, so the chain cannot choose each body's layout. Needed: a switch on a
  value of the previous item (or a value carried from item to item).
- **Nonce, Vendor ID and Encrypted payloads** have no pack of their own: their bodies are octets (the
  Encrypted payload's IV, ciphertext and integrity checksum, whose sizes the negotiated algorithms
  give).
- The four zero octets of port 4500 (the non-ESP marker) are not part of the message.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: an IKE_SA_INIT request (SA, KE, Nonce); an
INFORMATIONAL response with an Encrypted payload; a critical payload of an unassigned type; a header
with no payloads; a length longer than the input and a payload cut by the message end
(`malformed-wire`).
