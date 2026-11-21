# Pack: ais-binary-apps

AIS binary application messages of variable length, as gpsd's "AIVDM/AIVDO protocol decoding" restates
IMO SN.1/Circ.236 and 289: the applications `ais-binary` lists as not built because their records
repeat to the end of the payload. Wire `bits`, `layout sequential`, `armor sixbit`: the input is the
armored payload of the AIVDM sentence (fragments joined), as for `ais` and `ais-binary`. No kind:
`switch` blocks on the message type, the DAC and the FI choose the application; any other is `no-kind`.
Written by `tools/gen/ais-apps-pack.py`. The area notice (FI 22 and 23) is the pack `ais-area-notice`.

## What is mapped

The common header on the `ais` and `aisbin` keys of `ais-binary` (type, repeat, MMSI; for type 6 the
sequence number, destination MMSI and retransmit flag; spare; DAC; FI), then:

| Type, DAC, FI | Application | Records |
|---|---|---|
| 6, 1, 14 | tidal window (IMO236) | month and day; then 1 to 3 predictions to the end (latitude and longitude in ten-thousandths of a minute, from and to hour and minute, current direction and speed) |
| 6, 1, 32 | tidal window (IMO289) | as FI 14, with longitude before latitude in thousandths of a minute and an 8-bit current speed |
| 6, 1, 25 | dangerous cargo (IMO289) | unit and amount; then 1 to 28 cargo code and subtype pairs to the end |
| 6, 1, 28 and 8, 1, 27 | route information (addressed, broadcast) | linkage, sender class, route type, start month, day, hour, minute, duration; then the waypoints, counted by their 5-bit count (a `count` line: written from the list) |
| 8, 1, 17 | VTS-generated targets | 1 to 4 targets to the end: identifier type, then the identifier as a number (MMSI, IMO) or seven six-bit characters (call sign, other) by the type, position, course, second, speed |
| 8, 1, 26 | environmental | 1 to 5 sensor reports of 112 bits to the end: type, day, hour, minute, site, and the 85-bit payload by type (site location, station ID, wind, water level, 2D current, 3D current, horizontal current, sea state, salinity, weather, air gap; a reserved type as hex) |

Every value is the wire integer (signed where the source marks the field so), with the step and the
not-available code each key's description gives; positions are in a list or a report, so none binds
`lat` and `lon`.

## Shared keys

None of `core` or `track`. The header uses the `ais` and `aisbin` keys of `ais-binary` with the same
bits and meaning.

## Not mapped

- **Text descriptions (type 8 FI 29, type 6 FI 30)**: the text runs as six-bit characters to the end
  of the payload. A list to the end of its extent stops when fewer than 8 bits remain (engine-spec
  0.21; the armored message is counted as the message), so a last character that leaves 6 or 7 bits is
  read as padding and lost; a single text field needs a size, which the message does not give. The
  vector that showed it was dropped (rule 16). Needed: under `armor sixbit`, a list to the end whose
  items are read while an item's bits remain (or a character field to the end of the message).
- **Scaled values**: speeds, temperatures, levels and pressures are the wire integers; the source gives
  offsets and steps per field and disagrees with itself in places (the broadcast route table gives
  waypoint latitude in thousandths of a minute for the same 27 bits that the addressed table gives in
  ten-thousandths; water level and air gap steps are noted as conflicting with IMO289).
- **The VTS target identifier for MMSI and IMO**: gpsd records an open question on its bit order; the
  pack reads it big-endian, as the table shows.
- DAC 366 (St. Lawrence Seaway) and the other regional applications are not built.
- Times: day, hour and minute without a full date, as in `ais-binary`.

## Vectors

`tools/gen/ais-apps-vectors.py`, without an engine: both tidal windows; dangerous cargo; addressed and
broadcast routes; VTS targets by MMSI and by call sign; three environmental messages covering all
eleven sensor report types; a type 8 FI 31 message (`no-kind`); a route short of its waypoint count
(`malformed-wire`). Two text-description vectors were dropped with the applications (see the script).
