# gpsd-json

The JSON protocol of gpsd, the GNSS service daemon (gpsd_json(5)): one response or
report object per message, its kind chosen by the member `class`. Wire `json`, 16 kinds,
written by hand from the member tables of the document. Vectors are derived by
`tools/gen/gpsd-json-vectors.py` (standard library only, no engine; `--check` compares).

## Message convention

One message is one JSON object, without the CR-LF gpsd ends it with. Each kind has a
`when class <VALUE>` line; the encoder writes `class` first, then the members in the order
of the document's table, then members no line maps (residue). The document states that
the order of members is never significant, so this order is the pack's canonical form.

| Kind | class | What it is |
|---|---|---|
| `tpv` | TPV | time, position, velocity report |
| `sky` | SKY | sky view; `satellites` is the group `gpsd.satellites` |
| `gst` | GST | pseudorange noise statistics |
| `att`, `imu` | ATT, IMU | attitude; the same members, IMU sent as soon as measured |
| `pps`, `toff` | PPS, TOFF | PPS edge and serial-time offset against the system clock |
| `osc` | OSC | GPS-disciplined oscillator status |
| `version` | VERSION | daemon and protocol version |
| `devices` | DEVICES | device list; `devices` is the group `gpsd.devices` of DEVICE objects |
| `device` | DEVICE | one device |
| `watch` | WATCH | watcher policy |
| `poll` | POLL | cached `tpv` and `sky` lists (groups `gpsd.poll_tpv`, `gpsd.poll_sky`) |
| `error` | ERROR | error text |
| `subframe` | SUBFRAME | the header members of a subframe dump |
| `ack` | ACK | acknowledgement, `class` only |

The `class` member inside a DEVICES, POLL `tpv` or POLL `sky` item is a `const` of the
group: written by the encoder, not checked on decode.

Encoding from another format picks the first kind whose `requires` hold: `tpv` when the
entity has `lat` and `lon`. Every other kind requires a raw key of its own; `ack` requires
`gpsd.ack`, which no line maps, so an entity of another format never encodes as ACK.

## Shared-model keys and the evidence (TPV and POLL `tpv` items)

| Member | Key | Evidence (gpsd_json(5), in our words) |
|---|---|---|
| `lat` | `lat` | latitude in degrees, positive north |
| `lon` | `lon` | longitude in degrees, positive east |
| `altHAE` | `hae` | altitude as height above the ellipsoid, in metres, "probably WGS84" |
| `speed` | `speed_ms` | speed over ground, metres per second |
| `track` | `course` | course over ground, degrees from true north |
| `time` | `time_ms` | ISO 8601 time stamp in UTC, up to millisecond precision; `iso8601_ms` reads it |

`time` of SKY, GST, ATT, IMU and POLL is the same kind of time stamp and is `time_ms`
too.

**On the datum.** The document does not name a datum for `lat` and `lon`; TPV has a
member `datum` that it describes as "hopefully WGS84", and it qualifies `altHAE` with
"probably WGS84". A receiver reporting in another datum names it in `datum`, which this
pack carries as `gpsd.datum`; the binding assumes WGS 84, the datum of GNSS fixes. A
consumer that must be sure checks `gpsd.datum`.

## Not bound, and why

- `alt` is deprecated and undefined; `altMSL` is above the geoid, not the ellipsoid:
  raw `gpsd.alt`, `gpsd.alt_msl`.
- `eph`, `epv` and the other `ep*` estimates: the document guesses 95 % confidence and says
  the confidence is unknown; `ce` and `le` would claim a stated meaning. Raw.
- `magtrack` is magnetic; `velN`/`velE`/`velD` would be `track.vel_*` but the document
  gives their unit as metres (not metres per second), so they are raw.
- GST's `lat`, `lon` and `alt` are standard deviations in metres, not a position:
  `gpsd.gst_lat` and so on.
- ATT's `heading` is the vehicle's attitude, not its course over ground: raw.
- TOFF and PPS give times as integer seconds and nanoseconds; no transform joins them into
  milliseconds. Raw.
- DEVICE `activated` is not mapped: the table says an ISO 8601 string, and the document
  also shows `0` for a deactivated device. Unmapped, it is residue and round-trips as
  either.
- Members outside the tables (ATT `mode`, TOFF `precision`, the undocumented WATCH
  `timing`) are residue.

## Not mapped

- AIS, RTCM2, RTCM3 reports, the SUBFRAME page sub-object, and NMEA or raw dumps: the
  document defers their members to other documents or to the source code. A message with
  class AIS, RTCM2 or RTCM3 is `no-kind`.
- Items of a group carry no residue (0.7): a member of a satellite, a DEVICE in DEVICES, or
  a TPV or SKY in POLL that no line maps is dropped.
- `mode` cannot be supplied when another format is converted to TPV; gpsd always sends it,
  this pack writes it only when the entity has `gpsd.mode`.

## Vectors

| File | Case |
|---|---|
| `01-tpv-roundtrip` | every TPV member, out of order, plus residue |
| `02-sky-roundtrip` | SKY with three satellites |
| `03-gst-roundtrip` … `16-subframe-header-roundtrip` | one round trip per other kind |
| `17-tpv-to-geojson`, `18-tpv-to-cot-xml` | TPV to the shared formats |
| `19-unknown-class-is-no-kind`, `20-no-class-is-no-kind` | `no-kind` |
| `21-latitude-as-text`, `22-time-without-designator` | `transform-decode` |
| `packs/geojson/vectors/96-to-gpsd-json-tpv` | GeoJSON to TPV |
| `packs/cot-xml/vectors/21-to-gpsd-json-tpv` | CoT to TPV |

Every message is written for these vectors; none is taken from the document.

## Validity flag not applied

TPV `mode` 0 (unknown) and 1 (no fix): gpsd_json.adoc says there is likely no usable data then, and TPV `time` may be present but invalid without a fix. The pack keeps the flag as a raw key and binds the position whatever it says: a message whose
flag says there is no fix converts with the coordinates it carries (often 0, 0), as if they were a
position. The pack language has no gate for a JSON or protobuf member yet (asked of gt-lang); until
it has, a consumer must read the flag. Bit-level packs of the same messages (PX4) read the shared
keys only when the flag says so.
