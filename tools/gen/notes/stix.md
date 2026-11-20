## The form

One message is one STIX 2.1 object in its JSON serialization, as the object's schema in
`oasis-open/cti-stix2-json-schemas` describes it. The common `when type <type>` checks the
object's `type` on decode and writes it on encode. A bundle of several objects is not a
message of these packs: read each object of the bundle's `objects` array on its own.

The schemas are not normative; the STIX 2.1 OASIS Standard governs where they differ. The
packs restate the schemas' structure only; descriptions here and under "Mapped to shared
keys" are this project's words.

## Evidence for the shared keys

- `uid` (`id`), every pack: `common/core.json` and `common/identifier.json` give the
  identifier as the object's type, two dashes and a UUID, and say it identifies the object;
  all versions of one object share it.
- `time_ms` (`modified`), in the Domain Objects and Relationship Objects: `common/core.json`
  gives it as the time this version of the object was made, precise to the millisecond.
  It is the version's own time; `created` (the first version) stays a raw key. The schema
  states the timestamp form by a pattern (`common/timestamp.json`): RFC 3339 with the `Z`
  designator, that is UTC. `iso8601_ms` reads it; the raw key keeps the text as written. A
  leap second (`:60`), which the pattern allows, is refused by `iso8601_ms` and fails the
  decode. A fraction beyond milliseconds is cut on a round trip.
- `lat`, `lon` (`latitude`, `longitude`), in `stix-location` only: decimal degrees in
  `sdos/location.json`. The schema names no datum; the Location section of the STIX 2.1
  OASIS Standard makes WGS 84 the datum when `precision` is present. Without `precision`,
  the standard says the location is as precise as its other members (region, country and
  so on) allow.

Not bound:

- Cyber-observable Objects have no `created` or `modified`; the times they carry (a
  file's `mtime`, a registry key's `modified_time`, a process's `created_time`) are times
  of the thing observed, not of the record.
- `first_seen` / `last_seen` (sighting, campaign, intrusion-set and others) and
  `first_observed` / `last_observed` (observed-data) are the bounds of an interval.
- `confidence` is a 0 to 100 scale of the producer, not a position error.
