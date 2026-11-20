# Pack: l2tpv3-udp

The L2TPv3 headers over UDP (section 4.1.2) of IETF RFC 3931: the session header of a data message and
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
| `control` | T bit (octet 0, bit 0) = 1 | the control header from octet 0 |
| `data` | T bit = 0 | version (bits 12-15), reserved (16-31), `inet.l2tp_session_id` (32-63) |

Control message header (bits from its T bit): 0 T, 1 L (`inet.l2tp_length_bit`),
4 S (`inet.l2tp_sequence_bit`), 12-15 version (`inet.l2tp_version`), 16-31
length (`inet.l2tp_length`), 32-63 control connection ID
(`inet.l2tp_control_connection_id`), 64-79 Ns (`inet.l2tp_ns`), 80-95 Nr
(`inet.l2tp_nr`). The control header starts at octet 0. The reserved x bits are not mapped: written 0, ignored on
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
A control message, a data message with payload, and a data header cut short
(`malformed-wire`).
