# Pack: fix-message

One FIX tag=value message (FIX 4.x or FIXT 1.1 session encoding), as it travels on a FIX session: fields
"tag=value", each ended by SOH (0x01). Wire `bits`, `layout sequential`; the text of each field is
`until:<code> chars:ascii8`. One kind, `fix`, chosen by the first two octets `8=`. Written by
`tools/gen/finance-pack.py`.

## What is mapped

- **BeginString** (8), **BodyLength** (9) and **MsgType** (35), the three fields that open every message,
  by name. The `9=` and `35=` prefixes are written as constants.
- **Every other field**, in order, as a list of tag and value (tag up to `=`, value up to SOH): the rest
  of the header (SenderCompID, TargetCompID, MsgSeqNum, SendingTime ...), the body and the trailer, the
  CheckSum (10) last.

## Shared keys

None.

## Not mapped

- **Fields by name**: the body's fields depend on the message type and the version's data dictionary,
  and their order is free within limits, so they are a tag/value list. A message-type kind with named
  fields would need a dictionary and a "field by tag anywhere in the list" locator.
- **BodyLength and CheckSum computed**: kept as sent.
- **Repeating groups** (NoXXX counts followed by groups): flat in the list.
- **Data fields** (RawData and the like, whose value may hold SOH): their length field is not used.
- **Characters outside printable ASCII** in values: refused by `ascii8`.
- FIX binary encodings (SBE, FAST) and FIXML.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the message octets (SOH included).

## Vectors

`tools/gen/finance-vectors.py`, without an engine (body length and checksum computed there): a logon; a new
order single; a FIX 4.2 heartbeat; a message not opening with tag 8 (`no-kind`); a CheckSum without its
SOH (`malformed-wire`).
