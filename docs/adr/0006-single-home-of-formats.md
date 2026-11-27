# ADR 0006: This library is the single home of every format, mapping and encoder of the goat family

Status: Proposed (2026-11-27)

## TL;DR (for a layperson)

Several projects of the goat family each wrote their own code to read a sensor
message and write it as CoT, ASTERIX or SAPIENT. The copies disagree: one
writes a field another drops, and a fix made in one never reaches the others.
This record makes this library the only place where a format is decoded,
mapped or encoded. A format from a public specification lives here. A format
from a specification that is not public lives in the private overlay
repository, in the same form. Every other project selects packs and pins one
commit of this library; it keeps no conversion code of its own. A pack is
complete only when every value it decodes is either written to the shared
model or listed, with a reason, as not carried.

## Changes

No model file changes. This record changes what the repository accepts and
what its consumers may hold:

- `docs/consumer-proofs.md`: each consumer row gains the date its own
  conversion code is removed (today each row keeps that code one setting away).
- `tools/`: a pack completeness gate (below). Designed; a first version
  (`tools/route-coverage.py`) exists on a branch and is not merged.
- `docs/boundary.md`: unchanged. The public and controlled split it states is
  the split this record relies on.

## Context

`docs/consumer-proofs.md` lists five consumers. Each runs the library beside
its own conversion code and chooses between them by a setting. That was the
right shape while the library was being proven: each consumer's comparison
test measured the two paths on its own inputs.

It is the wrong shape to keep. Measured in the sensor-edge projects on
27 November 2026:

| What | Count |
|---|---|
| Separate implementations of a CoT encoder across the family's sensor-edge repositories (TypeScript twice, Rust twice, Kotlin, Go), beside pack `cot-xml` | 6 |
| Separate implementations of an ASTERIX CAT062 encoder (TypeScript twice, Rust, Python), beside packs `asterix-cat062`, `asterix-cat062-full`, `asterix-cat062-rcs` | 4 |
| Representations of one vendor radar's message set (two hand-written decoders, one set of generated packs kept in a consumer repository, one overlay pack family for a second interface of the same radar, one deploy script) | 5 |
| Commits of this library pinned by three consumer copies, against main `5daad57c6` | `9e951e9`, `9e951e9`, `d57d361` |

A mapping held outside this repository is checked by nothing here. In the
consumer mapping files for that radar's two track messages, 22 of 81 decoded
values are bound to an output and none of the other 59 records a reason; the
CAT062 mapping writes the height to I062/136 (a barometric flight level) where
this library's CAT062 packs read height from I062/130, and writes the target
family to I062/245, a callsign item. Height above mean sea level and height
above the ellipsoid are two keys, and only a consumer's own code decides which
one it writes to CoT `hae`.

The consumers also hold content this repository needs. One of them generated
56 controlled packs from its decoder schemas, with a round-trip vector each,
and measured both conversion paths on 2,926 fields: 2,176 equal, 318 with no
key in the public target pack, 178 needing a rule the pack language did not
state at commit `9e951e9`, 254 quirks of the consumer's own code. That list is
the work list for this record.

## Decision

1. **One home.** A format is decoded, mapped and encoded by a pack and the
   model modules it uses, in this repository or in the private overlay
   repository that pins it. No other repository of the goat family holds a
   decoder schema, a mapping file, a value table or an encoder for a message
   format.
2. **Public and controlled.** A format written from a public specification
   (CoT, ASTERIX, SAPIENT, ISA, NMEA and the like) is `distribution public`
   and lives here. A format written from a vendor document, a vendor capture
   or a controlled standard is `distribution controlled` and lives in the
   overlay. `docs/boundary.md` and `tools/boundary-gate` enforce the split;
   this record adds no exception to them.
3. **Pack completeness is gated.** For every pack that decodes, each raw key
   it reads is bound to a shared-model key (`field` or `derive`), or appears
   in the pack's `pack.md` under "Not carried" with one reason from a fixed
   list: no shared-model key exists (names the ADR that would add one), the
   pack language cannot state the rule yet (names the rule, decision 6), the
   value is framing, the value is reserved, the value is redundant with a
   named key. For every pack that encodes, each item of the format's
   specification the pack does not write is listed the same way. A key with
   neither a binding nor a reason fails CI. Designed, not built; the unmerged
   `tools/route-coverage.py` checks routes between packs and is the starting
   point.
4. **Consumers pin and select.** A consumer names packs in its configuration
   and pins one commit of this library (and, for controlled packs, one commit
   of the overlay). It may embed a copy of the pack and model files it names,
   checked by hash against that commit, as two consumers do today. It does
   not edit that copy, and it holds no conversion code beside it.
