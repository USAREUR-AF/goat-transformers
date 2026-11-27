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
| `p2`, `p3`, `p5`, `p6`, `p12`, `p13`, `p16`, `p21`, `p27`, `p39`, `p40`, `p41`, `p42`, `p44`, `p45`, `p46`, `p49`, `p51`, `p52`, `p57`, `p58`, `p63`, `p64`, `p65`, `p66`, `p67`, `p68`, `p69`, `p70`, `p71`, `p72`, `p76`, `p79`, `p80`, `p88`, `p90`, `p131`, `p132`, `p133`, `p134`, `p135`, `p136`, `p137`, `p138`, `p139`, `p140`, `p141`, `p143`, `p145`, `p180`, `p181`, `p254` | every other track-to-train packet of chapter 7, as its number |
| `p255` | 255, end of information |
| `other` | a number chapter 7 assigns to no track-to-train packet: NID_PACKET, Q_DIR and the body kept as bits |

Every packet but 0 and 255 is Q_DIR then L_PACKET, the bit length of the whole packet, stated as
`length 13 bits plus 23`. An iteration count N_ITER (5 bits) right before its items is a
`group … count 5`. A one-bit qualifier that gates the variables after it (Q_NEWCOUNTRY,
Q_SECTIONTIMER, Q_ENDTIMER, Q_DANGERPOINT, Q_OVERLAP) is a `presence` bit; a value that chooses
what follows (Q_DIFF, M_LEVELTR, Q_TRACKINIT, Q_SUITABILITY, M_VOLTAGE, Q_TEXTCONFIRM, Q_LXSTATUS and
the like) is a field and a `switch` on it. In packet 6, T_VBC depends on Q_VBCO, three fields
earlier: the `switch` on that key stands after NID_C. Packet 72's text is L_TEXT and that many
bytes, a `group … count 8` of bytes (the bytes, not text).

## Shared keys

None. Locations are distances along the track from the balise group, in units that Q_SCALE of
each packet sets (10 cm, 1 m or 10 m), not latitude and longitude, so they stay raw; speeds are in
5 km/h steps and are limits, not the train's speed; NID_C and NID_BG are raw.

## Not mapped

- Packet 3 (national values): when Q_NVKINT is 1, the integrated correction factors that follow
  are kept as bits. Inside their iterations, whether M_NVKVINT appears twice depends on
  Q_NVKVINTSET, a variable outside the iteration's items; a `switch` inside a group may name only
  a key of the item. Missing: a condition on a key of the enclosing scope, inside a group.
- Text (X_TEXT) is kept as byte values.
- Numbers chapter 7 assigns to no packet are kept as bits (kind `other`).
- A telegram whose filler after packet 255 is kept is longer than this message: trailing bits
  of eight or more are read as further packets.

## Packet kinds on encode

Each packet kind's `when` on NID_PACKET binds `etcs.nid_packet` (`when 8 <n> as etcs.nid_packet`, engine-spec 0.30). An
item of `etcs.packets` that records no kind is chosen by its keys (0.8 ruling 26, 0.5 Encode step 2).
It is the packet whose NID_PACKET the item holds. An item without one is `other`, the generic
packet. Before that binding, no packet kind had a term, so `p0`, the first, took every such item.
Only a library caller that builds the items itself, without a kind, meets this. A decoded message
records each item's kind, and no other format has this list, so no conversion vector can show it.
Vectors of this pack check `etcs.nid_packet` on decode.
