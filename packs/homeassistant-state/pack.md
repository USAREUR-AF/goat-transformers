# homeassistant-state

A Home Assistant state object: what the REST API returns for `/api/states/<entity_id>` (one
element of `/api/states`), and what `State.as_dict()` writes. Licence Apache-2.0.

## Message convention

One JSON object: `entity_id`, `state` (text), `attributes` (an object whose members depend on the
entity's domain), `last_changed`, `last_reported`, `last_updated` (Python `isoformat()` text, UTC,
with microseconds unless they are zero, and `+00:00`) and `context` (`id`, `parent_id`,
`user_id`).

## Shared keys

| Member | Key | Evidence (Home Assistant core, in this repository's words) |
|---|---|---|
| `entity_id` | `uid` | the entity's identifier, `<domain>.<object id>`, unique in an installation |
| `attributes.latitude`, `attributes.longitude` | `lat`, `lon` | the attribute names core defines for a position (device_tracker, person, zone and others); core's distance code treats them as degrees on the WGS 84 ellipsoid. An entity without them has no position |
| `attributes.friendly_name` | `callsign` | the entity's display name |
| `last_updated` | `time_ms` | when the state or its attributes were last written, UTC; `iso8601_ms`, so microseconds are truncated to the millisecond and the text comes back as `...SS.mmmZ` |

## Raw keys

The state text, `gps_accuracy` and a zone's `radius` (metres; `gps_accuracy` is not core `ce`, a
circular error whose confidence is not stated), `last_changed` and `last_reported` (text as
written), and the context ids. Every other scalar attribute is residue.

## Not mapped, and why

- A `null` member (`parent_id`, `user_id` when unset) is not carried: a round trip drops it.
- Attributes that are arrays or objects (`entity_id` lists of a group, `options` of a select) are
  not carried (arrays are outside the json wire's residue).
- `state` is always text; a sensor's number stays text, with its unit in the residue attribute
  `unit_of_measurement`.