5. **Node-owned values are context, stated once.** Values a format needs that
   no message carries (CAT062 SAC and SIC, the CoT stale interval and `how`,
   a SAPIENT node identifier, the geoid height of a site) are context keys
   declared in the model module of that format. A consumer supplies the
   values; it does not compute fields.
6. **A rule the pack language cannot state is added to the specification, not
   written in a consumer.** The measurement found six such rules at commit
   `9e951e9`. ECEF to geodetic, the largest (82 of 187 mapping entries), is in
   the specification now (`lat_of_ecef`, `lon_of_ecef`, `hae_of_ecef`). The
   remaining five are re-measured against main before any consumer code is
   removed: an integer from bit ranges that are not adjacent, an `int` key
   from an integer divided by a constant, an instant from a time of day plus a
   date the host holds, east-north-up velocity from ECEF velocity and
   position, and a list item built from scalar values. A sixth is needed by
   the same radar's track messages and is not in the specification at main
   `db0562221`: an instant from calendar fields (year, month, day, hour,
   minute, second, millisecond), absent when the fields are zero or are not a
   real date. Until it is, the consumer supplies `time_ms` as context and the
   pack lists the calendar fields under "Not carried" with that reason.
7. **Old code is deleted only on parity.** A consumer removes a decoder,
   mapping or encoder in one pull request per module, after a comparison on
   recorded inputs shows the pack path equal field by field. Each difference
   is one of three things, recorded in that pull request: a defect of the old
   code that the pack fixes, a value listed under "Not carried", or a blocker
   that stops the module.

## What is built and what is not

| Piece | Status |
|---|---|
| Public packs for CoT XML and protobuf, CAT062 (three packs), CAT048, CAT034, SAPIENT, ISA | Built, in `packs/` |
| The boundary gate and the `distribution` marking | Built (`docs/boundary.md`) |
| Controlled packs for the vendor sensor formats, generated from decoder schemas, with round-trip vectors | Built in a consumer repository; not yet in the overlay |
| Conformance vectors from recorded sensor frames | Not built. The consumer measurement used synthetic frames; three recorded fixtures exist in one consumer |
| Pack completeness gate (decision 3) | Designed, not built |
| Context keys for node-owned values (decision 5) | Built for CAT062 SAC/SIC and CoT `stale_ms`/`how`; not built for the geoid height of a site |
| The five remaining pack-language rules (decision 6) | Not re-measured against main |
| Removal of consumer conversion code | Not started. Two consumers default to the library for CoT and CAT062 and keep their own encoders |

## Consumers re-measured

No model file changes with this record, so no comparison moves. The table is
the starting state each consumer's removal is measured from.

| Project | Library commit pinned | Library is the default | Own conversion code still present |
|---|---|---|---|
| open-billie translator | `9e951e9` | CoT, CAT062 | CoT, CAT062 and SAPIENT encoders |
| open-billie format-ingest kid | `d57d361` | every route | none |
| sensor-edge TypeScript workspace (private) | `9e951e9` | no | three decoders, translator, five encoders, mapping files |
| goat-map, open-entity-gateway, first-bite, octo-pod | per `docs/consumer-proofs.md` | per that file | per that file |

## Consequences

- A fix to a mapping is made once and reaches every consumer at its next pin
  move. A consumer that needs a field asks for a model key or a pack line
  here.
- This repository and the overlay take on the vendor formats' maintenance.
  The overlay grows by three sensor families.
- A consumer cannot ship a conversion this library does not have. The cost is
  a pull request here before the consumer's own change; the gate in decision 3
  makes the missing piece visible first.
- Throughput moves from hand-written code to an engine. The one measurement
  of the WebAssembly binding in Node (a loaded machine, not a target device)
  put it at 8 to 26 times the per-message time of the hand-written path, 0.2
  to 1.5 ms per message. Consumers on a constrained device use a native
  engine, which is what the sensor-edge runtime in Rust already does.
- `docs/consumer-proofs.md` changes purpose: from a comparison of two live
  paths to a record of when each consumer's own path was removed and what the
  last comparison showed.

## Alternatives considered

- **Keep each consumer's code one setting away.** That is today's state. It
  preserves a fallback and keeps every duplicate alive; the defects above came
  from a duplicate nobody compared.
- **Keep vendor formats in the consumer that first decoded them.** One
  consumer does this today with generated controlled packs. A second consumer
  that needs the same radar then copies them or writes its own, which is the
  problem this record removes.
- **A shared mapping repository separate from the library.** Mappings are
  pack lines and model keys; a second repository would split one format across
  two homes and two gates.
