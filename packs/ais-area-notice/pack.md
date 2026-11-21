# Pack: ais-area-notice

The AIS IMO289 area notice (IMO SN.1/Circ.289 as gpsd's AIVDM document restates it): message type 8 with
DAC 1 and FI 22 (broadcast) and type 6 with DAC 1 and FI 23 (addressed). Wire `bits`, `layout
sequential`, `armor sixbit`: the input is the armored payload of the AIVDM sentence (fragments joined),
as for `ais` and `ais-binary`. No kind: `switch` blocks on the message type, DAC and FI choose the
layout; any other application is `no-kind`. Written by `tools/gen/maritime-pack.py`.

`ais-binary` on main lists FI 22 and 23 as not built, because the sub-areas repeat to the end of the
payload, which a fixed layout cannot read; this pack reads them with a sequential layout.

## What is mapped

- The common header on the `ais` and `aisbin` keys of `ais-binary` (type, repeat, MMSI; for type 6
  the sequence number, destination MMSI and retransmit flag; spare; DAC; FI).
- The notice header: message linkage ID, notice description (0-127), start month, day, hour and
  minute (UTC, each with its not-available value), duration in minutes.
- **The sub-areas** (1 to 10, 87 bits each) as a list to the end of the payload, each by its shape:
  circle or point (scale, position, precision, radius), rectangle (scale, south-west corner,
  precision, east and north dimensions, orientation), sector (scale, centre, precision, radius, left
  and right boundary), polyline and polygon (scale, four bearing and distance pairs), associated text
  (14 six-bit characters); a reserved shape keeps its 84 bits as hex.

Positions are kept as the wire's signed integers in thousandths of a minute (with the not-available
values 181000 and 91000); dimensions as the wire's integers, with the scale.

## Shared keys

None of `core` or `track`: the positions are in a list. The header uses the `ais` and `aisbin` keys of
`ais-binary` (`ais.msg_type`, `ais.mmsi`, `aisbin.dac`, `aisbin.fid` and the others), with the same
meaning and bits.

## Not mapped

- The notice's absolute geometry: polylines and polygons are bearings and distances from the previous
  point (the first from the circle before them); computing coordinates is outside a pack.
- The notice description and shape as text; the numbers are kept.
- Fragment joining and the AIVDM sentence, as for `ais`.

## Vectors

`tools/gen/maritime-vectors.py`, without an engine: a broadcast notice with a circle; a broadcast with a
point, a polygon and associated text; an addressed notice with a rectangle and a sector; a type 8 of
another FI (`no-kind`); a cut header (`malformed-wire`).
