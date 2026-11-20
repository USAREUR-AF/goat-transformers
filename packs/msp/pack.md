# Pack: msp

MSP v1, the MultiWii Serial Protocol as INAV and Betaflight speak it, for four replies of
the flight controller. Written by hand from INAV's message definitions
(`docs/development/msp/msp_messages.json`) and its MSP serial code
(`src/main/msp/msp_serial.c`, `msp_serial.h`) for the frame. Wire `bits`, least-significant-bit first (MSP
is little-endian), one byte per word. Four kinds.

## The message

One reply frame without its checksum byte: `$` `M` `>` (the common `when` lines; a request
`<` or an error `!` frame selects no kind), the payload size (u8), the command (u8), the
payload. The checksum, the XOR of size, command and payload, follows the payload; the pack
neither reads nor writes it (as for `ubx-*`).

| Kind | Command | Size | Payload |
|---|---|---|---|
| `raw_gps` | 106 MSP_RAW_GPS | 18 | fix type, satellites, latitude and longitude (i32, 1e-7 degree), altitude (i16), ground speed (i16, cm/s), ground course (i16, 0.1 degree), HDOP (u16, hundredths) |
| `attitude` | 108 MSP_ATTITUDE | 6 | roll and pitch (i16, 0.1 degree), yaw (i16, degree) |
| `altitude` | 109 MSP_ALTITUDE | 10 | estimated altitude (i32, cm), vertical speed (i16, cm/s), barometric altitude (i32, cm) |
| `analog` | 110 MSP_ANALOG | 7 | battery voltage (u8, 0.1 V), consumed capacity (u16, mAh), RSSI (u16), current (i16, 0.01 A) |

## Evidence for the shared keys

- `lat`, `lon` (`raw_gps`, `sscale:1/10000000`): degrees times 1e7 from the GNSS solution
  (`gpsSol.llh`); GNSS positions are on WGS 84.
- `speed_ms` (`raw_gps`, `sscale:1/100`): ground speed in cm/s.
- `course` (`raw_gps`, `sscale:1/10`): ground course of the GNSS solution in tenths of a
  degree, the direction of travel over ground.

## Not mapped, or not bound

- **Altitude of `raw_gps`**: above mean sea level, not the ellipsoid, and the definition
  gives centimetres in its unit column but whole metres in its note; raw key `msp.raw_gps_altitude`.
- **`altitude` kind**: altitude above home or sea level and barometric altitude; neither is
  `hae`. Raw keys.
- **Attitude, analog values**: no shared key; raw keys.
- **Every other MSP message** (INAV defines about 280) and the request frames: not mapped.
  `msp_messages.json` is machine-readable, so a generator could add them.

## Vectors

Written by `tools/gen/rc-telemetry-vectors.py` (no engine): a round trip per kind, the raw
GPS reply to geojson, a GeoJSON Feature to the raw GPS reply
(`packs/geojson/vectors/to-msp-raw-gps.json`), and a request frame that is `no-kind`.
