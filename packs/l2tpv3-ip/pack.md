# Pack: l2tpv3-ip

The L2TPv3 headers over IP (protocol 115, section 4.1.1) of IETF RFC 3931: the session header of a data message and
the control message header (section 3.2.1). Public. Written by hand from the
RFC; the layout is stated in this repository's words. I/O is hex text. Needs
engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the payload of the IP packet or UDP datagram. The pack reads the
header; the cookie, the L2-specific sublayer, the tunnel payload and control
message AVPs are read over and not written.

| Kind | `when` | Fields |
|---|---|---|
| `control` | octets 0-3 = 0 and the T bit (octet 4, bit 0) = 1 | the control header from octet 4 |
| `data` | none | `inet.l2tp_session_id`, octets 0-3 |

On encode the `control` kind requires `inet.l2tp_control_connection_id`, so an entity
without it, such as an l2tpv3-udp data message, is written as `data` (l2tpv3-udp vector 04).

Control message header (bits from its T bit): 0 T, 1 L (`inet.l2tp_length_bit`),
4 S (`inet.l2tp_sequence_bit`), 12-15 version (`inet.l2tp_version`), 16-31
length (`inet.l2tp_length`), 32-63 control connection ID
(`inet.l2tp_control_connection_id`), 64-79 Ns (`inet.l2tp_ns`), 80-95 Nr
(`inet.l2tp_nr`). The control header starts after 32 zero bits; its fields are as below, 4 octets
later. The reserved x bits are not mapped: written 0, ignored on
decode, as the RFC has them.

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The pack does not
check that L and S are 1 or that the version is 3.

## Shared keys

None.

## Not mapped, and why

- The cookie (0, 32 or 64 bits): its length is configured per session, not
  stated in the message.
- The L2-specific sublayer and the payload: their form is set per pseudowire.
- Control message AVPs: a list whose end is the message length; a `bits`
  group needs a count.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there.
A control message with an AVP, a data message with a cookie and payload, a
control header at its largest values, and a control message cut short
(`malformed-wire`).
