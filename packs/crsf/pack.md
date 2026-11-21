# Pack: crsf

CRSF, the serial protocol of TBS Crossfire and ExpressLRS radio links (CRSFv3), written by
hand from the TBS CRSF specification. Wire `bits`, most-significant-bit first (the
specification makes every field big-endian), one byte per word. Seven kinds, one per
broadcast telemetry frame type (two for the battery frame, with and without its optional id
byte).

## The message

One frame without its CRC byte, in both directions:

| Bytes | Content | In the pack |
|---|---|---|
| 0 | sync: the serial sync byte 0xC8, or a device address | raw key `crsf.sync`; encode writes 0xC8 when the entity has no value (`default`) |
| 1 | frame length: type, payload and CRC, so payload size + 2 | each kind's first `when` |
| 2 | frame type | each kind's second `when` |
| 3 to end | payload | the kind's fields |

The CRC (CRC-8, polynomial 0xD5, over type and payload) is the byte after the payload. The
pack neither reads nor writes it: a sender appends it, a receiver checks and drops it, as for
`ubx-*` and `mavlink2`. A rule that computes a checksum is a pack-language addition
(`docs/roadmap.md`).

| Kind | Type | Length byte | Payload |
|---|---|---|---|
| `gps` | 0x02 | 17 | latitude, longitude (i32, 1e-7 degree), ground speed (u16, 0.1 km/h), heading (u16, 0.01 degree), altitude (u16, metres + 1000), satellites (u8) |
| `gps_extended` | 0x06 | 22 | fix type, north, east and up velocity (i16, cm/s), speed and heading accuracy, height above the ellipsoid (i16, m), horizontal and vertical accuracy (cm), a reserved byte, HDOP and VDOP (u8, tenths) |
| `vario` | 0x07 | 4 | vertical speed (i16, cm/s) |
| `battery` | 0x08 | 10 | voltage (i16, 0.1 V), current (i16, 0.1 A), capacity used (u24, mAh), remaining (u8, %) |
| `battery_id` | 0x08 | 11 | the same, then the sensor id (u8) |
| `link_statistics` | 0x14 | 12 | uplink RSSI of two antennas, link quality, SNR, active antenna, RF profile, uplink power, downlink RSSI, link quality and SNR |
| `attitude` | 0x1E | 8 | pitch, roll, yaw (i16, 100 microradians) |

## Evidence for the shared keys

- `lat`, `lon` (`gps`, `sscale:1/10000000`): the specification gives latitude and longitude
  as signed integers of degrees divided by ten million. They are the GNSS receiver's
  position; GNSS positions are on WGS 84, the datum of `lat` and `lon`.
- `speed_ms` (`gps`, `uscale:1/36`): ground speed in tenths of a kilometre per hour; one
  tenth of a km/h is 1/36 m/s.
- `hae` (`gps_extended`): the specification states the value is the height above the GPS
  ellipsoid in metres, not above mean sea level.
- `track.vel_north_ms`, `track.vel_east_ms`, `track.vel_up_ms` (`gps_extended`,
  `sscale:1/100`): northward, eastward and upward speed in cm/s, north, east and up positive
  as the specification states. `track.def` derives `course` and `speed_ms` from the first
  two on a conversion.

## Not mapped, or not bound

- **`gps` altitude**: metres plus a 1000 m offset; the specification does not say what it is
  measured from, so it is the raw key `crsf.gps_altitude` and not `hae`.
- **`gps` heading**: the specification does not say whether it is the vehicle's heading or
  its course over ground; raw key.
- **Variometer sign**: the vario frame gives a vertical speed without stating its sign
  convention; raw key, not `track.vel_up_ms`.
- **Attitude** angles, **battery** and **link statistics** values have no shared key; raw
  keys in the specification's units.
- **Frame types not mapped**: the satellite clock frame (0x03), barometric altitude, airspeed, heartbeat, RPM,
  temperature, voltages, VTX, magnetometer, accelerometer and gyro, RC channels (11-bit
  packed), the MAVLink-FC and ESP-NOW frames, GPS home, and every extended-header frame
  (parameters, commands). They select no kind (`no-kind`).
- **Flight mode (0x21)**: a NUL-terminated string whose length is the frame's; a `bits`
  field has a fixed size, so it is not mapped. A string that fills the rest of the frame is
  a pack-language addition.
- **Longer frames**: the specification allows a sender to append fields; a frame whose
  length byte differs from a kind's value selects no kind.

## Vectors

Written by `tools/gen/rc-telemetry-vectors.py` (no engine): a round trip per kind, the GPS
frame to geojson, a GeoJSON Feature to the GPS frame
(`packs/geojson/vectors/to-crsf-gps.json`), and an unmapped type that is `no-kind`.
