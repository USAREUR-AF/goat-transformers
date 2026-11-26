# Pack: ltm

LTM (Lightweight Telemetry), the one-way telemetry INAV sends to ground stations and antenna
trackers. Written by hand from INAV's LTM telemetry code (`src/main/telemetry/ltm.c`).
Wire `bits`, least-significant-bit first (fields are little-endian), one byte per word.
Four kinds.

## The message

One frame without its checksum byte: `$` `T` (common `when` lines), the frame letter (each
kind's `when`), the payload. The checksum, the XOR of the payload bytes, follows the
payload and is not read or written. LTM has no length byte: each letter has a fixed size.

| Kind | Letter | Payload |
|---|---|---|
| `g` | G | latitude, longitude (i32, 1e-7 degree), ground speed (u8, m/s), altitude (i32, cm, relative to home), then one byte: satellites (bits 2 to 7) and fix type (bits 0 and 1) |
| `a` | A | pitch, roll, heading (i16, degree) |
| `s` | S | battery voltage (u16, mV), consumed capacity (u16, mAh), RSSI (u8, 0 to 254), airspeed (u8, m/s), then one byte: armed (bit 0), failsafe (bit 1), flight mode (bits 2 to 7) |
| `o` | O | home latitude and longitude (i32, 1e-7 degree), home altitude (i32), OSD on (u8), home fixed (u8) |

## Evidence for the shared keys

- `lat`, `lon` (`g`, `sscale:1/10000000`): the GNSS solution's latitude and longitude in
  degrees times 1e7 (`gpsSol.llh`); GNSS positions are on WGS 84.
- `speed_ms` (`g`, `uscale:1`): the ground speed of the GNSS solution, in whole metres per
  second (the code divides cm/s by 100).
- Only with a fix. `ltm_gframe` starts lat, lon and ground speed at 0 and the fix type at
  0, and fills them only when a GPS is present: fix type 1 for no fix (with the
  solution's last values), 2 for 2D, 3 for 3D. The three shared lines therefore lie in a
  gate block `if !0:128:2 0,1` (engine-spec 0.17): a frame with fix type 0 or 1 gives no
  position. The same bits are always the raw keys `ltm.g_lat`, `ltm.g_lon` and
  `ltm.g_ground_speed`, so every G frame comes back byte for byte. Encoded from `lat` and
  `lon` with no `ltm.g_fix_type`, the frame gets fix type 2, the smallest value the gate
  holds for; with a fix type of 0 or 1 given, an entity whose position is only in `lat`
  and `lon` is `transform-encode`.

## Not mapped, or not bound

- **`g` altitude**: the navigation estimate of height, relative to the home position; not
  `hae`. Raw key.
- **`o` home position**: the home point, not the vehicle's position; raw keys, not `lat`
  and `lon`.
- **The N (navigation status) and X (extended) frames** of INAV, and frames of other LTM
  implementations: not mapped.

## Vectors

Written by `tools/gen/rc-telemetry-vectors.py` (no engine): a round trip per kind, the G
frame to geojson, a GeoJSON Feature to the G frame (`packs/geojson/vectors/to-ltm-g.json`),
a G frame cut short, `malformed-wire`, a G frame without GPS to geojson (no position) and a
G frame without a fix as a round trip.
