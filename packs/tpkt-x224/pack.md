# Pack: tpkt-x224

TPKT (RFC 1006) with the ISO 8073 / X.224 transport TPDU it carries (the TPDU structure as RFC 905 states
it). Wire `bits`, `layout sequential`, `bit_order msb`. One kind, `tpkt`, chosen by the version octet 3.
One message is one TPKT packet as it travels over TCP: version, reserved octet, the 16-bit length of the
whole packet (a `length 16 whole` block), then the TPDU. Written by `tools/gen/rdp-neg-pack.py`.

## What is mapped

- **TPKT**: the reserved octet; the length is written by the block.
- **Length indicator**: a `length 8 bytes` block over the TPDU header after the indicator, as RFC 905
  defines it (the user data is outside it).
- **TPDU code** (the high four bits of the code octet) and the low four bits (`credit` for CR and CC).
- **Fixed part** by code:
  - CR (14) and CC (13): destination reference, source reference, class, options;
  - DT (15): the end-of-TSDU mark and the send sequence number (the class 0 and 1 normal format);
  - DR (8): destination reference, source reference, disconnect reason;
  - ER (7): destination reference, reject cause.
  - Any other code: the rest of the header as octets.
- **Variable part** (the parameters) as octets, and the **user data** after the header as octets.

## Shared keys

None. Nothing in TPKT or X.224 has the meaning of a `core` or `track` key.

## Not mapped

- **Parameters one by one** (TPDU size, calling and called TSAP, checksum, additional option selection
  and others): the variable part is a sequence of code, length, value parameters; it is kept as octets.
  A `while`-group of parameters would read them, but X.224 parameters end where the length indicator
  ends, and RDP puts its own data in that place (see `rdp-x224-negotiation`); octets keep both readable.
- **Extended formats** (classes 2 to 4 with extended sequence numbers, the 31-bit DT number and 16-bit
  credit), and the AK, EA, RJ, ED and DC TPDUs: as octets after the code octet.
- **Several TPDUs concatenated** in one packet (RFC 905 allows it for some classes): the first is read,
  the rest is user data.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one TPKT packet.

## Vectors

`tools/gen/rdp-neg-vectors.py`, without an engine: CR, CC with a parameter, DT with user data, DR, ER, an
AK kept as octets, a DT converted to `rdp-x224-negotiation`, a version 2 packet (`no-kind`) and a packet
shorter than its TPKT length (`malformed-wire`).
