## What the message is

ADAPT (AgGateway's Agricultural Data Application Programming Toolkit) is a common data model for
farm management and machine data: fields and their boundaries, crops, products, devices, guidance
patterns, and the plans, recommendations, work orders and work records of field operations. A
dataset is serialized as one file `adapt.json` whose root holds a `catalog` (setup data) and
`documents` (transactional data); the standard also allows each component to travel alone as
JSON in a service. Pack `adapt-root` reads the `adapt.json` root; each other `adapt-*` pack reads
one component as a standalone JSON object.

The schema descriptions are not copied; these notes and the key meanings are this repository's
words.

## Everything raw

- Geometry (field boundaries, guidance lines, obstacles, the A and B points of a line) is
  well-known text (WKT) in a string, not latitude and longitude numbers: the `json` wire has no
  transform that parses WKT, so no position binds `lat` or `lon`.
- Times are inside `timeScopes` arrays (each with a date context and a start and end), not one
  time of the component, so none binds `time_ms`; they stay raw text.
- Identifiers are `id` objects with a reference id and unique ids from several sources; they stay
  raw, as items of lists.
