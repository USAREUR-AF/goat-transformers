# etcs-balise-telegram

A Eurobalise telegram of ERTMS/ETCS: what a balise sends a passing train. Licence
`LicenseRef-unstated` (PROVENANCE.md).

## Message convention

The user information of one telegram: the 50-bit header, then the packets, ending with packet 255,
then zero bits to the next whole byte. The air-gap encoding of the telegram (the 341 or 1023
transmitted bits and their check bits) is undone before; the filler a telegram holds after packet
255 is not part of the message (the receiver stops at packet 255). Bits are read most significant
first (`bit_order msb`, `layout sequential`).

## Layout

The header: Q_UPDOWN, M_VERSION, Q_MEDIA, N_PIG, N_TOTAL, M_DUP, M_MCOUNT, NID_C, NID_BG, Q_LINK.
Then the packets, a `group … rest` whose items select a kind by NID_PACKET (8 bits):

| Kind | Packet |
|---|---|
| `p0` | 0, virtual balise cover marker (NID_VBCMK; no Q_DIR or L_PACKET) |
| `p5` | 5, linking |
| `p12` | 12, level 1 movement authority |
| `p21` | 21, gradient profile |
| `p27` | 27, international static speed profile |
| `p41` | 41, level transition order |
| `p44` | 44, data for applications outside ETCS (the data kept as bits) |
| `p255` | 255, end of information |
| `other` | any other packet: NID_PACKET, Q_DIR and the body kept as bits |

Every packet but 0 and 255 is Q_DIR then L_PACKET, the bit length of the whole packet, stated as
`length 13 bits plus 23`. An iteration count N_ITER (5 bits) right before its items is a
`group … count 5`. A one-bit qualifier that gates the variables after it (Q_NEWCOUNTRY,
Q_SECTIONTIMER, Q_ENDTIMER, Q_DANGERPOINT, Q_OVERLAP) is a `presence` bit; a value that chooses
what follows (Q_DIFF, M_LEVELTR, NID_XUSER) is a `switch`.

## Shared keys

None. Locations are distances along the track from the balise group, in units that Q_SCALE of
each packet sets (10 cm, 1 m or 10 m), not latitude and longitude, so they stay raw; speeds are in
5 km/h steps and are limits, not the train's speed; NID_C and NID_BG are raw.

## Not mapped

- Packets other than those above are kept as bits (kind `other`), not as variables.
- A telegram whose filler after packet 255 is kept is longer than this message: trailing bits
  of eight or more are read as further packets.
