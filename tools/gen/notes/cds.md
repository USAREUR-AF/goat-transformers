## The form

One message is one object of a CDS data model as the Curbs, Events and Metrics APIs return
it in their `data` arrays (a Curb Zone, a Curb Event, an Aggregate, ...), described by
`Shared Data Models/<model>.yaml` of `openmobilityfoundation/cds-openapi`, the OpenAPI form
of CDS 1.1.0. The API's response envelope (`version`, `time_zone`, `data`) is not a pack.

## Evidence for the shared keys

- `uid`: the model's own identifier (`curb_zone_id`, `curb_area_id`, `curb_space_id`,
  `curb_object_id`, `event_id`), which the specification's README gives as the ID of that
  record (a UUID). Curb status, session and aggregate records have no identifier of their
  own and bind none.
- `time_ms`: CDS timestamps are integers of milliseconds since 1970-01-01 UTC
  (`timestamp.yaml`), the unit of `time_ms`. Bound for `last_updated_date` of zones, areas,
  spaces and objects (when the record's properties were last updated, which the README
  states) and for `event_time` of events (when the event occurred). Other times
  (`published_date`, `start_date`, `end_date`, `event_publication_time`) are raw keys.

Not bound:

- **Positions.** Geometries (`geometry`, `event_location`) are GeoJSON geometry objects
  nested in the record; their coordinates are JSON arrays, and the json wire addresses no
  array element, so the position stays in a raw list. The same gap stands for MDS.
