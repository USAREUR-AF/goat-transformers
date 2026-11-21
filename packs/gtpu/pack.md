# Pack: gtpu

A GTP-U message (3GPP TS 29.281, ETSI TS 129 281 V19.2.0): the header, its optional fields and
extension headers, and the payload. Wire `bits`, `layout sequential`, most significant bit first,
big-endian. No kind. Input and output are hex; one message is one UDP payload (port 2152).
Written by `tools/gen/gtp-pack.py`.

**Licence.** The specification states no licence; its ETSI and 3GPP editions reserve all rights.
The layout is restated in this project's words, and the pack is labelled `LicenseRef-unstated`
(PROVENANCE.md quotes both notices and the ETSI SR 000 314 pointer to declared essential IPRs).

## What is mapped

The mandatory header: version, protocol type, the spare bit, the flags E, S and PN, the message
type, the length (a `length 16 bytes plus -4` block: the length counts what follows the first 8
octets, and the block also holds the TEID), and the TEID.

When any of E, S and PN is 1, the sequence number, N-PDU number and next extension header type
follow (nested `switch`es on the three flags). When the next type is not 0, the extension headers
follow, up to four: each its length in 4-octet units, its content as hexadecimal digits (`hex`, of
4 × length − 2 octets, for lengths 1 to 16), and the next type. The type of each header is the next
type before it; the contents are not laid out by type.

Then the payload: a G-PDU (message type 255) carries its T-PDU as octets; every other message
carries IEs: Recovery (14, the restart counter), TEID Data I (16), and the IEs of type 128 and above
(GTP-U peer address, extension header type list, private extension) as a length and octets.

## Shared keys

None.

## Not mapped

- **Extension header contents** (PDU session container, UDP port, PDCP PDU number, RAN containers)
  are hex digits, not laid out by type: the length of the content is a count of 4-octet units, which
  a `length` block cannot read (it counts bytes or bits), so the pack chooses the content's size by a
  `switch` on the length and cannot also switch on the type.
- **More than four extension headers**, or one longer than 16 units, is `no-kind`.
- A next type is read as such even when E is 0 (the sender sets it to 0 then).

## Vectors

`tools/gen/gtp-vectors.py`, without an engine: a G-PDU; a G-PDU with a PDU session container; a
G-PDU with a sequence number and two extension headers; an echo response with Recovery; an error
indication with TEID Data I and a peer address; an end marker; a truncated G-PDU (`malformed-wire`).
