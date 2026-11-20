## The form

One message is one GOFS feed file (`gofs.json`, `system_information.json`, `zones.json` and
the others) as its JSON Schema in `MobilityData/gofs` (`schema/`) describes it. The
repository calls these schemas partial and a work in progress; the packs follow them as
they stand at the pinned commit. Each file is one object with `last_updated`, `ttl`,
`version` and `data`; the caller chooses the pack by the file it reads.

## Evidence for the shared keys

- `time_ms` (`last_updated`): every schema gives it as the last time the feed's data was
  updated, an integer of POSIX seconds, which count seconds since 1970-01-01 00:00:00 UTC.
  `iscale:1000` (engine-spec 0.15) reads it as milliseconds and writes it back as whole
  seconds; the raw key keeps the integer as written. GOFS shares this member with GBFS
  before 3.0 (packs `gbfs-1.0-*` to `gbfs-2.3-*`).

Not bound:

- Positions: `zones.json` holds a GeoJSON FeatureCollection whose geometries are arrays of
  coordinates; the json wire addresses no array element, so they are not mapped.
- `ttl` and other durations in seconds are raw keys.
