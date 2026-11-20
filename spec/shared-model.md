# Shared model

Status: Written. Version 0.4.

Every format decodes to this model and encodes from it. A conversion from format
A to format B is "decode A to the model, encode the model to B". The model is the
only thing the formats agree on.

## Modules

The model is a set of modules. A module is a named list of typed keys in one
file, `model/<module>.def` (grammar: `spec/engine-spec.md`, Version 0.4). A pack
names the modules it uses and maps wire fields to their keys. Two formats that
map the same key convert that value to each other; the more modules two formats
share, the more of a message carries between them.

| Module | Holds | Defined in |
|---|---|---|
| `core` | identity, type, time, position, error, name, course and speed of one reported thing | `model/core.def` |
| `track` | sensor-track facts: source, velocity vector, class, confidence, uncertainty, status flags, and the list of identifiers | `model/track.def` |
| `detection` | one dwell or scan of a sensor (time and its quality, the sensor and its position, the coverage) and the list of its detections, with no track identity: position and errors, radial velocity, signal to noise, classification | `model/detection.def` |
| `cat062` | values of ASTERIX Category 062 as the category holds them: SAC, SIC, time of day, track number, the status bits MON, CNF, SIM, TSE and CST. Uses `track`: it derives the time of day from `time_ms`, the track number from `uid`, and SIM from the three flags of `track` that say the data is not live | `model/cat062.def` |
| `probe` | synthetic keys and lists for the conformance vectors of derived keys, of groups and of sequential layouts; no real format maps them | `model/probe.def` |

A format with a message catalog of its own usually also has its own module of
raw wire values (for example `n2k` for NMEA 2000), so every field decodes and
round-trips even where it has no key in `core` or `track` yet.

A key of `core` is written bare in a pack (`lat`). A key of any other module is
written `<module>.<key>` (`track.confidence`).

The model grows by adding modules and by adding keys to a module. A key is never
renamed and never changes type. A concept that only some formats carry goes in
its own module, so a format that does not carry it never mentions it.

## Types and units

A key has one of three types: `string`, `float`, `int`. A flag is an `int`:
1 when the source states it, 0 when the source denies it, absent when the source
says nothing.

Units are fixed by the module: degrees, metres, metres per second, epoch
milliseconds. Each pack converts its format's units to these on decode and back
on encode. No consumer of the model does unit math.

Every pack must produce a key's declared type. A format whose wire holds the
value as a different type uses a transform that yields the declared type. The
engine checks this when the pack loads and refuses a mismatch
(`key-type-mismatch`), so two loaded packs can never disagree on a key's type.

## Lists

Status: Written. Version 0.7. A part of a message that repeats is a list: a
module declares it with a `list` line, and a pack maps it with a `group` block
(`spec/engine-spec.md`, Version 0.7).

- A list is named like a key (`track.identifiers`; bare for `core`) and shares
  its module's key names: a module cannot have a key and a list of one name.
- Its value is an ordered sequence of items. An item holds model keys, and may
  hold lists of its own. Any declared key may appear in an item; the keys an
  item holds are the ones the `group` maps. An item has no residue. An item
  has a kind only where the `group` body of a sequential binary pack holds
  kinds (`spec/engine-spec.md`, Version 0.8): the item then records the kind
  it selected, as an entity does, and that pack writes it as the same kind.
- A list that is present and empty is distinct from an absent list. JSON
  writes the first as `[]`; XML and protobuf cannot tell the two apart and
  read a message with no item as an absent list.
- Two formats that map the same list convert it to each other, item by item,
  each item carrying the keys both groups map.
- Derived keys and caller-supplied keys are keys of the entity itself. They do
  not reach into items.

The `model_keys` of a format name a list `<list>[]` and an item key
`<list>[].<key>` (`track.identifiers[]`, `track.identifiers[].track.id_value`).

## Distribution: public and controlled

Every module and every pack carries a `distribution` line, `public` or
`controlled`, and at least one `source` line naming the document it was written
from.

- A `public` pack may use only `public` modules.
- A `controlled` pack may use `public` and `controlled` modules.

A format written from a controlled standard therefore converts to and from every
public format through the public modules it maps, and to and from other
controlled formats through the controlled modules as well. The public modules
contain no key that exists only in a controlled standard, because such a key is
declared in a controlled module, and a controlled module is kept in a private
overlay repository, never in this one.

An engine set to `--max-distribution public` refuses every controlled module and
pack, so a deployment entitled only to public formats cannot load anything else.

## The `core` module

