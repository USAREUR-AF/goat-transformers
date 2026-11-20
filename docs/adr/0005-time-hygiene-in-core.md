# ADR 0005: Time hygiene in core, on two axes, never invented

Status: Proposed (2026-11-20)

<!-- Number 0005 assumes 0.30 and 0.31 take 0003 and 0004; it is renumbered on
rebase if not. The consumer table is filled on the branch at its final commit. -->

## Changes

`model/core.def`: version 0.2.0 → 0.3.0.
`model/core.def`: key `time_utc_state` added, `string`, `-` (`confident` or `unknown`).
`model/core.def`: key `time_utc_error_ms` added, `float`, `ms`.
`model/core.def`: key `time_anchor` added, `string`, `-` (`gnss`, `peer_nts`, `wan_nts`, `orphan`, `none`).
`model/core.def`: key `time_anchor_age_ms` added, `int`, `ms`.
`model/core.def`: key `time_attested` added, `int`, `-`.
`model/core.def`: key `time_attestation` added, `string`, `-`.
No key is renamed or retyped; `time_error_ms` and `time_state` (core 0.2.0) are unchanged.

## Context

The operator asked whether the shared model keeps goat's time hygiene as a
first-class element (leads/shared-model-hardening.md, item 5). goat's time hygiene
separates two questions (goatcore ADR 1037, lines 34-35):

> **Internal coherence** — is this node locked to the fabric ensemble within a bounded synchronization error?
>
> **UTC confidence** — how well is the ensemble anchored to true UTC, and how fresh is the last anchor?

and (line 37): "A node can be **internally-coherent but UTC-unknown** — the
correct and common state for denied-edge operation — and that must read as *fully
healthy for fabric ordering*, degraded only for UTC-bound operations."

Core 0.2.0 (#120) carries the first axis only. A report that crosses the model
loses its UTC confidence and whether its time quality was attested or merely
claimed. Example: a CoT event stamped on a denied-edge node that is coherent with
its fabric but has no UTC anchor reaches goat-processors as `time_state =
coherent` with nothing to say that its absolute time is unknown, so a consumer
cannot tell it from a GNSS-anchored report.

goatcore names the axes in prose and has not yet named their fields: its design
lists the split as "two-axis split live (coherence vs UTC) — model adopted, engine
pending" (time-hygiene-trusted-time.md, lines 304-305, across a line break). The
names below take what goatcore does name, verbatim, and say where it names nothing.

## Decision

Core gains the UTC-confidence axis and an attestation (spec 0.32, which states the
sources line by line):

| Key | Type | Unit | Values | Name taken from (goatcore) |
|---|---|---|---|---|
| `time_utc_state` | string | - | `confident`, `unknown` | the axis's two labels, "🟢 UTC-confident" and "🟡 UTC-unknown" (time-hygiene-trusted-time.md lines 242-243), lowercased; no enum exists |
| `time_utc_error_ms` | float | ms | one-sigma uncertainty, ≥ 0 | `sigma_us` (time-quality-attestation.md line 55), in ms |
| `time_anchor` | string | - | `gnss`, `peer_nts`, `wan_nts`, `orphan`, `none` | `selected_source` (`ops/time-hygiene/internal/state/state.go` lines 36-40, JSON tag line 62), exactly |
| `time_anchor_age_ms` | int | ms | ≥ 0 | `seconds_since_external_lock` (time-quality-attestation.md line 57), in ms |
| `time_attested` | int | - | 1 attested, 0 stated not attested | `attested` (`crates/goat-cli/src/health_wire.rs` line 202) |
| `time_attestation` | string | - | `ntp-attest-v1:<valid_until_ms>:<host_id>` | `Alg = "ntp-attest-v1"`, `host_id`, `valid_until` (`ops/time-hygiene/internal/attest/attest.go` lines 29, 37, 44) |

Why `core` and not a module of its own: shared-model.md puts "a concept that only
some formats carry" in its own module. Time quality is not a format's concept: it
describes the `time_ms` of every report, whatever its format, as `time_error_ms`
and `time_state` already do, and the operator decided it is first-class.

What a pack does when the source does not state it: nothing. Every key is absent
unless the source states it or the caller passes it as context. No `default`, no
`derive`, no `const`, no `absent` sentinel, and no unconditional `bits` field
writes one; `tools/gen/gtcheck.py` refuses each in CI, for these five keys and for
`time_error_ms` and `time_state`. A UTC confidence that is decaying is `confident`
with a growing `time_utc_error_ms` and `time_anchor_age_ms` until the source calls
it `unknown`; there is no third state, because goatcore has none.

Where goatcore's names and the operator's brief differ, goatcore wins: the brief
itself says to "Name and shape the keys to match the goatcore time-hygiene
vocabulary and EnvHealthV1 time domain exactly" (leads/shared-model-hardening.md,
item 5). Two places differ:

- The brief lists the UTC states as anchored, decaying and unknown. goatcore
  labels the axis "🟢 UTC-confident" and "🟡 UTC-unknown" (time-hygiene-trusted-
  time.md lines 242-243) and has no label for a decaying state, only the prose
  "UTC-confidence decays honestly" (line 158). `time_utc_state` therefore takes
  `confident` and `unknown`; a decaying confidence is `confident` with a growing
  `time_utc_error_ms` and `time_anchor_age_ms`.
- The brief lists the anchor kinds as gnss, nts, peer-nts and none. goatcore's
  code names them `SourceGNSS    SelectedSource = "gnss"`,
  `SourcePeerNTS SelectedSource = "peer_nts"`, `SourceWanNTS  SelectedSource =
  "wan_nts"`, `SourceOrphan  SelectedSource = "orphan"`, `SourceNone
  SelectedSource = "none"` (`ops/time-hygiene/internal/state/state.go` lines
  36-40). `time_anchor` takes those values exactly.

If goatcore later fixes an enum for these fields, a new key carries its spelling
(a key is never renamed); otherwise goatcore adopts these spellings when its
engine builds the two-axis split.

## Consumers re-measured

Filled on the branch, at its commit, before merge.

| Project | Library commit | Result before | Result after | Differences |
|---|---|---|---|---|
| open-entity-gateway | (branch) | | | |
| open-billie | (branch) | | | |
| first-bite | (branch) | | | |
| goatstuff | (branch) | | | |
| octo-pod | (branch) | | | |

## Consequences

- Time quality travels with every report on both axes, and a consumer can tell
  attested quality from claimed. goat-processors reads the keys as it reads
  `time_error_ms` and `time_state`.
- No engine changes. Packs gain mappings as their formats state time quality.
- A format that cannot carry a key the entity holds drops it; the capability
  report lists it, and the loss report of spec 0.30 names it per conversion.
- Consumers that pass none of the keys see no change.
