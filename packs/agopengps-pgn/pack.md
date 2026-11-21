# agopengps-pgn

The PGN messages AgOpenGPS (open-source guidance and section control for farm machinery) passes
over UDP between AgIO, the AgOpenGPS application and its steering, section and task-controller
modules. They borrow the name PGN from ISO 11783 but are AgOpenGPS's own frames, not ISOBUS. Licence
Apache-2.0.

## Message convention

One UDP datagram: 0x80, 0x81, the source address, the PGN (one byte), the number of data bytes,
the data, and a one-byte sum of the bytes from the source address to the last data byte. Multi-byte
values are little-endian. `bits`, `layout sequential`, `bit_order lsb`; the data is a `length 8
bytes` block, so a kind reads only the data bytes the length byte counts.

## Kinds

One per documented PGN: 214 GPS position, 208 latitude and longitude, 211 IMU, 212 IMU disconnect,
221 display message, 222 remote commands, 228 rate control, 229 extended section control, 234
remote switches, 235 section dimensions, 236 relay configuration, 238 machine configuration, 239
machine data, 240 ISOBUS heartbeat, 241 section control enable, 242 process data, 243 field name,
250 sensor, 251 autosteer configuration, 252 autosteer settings, 253 steer module, 254 autosteer
data. Other PGNs are `no-kind`.

## Shared keys

| Field | Key | Evidence |
|---|---|---|
| PGN 214 longitude, latitude (doubles) | `lon`, `lat` | the document calls them the GPS longitude and latitude; AgOpenGPS reads the pair into its WGS 84 position type, in degrees (UDPComm.Designer.cs). `double.MaxValue` means no position: `absent` |
| PGN 208 latitude, longitude (int32) | `lat`, `lon` | the document and the encoder state the scale: the angle times 0x7FFFFFFF / 90 for latitude and / 180 for longitude, so `sscale:90/2147483647` and `sscale:180/2147483647` |

The altitude of PGN 214 is metres from the GGA sentence, a height above mean sea level, not a height
above the WGS 84 ellipsoid, so it is not `hae`. Headings, speed and roll stay raw: the document does
not state the speed's unit, and the single-antenna heading may be a course or a heading.

## Not mapped

- The checksum is a raw key and is not checked or recomputed. Missing: an additive (sum modulo 256)
  checksum on the `bits` wire. An entity from another format encodes with checksum 0, so there is
  no vector from geojson to this pack.
- Data bytes beyond those a kind names are skipped on decode and not written back (the steer
  module's eighth byte, for example): such a frame does not round-trip exactly.
- Text (PGN 221 message, 243 field name) and the bit masks of sections are carried as bytes.
- The document's PGN lengths are sometimes the whole frame and sometimes the data; the pack follows
  the length byte. PGN 214 has 51 data bytes as AgIO sends it.
