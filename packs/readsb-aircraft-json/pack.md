# readsb-aircraft-json

The `aircraft.json` file that readsb and dump1090-fa write: an object with
`now`, `messages` and the array `aircraft`. Wire `json`, no kinds. The array is
the list `readsb.aircraft`, one item per aircraft object, with the same lines
and keys as pack `readsb-aircraft` (see its pack.md for the evidence of each
binding). Hand-written; vectors derived by
`tools/gen/alerts-adsbjson-vectors.py`.

## Message convention and limits

- One message is one `aircraft.json` document.
- List items carry no residue (0.7): an aircraft member no line maps
  (`alt_baro`, `alert`, `spi`, `wd`, `ws`, `oat`, `tat`, `r`, `t`, `dbFlags`,
  `lastPosition`, arrays) is dropped. A round trip is exact only when every
  member of every aircraft is mapped (vector 01); vector 02 shows the drop.
- Derived keys apply to the entity's own keys, not to items (0.7), so items
  hold `readsb.alt_geom` and `readsb.gs` but no `hae` or `speed_ms`.
- No other pack maps the list `readsb.aircraft`, so a conversion to GeoJSON or
  CoT carries nothing from the aircraft. For one aircraft at a time, use
  `readsb-aircraft`. A conversion that splits a list into one message per item
  is not in the pack language.
- `now` is `time_ms` through `iscale:1000` and also `readsb.now`, as in
  `readsb-aircraft` (see its pack.md for the evidence). The file's `now` is the
  entity's time; items have no `now`.

## Vectors

| File | Case |
|---|---|
| `01-file-roundtrip` | two aircraft, every member mapped |
| `02-item-members-unmapped-are-dropped` | items without residue |
| `03-no-aircraft` | empty array written as `[]` |
