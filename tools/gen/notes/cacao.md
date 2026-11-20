## The form

One message is one CACAO 2.0 playbook in its JSON serialization, as `schemas/playbook.json`
of the TC Open Repository `oasis-open/cacao-json-schemas` (Apache-2.0) describes it. The
common `when type playbook` checks the object's `type` on decode and writes it on encode.
The schemas follow the CACAO Security Playbooks Version 2.0 Committee Specification; the
pack restates the schemas' structure only and takes no text of the specification.

## Evidence for the shared keys

- `uid` (`id`): `data-types/identifier.json` gives an identifier as the object's type, two
  dashes and an RFC 4122 UUID; `playbook.json` says it identifies the playbook and that its
  versions share it.
- `time_ms` (`modified`): `playbook.json` gives it as the time this version of the
  playbook was last changed. `data-types/timestamp.json` states the form by a pattern:
  RFC 3339 with the `Z` designator, UTC. `created` (the first version) stays a raw key.
- `stale_ms` (`valid_until`): `playbook.json` gives it as the time after which the playbook
  is no longer to be taken as valid for execution; the same timestamp form.

A leap second (`:60`), which the timestamp pattern allows, is refused by `iso8601_ms` and
fails the decode; a fraction beyond milliseconds is cut on a round trip.

Not bound: `valid_from` (start of validity, not the version's time), `created`.

## What is not mapped

- `workflow`, `agent_definitions`, `target_definitions`, `authentication_info_definitions`,
  `extension_definitions`, `data_marking_definitions` and `playbook_variables` are objects
  whose member names are identifiers chosen by the author (dictionaries); the json wire
  addresses members by fixed names, so they are not mapped. The workflow steps, the core of
  a playbook, are therefore not carried: a round trip keeps their scalars as residue.
