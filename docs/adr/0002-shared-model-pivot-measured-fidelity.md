# ADR 0002: Shared-model pivot, measured fidelity, pair overrides

Status: Accepted (2026-11-15)

## Context

Converting N formats any-to-any is either N×N direct conversions (lossless per
pair, unmaintainable) or a pivot: every format to and from one shared model, 2N
mappings. A pivot is lossy for anything it does not model. Some systems pick
one rich format as the pivot and treat it as lossless. No pivot is lossless across formats unless it is a
strict superset of all of them; such a claim is a per-pair, per-message property,
not a blanket guarantee.

## Decision

Use the **shared model as the pivot** (2N), not N×N. Do not adopt any format's own
model as the universal pivot.

Make losslessness **measured, not asserted**. Grade each conversion:

- `lossless` — A→B→A returns the original within B's expressivity, proven by a vector.
- `lossy-logged` — the pivot drops a named field; it round-trips same-format via
  residue but does not reach B; what is dropped is recorded.
- `pair-override` — a direct A↔B rule carries a pair losslessly where the pivot
  cannot. Overrides are the exception and each cites its evidence.

A claim that a third format is a lossless pivot for a sub-domain is one way to
implement an override — adopted only where a round-trip vector shows it holds,
never where merely asserted.

## Consequences

- The matrix stays 2N; the N×N cost is paid only on the specific pairs that must
  not lose anything.
- Loss is visible and logged, not hidden inside a "lossless" claim.
- A claim that a format is a lossless pivot is tested by vectors; the design
  does not assume it.
- See `docs/design.md` §Fidelity.
