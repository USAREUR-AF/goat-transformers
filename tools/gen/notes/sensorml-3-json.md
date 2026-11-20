## What a message is

One SensorML 3.0 description as the JSON object the JSON encoding defines: a
PhysicalSystem, a PhysicalComponent, a SimpleProcess, an AggregateProcess or a Deployment.
The member `type` selects the kind.

## Evidence for the shared keys

- `uid` (`uniqueId`, every kind): the schema describes it as the URI that serves as the
  globally unique identifier of the described feature, typically a URN. That is the stable
  identifier of the entity the message describes.
- `callsign` (`label`, every kind): the schema describes it as a human-readable label for the
  feature, the meaning of `callsign` in the shared model.

Not bound:

- `position` of a PhysicalSystem or PhysicalComponent may be a GeoJSON Point, a GeoPose, a
  SWE Common Vector or DataRecord, or a reference. A Point's position is the array
  `coordinates`, which the `json` wire cannot address element by element, so `lat` and
  `lon` are not bound (an array-index locator would allow it).
- `validTime` is a period (an array of two instants), not the time of a report.

## Licence basis

The schemas are published by OGC in `opengeospatial/ogcapi-connected-systems` under the OGC
Software License (the repository's `LICENSE`); `schemas.opengis.net/sensorML/3.0/json/`
holds the same files with other relative reference paths. That license permits use, copying
and modification provided the copyright notice is kept and a modified copy says it holds
changes OGC has not approved. This pack is such a change: it is derived from the schemas and
has not been approved or adopted by OGC. `PROVENANCE.md` keeps the notice in full.
