# usgs-earthquake

One earthquake event of the USGS Earthquake Hazards Program GeoJSON summary feed: a GeoJSON
Feature whose geometry is a Point `[longitude, latitude, depth]`. Wire `geojson`, no kinds.
Written by hand from the feed's documented member list; vectors are derived by
`tools/gen/usgs-earthquake-vectors.py` (standard library only, no engine; `--check`
compares). The whole feed, with its metadata and every event, is the pack
`usgs-earthquake-feed`.

## Message convention

One message is one Feature of the `features` array of a summary feed (`summary/*.geojson`),
or a feed of one event. Lines follow the document's order of the `properties` members.

## Shared-model keys and the evidence

| Member | Key | Evidence (USGS documentation, in our words) |
|---|---|---|
| `geometry` coordinate 1 | `lon` | the ComCat event terms give longitude in decimal degrees, negative to the west, in the WGS 84 reference frame |
| `geometry` coordinate 2 | `lat` | latitude in decimal degrees, negative to the south, WGS 84 |
| `properties.time` | `time_ms` | the time the event occurred (its origin time), in milliseconds since the Unix epoch, UTC, without leap seconds |
| `id` | `uid` | a unique identifier of the event; the documentation adds that it is the current preferred one and may change over time (the other identifiers are in `ids`) |

The event terms were read from the ComCat documentation as archived on 2026-04-14: the
feed page's links to them (`data/comcat/data-eventterms.php`) now redirect back to the
feed page.

## Not bound, and why

- The third coordinate is the depth in kilometres, measured from a reference that depends
  on the locating network (the WGS 84 geoid, mean sea level, or the stations' average
  elevation): raw key `usgsquake.depth_km`, not `hae`.
- `updated` is the time of the last update, not of the event: raw.
- `mag`, `sig`, `nst`, `rms`, `gap` and the rest are raw keys of the module `usgsquake`.

## Not mapped: members the feed sends as null

`tz`, `felt`, `cdi`, `mmi`, `alert` and `dmin` are `null` for most events (in a week of the
all-events feed read on 2026-11-20, `tz` in every event, `felt` and `cdi` in 95 %, `alert`
in 99 %). On the geojson wire a `null` under a `field` line fails its transform, and an
`absent` sentinel cannot name `null` (ruling 13 of 0.9), so these members are not lines of
this pack. They are residue: a `null` is dropped, and a number comes back as a string of its
text (ruling 13 of 0.6). The json pack `usgs-earthquake-feed`, where `null` is absent, maps
them. `title`, which the feed sends but the member list does not name, is residue too.

## Vectors

| File | Case |
|---|---|
| `01-event-roundtrip` | every mapped member, out of order; residue numbers back as strings |
| `02-event-nulls-roundtrip` | the members a small automatic event sends as null are dropped |
| `03-event-to-geojson`, `04-event-to-cot-xml` | to the shared formats; depth not carried |
| `05-time-not-integer` | `transform-decode` |
| `packs/geojson/vectors/97-to-usgs-earthquake` | GeoJSON to an event; hae not written as depth |

Every event is written for these vectors; none is taken from a live feed.
