# readsb-aircraft

One aircraft object of the JSON that the ADS-B decoders readsb and
dump1090-fa write: a line of readsb's `--net-json-port` output ("one aircraft
object per line, each with its own now"), or one element of the `aircraft`
array of `aircraft.json` (pack `readsb-aircraft-json` reads the whole file).
Wire `json`, no kinds. Hand-written; vectors derived by
`tools/gen/alerts-adsbjson-vectors.py` (standard library only, no engine).

## Message convention

One message is one JSON object. Lines follow the member order of
README-json.md. Members no line maps are residue and come back on a round
trip, including nested objects of scalars (`lastPosition`); arrays (`mlat`,
`tisb`, `nav_modes`, `acas_ra`) are not carried (0.5, json residue).

## Shared-model keys and the evidence

| Member | Key | Evidence (README-json.md of readsb and dump1090-fa, in our words) |
|---|---|---|
| `lat`, `lon` | `lat`, `lon` | the aircraft position in decimal degrees. The document does not name the datum; the positions are those of ADS-B (RTCA DO-260B, to which the document refers), which are WGS 84, and the same document states the WGS 84 ellipsoid for `alt_geom` |
| `alt_geom` | `hae` (derived) | geometric (GNSS or INS) altitude in feet referenced to the WGS 84 ellipsoid. Carried as `readsb.alt_geom` in feet; `model/readsb.def` derives `hae = alt_geom * 3048 / 10000` (1 ft = 0.3048 m exactly) and the reverse |
| `gs` | `speed_ms` (derived) | ground speed in knots. Carried as `readsb.gs`; derived `speed_ms = gs * 1852 / 3600` (1 kt = 1852 m per hour exactly) and the reverse |
| `track` | `course` | true track over ground in degrees |
| `now` | `time_ms` | the time the object (or the file) was written, in seconds since the Unix epoch (1970-01-01 00:00:00 UTC), as a number with a fraction. Read with `iscale:1000` (engine-spec 0.15): the number's digits as an exact decimal times 1000, rounded, so `1714566600.5` is `1714566600500`. Encode writes `time_ms / 1000` exactly (`1714566600.5`, or `1714566601` for a whole second). The same member is also `readsb.now` (ruling 16 of 0.5); `time_ms` is the first line, so encode writes it when the entity has it |
| `flight` | `callsign` | callsign, the flight name or registration, 8 characters; trailing spaces are kept as written |
| `hex` | `uid` | the aircraft's 24-bit ICAO address as 6 hex digits, or a non-ICAO address marked by a leading `~`; it identifies the aircraft across messages |

The json wire has no scale transform, so the two unit conversions are derive
lines of the module. They run in `convert` between formats, not on a
same-format round trip, so `alt_geom` and `gs` round-trip as written.

## Not bound, and why

- `now` is bound to milliseconds: a `now` written with more than three
  fraction digits is rounded to the millisecond, and a round trip writes the
  rounded value. readsb and dump1090-fa write fewer digits than that. The
  position and the message are older than `now` by `seen_pos` and `seen`
  seconds; `time_ms` is `now`, the time the decoder wrote the report, not the
  time of the position.
- `seen_pos` and `seen` are ages relative to `now`; raw.
- `alt_baro` is a barometric altitude, not `hae`, and is either a number or the
  text `ground`; no single transform reads both, and a failing transform fails
  the decode, so no line maps it. It is residue and round-trips.
- `mag_heading`, `true_heading`, `nav_heading` are headings, not the track.
- `nav_altitude_mcp`, `nav_altitude_fms`, `nav_heading`: the document states no
  unit; raw.
- `rc` (metres) is a containment radius, not a circular error estimate; raw.
- `alert`, `spi`, `wd`, `ws`, `oat`, `tat`, `r`, `t`, `desc`, `dbFlags`,
  `lastPosition`, `rr_lat`, `rr_lon`, `gpsOkBefore`, `dst`, `dir`: residue.

## Vectors

| File | Case |
|---|---|
| `01-aircraft-roundtrip` | every mapped member, residue scalars and a nested object, arrays dropped |
| `02-aircraft-to-geojson` | lat, lon, hae from feet, speed from knots, course, callsign, id, `time_ms` from `now` |
| `03-aircraft-to-cot-xml` | to CoT with its defaults; `now` gives `time` and `start` |
| `04-ground-and-non-icao` | `alt_baro` "ground" as residue; `~` address |
| `05-latitude-as-text` | `transform-decode` |
| `packs/geojson/vectors/95-to-readsb-aircraft` | hae to feet, speed to knots |
| `packs/geojson/vectors/96-to-readsb-aircraft-with-time` | `time_ms` to `now` in seconds with a fraction |

The derived values were chosen to derive exactly: 1000 ft is 304.8 m, 360 kt is
185.2 m/s, and back.
