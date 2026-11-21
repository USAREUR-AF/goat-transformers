# Consumer proofs

Each project below runs the library in its own conversion path, beside its
own conversion code, chosen by a setting. In open-billie (CoT and CAT062),
goatstuff's goat-map and open-entity-gateway (CoT and CAT062) the setting now
defaults to the library, and the project's own code stays one setting away.
Each project's tests compare the two paths on that project's own inputs field
by field and fail when the result moves.

## Where each consumer stands (21 November 2026)

Each figure is the last one the project's own comparison measured, at the
library commit it pins; the sections below give the detail. "Default" says
whether the project uses the library unless told otherwise.

| Consumer | Pinned commit | Library is the default | Formats on the library | CI job that proves it | Last measured | What is left |
|---|---|---|---|---|---|---|
| open-billie | `9e951e9` (main `03da1d0`) | Yes for CoT and CAT062 (open-billie#35); no for SAPIENT, which stays on open-billie's own encoder | CoT, ASTERIX CAT062; SAPIENT when chosen (`BILLIE_SAPIENT_ENCODER`) | `ci.yml` job `rust`, step "Test translator" (`tests/goat_transformers_compare.rs` against its baseline file), and "Test translator without the goat-transformers encoder path" | 33 inputs per format. CAT062: 25 encoded by both, 7 refused by both, 1 refused by one path; 25 of 25 byte-identical; 397 of 397 fields equal. CoT: 28 of 33 byte-identical; 588 of 594 fields equal. SAPIENT: 0 of 33 byte-identical; 685 of 719 fields equal | CoT: `time`, `start`, `stale` with no fraction at a whole second, 6 fields on 2 inputs (spec 0.55, not yet merged). CAT062: 1 input that open-billie's encoder refuses (longitude 180, track number above 4095 or altitude out of range) and the library writes (spec 0.56 `range`, not yet merged). SAPIENT: `object_info[]` type and value, 32 fields on 16 inputs (spec 0.58, planned); `timestamp.nanos` written as 0 at a whole second, 2 fields (spec 0.56, not yet merged); SAPIENT is not the default until these close |
| goat (goatstuff) | `9e951e9` (`ops/xf/goat-transformers.ref`, main `9a3766d`) | Yes for goat-map's CoT to GeoTrackV1 (goatstuff#118; `GOATMAP_COT_ENGINE=builtin` selects goat-map's own code). `ops/zenoh-shims/transform-shim` has no other path | CoT XML to GeoTrackV1 (goat-map); the shim's routes: Canonical Track v2, CoT protobuf, CoT XML, GeoTrackV1, GeoJSON | `ci.yml` job `python-and-ansible`, step "Python tests" (`pytest ops`, which holds `tests-public/test_cot_library.py` against `cot_parity_baseline.json`); `transform-shim.yml` | `tools/cot_parity.py` over 26 CoT inputs: both paths accept 16 and refuse 9, and differ on 1. The 16 give 368 members. goat-map's library path: 353 equal, 15 the same number in another form, 0 different. The packs alone: 271 equal, 15 other form, 49 absent, 33 different. `pytest ops`: 336 passed, 2 skipped | goat-map completes the packs' output with its own steps for 82 members: `affiliation` and `dimension` from the CoT type, 32 (spec 0.57, planned); `org`, `course_deg`, `speed_mps`, `descriptor` written `null` when absent, 19 (spec 0.56, not yet merged); `ce_m`, `le_m` above 9999999 read as unknown, 31 (spec 0.56, not yet merged). One input (an event with no `uid`) differs: goat-map publishes an id its schema does not allow, the packs refuse the event |
| octo-pod | `1f24c0b` on the open octo-pod#31 (not on main) | Not applicable: the translation gateway has no other conversion path. It is not merged and not deployed | SAPIENT to CoT XML and GeoJSON; CoT XML to SAPIENT | `ci.yml` job `gateway` on octo-pod#31 (`cargo test`, the 38 BSI Flex 335 reference vectors, the pen test) | `cargo test`: 40 passed. Reference vectors: of 3 detections, 3 convert to CoT and 0 to GeoJSON (none has a position in degrees: 2 give UTM metres, 1 range and bearing); every other message is skipped (`no-shared-value`) | Merge of octo-pod#31 (under review). A detection with no position in degrees is skipped for GeoJSON and converts to a CoT event with no lat or lon. CoT to SAPIENT: no object id and no report id, so a SAPIENT controller that validates detections refuses the result |
| first-bite | `6d99371` (main `578723e`) | No: the library is in `mind`'s default build (first-bite#75), but each subpub chooses its transform, and CoT stays on first-bite's own `cot` unless a subpub names `xf` | Its four public dictionaries' interfaces decoded by generated `bits` packs; CoT out | `ci.yml` jobs `test` (`cargo test --workspace`, default build) and `test (goat-transformers)` (`flow/tests/xf_packs.rs`, `flow/tests/xf_cot.rs`) | Fixtures (27 dictionary vectors, 5 weather-station records, 10 NTP packets): 42 of 42 messages typed alike; 461 of 462 fields equal. `xf` against `cot` on 502 weather-station records: `version`, `uid`, `type`, `how`, `ce`, `le` equal on 502 of 502; `lat` 473, `lon` 449, `hae` 500 of 502 equal | 1 fixture field: a scaled value with an offset that first-bite rounds to the decimal places of its scale (spec 0.55 `<places>`, not yet merged). `lat`, `lon`, `hae` on 29, 53 and 2 records: neighbouring doubles of first-bite's JSON text. CoT time text: `.000Z` where `cot` writes `+00:00`, on 502 records (the same instant). `xf` is not the default transform |
| open-entity-gateway | `65596364f` (open-entity-gateway#39, main `80949a0`) | Yes for CoT (unless a destination sets `time_form`, which only the gateway's own encoder writes) and CAT062 (open-entity-gateway#37); no for SAPIENT | CoT, ASTERIX CAT062; SAPIENT when a destination sets `encoder: goat-transformers` | `ci.yml` step `python -m pytest -rs tests vendors/lattice/tests` (`tests/test_goat_transformers_encoder.py` against `tests/vectors/goat-transformers-baseline.json`) | 4 inputs per format; 76 recorded differences, every other compared field equal. `pytest`: 233 passed, 11 skipped, 3 xfailed | CAT062: I062/080 second and third extents written although all zero, 48 differences on 4 inputs (spec 0.59, planned). CoT: `time`, `start`, `stale` text against the gateway's `time_form`, 12 differences on 4 inputs: 9 at a whole second (spec 0.55, not yet merged), 3 with `.25Z` (spec 0.59, planned). SAPIENT: `track_info[]` type and value, 16 differences on 4 inputs (spec 0.58, planned); SAPIENT is not the default |

Two consumers use the library by default for at least one format (open-billie,
open-entity-gateway), goat-map uses it by default with three of its own
completion steps, octo-pod's gateway is library-only but not merged, and
first-bite ships it in its default build without making it the default
transform.

## open-billie: Canonical Track v2 to CoT, CAT062 and SAPIENT

The translator (`runtime/rust/translator`) encodes each validated Canonical
Track v2 record through its own encoder or through the library, per format.
The values the node owns are computed by the translator's own code and passed
as context: the scoped track identity, the CoT stale time and `how`, the
CAT062 SAC and SIC, and the SAPIENT node identifier, timestamp, report and
object identifiers.

`runtime/rust/translator/tests/goat_transformers_compare.rs` encodes 33 inputs
(schema examples, the runtime-contract request, the tracks of the translator's
unit tests, ten tracks from its decoder vectors) through both paths, parses
both outputs and compares them field by field against a committed baseline.
Measured in open-billie's CI at library commit `9e951e9`, after open-billie#33
made its own encoders follow the library on the CAT062 MRH bit and the WGS84
e2, against `runtime/rust/translator/tests/fixtures/goat-transformers-baseline.json`:

| Format | Encoded by both | Refused by both | One path refuses | Byte-identical | Fields equal |
|---|---|---|---|---|---|
| ASTERIX CAT062 | 25 | 7 | 1 | 25 of 25 | 397 of 397 |
| CoT | 33 | 0 | 0 | 28 of 33 | 588 of 594 |
| SAPIENT | 33 | 0 | 0 | 0 of 33 | 685 of 719 |

At `0be9fc9` the figures were CAT062 397 of 397, CoT 547 of 594 and SAPIENT 579
of 717. Since then the library maps the SAPIENT position errors (spec 0.16),
the CoT `opex`, `detail/remarks` and SAPIENT `state` from the status flags, the
SAPIENT confidence written only with a class, and the empty CoT `detail` (spec
0.18). Earlier measurements outside the project, with the identities not yet
supplied as context: CoT 161 of 594 at spec 0.5 and 514 at spec 0.6; SAPIENT
130 of 717 and 416.

What still differs, and what closes it:

| Format | Field | Inputs | Closed by |
|---|---|---|---|
| SAPIENT | `object_info[]` (type and value) from the identifiers of one scheme | 16 | list items selected by a value (spec 0.58, planned) |
| SAPIENT | `timestamp.nanos` written as 0 at a whole second, where open-billie omits it | 2 | a protobuf scalar left out at its default (spec 0.56, not yet merged) |
| CoT | `time`, `start`, `stale`: no fraction on a whole second | 2 | `iso8601_si` (spec 0.55, not yet merged) |
| CAT062 | a longitude of 180, a track number above 4095, an altitude outside -1500 to 150000 ft refused | 1 | `range` (spec 0.56, not yet merged) |

A SAPIENT report identifier is new for every message on both paths; the test
counts two valid ULIDs as equal.

## first-bite: decoding its dictionaries, CoT out

`flow` has a transform `xf` beside its own `cot`. `tools/bite2pack` turns
first-bite's JSON dictionaries into `bits` packs, one per interface; the four
public dictionaries' packs are compiled in. The join point is
`flow/src/xf.rs`.

Measured in first-bite's CI at library commit `6d99371` (first-bite#75):

| Comparison | Test | Result |
|---|---|---|
| decode of every fixture (27 dictionary vectors, 5 weather-station records, 10 NTP packets), message type chosen | `flow/tests/xf_packs.rs` | 42 of 42 |
| the same fields, same value in the form first-bite writes | `flow/tests/xf_packs.rs` | 461 of 462 |
| the same field, a scaled value differing in the last digits of the double | | 1 of 462 |
| `xf` against `cot` on 502 weather-station Position records: `version`, `uid`, `type`, `how`, `point` `ce` and `le` | `flow/tests/xf_cot.rs` | 502 of 502 |
| `lat`, `lon`, `hae` | | 473, 449, 500 of 502 equal; the rest neighbouring doubles from first-bite's JSON text |

At `0be9fc9` the fixture comparison was 443 of 462; the 18 `bytes` fields of 2
to 8 bytes that were an integer where first-bite writes hex text are equal
since spec 0.22 (`hex` on `bits`; `tools/bite2pack` maps an msb0 `bytes` field
with it). At spec 0.5 it was 406. On 40,000 generated valid payloads both
decoders chose the same message type for all.

What still differs, and what closes it:

| Difference | Fields | Closed by |
|---|---|---|
| a scaled field with an offset, rounded by first-bite to the decimal places of its scale | 1 | the `<places>` argument of `uscale` and `sscale` (spec 0.55, not yet merged) |
| CoT `time`, `start`, `stale` text: `.000Z` against `+00:00` | 502 | none: both are valid `xs:dateTime` |

## goatstuff: a fabric peer and goat-map

`ops/zenoh-shims/transform-shim` subscribes to keys that carry one format,
converts each message with the Rust engine and republishes it under another
key, by a route table read at start; a route's `set` supplies context from the
key, the sample and its timestamp. goat-map's CoT to GeoTrackV1 runs on the
Python engine; `GOATMAP_COT_ENGINE` defaults to `library` (goatstuff#118), and
`builtin` selects goat-map's own `goatmap/cot.py`.

Measured by `ops/serve/goat-map/tools/cot_parity.py` over 26 CoT inputs,
against `tests-public/cot_parity_baseline.json` in goatstuff's CI, at library
commit `9e951e9` (goatstuff#111). Both paths accept 16 and refuse 9; the 16 give
368 members.

| Stage | Equal | Same number, other form | Absent from the packs' output | Different |
|---|---|---|---|---|
| the packs alone | 271 | 15 | 49 | 33 |
| goat-map's library path | 353 | 15 | 0 | 0 |

goat-map completes the packs' output with three named steps. Each is closed
in the library by:

| Members | Count | Step in goat-map | Closed by |
|---|---|---|---|
| `affiliation`, `dimension` from the CoT type | 32 | `complete_type_letters` | a token of a string, and a value-table entry for an unlisted value (spec 0.57, planned) |
| `ce_m`, `le_m` | 31 | `complete_error_sentinel` | Absent-value sentinels |
| `org`, and `course_deg`, `speed_mps`, `descriptor` when absent | 19 | `complete_null_members` | the `null` field option (spec 0.56, not yet merged) |

The two paths differ on one input, an event with no `uid`: goat-map publishes
an id its schema does not allow, and the packs refuse the event.

## octo-pod: a translation gateway beside the arms

`gateway/translate` is a separate unit, not an arm: it subscribes to declared
capture keys under its own certificate, converts each sample with the Rust
engine and publishes the result on its own key with the source key, timestamp
and SHA-256 attached; the captured sample is never changed. It is off unless a
pod declares it. Built, in review as octo-pod#31 with its ADR 0004.

## open-entity-gateway: CoT, SAPIENT and CAT062 destinations

Each destination takes `encoder: native` (the default) or `goat-transformers`
(`docs/goat-transformers-encoder.md` in that repository). The track is written
as Canonical Track v2 and converted by the Python engine; the gateway passes
what it decides as context: the CoT `track.scoped_id`, type, stale, `how`,
callsign and `access`; the CAT062 SAC, SIC, track number, confirmed, SRC
and service identification; the SAPIENT object and report identifiers and
class. The SAPIENT session stays the gateway's. With `goat-transformers`, a
pack that does not load, or the one destination key only the native encoder
writes (`time_form`), stops the gateway at start.

`tests/test_goat_transformers_encoder.py` encodes every example record and
track both ways (four inputs a mapping matches) and compares the outputs
field by field against a committed baseline. Equal on every input: the CoT
`uid`, type, position, errors, `how`, stale instant, course, speed, callsign
and `access`; the CAT062 data source, time of day, position, track number,
velocity, altitude, MRH and SRC; the SAPIENT object id, report id, location,
datum, class and velocity. Measured in its CI at library commit `7597d81`:

| Format | Field | Inputs | Closed by |
|---|---|---|---|
| CoT | time text: `.000Z` against the destination's `time_form` | 4 | none: the same instant; or a time transform that writes the shortest fraction (spec 0.18) |
| CAT062 | I062/080 second and third extents written, all zero | 4 | a chain extent written only when it holds a non-zero bit (not yet claimed) |
| SAPIENT | `track_info[]` | 4 | context for the items of a list key (not yet claimed) |

MRH is not context: the pack sets it to 1 when I062/130 is written
(`derive cat062.mrh present hae`, spec 0.12), and the result is the
gateway's own MRH on every input (open-entity-gateway#30).

The gateway's destination suites run once per encoder. Three library runs are
strict expected failures, each naming its cause: a longitude of 180 written
as 2^25 rather than -180, an altitude outside -1500 to 150000 ft written
rather than refused, and SAPIENT `track_info`. The 14 CoT schema runs and the
CAT062 service identification run that failed at `712df03` pass.

Its two example tracks are also vectors 33 to 39 of `canonical-track-v2`.
