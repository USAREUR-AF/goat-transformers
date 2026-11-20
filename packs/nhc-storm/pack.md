# nhc-storm

One active tropical cyclone of the National Hurricane Center's Tropical Cyclone Status JSON
file (`https://www.nhc.noaa.gov/CurrentStorms.json`): an element of its `activeStorms`
array. Wire `json`, no kinds. Written by hand from the NHC file reference; vectors are
derived by `tools/gen/nhc-vectors.py` (standard library only, no engine; `--check`
compares). The whole file is the pack `nhc-current-storms`.

## Shared-model keys and the evidence

| Member | Key | Evidence (NHC file reference, in our words) |
|---|---|---|
| `id` | `uid` | the storm identifier, always eight characters (basin, number, year) |
| `name` | `callsign` | the storm's name |
| `latitudeNumeric`, `longitudeNumeric` | `lat`, `lon` | the present storm centre in decimal degrees (see the note on the datum) |
| `lastUpdate` | `time_ms` | the time at which the storm status summary is valid; every date-time of the file is ISO 8601 in UTC (`...Z`) |
| `movementDir` | `course` | the present direction of motion, decimal degrees from true north |
| `movementSpeed` | `speed_ms` (derived) | the present speed of motion in miles per hour: raw key `nhc.movement_speed_mph`; `model/nhc.def` derives `speed_ms = mph * 1609344 / 3600000` (1 mph = 0.44704 m/s exactly) and the reverse |

**On the datum.** The reference gives the position in decimal degrees and names no datum.
NHC advisories give storm centres as geographic latitude and longitude; the pack takes
them as WGS 84, the datum of the shared model, and a consumer that needs the datum stated
in the source should treat these as approximate.

**On names.** The reference's rules say every property name is camelCase, and the site's
example file names the numeric position `latitudeNumeric` and `longitudeNumeric`; the
reference's annotated example writes `latitude_numeric` once. The pack follows the rule.

## Not mapped

- `intensity` (knots) and `pressure` (millibars): the reference lists them as numbers, and
  the site's example file sends them as text. A line can read one JSON type only, so they
  are not lines; at the top level they are residue and come back as sent, number or text.
- `fileUpdateTime` (sent inside each advisory object, not in the reference),
  `stormSurgeWatchWarningGIS` and `potentialStormSurgeFloodingGIS`: residue; a `null`
  member is not carried.
- `latitude` and `longitude` as text (`24.5N`) are raw keys.

## Vectors

| File | Case |
|---|---|
| `01-storm-roundtrip` | every documented member, text intensity and pressure, nested residue |
| `02-storm-numeric-intensity` | intensity and pressure as numbers |
| `03-storm-to-geojson`, `04-storm-to-cot-xml` | to the shared formats; speed from mph |
| `05-last-update-not-iso` | `transform-decode` |
| `packs/geojson/vectors/99-to-nhc-storm` | GeoJSON to a storm; speed to mph |

Every storm is written for these vectors; none is taken from the NHC example files.
