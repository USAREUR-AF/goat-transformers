---
name: extend-the-pack-language
description: Add a rule to the goat-transformers pack language or the engines - a directive, a transform, a field option, a derive function, a canonical-form ruling, or a whole wire type - so that it works identically in all seven engines. Use when a format needs something no pack can state today, when docs/roadmap.md lists the needed addition as Designed, when two engines disagree on a vector, or when asked to implement a spec section in the engines.
---

# Extend the pack language

A pack can state only what `spec/engine-spec.md` has a rule for. An addition
is one change made in a fixed order, so that seven independent engines end in
agreement. Read `AGENTS.md` first; rules 1, 2 and 5 are the method.

Order: specification text, reference engine, independently derived vectors,
the other six engines. Do not start a later step before the earlier one is
written down.

## 1. State the need

Name the format and the field that cannot be mapped, and the row of
`docs/roadmap.md` (Pack-language additions, Wire types) it belongs to. Prefer
the smallest rule that is data, not code: a directive with a fixed meaning. A
rule that only one format could ever use is a sign the rule is too narrow or
belongs in a pair rule (`docs/adr/0002`).

## 2. Write the specification text

Add to `spec/engine-spec.md`, in the style of the existing version sections
(for a new version: a `# Version 0.N: <title>` section with a `Status:` line):

- the grammar line, in a code block;
- decode, then encode, each as a rule a programmer can implement without
  asking a question: the type the rule yields, rounding (the specification
  uses round-half-away-from-zero), byte and bit order, what happens at the
  ends of the range;
- the canonical output form, when the rule writes text;
- every error by name: which condition gives `bad-directive` at load,
  `transform-decode`, `transform-encode`, `malformed-wire`, `no-kind`;
- how it interacts with kinds, `default`, `via`, groups and residue;
- numbered rulings for the cases a reader would otherwise decide alone, and a
  list "stated, not yet pinned by a vector" for any that have no vector.

If the model changes (a new key type, a list rule), change
`spec/shared-model.md` too. If vectors gain a member, change
`spec/vector-format.md`.

Then have the text reviewed for ambiguity before any code: use the
`spec-reviewer` agent. Every ambiguity it quotes becomes a ruling.

## 3. Write the vectors, by hand

Create or extend a synthetic pack `packs/conformance-<topic>/` (see the
existing `packs/conformance-*` for the pattern): a format invented to exercise
each rule, with `source "synthetic format, no external standard"`, mapping keys
of `model/probe.def` where no real key fits.

- One vector per rule and per ruling, named for what it shows
  (`06-status-of-one-octet-is-written-with-the-default-extents.json`).
- Edge values: zero, the largest and smallest value, a value that rounds, the
  empty case, the error case (`expect_error`).
- A load vector under `packs/conformance/load-vectors/` for each load error.
- Work every `expect` from the specification text by hand or with a short
  program that imports no engine. Use the `vector-deriver` agent, and give it
  the specification section only. A vector whose expected bytes came from an
  engine proves only that the engine agrees with itself.

Where a real format motivated the change, also add a vector from a message
that the format's source publishes.

## 4. Implement in the reference engine

`engines/rust` (`src/lib.rs`, `src/seq.rs` for sequential layouts).

```bash
cd engines/rust && cargo test --release
```

Each failure names a vector. If the reference engine and a hand-derived vector
disagree, decide from the specification text which is wrong. If the text does
not decide, the text is incomplete: add the ruling first.

## 5. Implement in the other six engines, independently

One agent per engine (`engine-implementer`), each given:

- its one directory, `engines/<language>/`;
- the specification section and the names of the new vectors;
- nothing from any other engine: no code, no diff, no description of how
  another engine did it.

Each agent reports its test result and any sentence of the specification it
had to interpret. Two engines that interpret a sentence differently have found
an ambiguity: quote the sentence, write the ruling into the specification, add
a vector that pins it, and return to step 4. Do not settle a disagreement by
reading the reference engine's source.

Test commands for each engine are in `AGENTS.md` (Commands). The C library and
the WebAssembly module wrap the Rust engine; run `bindings/c/test.sh` and
`node --test bindings/wasm/test/vectors.test.mjs` after the Rust change.

## 6. Use it in a real pack

Change or add the pack that needed the rule, with its vectors, in the same
pull request or the next one. Update the pack's `pack.md` ("not mapped"
shrinks).

## 7. Update the documents in the same change

- `docs/roadmap.md`: the row moves from Designed to Built, with the version.
- `docs/design.md` and `docs/coverage-roadmap.md` where they name the rule.
- `README.md` counts: `python3 -I tools/repo-stats`.
- A decision a later reader would need the reason for: an ADR under
  `docs/adr/` and its row in `docs/adr/INDEX.md`.

## 8. Gate

```bash
python3 -I tools/boundary-gate
```

All seven engines pass every vector, old and new. A change that makes an
existing vector fail is a change of behavior: it needs its own ruling in the
specification ("Two corrections to earlier rulings" in Version 0.6 is the
pattern), never a silent edit of the vector.

## A derive function or a transform only

The same order, smaller: the row in the function or transform table of the
specification; vectors in `packs/conformance-derive-functions/` or the
matching `conformance-rules-*` pack; a load vector for a wrong argument count;
the reference engine; the other six. A derived float is stated in a vector's
`model` with `"@complete": true` and compared within 1e-9 relative, not in
`expect`, unless the value derives exactly.
