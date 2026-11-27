# etcs-radio-train-to-track

An ERTMS/ETCS radio message from the train to the RBC (Euroradio, application level). Licence
`LicenseRef-unstated` (PROVENANCE.md).

## Message convention

NID_MESSAGE, L_MESSAGE (the byte length of the whole message, padding included, `length 10
whole`), T_TRAIN (the on-board clock, 10 ms units), NID_ENGINE, the message's own variables, then
its packets (packet 0 or 1, the position report, then any others), and padding to a whole byte.

## Kinds

| Kind | NID_MESSAGE | Variables before the packets |
|---|---|---|
| `validated_train_data` | 129 | none (packet 11 follows the position report) |
| `request_for_shunting` | 130 | none |
| `ma_request` | 132 | Q_MARQSTREASON |
| `train_position_report` | 136 | none |
| `shorten_ma_granted`, `shorten_ma_rejected` | 137, 138 | T_TRAIN of the request |
| `acknowledgement` | 146 | T_TRAIN of the message acknowledged |
| `emergency_stop_acknowledgement` | 147 | NID_EM, Q_EMERGENCYSTOP |
| `track_ahead_free_granted`, `end_of_mission` | 149, 150 | none |
| `radio_infill_request` | 153 | NID_C, NID_BG, Q_INFILL |
| `no_compatible_version`, `session_initiation`, `session_termination` | 154, 155, 156 | none |
| `som_position_report` | 157 | Q_STATUS |
| `text_message_acknowledged` | 158 | NID_TEXTMESSAGE |
| `session_established` | 159 | none (packet 2 follows) |

The packets are a `group … rest` whose items select a kind by NID_PACKET: `tp0` position report,
`tp1` position report based on two balise groups, `tp2` supported system versions, `tp4` error
reporting, `tp5` train running number, `tp9` level 2/3 transition information, `tp11` validated
train data, `tp44` data for applications outside ETCS (kept as bits), and `tother` for a number
chapter 7 assigns to no train-to-track packet. A train-to-track packet has no Q_DIR: L_PACKET, the
bit length of the whole packet, follows NID_PACKET (`length 13 bits plus 21`). Whether a message
carries the packets its definition requires (packet 0 or 1, packet 11, packet 2) is not checked.

On encode with no recorded kind, each message requires its keys: a key of its own where it has
one, otherwise all of its keys; the NID_MESSAGE values are distinct, so the order does not change
decode. Nine messages (validated train data, request for shunting, train position report, track
ahead free granted, end of mission, no compatible version, session initiation, termination and
established) carry the same keys and differ only in NID_MESSAGE, so such an entity is written as
validated train data. Choosing by a key's value is a language addition.

## Shared keys

None. The position report gives the train's position as a distance from the LRBG along the track
(D_LRBG, in Q_SCALE units) with its confidence interval, not latitude and longitude, and its speed
V_TRAIN in 5 km/h steps inside a packet item, so no key binds `lat`, `lon` or `speed_ms`. T_TRAIN
is the on-board clock, not UTC.

## Not mapped

- Packet 44's data is kept as bits.
