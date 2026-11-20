# usgs-earthquake-feed

The USGS Earthquake Hazards Program GeoJSON summary feed as a whole: a GeoJSON
FeatureCollection with `metadata`, `bbox` and `features`, read on the `json` wire. Written
by hand from the feed's documented member list; vectors are derived by
`tools/gen/usgs-earthquake-vectors.py`. One event on the geojson wire, with its position
bound, is the pack `usgs-earthquake`.

## Shared-model keys and the evidence

| Member | Key | Evidence |
|---|---|---|
| `metadata.generated` | `time_ms` | the ComCat event terms (archived 2026-04-14): the time the feed was last updated, in milliseconds since the Unix epoch |

Every event of `features` is an item of the list `usgsquake.events`. Inside an item the
origin time is `time_ms` and the identifier `uid`, with the evidence of `usgs-earthquake`;
a list item does not reach the message's own keys, so no other format sees them. An item's
coordinates are the list `usgsquake.coordinates` (longitude, latitude, depth in km, in that
order): the json wire addresses no position inside an array, so they are not bound to
`lon` and `lat`.

## Notes

- On the json wire a `null` member is absent, so every documented member is mapped,
  including those the feed usually sends as null (`tz`, `felt`, `cdi`, `mmi`, `alert`,
  `dmin`).
- The FeatureCollection's `type` and each event's `type` and `geometry.type` are `const`
  lines: written on encode, not checked on decode.
- An item has no residue (0.7): an event member the list does not name (`title`) is dropped.
