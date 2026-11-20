# uat

UAT (Universal Access Transceiver, 978 MHz) is the ADS-B data link of general aviation in the
United States below 18,000 ft, the counterpart of 1090 MHz Extended Squitter (pack `adsb`). This
pack reads the downlink ADS-B payloads an aircraft, a surface vehicle or a ground station
(TIS-B, ADS-R) sends. The layout is restated from the open decoder dump978 (PROVENANCE.md); the
standard itself, RTCA DO-282, is a paid document and was not used.

## Message convention

A message of this pack is one downlink payload after the receiver has removed the sync word and
corrected it with its Reed-Solomon parity: 18 bytes for a basic message (payload type 0), 34
bytes for a long message (payload types 1 to 31). This is the hex dump978 writes after `-` on
its raw output line, without the `;` and the metadata that follow. Uplink (FIS-B) frames are not
messages of this pack.

## Layout

`wire bits`, `bit_order msb`, `word_bytes 1`: offsets count from the most significant bit of the
first payload byte. dump978 numbers bytes from 1 and the bits of a byte from 1 (most significant)
to 8, so its byte `b`, bit `i` is offset `8 x (b - 1) + i - 1` here.

The header (bytes 1-4) holds the payload type (5 bits), the address qualifier (3 bits) and the
24-bit address. The payload type selects which parts follow (dump978's composition table):

| Kind | Payload type | Parts after the header |
|---|---|---|
| `basic` | 0 | state vector (bytes 5-17), one reserved byte |
| `long-sv-ms-auxsv` | 1 | state vector, mode status (18-29), auxiliary state vector (30-31) |
| `long-sv-auxsv` | 2, 5 | state vector, auxiliary state vector |
| `long-sv-ms-ts` | 3 | state vector, mode status, target state at byte 30 |
| `long-sv-ts` | 4 | state vector, target state at byte 30 |
| `long-sv-ts25-auxsv` | 6 | state vector, target state at byte 25, auxiliary state vector |
| `long-sv` | 7 to 10 | state vector |
| `header-only` | 11 to 31 | nothing dump978 decodes |

The payload type is also a raw key (`uat.payload_type`), so a kind that covers several codes
writes back the code it read. Bits dump978 does not decode are raw `reserved_bits_*` keys, so a
round trip is exact.

Inside the state vector the layout depends on other bits, which the pack states with gate blocks
(engine-spec 0.17): the air/ground state (airborne: north/south and east/west velocity and the
vertical rate; on the ground: ground speed, a track or heading angle and its type, the aircraft
size and the GPS antenna offset), the address qualifier (ADS-B, vehicle and beacon: the UTC
coupling bit and the uplink feedback; TIS-B and ADS-R: the site id), and the altitude type bit,
which says whether the state vector's altitude is pressure or geometric altitude (the auxiliary
state vector then holds the other).

## Shared keys

| Wire field | Key | Evidence (dump978, in this repository's words) |
|---|---|---|
| bytes 5-7, 23 bits | `lat` | the raw value times 360/2^24 degrees, less 180 when the result is above 90: a 23-bit two's-complement value with weight 180/2^23, `sscale:180/8388608` |
| bytes 7-10, 24 bits | `lon` | the raw value times 360/2^24 degrees, less 360 when the result is above 180: a 24-bit two's-complement value with the same weight |
| bytes 15-16, 9 bits, on the ground when the track/heading type is 1 (true track) | `course` | the raw value times 360/512 degrees, a true track: `uscale:45/64` |

Latitude and longitude are WGS 84: dump978 does not name the datum, but the UAT position is the
GNSS position the aircraft reports, and the weight is the 24-bit angular weighting that GDL 90
(pack `gdl90`) uses for the same UAT positions. The pack reads a position only when the latitude
and longitude bits are not all zero (a gate on bits 32-78): dump978 treats all-zero latitude,
longitude and NIC as no position.

Two points differ from dump978 at the edges. A latitude raw value of exactly 2^22 decodes as -90
here (two's complement) and as +90 in dump978; the two poles encode identically, as dump978
notes. A real position at exactly 0 degrees latitude and 0 degrees longitude reads as no
position here.

## Not mapped, and why

- **Altitudes** stay raw keys in feet: `uat.pressure_altitude_ft` (pressure altitude is not
  `hae`) and `uat.geometric_altitude_ft`, because dump978 does not state the height reference of
  the geometric altitude (ellipsoid or mean sea level). Both read (raw - 41) x 25 ft; raw 0 is
  absent.
- **Velocities**: each component is a sign bit and a magnitude where 0 means no data and the
  value is the magnitude minus 1 (times 4 when supersonic). No transform states "sign and
  magnitude, less one", so the raw sign and magnitude are kept and `track.vel_north_ms` and
  `track.vel_east_ms` are not bound. Missing: a sign-magnitude transform with an offset on the
  magnitude, or a `smscale` whose offset follows the sign.
- **Ground speed**: the raw value minus 1, in knots; the knot is 463/900 m/s, and an offset of
  -463/900 is not a decimal the scaled transforms accept. Raw.
- **Callsign**: dump978 packs the emitter category and eight characters into three 16-bit words
  in base 40 (three characters per word, the alphabet 0-9, A-Z, space and three more). The
  `chars` transform reads characters of a fixed bit width (`icao6`, `ais6`, `ascii7`); base 40 is
  not a bit width, so `callsign` is not bound and the three words are raw. Missing: a base-40
  (radix) character transform.
- **Magnetic or true heading** on the ground and the selected heading of the target state: raw
  (core `course` is the direction of travel, not the heading).
- **Address**: the 24-bit address is a raw integer, as in pack `adsb`; the address qualifier says
  whether it is an ICAO address.

## Vectors

`tools/gen/uat-vectors.py` builds every payload by placing each value at dump978's byte and bit
numbers, and computes the expected model with dump978's arithmetic; the GeoJSON text is written
to the rules of engine-spec 0.1.1. A round trip for each kind (payload types 0, 1, 2, 3, 4, 5, 6,
9 and 12), conversions to geojson (airborne, on the ground with a true track, a southern and
eastern position, no position) and from geojson (the basic kind), and a short input.
