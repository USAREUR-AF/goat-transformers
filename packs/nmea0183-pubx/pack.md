# Pack: nmea0183-pubx

The u-blox `$PUBX` proprietary NMEA 0183 sentences 00, 01, 03 and 04, in the field order gpsd's "NMEA
Revealed" lists. Wire `text`, start `$`, `checksum nmea`. Kinds by fields 0 and 1 (`PUBX`, then `00`,
`01`, `03`, `04`). One message is one sentence. Written by `tools/gen/maritime-pack.py`. The `nmea0183`
pack on main does not read `$PUBX` (its `proprietary` kind takes it as a tag only).

## What is mapped

| Kind | Fields |
|---|---|
| `pubx-00` | time (`hhmmss.ss`), latitude and longitude (`ddmm.mmmmmm` with N/S and E/W), altitude, navigation status, horizontal and vertical accuracy, SOG, COG, vertical velocity, ageC, HDOP, VDOP, TDOP, GU, RU, DR |
| `pubx-01` | time, UTM easting and northing with their letters, then the same fields as 00 |
| `pubx-03` | the number of satellites, then six fields per satellite (ID, s, AZM, EL, SN, LK) |
| `pubx-04` | time, date, UTC time of week, week, a reserved field, Clk_B, Clk_D, PG |

The fields whose units and formats the source does not state are strings, kept as written.

## Shared keys

`lat` and `lon` (`pubx-00`): the source gives the latitude and longitude of PUBX 00 as the NMEA pair
of a `ddmm.mmmm` field and a hemisphere letter (its example sentence has six decimals of minutes),
the form `dm` reads, north and east positive. The cited source gives no datum for this sentence, and none is asserted
here: core `lat` and `lon` mean WGS 84, so binding them is an assumption. No other key: the
time fields have no date in 00 and 01, and the 04 date's time scale is not stated.

## Not mapped

- **Units** of altitude, accuracies, speeds and clock values: gpsd lists the fields by name only; the u-blox
  receiver manuals: not read. The values are strings.
- Other PUBX sentences are not in the source.

## Vectors

`tools/gen/maritime-vectors.py`, without an engine: one sentence of each kind; PUBX 02, which the source
says does not exist (`no-kind`).
