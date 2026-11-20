# Pack: sensorthings-1.0

OGC SensorThings API Part 1: Sensing, version 1.0 (OGC 15-078r6): one entity as its JSON
object, including the MultiDatastream extension of clause 12. Written by hand from the
entity tables of clauses 8.2 and 12. Wire `json`.

This pack has the kinds and lines of `sensorthings-1.1` and one kind before them,
`MultiDatastream`. Its message convention, kinds, shared-key bindings with their evidence
(clause 8.2 has the same tables in both versions for `Thing.name`, `HistoricalLocation.time`
and `Observation.resultTime`), raw keys and what is not mapped are stated in
`packs/sensorthings-1.1/pack.md`. What differs:

- **MultiDatastream** (clause 12): selected when `multiObservationDataTypes` is present.
  `unitOfMeasurements` is the group `sensorthings.units` (name, symbol and definition of
  each element of the results) and `multiObservationDataTypes` the group
  `sensorthings.multi_observation_data_types` (the observation type of each element). Its
  `observedArea` keeps its type; its coordinates are not carried.
- **The result of a MultiDatastream's Observation** is an array, which the `json` wire does
  not carry outside a group, and a group cannot stand at `result` because the result of
  every other Observation is a scalar or an object. The output of such an Observation has no
  `result` (vector `multidatastream-observation-array-result-dropped`).
- **`properties`**: version 1.0 gives it to a Thing only; other entities of 1.0 have none.
  Wherever it occurs it is residue.

## Vectors

Written by `tools/gen/sensorthings-vectors.py`; see `packs/sensorthings-1.1/pack.md`. This
pack has in addition a MultiDatastream round trip and the dropped array result.
