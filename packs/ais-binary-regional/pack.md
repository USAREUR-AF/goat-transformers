# Pack: ais-binary-regional

The St. Lawrence Seaway and U.S. Coast Guard PAWSS AIS binary messages (DAC 316, Canada, and 366, United
States), from the Seaway's AIS Data Messaging Formats and Specifications, Revision 4.1, which gpsd's AIVDM
document names as their description. Wire `bits`, `layout sequential`, `armor sixbit`: the input is the
armored payload of a type 6 or type 8 message. No kind: `switch` blocks on the message type, DAC, FI and
the Seaway message ID choose the layout; any other is `no-kind`. Written by
`tools/gen/ais-regional-pack.py`. Labelled `LicenseRef-unstated` (PROVENANCE.md).

The other regional applications gpsd describes, DAC 200 (inland waterways) and 235/250 (UK and Ireland
AtoN monitoring), are already in `ais-binary`.

## What is mapped

The common header on the `ais` and `aisbin` keys of `ais-binary` (type, repeat, MMSI; for type 6 the
sequence number, destination MMSI and retransmit flag; spare; DAC; FI), then two reserved bits and the
message ID, then:

| FI, message ID | Message | Content |
|---|---|---|
| 1, 1 | weather station | 1 to 4 reports to the end: time tag, station ID, position, wind speed, gust and direction, pressure, air temperature, dew point, visibility, water temperature |
| 1, 2 | wind | 1 to 6 reports: time tag, station ID, position, wind speed, gust, direction |
| 1, 3 | water level | 1 to 6 reports: time tag, station ID, position, level type, level, datum, reading type |
| 1, 4 | PAWSS hydro current | 1 to 6 reports: time tag, station ID, position, current speed and direction |
| 1, 5 | PAWSS hydro salinity and temperature | 1 to 6 reports: time tag, station ID, position, salinity, water temperature |
| 1, 6 | water flow | 1 to 6 reports: time tag, station ID, position, flow |
| 2, 1 | lockage order | time tag, lock ID, position, then 1 to 6 schedule reports (vessel name, direction, ETA) |
| 2, 2 | estimated lock times | time tag, vessel name, last location and ATA, first and second lock with their ETAs, the delayed lock |
| 32, 1 | version | major and minor revision |

The message works with either message type (the specification sends most as broadcasts and the
estimated lock times addressed). Values are the wire integers with the steps and not-available codes in
each key's description; names are six-bit text.

## Shared keys

None of `core` or `track`: positions are in reports. The header uses the `ais` and `aisbin` keys of
`ais-binary` with the same bits.

## Not mapped

- **The PAWSS vessel procession order** (FI 1, message ID 3 in Appendix A): it has the same FI and message
  ID as the Seaway water level message, and DAC 366 is used by both systems; the two layouts cannot be told
  apart by a field. The pack reads FI 1, ID 3 as water level. (gpsd's table also lists PAWSS salinity under
  ID 6; the specification's Appendix gives 5, which the pack follows.)
- **Seaway safety-related messages** (section 10) are AIS types 12 and 14 (text), read by `ais`.
- **DAC 367 (USCG)** and the Thames (Port of London) extensions: gpsd lists no layout for them, and their
  documents were not read.
- Times: month, day, hour and minute without a year.

## Vectors

`tools/gen/ais-regional-vectors.py`, without an engine: wind (two stations); weather; water level; water
flow; PAWSS current; PAWSS salinity and temperature; lockage order; addressed estimated lock times;
version; an unassigned message ID (`no-kind`); a cut report (`malformed-wire`).
