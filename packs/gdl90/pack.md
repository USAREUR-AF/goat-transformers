# Pack: gdl90

GDL 90 message payloads, the serial and UDP protocol between UAT/ADS-B
receivers and cockpit displays, together with the two ForeFlight extension
messages that travel in the same stream. Public. Every layout is restated from
Stratux (BSD-3-Clause, commit `36b504555408fb90dd5cf1171d4f91f99571e50c`), an
open-source receiver that writes these messages; no other source was used
(`PROVENANCE.md`). I/O is hex text. Needs engine version 0.9 (`absent`; kinds,
`bit_order msb`, `swap`, `trim`, `default`).

Uses the modules `core` and `gdl90` (`model/gdl90.def`).

## Message convention

A message of this pack is one **payload**: byte 0 is the message ID, and the
bytes follow as Stratux builds them before `prepareMessage`. On the wire a
payload is framed: a 0x7E flag, the payload and a 2-byte CRC (polynomial
0x1021, register starting at 0, low byte first), with every 0x7E or 0x7D byte
of payload and CRC sent as 0x7D followed by the byte XOR 0x20, and a closing
0x7E flag. The pack holds none of that. A caller removes the flags, undoes the
escapes, checks and drops the CRC, and passes the payload. The framed form of
each round-trip vector is in its `reference`, computed by
`tools/gen/gdl90-vectors.py`. Addition that would hold the framing: "Layered
wires and framing" (docs/roadmap.md, Designed): flag delimiting, byte
stuffing and a CRC-16 checksum rule around a payload pack.

Decode reads the bytes the selected kind maps and ignores any after them;
input shorter than the kind is `malformed-wire`.

## Kinds

Bits count from the most significant bit of byte 0 (`word_bytes 1`,
`bit_order msb`); byte *n* starts at offset 8*n*.

| Kind | ID (`when`) | Bytes | Stratux function |
|---|---|---|---|
| `heartbeat` | 0 | 7 | `makeHeartbeat` |
| `uplink` | 7 | 4 mapped (+ 432 payload, not mapped) | `relayMessage` |
| `traffic` | 20 | 28 | `makeTrafficReportMsg` |
| `ownship` | 10 | 28, the traffic layout | `makeOwnshipReport` |
| `ownship-geometric-altitude` | 11 | 5 | `makeOwnshipGeometricAltitudeReport` |
| `foreflight-id` | 0x65, sub-ID 0 | 39 | `makeFFIDMessage` |
| `foreflight-ahrs` | 0x65, sub-ID 1 | 12 | `makeFFAHRSMessage` |

`model/gdl90.def` states each field. Points worth knowing:

- **Heartbeat time.** The seconds since 0000Z are 17 bits: bit 16 is the
  most significant bit of byte 2 and the low 16 bits are bytes 3-4, least
  significant byte first (`swap`). Two keys hold them; the date is not in the
  message, so nothing maps to `time_ms`.
- **Heartbeat status bits.** Stratux writes four bits of byte 1 and two of
  byte 2 and names them; the others, and the two message-count bytes (a TODO
  in Stratux), are carried as raw keys so a message round-trips.
- **Reports.** Byte 1 holds the alert status (high nibble) and address type
  (low nibble); bytes 2-4 the address; 5-7 and 8-10 latitude and longitude;
  11 and the high nibble of 12 the altitude code; the low nibble of 12 the
  airborne, extrapolated and track-type bits; 13 NIC and NACp; 14-16 speed and
  vertical velocity (12 bits each); 17 track; 18 emitter category; 19-26 the
  call sign; 27 priority status and a spare nibble.
- **ForeFlight ID capabilities.** Stratux writes the mask in byte 38 alone and
  leaves bytes 35-37 zero; the pack maps them so.

## Shared keys, with evidence

