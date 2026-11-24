# Pack: sirf-binary

A SiRF binary frame: start A0 A2, the payload length, the
payload, the checksum, end B0 B3. Wire `bits`, `layout sequential`, `bit_order msb` (big-endian). One kind,
`sirf`. Written by `tools/gen/gnssbin-pack.py`.

## What is mapped

- **Frame**: the payload length (`length 16 bytes`), the message ID, the checksum (as sent), the end.
- **MID 41, Geodetic Navigation Data**, the fields gpsd reads: navigation type, extended week, time of
  week, the UTC date and time, latitude, longitude, the altitude above the ellipsoid and above mean sea
  level, the map datum, speed, track, climb, the horizontal and vertical position error, the speed error,
  HDOP. The octets gpsd does not read are kept as hexadecimal (`unread_*`), so the frame round trips.
- Any other message: the payload after its ID as octets.

## Shared keys

- **lat, lon** (`core.lat`, `core.lon`, degrees): gpsd reads the 32-bit signed values at payload offsets
  23 and 27 and multiplies them by 1e-7 to get its latitude and longitude in degrees (`sscale:1/10000000`).
- **hae** (`core.hae`, metres above the WGS84 ellipsoid): gpsd reads the signed value at offset 31,
  multiplies it by 1e-2 into its altitude above the ellipsoid, under its comment that the altitude is
  WGS84; the value at offset 35 is the altitude above mean sea level and is `sirf.altitude_msl`.
- **Datum**: the frame carries a map datum code (offset 39) that gpsd skips. The binding takes the
  positions as WGS84, as gpsd does; a receiver set to another map datum would report positions in that
  datum, and the code is kept in `sirf.map_datum` so a consumer can check it.
- **time_ms** is not bound: the extended week and time of week count GPS weeks and seconds, and the UTC fields are left
  empty by older firmware (gpsd notes this); the conversion needs leap seconds.

## Not mapped

- **The checksum computed** (the payload's sum, 15 bits): kept as sent.
- **Other messages** (2 Measure Navigation Data, 4 tracker data, 7 clock status, 8 navigation subframes
  ...): octets.
- **The octets gpsd does not read** in MID 41: kept as hex, not named.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one frame, start to end.

## Vectors

`tools/gen/gnssbin-vectors.py`, without an engine: MID 41 with a 3-D fix; MID 41 south and west with a
negative ellipsoidal height; another message as octets; a wrong start (`no-kind`); a cut frame
(`malformed-wire`); MID 41 converted to GeoJSON (the point from lat, lon and hae).
