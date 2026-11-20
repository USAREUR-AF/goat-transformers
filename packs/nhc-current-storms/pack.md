# nhc-current-storms

The whole NHC Tropical Cyclone Status JSON file (`CurrentStorms.json`): an object with one
member, `activeStorms`, the array of active storms (empty when there is none). Wire `json`;
the array is the list `nhc.storms`, one item per storm, with the lines and evidence of the
pack `nhc-storm`.

- Inside an item the storm's id, position, time and course are `uid`, `lat`, `lon`,
  `time_ms` and `course`; a list item does not reach the message's own keys, so no other
  format sees them, and derived keys (the speed in m/s) do not apply to items. One storm at
  a time, with its position bound, is the pack `nhc-storm`.
- Items carry no residue (0.7): a storm member no line maps (`intensity`, `pressure`,
  `fileUpdateTime`, the storm surge GIS objects) is dropped.
