# Pack: seatalk1

One Raymarine SeaTalk 1 datagram: the command octet, the attribute octet (its low nibble the number of
data octets after the first, its high nibble data in several datagrams), and the data. Wire `bits`,
`layout sequential`, `bit_order msb`; 16-bit values are little-endian (`swap`) except the apparent wind
angle. Kinds by the command, one per datagram Signal K's NMEA 0183 parser decodes, and `other` (no
`when`, last) for every other command. Written by `tools/gen/seatalk-pack.py`.

The datagram reaches a computer as the octets of the 9-bit SeaTalk bus (the command octet flagged by the
ninth bit), or as the hexadecimal fields of an `$STALK` sentence; this pack takes the octets.

## What is mapped

| Command | Kind | Fields |
|---|---|---|
| 0x00 | `depth` | the Y and Z flag bits (anchor alarm, metric units, transducer defective, deep and shallow alarm), depth in tenths of a foot |
| 0x10 | `apparent-wind-angle` | angle, degrees (high octet first, half degrees) |
| 0x11 | `apparent-wind-speed` | units flag, knots, tenths |
| 0x20 | `speed-through-water` | knots |
| 0x21 | `trip-mileage` | low 16 bits, high nibble |
| 0x22 | `total-mileage` | nautical miles |
| 0x25 | `total-and-trip-log` | total low 16 bits (high bits in the attribute), trip low 16 bits and high nibble |
| 0x26 | `speed-through-water-2` | sensor 1, sensor 2 or average (hundredths of a knot), flags D and E |
| 0x27 | `water-temperature` | degrees Celsius (`uscale:1/10:-10`) |
| 0x50, 0x51 | `latitude`, `longitude` | whole degrees; the minutes word (top bit the hemisphere) |
| 0x52 | `speed-over-ground` | knots |
| 0x53 | `magnetic-course` | the VW octet (with U in the attribute) |
| 0x54 | `gmt-time` | the RS octet (with T in the attribute), hours |
| 0x56 | `date` | day, year (month in the attribute) |
| 0x57 | `satellite-info` | HDOP (satellite count in the attribute) |
| 0x82 | `target-waypoint-name` | the three name octets and their complements |
| 0x84 | `heading-course-rudder` | heading VW, course XY, autopilot mode, alarms, rudder, SS, TT |
| 0x85 | `navigation-to-waypoint` | XTE low octet and the V, U, Z, W, ZZ, Y, F fields, the zero octet, the complement |
| 0x99 | `compass-variation` | degrees, signed |
| 0x9C | `heading-rudder` | heading VW, rudder |
| other | `other` | command, attribute high nibble, the first data octet and the rest (counted by the low nibble) |

## Shared keys

None. Latitude and longitude are split across the degrees octet and a word that mixes the hemisphere with
the minutes; a `core.lat` value would need arithmetic over two fields and a sign from a bit, and the
datum is not stated by the source.

## Not mapped

- **Values split across nibbles, octets and bits**: heading and course (U, VW, V, XY), time (T and RS),
  mileage (low and high parts), latitude and longitude minutes and hemisphere, the 0x85 distances and
  bearing, and the waypoint name's six-bit characters: each part is a key; the combining formulas are
  in the key descriptions. Combining them needs derived keys over several fields.
- **Depth bit 15**: kept in `depth_raw` (the source masks it before scaling).
- **The ninth (command) bit** of the bus and collisions: below this pack.
- Datagrams the source does not decode (autopilot commands 0x86, the 0x58 raw position, 0x30 lamp
  intensity and others): kept by `other`.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one datagram.

## Vectors

`tools/gen/seatalk-vectors.py`, without an engine: depth with flags; apparent wind angle and speed; speed
through water (0x20 and 0x26); total and trip log; water temperature; latitude south and longitude east;
GMT time; heading, course and rudder; compass variation; a waypoint name; another datagram (`other`); a
cut depth datagram (`malformed-wire`).
