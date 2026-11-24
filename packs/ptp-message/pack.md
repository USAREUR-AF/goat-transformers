# Pack: ptp-message

A PTP (IEEE 1588, version 2) message as linuxptp lays it out: the 34-octet common header,
the body by message type, and the suffix TLVs to the message length. Wire `bits`, `layout sequential`,
most significant bit first. No kind: a `switch` on the message type chooses the body; an unassigned type
is `no-kind`. One message is one UDP or Ethernet payload.
Written by `tools/gen/gnss-time-pack.py`.

## What is mapped

- **Header**: transport specific (major SDO ID), message type, minor version, version, the message
  length (`length 16 whole`, written on encode), domain, the flag bits one by one (alternate master,
  two-step, unicast, leap 61, leap 59, UTC offset valid, PTP timescale, time traceable, frequency
  traceable, synchronization uncertain; the others as their bits), correction (scaled nanoseconds,
  signed), source port identity (clock identity as hex, port number), sequence ID, control, log
  message interval.
- **Bodies**: Sync and Delay_Req (origin timestamp), Pdelay_Req (origin timestamp, reserved port
  identity), Pdelay_Resp and Pdelay_Resp_Follow_Up (timestamp, requesting port identity), Follow_Up
  (precise origin timestamp), Delay_Resp (receive timestamp, requesting port identity), Announce
  (origin timestamp, current UTC offset, grandmaster priorities, clock class, accuracy and variance,
  grandmaster identity, steps removed, time source), Signaling (target port identity), Management
  (target port identity, boundary hops, action). Timestamps are the 48-bit seconds and the nanoseconds.
- **Suffix TLVs** to the message length: type, and the value in the extent of the length: management
  (management ID, then data as octets), organization extensions (organization ID and subtype as hex,
  data as octets), path trace (a list of clock identities), others as octets.

## Shared keys

None. PTP timestamps are on the PTP timescale (TAI) when the PTP timescale flag is set and on an
arbitrary timescale otherwise, not UTC; they are kept as seconds and nanoseconds and do not bind
`time_ms`. The Announce's current UTC offset is kept beside them.

## Not mapped

- **Management TLV data** by management ID (the clock and port data sets) and the other TLVs' values
  (unicast negotiation, authentication, alternate time offset ...) are octets.
- Messages padded past the message length (short Ethernet frames) are read to the message length; the
  padding is not written back.
- The PTP over Ethernet and UDP framing.

## Vectors

`tools/gen/gnss-time-vectors.py`, without an engine: a two-step Sync; a Follow_Up with a negative correction;
a Delay_Resp; an Announce with a path trace TLV; a Pdelay_Req; a Management GET; a Signaling message with
an organization extension TLV; an unassigned message type (`no-kind`); a message cut before its length
(`malformed-wire`).
