# Pack: ccsds-clcw

The CCSDS Communications Link Control Word (CCSDS 232.0-B-4 with Technical
Corrigendum 1, section 4.2.1): the 4-octet report the receiving end of a TC
link returns, carried in the operational control field of TM and AOS frames.
Public. Hand-written from the Blue Book; I/O is hex text. Needs engine version
0.5.

Uses the modules `core` and `ccsdsclcw` (`model/ccsdsclcw.def`).

## Message convention

A message is the 4 octets of the word. Longer input is accepted and the extra
octets are ignored; shorter input is `malformed-wire`.

## Addressing

`word_bytes 1`, `bit_order msb`; "bits *a*-*b*" is `0:<a>:<b-a+1>`.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0 | control word type | `when 0:0:1 0` | `1` is another report in the same field; `no-kind` |
| 1-2 | CLCW version number | `when 0:1:2 0` | `00`; other values are `no-kind` |
| 3-5 | status field | `ccsdsclcw.status_field` | mission-defined |
| 6-7 | COP in effect | `ccsdsclcw.cop_in_effect` | 1 = COP-1 |
| 8-13 | virtual channel identification | `ccsdsclcw.virtual_channel_id` | |
| 14-15 | reserved spare | not mapped | written as `00` |
| 16 | no RF available flag | `ccsdsclcw.no_rf_available` | |
| 17 | no bit lock flag | `ccsdsclcw.no_bit_lock` | |
| 18 | lockout flag | `ccsdsclcw.lockout` | |
| 19 | wait flag | `ccsdsclcw.wait` | |
| 20 | retransmit flag | `ccsdsclcw.retransmit` | |
| 21-22 | FARM-B counter | `ccsdsclcw.farm_b_counter` | |
| 23 | reserved spare | not mapped | written as `0` |
| 24-31 | report value | `ccsdsclcw.report_value` | N(R) |

One kind, `clcw`, with no `when` of its own and no `requires`, so that the two
common `when` lines apply (0.5 ruling 8).

## Shared keys

None. A link status report has no position, time or name.

## Not mapped

The two reserved spare fields only. A CLCW inside a TM or AOS frame is read by
taking the operational control field out of the frame first: the frame packs
do not locate it (see `ccsds-tm-frame/pack.md`, Not mapped).

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-vectors.py` from its own layout
table: a nominal round trip, every flag set, control word type 1 (`no-kind`),
version `01` (`no-kind`), and a cut word (`malformed-wire`).
