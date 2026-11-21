# etcs-radio-track-to-train

An ERTMS/ETCS radio message from the RBC (or an RIU) to the train (Euroradio, application level). Licence
`LicenseRef-unstated` (PROVENANCE.md).

## Message convention

The application message: NID_MESSAGE, L_MESSAGE (the byte length of the whole message, padding
included, `length 10 whole`), T_TRAIN, M_ACK, NID_LRBG (as its NID_C and NID_BG parts), the
message's own variables and packets, the optional packets, and the padding to a whole byte. The
Euroradio safe connection layers around it are not part of the message.

## Kinds

| Kind | NID_MESSAGE | Content after the header |
|---|---|---|
| `sr_authorisation` | 2 | Q_SCALE, D_SR, optional packets |
| `movement_authority` | 3 | packet 15 (level 2/3 MA), optional packets |
| `exit_trip_recognition` | 6 | nothing |
| `train_data_acknowledgement` | 8 | T_TRAIN of the train data message |
| `request_to_shorten_ma` | 9 | packet 15, optional packets |
| `conditional_emergency_stop` | 15 | NID_EM, Q_SCALE, D_REF, Q_DIR, D_EMERGENCYSTOP |
| `unconditional_emergency_stop` | 16 | NID_EM |
| `revocation_of_emergency_stop` | 18 | NID_EM |
| `general_message` | 24 | optional packets |
| `sh_refused` | 27 | T_TRAIN of the request |
| `sh_authorised` | 28 | T_TRAIN of the request, optional packets |
| `system_version` | 32 | M_VERSION |
| `ma_shifted_location` | 33 | Q_SCALE, D_REF (16 bits, two's complement), packet 15, optional packets |
| `track_ahead_free_request` | 34 | Q_SCALE, D_REF, Q_DIR, D_TAFDISPLAY, L_TAFDISPLAY |
| `infill_ma` | 37 | packets 136 and 12 and the optional packets, all read as the packet list |
| `session_termination_acknowledgement` | 39 | nothing (M_ACK 0) |
| `train_rejected`, `train_accepted`, `som_position_report_confirmed` | 40, 41, 43 | nothing |
| `coordinate_system_assignment` | 45 | Q_ORIENTATION |

The messages whose definition lets optional packets follow (8.4.4.4) end with a `group … rest`
using the item kinds of `etcs-balise-telegram` (every track-to-train packet) plus 15. The packet
list does not enforce which packets a message may carry. Every track-to-train message of chapter
8 is a kind.

## Shared keys

None, as for the balise telegram: track-relative distances, speed limits and balise identities
stay raw. T_TRAIN is the RBC's clock in 10 ms units, not a UTC time, so it is not `time_ms`.

## Not mapped

- The limits of `etcs-balise-telegram` apply to the packets (packet 3's correction factors, text
  as bytes).
