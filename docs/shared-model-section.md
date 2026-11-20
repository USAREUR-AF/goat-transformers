## The shared model

Every format in this library converts through one common set of typed values:
the shared model. This section says what it is, why the library is built on
it, what it guarantees, and how it is kept safe. The full definition is
[spec/shared-model.md](spec/shared-model.md).

![The shared model drawn as a horizontal bar that every format connects to; formats of a private overlay connect to the same bar.](site/assets/model-bus.svg)

### What it is

A conversion is two steps: decode the source message into keys of the model,
then encode those keys into the target format. No format is converted to
another directly.

| Part | What it holds | Defined in |
|---|---|---|
| `core` | what any position report means, in fixed units: identifier, type, time, latitude and longitude (WGS 84), height above the ellipsoid, horizontal and vertical error, course, speed, name. These are the fields of a Cursor on Target event. | [model/core.def](model/core.def) |
| `track` | facts about a sensor track: its source, velocity vector, class, confidence, uncertainty and status flags. These follow the Canonical Track v2 contract field for field. | [model/track.def](model/track.def) |
| one module per format | every other field of that format, under its own name, so that nothing is lost when a message goes back to its own format | `model/<module>.def` |

Units are fixed by the model, not by a format: degrees, meters, meters per
second, milliseconds since 1970 (UTC). Each format's pack converts its own
units on the way in and on the way out.

### Why a shared model

| Approach | Work for N formats | A new format needs |
|---|---|---|
| A converter for each pair of formats | N × (N − 1) converters | a converter to and from every existing format |
| One shared model (this library) | N packs | one pack |

The same pattern carries other wide conversion tools: pandoc converts
documents through one document model, and GDAL converts geographic data
through one data model.

The library does not use an existing message standard as the hub. Each
candidate covers one domain (air traffic, land tactical data, maritime, space
telemetry) and leaves the others out, several are heavy to implement, and
some are not public. The shared model reuses existing definitions where they
fit instead of inventing new ones: `core` is the Cursor on Target event, and
`track` is the Canonical Track v2 contract.

### What it guarantees, and what it does not

| Conversion | What happens |
|---|---|
| A format to itself | Nothing is lost. A field the model has no key for is kept with the message and written back, so the message returns in its canonical form. Round-trip conformance vectors pin this. |
| One format to another | Exactly the values that both formats map carry. The capability report (`goat-xf capability --from A --to B`, or `goat-xf matrix`) lists what carries and what is dropped, from the two packs alone, before any message is converted. |
| A pair that must lose nothing | Not guaranteed by the model. A direct rule for that pair is planned (spec version 0.53). |

Cross-format loss is listed by the capability report but not yet reported per
message. A per-conversion loss report, and a strict mode that refuses a
conversion that would drop a field the caller requires, are being added.

### How it is kept safe

| Risk | Safeguard |
|---|---|
| A key changes meaning under its users | Keys are never renamed and never change type. A new meaning is a new key. |
| A pack writes a value of the wrong type | Every engine checks each pack against the model when it loads, and refuses a mismatch. |
| One implementation reads the model differently | Seven engines, written independently from the specification, must give the same bytes on every conformance vector. |
| All engines agree on a wrong value | Values are compared with the projects' own encoders and decoders on their own inputs ([docs/consumer-proofs.md](docs/consumer-proofs.md)). Every conversion vector's decoded values are checked against a plausible range or set for their key (latitude, longitude, height, errors, course, speed, times, confidence, class, flags), and every pack that maps a height must name its vertical datum (`tools/model-checks.py`, rules in `tools/model-ranges.json`). Checks against each format's reference implementation are being added. |
| A change to the model breaks a user | Each project pins a library commit, so a change reaches no one until they move. A change to `core` or `track` needs a written decision record ([docs/adr/](docs/adr/INDEX.md)) and is measured against every known user before it merges. |

### Time quality

Time quality travels with every report, on two independent axes. A pack never
invents it: each key is absent unless the source message states it.

| Axis | Keys | Status |
|---|---|---|
| Coherence of the clock that stamped the report | `time_error_ms` (the error bound), `time_state` (`coherent`, `drifting` or `free-running`) | in `core` |
| Confidence in UTC, and a signed attestation of time quality | the UTC state, its error bound, the anchor and the age of the last anchor; an attestation reference | being added |

A clock can be coherent while its relation to UTC is unknown. That is a normal,
healthy state, and with the second axis the model can state it.
