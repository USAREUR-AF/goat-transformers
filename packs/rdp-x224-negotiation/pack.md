# Pack: rdp-x224-negotiation

The first two PDUs of an RDP connection ([MS-RDPBCGR] 2.2.1.1 and 2.2.1.2): TPKT, the X.224 Connection
Request with the client's routing token or cookie line and RDP_NEG_REQ (and the correlation info), the
X.224 Connection Confirm with RDP_NEG_RSP or RDP_NEG_FAILURE, and the X.224 DT TPDU that carries every
later PDU. Wire `bits`, `layout sequential`, `bit_order msb`; TPKT and X.224 are big-endian, the RDP
structures little-endian (`swap`). One kind, `tpkt`, chosen by the version octet 3. One message is one
TPKT packet. Written by `tools/gen/rdp-neg-pack.py`. Labelled `LicenseRef-MS-OpenSpec` (PROVENANCE.md).

The TPKT and X.224 lines are those of `tpkt-x224`, with the same `tpkt` keys; only the variable part of
CR and CC differs.

## What is mapped

- **TPKT and X.224** (module `tpkt`): as in `tpkt-x224` (TPKT length block, length indicator block, TPDU
  code, references, class and options, DT, DR, ER, other codes as octets, user data as octets).
- **Connection Request** (code 14), inside the length indicator, which [MS-RDPBCGR] says counts the token
  or cookie, its CR LF and the RDP structures:
  - the first octet (`first_octet`): 67, the letter C, starts the routing token or cookie line; 1 starts
    RDP_NEG_REQ directly;
  - after a C: the rest of the line up to CR (`token_line`), the LF, then the negotiation type;
  - RDP_NEG_REQ: flags, length, requested protocols;
  - when the flags have 0x08 (correlation info present), the correlation info: type, flags, length, the
    16-octet correlation ID and the 16 reserved octets (`hex`).
- **Connection Confirm** (code 13): the negotiation type, then RDP_NEG_RSP (flags, length, selected
  protocol) or RDP_NEG_FAILURE (flags, length, failure code).

## Shared keys

None. The negotiation fields have no `core` or `track` meaning.

## Not mapped

- **The routing token's own format** is given by another document ([MSFT-SDLBTS], not read). The pack
  reads a token only when it begins with C, as the cookie must; a variable part that begins with another
  octet than C or 1 decodes with the RDP keys absent.
- **The C split**: the pack chooses between the line and RDP_NEG_REQ by the first octet, so the line's
  key lacks its first character (`token_line` holds the text from the second character). A prefix match
  on a text field is not in the pack language.
- **Absent structures re-encode as one zero octet.** Under ruling 7 of 0.8, encode writes every line of a
  length block and writes an absent line as zero bits. A CR with no variable part, a cookie with no
  RDP_NEG_REQ, or a CC with no negotiation data therefore re-encodes with one more octet (00) and both
  lengths one larger (vectors 07 and 08). Needed for an exact round trip: a field written only when its
  key is present, in a `layout sequential` length block.
- **The MCS, GCC and later PDUs** in DT user data: octets.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one TPKT packet.

## Vectors

`tools/gen/rdp-neg-vectors.py`, without an engine: cookie with RDP_NEG_REQ; RDP_NEG_REQ alone; RDP_NEG_REQ
with the correlation info; RDP_NEG_RSP; RDP_NEG_FAILURE; a DT; a cookie without RDP_NEG_REQ and a CC
without negotiation data (one zero octet added); a DT converted to `tpkt-x224`; a correlation info cut by
the length indicator (`malformed-wire`); a version 2 packet (`no-kind`).
