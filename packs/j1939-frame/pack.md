# Pack: j1939-frame

One SAE J1939 frame: the 29-bit identifier and the data, read by PGN. Wire `bits`, `layout sequential`,
`bit_order lsb` (J1939 data is little-endian). No kinds. Written by `tools/gen/j1939-pack.py`.

## Message convention

The identifier is outside the CAN data, so a message is:

1. 4 octets: the SocketCAN `can_id`, little-endian, as `struct can_frame` holds it on a little-endian
   host (Linux `include/uapi/linux/can.h`): bits 28-0 the identifier, bit 31 the extended-frame flag
   (1 for J1939), bit 30 RTR, bit 29 the error flag;
2. the data: the frame's data field, or the reassembled data of a transport-protocol message (as for
   a DM1 with several DTCs).

This differs from `nmea2000`, which puts the 3-octet PGN first and drops priority and addresses; here
the whole identifier is kept, so the source address, the destination address and the priority round
trip. `input` and `expect` are lowercase hexadecimal text.

## What is mapped

- **Identifier**: SA, PS, PF, DP, EDP, priority, and the three SocketCAN flags.
- **The PGN rule** (j1939.rst): with PF below 240 (PDU1) PS is the destination address and is not part
  of the PGN; with PF 240 or more (PDU2) PS is the group extension and part of it. The pack keeps PS as
  one key, `pdu_specific`, and chooses the data layout by PF (and, for DM1, PS); the PGN itself is not a
  key (see below).
- **Data, with EDP and DP 0**:
  - PF 0xEA, Request (PGN 59904): the requested PGN.
  - PF 0xEE, Address Claimed (60928): the NAME's ten fields.
  - PF 0xEC, TP.CM (60416): the control byte; RTS (size, packets, maximum per CTS), CTS (packets, next
    packet), EOMA and BAM (size, packets), Abort (reason), each with its reserved octets; any other
    control byte's four octets; then the PGN.
  - PF 0xEB, TP.DT (60160): the sequence number and the seven data octets.
  - PF 0xE8, Acknowledgement (59392): control, group function, reserved, address, PGN.
  - PF 0xFE with PS 0xCA, DM1 (65226): the four lamp statuses and their flash codes, then the DTCs: the
    SPN's low 16 bits, the FMI, the SPN's high 3 bits, the occurrence count and the conversion method
    bit.
  - Anything else, and any frame with EDP or DP set: the data as octets.

## Shared keys

None. Nothing has a `core` or `track` meaning; the PGN-numbered fields of `nmea2000` are another module.

## Not mapped

- **The PGN as one number**: it is EDP, DP, PF and (in PDU2) PS; a derived key would need arithmetic
  over four fields and a condition on PF.
- **The SPN as one number**: it is `spn_high` × 65536 + `spn_low`, split by its bit positions.
- **DM1 padding**: a one-DTC frame ends with 0xFF 0xFF, which the pack reads as a DTC item of two
  octets whose low SPN is 0xFFFF (the list holds four-octet items otherwise). A real DTC whose low 16 SPN
  bits are 0xFFFF would be read the same way, with the rest of its octets as the next item.
- **The older SPN conversion methods** (the conversion bit set): the bits are read in the current layout
  only.
- **Transport reassembly**, other PGNs (the J1939-71 parameters), the other DMs, and J1939-22 (CAN FD).

## Vectors

`tools/gen/j1939-vectors.py`, without an engine: a global Request for Address Claimed; Address Claimed
with a NAME; TP.CM RTS, CTS, EOMA, BAM and Abort; TP.DT; an Acknowledgement NACK; DM1 with one DTC and
its padding; a reassembled DM1 with two DTCs, one with an SPN above 65535; a PDU2 PGN as octets; a data
page 1 frame as octets; a cut NAME (`malformed-wire`).
