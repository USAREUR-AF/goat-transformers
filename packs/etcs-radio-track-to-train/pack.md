# etcs-radio-track-to-train

An ERTMS/ETCS radio message from the RBC to the train (Euroradio, application level). Licence
`LicenseRef-unstated` (PROVENANCE.md).

## Message convention

The application message: NID_MESSAGE, L_MESSAGE (the byte length of the whole message, padding
included, `length 10 whole`), T_TRAIN, M_ACK, NID_LRBG (as its NID_C and NID_BG parts), the
message's own variables and packets, the optional packets, and the padding to a whole byte. The
Euroradio safe connection layers around it are not part of the message.

## Kinds

| Kind | NID_MESSAGE | Content after the header |
|---|---|---|
| `movement_authority` | 3 | packet 15 (level 2/3 MA), optional packets |
| `general_message` | 24 | optional packets |
| `ma_shifted_location` | 33 | Q_SCALE, D_REF (16 bits, two's complement), packet 15, optional packets |

Optional packets are a `group … rest` with the item kinds of `etcs-balise-telegram` (5, 12, 21,
27, 41, 44 and `other`) plus 15. Other messages are `no-kind`.

## Shared keys

None, as for the balise telegram: track-relative distances, speed limits and balise identities
stay raw. T_TRAIN is the RBC's clock in 10 ms units, not a UTC time, so it is not `time_ms`.

## Not mapped

- Messages other than 3, 24 and 33.
- The packets of the optional list beyond those named are kept as bits.
