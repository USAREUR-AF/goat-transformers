# Consumer proofs

Each project below runs the library in its own conversion path, beside its
own conversion code, chosen by a setting that defaults to the project's own
code. Each project's tests compare the two paths on that project's own inputs
field by field and fail when the result moves.

| Project | Language | Where the library runs | How it is chosen | Library pinned | Status |
|---|---|---|---|---|---|
| open-billie | Rust | the translator's CoT, ASTERIX CAT062 and SAPIENT encoders (`runtime/rust/translator`) | cargo feature `goat-transformers`, then `BILLIE_COT_ENCODER`, `BILLIE_CAT062_ENCODER`, `BILLIE_SAPIENT_ENCODER` = `goat-transformers` | Rust crate by git `rev`; packs copied with SHA-256 sums | Built, merged (open-billie#28); the compare test runs in its CI |
| first-bite | Rust | `flow`: a transform `xf` beside `cot`; its dictionaries generated into packs by `tools/bite2pack` | cargo feature `goat-transformers` and `subtype: "xf"` in a subpub | Rust crate by git `rev`; target packs copied, `UPSTREAM` names the commit | Built, merged (first-bite#72); both tests run in its CI |
| goatstuff | Rust and Python | `ops/zenoh-shims/transform-shim`, a fabric peer that converts by route; goat-map's CoT to GeoTrackV1 on the Python engine | the shim's route table; `GOATMAP_COT_ENGINE=library` | `ops/xf/goat-transformers.ref`; bundles checked against a manifest | Built, merged (goatstuff#106); not deployed |
| octo-pod | Rust | `gateway/translate`, a separate gateway beside the capture arms | a pod's `50-translate.yml`; none means no gateway | Rust crate by git `rev`; packs copied with a manifest | Built, open for review (octo-pod#31) |
| open-entity-gateway | Python | the CoT, SAPIENT and CAT062 adapters, on the Python engine | per destination `encoder: native` or `goat-transformers` | engine and packs copied at one commit with SHA-256 sums, checked in CI | Built, merged (open-entity-gateway#18 to #21, #30, #31); the compare test runs in its CI |

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
Measured in open-billie's CI at library commit `0be9fc9`:

| Format | Encoded by both | Refused by both | One path refuses | Byte-identical | Fields equal |
|---|---|---|---|---|---|
| ASTERIX CAT062 | 25 | 7 | 1 | 25 of 25 | 397 of 397 |
| CoT | 33 | 0 | 0 | 17 of 33 | 547 of 594 |
| SAPIENT | 33 | 0 | 0 | 0 of 33 | 579 of 717 |

Earlier measurements outside the project, with the identities not yet
supplied as context: CoT 161 of 594 at spec 0.5 and 514 at spec 0.6; SAPIENT
130 of 717 and 416.

What still differs, and the row of `docs/roadmap.md` that closes it:

| Format | Field | Inputs | Closed by |
|---|---|---|---|
| SAPIENT | `location.x_error`, `location.y_error` (meters to degrees at the track latitude) | 31 each | Further value functions (meters to degrees) |
| SAPIENT | `classification[].confidence`, written only when a class is | 31 | Conditional output |
| SAPIENT | `object_info[]` from the identifiers of one scheme, with a constant type | 16 | Conditional output (items selected by value, a constant per item) |
| SAPIENT | `state` from the status flags | 13 | Conditional output and flag tokens |
| CoT | `opex="s"` from three flags | 13 | Conditional output and flag tokens |
| CoT | `detail/remarks` from the status flags | 13 | Conditional output and flag tokens |
| CoT | time text with no fraction on a whole second | 2 | a time transform that omits a zero fraction (not yet a row) |
| CoT | an empty `detail` element always written | 2 | an `xml` directive that always writes an element (not yet a row) |
| CAT062 | a longitude of 180, a track number above 4095, an altitude outside -1500 to 150000 ft refused | 1 | a field option that refuses a value outside a range (not yet a row) |

A SAPIENT report identifier is new for every message on both paths; the test
counts two valid ULIDs as equal.

## first-bite: decoding its dictionaries, CoT out

`flow` has a transform `xf` beside its own `cot`. `tools/bite2pack` turns
first-bite's JSON dictionaries into `bits` packs, one per interface; the four
public dictionaries' packs are compiled in. The join point is
`flow/src/xf.rs`.

Measured in first-bite's CI at library commit `0be9fc9`:

| Comparison | Test | Result |
|---|---|---|
| decode of every fixture (27 dictionary vectors, 5 weather-station records, 10 NTP packets), message type chosen | `flow/tests/xf_packs.rs` | 42 of 42 |
| the same fields, same value in the form first-bite writes | `flow/tests/xf_packs.rs` | 443 of 462 |
| the same fields, same bytes in another form (hex text against an integer) | | 18 of 462 |
| the same field, a scaled value differing in the last digits of the double | | 1 of 462 |
| `xf` against `cot` on 502 weather-station Position records: `version`, `uid`, `type`, `how`, `point` `ce` and `le` | `flow/tests/xf_cot.rs` | 502 of 502 |
| `lat`, `lon`, `hae` | | 473, 449, 500 of 502 equal; the rest neighbouring doubles from first-bite's JSON text |

At spec 0.5 the fixture comparison was 406 of 462: `optional`, `swap` and
`trim` (spec 0.6) and generated value tables for every 8-bit labelled field
closed the rest but the 19 below. On 40,000 generated valid payloads both
decoders chose the same message type for all.

What still differs, and what closes it:

| Difference | Fields | Closed by |
|---|---|---|
| a `bytes` field of 2 to 8 bytes is an integer where first-bite writes hex text | 18 | a `hex` transform on the `bits` wire (not yet a row) |
| a scaled field with an offset, rounded by first-bite to the decimal places of its scale | 1 | a rounding argument of `uscale` and `sscale` (Further value functions) |
| CoT `time`, `start`, `stale` text: `.000Z` against `+00:00` | 502 | none: both are valid `xs:dateTime` |
| `<detail/>` written by `cot` when empty | 502 | none needed; an `xml` directive that always writes an element would make them equal |

## goatstuff: a fabric peer and goat-map

`ops/zenoh-shims/transform-shim` subscribes to keys that carry one format,
converts each message with the Rust engine and republishes it under another
key, by a route table read at start; a route's `set` supplies context from the
key, the sample and its timestamp. goat-map's CoT to GeoTrackV1 runs on the
Python engine with `GOATMAP_COT_ENGINE=library`; the default is its own
`goatmap/cot.py`.

Measured by `ops/serve/goat-map/tools/cot_parity.py` over 26 CoT inputs,
against `tests-public/cot_parity_baseline.json` in goatstuff's CI. Both paths
accept 16 and refuse 9; the 16 give 368 members.

| Stage | Equal | Same number, other form | No member where goat-map writes `null` | Different |
|---|---|---|---|---|
| the packs alone | 271 | 15 | 19 | 63 |
| goat-map's library path | 353 | 15 | 0 | 0 |

goat-map completes the packs' output with three named steps. Each is closed
in the library by:

| Members | Count | Step in goat-map | Closed by |
|---|---|---|---|
| `affiliation`, `dimension` from the CoT type | 32 | `complete_type_letters` | a derive function that takes a token of a string, and a value-table entry for an unlisted value (not yet rows) |
| `ce_m`, `le_m` | 31 | `complete_error_sentinel` | Absent-value sentinels |
| `org`, and `course_deg`, `speed_mps`, `descriptor` when absent | 19 | `complete_null_members` | a `json` directive that writes `null` for an absent member (not yet a row) |

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
datum, class and velocity. Measured in its CI at library commit `6eeec00`:

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
