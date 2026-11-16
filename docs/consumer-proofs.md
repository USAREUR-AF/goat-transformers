# Consumer proofs

Status: Measured. Each proof runs the library beside a project's own
conversion code, on that project's own test inputs, and compares the results
field by field. The harnesses are not part of either project and are not in
this repository.

## open-billie: Canonical Track v2 to CoT and to SAPIENT

`USAREUR-AF/open-billie` has a Rust translator with hand-written encoders
(`runtime/rust/translator/src/cot.rs`, `sapient.rs`). The proof adds the Rust
engine as an optional dependency and converts the same 33 inputs (schema
examples, the tracks in the translator's unit tests, and ten tracks from its
decoder vectors) through both paths.

| Target | Packs at spec 0.5 | Packs and rules at spec 0.6 |
|---|---|---|
| CoT, fields equal | 161 of 594 | 514 of 594 |
| SAPIENT, fields equal | 130 of 717 | 416 of 717 |

The caller supplies three values as context: the stale time, the CoT `how`
token and the SAPIENT node identifier.

What still differs, and what would close it:

| Difference | Inputs | Needs |
|---|---|---|
| Scoped track identity (four identifiers joined and escaped) in CoT `uid` and SAPIENT `id` | 33 | the host to supply it as context, or a join with escaping |
| SAPIENT `report_id` and `object_id` (identifiers the host allocates) | 33 | context |
| SAPIENT timestamp as seconds and nanoseconds | 33 | a function that splits an instant |
| SAPIENT horizontal error in degrees | 31 | meters to degrees at a latitude |
| SAPIENT class confidence, written only when a class exists | 31 | conditional output |
| CoT `opex` and `remarks`, SAPIENT `state`, built from status flags | 13 | flags to tokens |
| SAPIENT `object_info` | 16 | groups |
| CoT time text without a zero fraction; an always-present empty `detail` | 2 | agreement on the canonical form |

ASTERIX CAT062, the translator's third target: the `asterix-cat062` pack
reproduces the hand-written encoder byte for byte on six test tracks, with the
two site codes supplied by the caller as context.

## first-bite: decoding its dictionaries

`USAREUR-AF/first-bite` decodes fixed-layout binary messages from JSON
dictionaries. The proof converts its four public dictionaries into five packs
and compares decoded values with first-bite's own decoder.

| Measure | Result |
|---|---|
| Dictionary fields mapped | 233 of 234 |
| Fixture fields equal (42 messages) | 406 of 462 |
| Generated valid payloads, same message type chosen | 40,000 of 40,000 |
| Generated valid payloads, fields equal | 463,394 of 468,000 |

Measured at spec 0.5. The causes of the 56 differing fixture fields, and the
spec 0.6 option that addresses each:

| Cause | Fields | Addressed by |
|---|---|---|
| A truncated message is refused whole | 52 | `optional` |
| One little-endian field in a big-endian interface | 2 | `swap` |
| Trailing spaces kept in text | 1 | `trim` |
| A decimal offset differs in the last digits | 1 | open |

Of the equal fields, 87 are equal in value and different in form: first-bite
writes a label, `true` or `false`, or hex text where the library yields the
integer. Value tables (`map`, `via`) state the labels.

The join point is `Transform::apply` in `flow/src/subpub.rs`: a transformer
subtype that reads the record's payload, dictionary and subsystem and calls
`convert`.
