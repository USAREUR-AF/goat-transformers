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
| open-entity-gateway | Python | the CoT, SAPIENT and CAT062 adapters, on the Python engine | per destination `encoder: native` or `goat-transformers` | engine and packs copied at one commit with SHA-256 sums, checked in CI | Built, in review (`feat/goat-transformers-encoder`, closes open-entity-gateway#8) |

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

## open-entity-gateway: CoT, SAPIENT and CAT062 adapters

Each destination chooses `encoder: native` or `goat-transformers`. The gateway
passes the values it owns as context: the CoT scoped `uid`, type, stale, `how`,
callsign, course and speed; the CAT062 SAC, SIC, track number, confirmed and
SIM; the SAPIENT object and report identifiers and class.
`tests/test_goat_transformers_compare.py` compares both paths field by field
against a committed baseline, and the gateway's existing suites run once per
encoder; each library run that fails is a strict `xfail` naming its row below.
Measured at library commit `712df03`, 24 inputs per format:

| Format | Encoded by both | Refused by both | Refused by one | Fields equal |
|---|---|---|---|---|
| CoT | 23 | 1 | 0 | 266 of 371 |
| SAPIENT | 24 | 0 | 0 | 187 of 343 |
| CAT062 | 22 | 1 | 1 | 399 of 466 |

Its two example tracks are also vectors 33 to 39 of `canonical-track-v2`.

| Format | Field | Inputs | Closed by |
|---|---|---|---|
| CoT | `@access` | 23 | a key and field in `cot-xml` |
| CoT | time text `.250Z` against `.25Z` | 13 | a time transform that writes the shortest fraction (not yet a row) |
| CoT | a track time with sub-millisecond digits | 9 | a time key finer than the millisecond (not yet a row) |
| CoT | an empty `<detail/>` | 16 | an `xml` directive that always writes an element (not yet a row) |
| SAPIENT | `track_info[]` | 24 | context for the items of a list key (not yet a row) |
| SAPIENT | `classification`, `detection_confidence`, `up_rate` written by the library only | 3, 2, 2 | none: the gateway's own encoder drops them |
| SAPIENT | `north_rate` 8e-16 against 0 | 2 | none: the gateway's round trip through course and speed |
| CAT062 | I062/080 MRH | 20 | `cat062.mrh` as context, then the rule through Conditional output |
| CAT062 | I062/080 written as four octets against one or two, and LEN | 22 | a chain extent written only when it holds a non-zero bit (not yet a row) |
| CAT062 | I062/080 SRC | 2 | a `cat062.src` key |
| CAT062 | longitude 180 | 1 | a longitude wrap (not yet a row) |
| CAT062 | an altitude outside -1500 to 150000 ft, refused by the gateway only | 1 | a field option that refuses a value outside a range (not yet a row) |