| Field | Key | Evidence |
|---|---|---|
| report bytes 5-7, 8-10 | `lat`, `lon` (`sscale:180/8388608`) | Stratux `makeLatLng` divides degrees by `LON_LAT_RESOLUTION = 180.0 / 8388608.0` and writes the 24-bit two's complement result, most significant byte first; decode is the count x 180/2^23 degrees. The degrees are those of Stratux's GPS fixes (`mySituation.GPSLatitude`) and of decoded ADS-B/UAT positions. Stratux states no datum for them; its GPS heights are relative to the WGS 84 ellipsoid (`gps.go`, `GPSHeightAboveEllipsoid`) and it applies no datum shift, so the positions are taken as WGS 84. This is the one inference in the pack. |
| report bytes 19-26 | `callsign` (`ascii trim`) | Stratux writes the tail number or call sign, up to 8 ASCII characters, NUL-padded, in both reports. |

Encode precision: `sscale` rounds half away from zero, Stratux truncates
(`int32(v)`). A position that is a whole number of counts encodes the same in
both; others can differ by one count (about 2 m).

Not bound, and why:

- Pressure altitude (`gdl90.alt_raw`, feet = 25 x raw - 1000) is barometric,
  not `hae`. Limit: in a traffic report Stratux does not always put a pressure
  altitude there. Its UAT decoder (`traffic.go`, `parseDownlinkReport`) keeps a
  target's altitude together with a flag, `AltIsGNSS`, set from the frame when
  the target reports a geometric altitude, and `makeTrafficReportMsg` writes
  that altitude without testing the flag. The traffic report has no bit to say
  which one it is, so `gdl90.alt_raw` and `gdl90.pressure_alt_ft` of a Stratux
  traffic report may hold a GNSS altitude, and the pack cannot tell.
- Geometric altitude (`gdl90.geo_alt_ft`): Stratux writes GPS altitude above
  mean sea level and sets ForeFlight capability bit 0 to say so; its `gps.go`
  notes that the height above the WGS 84 ellipsoid is what the protocol
  specifies and that most displays use MSL. The reference is the sender's, so
  it is not `hae`.
- Speed (knots): Stratux states no "no information" code for it; it writes
  the speed whether or not it has one and says which by `track_type` (0 = not
  valid). A pack cannot make a key absent on another field's value, so
  `speed_ms` stays unbound; the raw knots are `gdl90.speed_kt`.
- Vertical velocity: with its sentinel now absent (`gdl90.vvel_fpm`, ft/min),
  but Stratux does not state the sign of the report field (up or down
  positive), so it is not `track.vel_up_ms`.
- Track: valid only by `track_type`, and magnetic or true by the same bits.
- Address: a 24-bit integer; `uid` is a string.

## "No value" codes (engine-spec 0.9)

Version 0.2 of the pack marks each value Stratux names as meaning "no value"
with the field option `absent`. A field that holds it decodes to no key; an
entity without the key writes it.

| Field | Code | Stratux |
|---|---|---|
| pressure altitude (`gdl90.alt_raw`, `gdl90.pressure_alt_ft`) | 4095 (0xFFF) | `makeOwnshipReport`: "invalid altitude"; `makeTrafficReportMsg`: invalid or unavailable |
| vertical velocity (`gdl90.vvel_raw`, `gdl90.vvel_fpm`) | 0x800 | `makeOwnshipReport`: no information available |
| geometric altitude figure of merit (`gdl90.geo_fom_raw`) | 0x7FFF | `makeOwnshipGeometricAltitudeReport`: not available |
| ForeFlight ID serial (`gdl90.ff_serial`) | all 0xFF (2^64 - 1) | `makeFFIDMessage`: invalid |
| AHRS roll and pitch (`gdl90.ahrs_*_tenths`, `gdl90.ahrs_*_deg`) | 0x7FFF | `makeFFAHRSMessage`: values if invalid |
| AHRS heading, indicated and true airspeed | 0xFFFF | `makeFFAHRSMessage`: values if invalid |

