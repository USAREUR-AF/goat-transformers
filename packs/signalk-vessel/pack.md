# signalk-vessel

Signal K is an open data format for marine data: a JSON tree of everything a vessel's sensors
report, served over HTTP and WebSocket. This pack reads one vessel object.

Licence: CC-BY-SA-2.0 (share-alike), profile `open+copyleft`; see PROVENANCE.md.

## Message convention

The message is one vessel object: the value of `vessels.<id>` in the full data model, as a Signal
K server returns it for `/signalk/v1/api/vessels/<id>` (`self` for the own vessel). The full model
document itself is not a message of this pack, because the vessel sits under a key that is its
own identifier, which a member path cannot name. Each leaf of the tree is an object with a
`value`, a `timestamp` and a `$source`.

## Shared keys

| Member | Key | Evidence (the schema, in this repository's words) |
|---|---|---|
| `navigation.position.value.latitude` | `lat` | the position is stated in the WGS 84 datum; latitude in degrees |
| `navigation.position.value.longitude` | `lon` | longitude in degrees, same datum |
| `navigation.position.timestamp` | `time_ms` | RFC 3339 text, UTC only (the pattern requires `Z`); `iso8601_ms`. It is the time of the position |
| `navigation.speedOverGround.value` | `speed_ms` | speed over ground in m/s |
| `navigation.courseOverGroundTrue.value` | `signalk.cog_true_rad`, and `course` derived | course over ground, true, in radians. Core `course` is degrees true, and the factor 180/π is not exact, so the member is a raw key in radians and the module derives `course` with `deg` (engine-spec 0.16); the reverse line derives the radians from `course` with `rad` |
| `name` | `callsign` | the vessel's name, a human-readable name |

Canonical output: the position timestamp is written back with three fraction digits
(`...:30Z` becomes `...:30.000Z`), as `iso8601_ms` writes it. The other timestamps are raw text.

## Raw keys

The vessel's uuid and MMSI; the altitude of the position (metres, but the schema states no height
reference, so not `hae`); the timestamps and sources of course and speed; magnetic course, true and
magnetic heading, rate of turn and magnetic variation (radians; headings are not `course`); speed
through water; the GNSS date and time text; the navigation state.

Every other scalar member of the vessel object, in any group, is residue and comes back on a round
trip. Arrays are not carried (engine-spec 0.5).

## Not mapped, and why

- **The `values` object of a leaf** (one value per source, keyed by the source reference): its
  members are named by data, not by the schema. Scalars inside it are residue; the pack cannot
  bind them.
- **Other vessels, aircraft, aids to navigation**: one object per message; a pack for each would
  follow the same pattern.
