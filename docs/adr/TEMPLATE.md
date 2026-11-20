# ADR NNNN: <the decision, in a few words>

Status: Proposed (YYYY-MM-DD)

<!-- Copy this file to docs/adr/NNNN-<short-name>.md, with the next number,
and add a row to docs/adr/INDEX.md. A change to model/core.def or
model/track.def needs one (AGENTS.md, "The shared model is governed like the
specification"); CI runs tools/model-governance.py on every pull request. -->

## Changes

The model files this decision changes, each on its own line, with what
changes in it: `model/core.def`: key `<key>` added, `<type>`, `<unit>`.
A key is never renamed and never changes type; a new meaning is a new key.

## Context

What a user needs that the model cannot hold today, with an example message.

## Decision

What is added, why it belongs in `core` or `track` and not in a module of its
own, its type and unit, and what a pack does when the source does not state
it (the key is absent; a pack never invents a value).

## Consumers re-measured

Every project that pins this library ran its comparison at the commit of this
change before it merged (docs/consumer-proofs.md). One row per project.

| Project | Library commit | Result before | Result after | Differences |
|---|---|---|---|---|
| <project> | <commit> | <fields equal> | <fields equal> | <none, or each difference and why> |

## Consequences

What changes for packs, engines and users; what a format that cannot carry the
new key does (the capability report lists it as dropped).
