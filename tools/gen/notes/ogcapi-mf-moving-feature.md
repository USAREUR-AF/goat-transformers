## What is not carried

A moving feature in MF-JSON Prism: a GeoJSON-like Feature whose `temporalGeometry` holds the
trajectory. It is read on the json wire, not the geojson wire, because the trajectory is a
top-level member. No shared key is bound:

- **The trajectory positions.** `temporalGeometry.coordinates` is an array of positions, each
  an array of numbers: an array of arrays is not addressable on the json wire, so the
  positions are not mapped, and no single position could be bound to `lat` and `lon` anyway
  (a track of many points; the model holds one position). `temporalGeometry.datetimes` (the
  instants of the positions) is mapped as a list of strings.
- **`id`.** A string or an integer; no transform reads either, so `uid` is not bound.
- **`properties`** (open), **`geometry`** (the static GeoJSON geometry, outside this schema
  set) and the temporal property values, keyed by property name, are not mapped.

A pack-language addition that reads an array of fixed-length number arrays into a list of
positions would carry the trajectory.