| Key | Type | Unit | Meaning |
|---|---|---|---|
| `uid` | string | | stable identifier of the entity |
| `type` | string | | CoT-style type token (`a-f-G-U-C-I`), the shared type vocabulary |
| `time_ms` | int | epoch milliseconds UTC | time the report is valid |
| `time_error_ms` | float | milliseconds | coherence error bound of the clock that stamped `time_ms`, 0 or more: the bound, not the offset; absent when not stated |
| `time_state` | string | | state of the clock that stamped `time_ms`: `coherent`, `drifting` or `free-running`; absent when not stated |
| `time_utc_state` | string | | UTC confidence of the clock that stamped `time_ms`: `confident` or `unknown`; absent when not stated |
| `time_utc_error_ms` | float | milliseconds | one-sigma uncertainty of `time_ms`'s offset from UTC, 0 or more; absent when not stated |
| `time_anchor` | string | | the time source the clock is anchored to: `gnss`, `peer_nts`, `wan_nts`, `orphan` or `none`; absent when not stated |
| `time_anchor_age_ms` | int | milliseconds | time from the last external anchor (`gnss`, `wan_nts`, `peer_nts`) to `time_ms`; absent when not stated |
| `time_attested` | int | | 1 when a signed attestation backs the time quality, 0 when the source states it is not attested; absent when not stated |
| `time_attestation` | string | | the attestation the time quality rests on: `ntp-attest-v1:<valid_until epoch ms>:<host_id>`; absent when not stated |
| `lat` | float | degrees, WGS84 | latitude |
| `lon` | float | degrees, WGS84 | longitude |
| `hae` | float | metres | height above WGS84 ellipsoid |
| `ce` | float | metres | circular (horizontal) error |
| `le` | float | metres | linear (vertical) error |
| `callsign` | string | | human-readable name |
| `course` | float | degrees true | direction of travel |
| `speed_ms` | float | metres per second | ground speed |
| `how` | string | | provenance token (`m-g`, `h-e`, ...) |
| `stale_ms` | int | epoch milliseconds UTC | time after which the report is no longer valid |

### Time quality: two axes, never invented

goat's time hygiene asks two independent questions about the clock that stamped
`time_ms`: is it in step with its fabric (internal coherence: `time_error_ms`,
`time_state`), and how well is it anchored to UTC (UTC confidence:
`time_utc_state`, `time_utc_error_ms`, `time_anchor`, `time_anchor_age_ms`). A
report can be coherent but UTC-unknown, a normal state at a denied edge.
`time_attested` and `time_attestation` say whether a signed attestation backs the
claim. None of these keys is ever defaulted, derived or written by a pack that
does not read it from the source (`tools/time-quality-guard.py`); a caller may
pass them as context. Version 0.32 of `spec/engine-spec.md` and ADR 0005 give
the sources of the names in goat's own documents.

## The `track` module

The keys match the Canonical Track v2 contract of `USAREUR-AF/open-billie`
(`schemas/canonical-track-v2.schema.json`) field for field: `source_id`,
`generation`, `vel_east_ms`, `vel_north_ms`, `vel_up_ms`, `class`,
`confidence`, `sigma_east_m`, `sigma_north_m`, `sigma_up_m`, and the flags
`confirmed`, `coasting`, `simulated`, `header_simulated`, `test_data`,
`final_update`. Four keys are derived from the flags (`model/track.def`, Versions 0.8 and 0.18): `simulated_any` (any of `simulated`, `header_simulated`, `test_data`), `tentative` (`not confirmed`), `status_text` (the flags as the comma-separated tokens `test-data`, `simulated`, `tentative`, `coasting`, `final-update`) and `opex` (`s` for a simulated track, as CoT writes it). Types, units
and meanings are in `model/track.def`.

The contract's `identifiers` array is the list `track.identifiers`. Each item
holds two keys:

| Key | Type | Meaning |
|---|---|---|
| `track.id_scheme` | string | the scheme the identifier belongs to (for example `icao24`) |
| `track.id_value` | string | the identifier in that scheme |

## The `detection` module

One dwell or scan of a sensor and the detections it holds, with no track
identity: a radar scan of plots, a moving-target dwell of target reports.

The dwell's keys are written `detection.<key>` at the top of the entity:
`dwell_id`, `time_ms` (the dwell time), `time_error_ms` and `time_state` (as
the core keys of the same names), `sensor_id`, `sensor_lat`, `sensor_lon`,
`sensor_hae`, and, where the sensor states them, `coverage_wkt` (the covered
area as WKT) and `revisit_ms`.

Each detection is one item of the list `detection.items`. An item holds the
core keys `lat`, `lon`, `hae`, `ce`, `le` and, where the sensor gives a
detection its own time, `time_ms`; and the item keys of the module:
`item_id`, `range_error_m` and `cross_range_error_m` (where the sensor states
those in place of `ce`), `radial_velocity_ms` (positive when the range
increases) and `radial_velocity_error_ms`, `snr_db`, `classification` and
`classification_probability`. A present, empty `items` is a dwell that detected
nothing, which is not the same as an absent list. A pack whose wire gives the
radial velocity with the opposite sign states it with a negative scale.

Absent means "not stated", never 0. Types, units and meanings are in
`model/detection.def`. The key set was agreed with goat-processors, whose
`track` function reads it.

## Residue

A field a format carries that no loaded module has a key for is stored under
`residue`, keyed by that format's locator string, with the original wire value.
On encode back to the same format, residue is written back out, so decode then
encode to the same format returns an equal message. Residue does not cross
formats: encoding to a different format ignores another format's residue.

## Type vocabulary

The `type` key uses the CoT type grammar (`a-.-.-.` affiliation-dimension) as
the shared vocabulary, because it is public and hierarchical. Each non-CoT
format's pack carries a table mapping its own type codes to and from CoT type
tokens. A code with no mapping passes through: it keeps its native value in
`type` and is written back unchanged through the same locator
(`spec/engine-spec.md`, Type mapping). Residue is not involved.

## Why a model and not a format's own

No fielded format is a neutral go-between: each carries assumptions the others
do not share. The model takes what a report means, in fixed units, so that
adding the Nth format needs one pack, not N−1 pair rules. A pair that must lose
nothing and cannot get there through the modules uses a direct pair rule
(`docs/adr/0002`).
