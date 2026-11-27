# Pack: srt-packet

An SRT packet (draft-sharabayko-srt-01, the published description of Haivision's Secure Reliable
Transport): data packets and control packets with the handshake. Wire `bits`, `layout sequential`,
most significant bit first. Two kinds by the first bit: `data` (0) and `control` (1). Input and
output are hex; one message is one UDP payload. Written by `tools/gen/media-pack.py`.

## What is mapped

**`data`**: packet sequence number, the position PP, the in-order flag O, the key flags KK, the
retransmission flag R, the message number, the timestamp, the destination socket ID, the payload as
octets.

**`control`**: control type, subtype, type-specific information, timestamp, destination socket ID,
and the control information field by type:

| Type | Read as |
|---|---|
| 0 handshake | version, encryption, extension field, initial sequence number, MTU, flow window, handshake type, SRT socket ID, SYN cookie, peer IP (128 bits, `hex`), then the extensions: type and length; HSREQ and HSRSP laid out (SRT version, flags, receiver and sender latency); the others' content as hex |
| 2 ACK, 3 NAK | the field as 32-bit words |
| 7 drop request | first and last sequence number |
| 6 ACKACK | nothing |
| any other (keep-alive, congestion warning, shutdown, peer error, user-defined) | the field as octets |

## Shared keys

None. The timestamp counts microseconds from the socket's creation, not a date.

## Not mapped

- **Handshake extension contents** other than HSREQ and HSRSP (key material, stream ID, congestion
  control, packet filter, group) are octets, `srt.ext_octets`: the extension length counts 4-octet
  units and is read as a count that sizes them (engine-spec 0.83, `length @ext_units units 32`), up
  to the 512-byte stream ID of section 3.2.1.3 and beyond (vector 11). That count is not a key, so
  `srt.ext_length` is present only for HSREQ and HSRSP; `srt.ext_content` (hex, at most 63 units)
  is withdrawn. On encode the content must be a whole number of 4-octet units.
- The ACK words are not named: a light ACK has one word, a small ACK four, a full ACK seven, and the
  message gives no count for the optional ones.
- The payload of an encrypted data packet is ciphertext.

## Vectors

`tools/gen/media-vectors.py`, without an engine: data; an induction handshake; a conclusion
handshake with HSREQ and a stream ID; ACK; NAK; ACKACK; drop request; keep-alive; a cut handshake
(`malformed-wire`).

## Kind on encode from another format

Each kind requires the header fields it always has.
An entity that fits no kind is `no-kind`.