With the codes out of the way, three values gain a scaled key on the same
bits, after the raw key: `gdl90.pressure_alt_ft` (`uscale:25:-1000`, feet),
`gdl90.vvel_fpm` (`sscale:64`, ft/min) and `gdl90.ahrs_roll_deg`,
`gdl90.ahrs_pitch_deg` (`sscale:1/10`, degrees). On encode the raw key wins
when both are present (engine-spec 0.5 ruling 5). They are raw keys of
`gdl90`: pressure altitude is barometric, not `hae`, and the sign of the
vertical velocity is not stated.

The `default` lines of version 0.1 for the altitude and the vertical velocity
are gone: the first sentinel is what an absent key now writes, so a position
from another format still does not read as -1000 ft, with the same bytes.
`traffic` is the kind an entity from another format encodes as (its `requires`
is `lat lon`).

## Not mapped

| Part | Why |
|---|---|
| Framing: flags, escapes, CRC | layered framing and a checksum rule, Designed |
| Uplink payload (432 bytes after the 4 header bytes) | binary; the `bits` wire has no bytes transform. Encode writes the 4 header bytes |
| Message IDs other than the seven kinds (for example the pass-through basic and long reports 0x1E and 0x1F that Stratux relays, its own 0x4C and status messages) | not requested; the ones Stratux relays carry binary UAT payloads, as the uplink |
| The meaning of the bits Stratux does not write | Stratux states none; they are raw keys |

## Vectors

22 vectors (19 under `vectors/`, the three from `geojson` under `packs/geojson/vectors/to-gdl90-*`), written by `tools/gen/gdl90-vectors.py`
(standard library only, imports no engine) from its own layout tables:
round trips of every kind (two heartbeats, traffic, ownship, two geometric
altitudes, ForeFlight ID, two AHRS), the uplink with its payload dropped,
traffic to GeoJSON and to CoT, GeoJSON to traffic, a longitude of 180 degrees
(`transform-encode`), two unknown IDs (`no-kind`) and two cut messages
(`malformed-wire`).

Added with version 0.2 (vectors 19, 20, 22 and `to-gdl90-geojson-to-traffic-pressure-altitude-from-context`):
an ownship whose altitude and vertical velocity are sentinels takes both from
the convert context, which fills only absent keys; a traffic report with real
values keeps them under the same context; a GeoJSON point with a pressure
altitude in feet from the context encodes the altitude code 220; an AHRS roll
of 0x7FFF takes its degrees from the context. The vectors of version 0.1 whose
fields hold sentinels now pin no key for them.

## Golden vectors

16 vectors `golden-<kind>-<n>.json`, written by `tools/gen/golden-gdl90.py` from gdl90
(github.com/etdey/gdl90, MIT; PROVENANCE.md), a reference GDL 90 encoder and decoder, run, not
copied. The inputs are the heartbeat and geometric altitude messages of its decoder tests and
messages its encoder builds: 3 heartbeats, 5 traffic and 2 ownship reports (positions in every
quadrant and at the ends of the field, altitudes from -1,000 to 101,350 ft, vertical rates of
both signs), 3 geometric altitudes and 2 ForeFlight ID messages. Each frame is unframed and its
CRC checked with the reference's own check; the payload is a round trip, and the model values are
what the reference decodes (for the ForeFlight ID message, which it does not decode, the arguments
its encoder took). Not compared, each for a reason in the reference (the script names them): the
alert status (its decoder reports 0 for every status), velocities of "no data" (it reports 0), the
reserved bit of the heartbeat's message counts, and the uplink and AHRS messages (it has no encoder
for them).

Text padding. Every call sign and ForeFlight name in these vectors fills its field. The GDL 90
ICD (Rev A, 3.5.1.11) allows only `0` to `9`, `A` to `Z` and the space in a call sign, the space
as the trailing pad; the reference pads with spaces, and so do the two report messages of its tests.
This pack writes NUL padding, as Stratux does (above) and as `ascii` encodes; decode, with `trim`,
reads either. So a report with a short call sign written by an ICD-conformant sender comes back
NUL-padded: the call sign is kept, the bytes are not. The ForeFlight specification says only
"UTF8 string" for the two names.
