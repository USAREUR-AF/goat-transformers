# ADR 0001: Data-driven packs and independent per-language engines

Status: Accepted (2026-11-15)

## Context

The library converts tactical messages between many formats, in many languages
(Rust, Go, C++, Java, Python, Erlang, Zig). Two forces pull against each other:
breadth of formats and breadth of languages. Hand-writing each format in each
language is work proportional to formats × languages, and lets the languages
drift apart.

## Decision

A format is **data**, not code. Each format is a pack: a `pack.def` dictionary,
mapping rules, and conformance vectors (`spec/engine-spec.md`, `spec/pack` format).
Each language implements **one** engine that interprets packs. A new format is new
data files, working in every language at once — not new code in each.

The engines are **independent**: each is written from the specification and the
shared vectors, never from another engine's source (`spec/interop-and-sharing.md`).
They exist to cross-check each other — all engines run all vectors, byte-for-byte.
Cross-language FFI (the Rust C ABI / WebAssembly) is allowed for shipping, but the
conformance cross-check always runs the independent native engines.

## Consequences

- Work scales with formats + languages, not formats × languages.
- A defect in one engine is caught by the others on the shared vectors.
- The cost is one spec precise enough that seven engines agree byte-for-byte; the
  v0.1.1 rulings (`spec/engine-spec.md`) exist to pin the points where they didn't.
- A new wire type (text or binary) is a change to all engines, so wire types are
  added deliberately and proven on the reference before fan-out.
