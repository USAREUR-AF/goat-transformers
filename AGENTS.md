# AGENTS.md

Instructions for an AI assistant working in this repository. A person can read
it too: it is the short form of [CONTRIBUTING.md](CONTRIBUTING.md),
[docs/design.md](docs/design.md) and [docs/boundary.md](docs/boundary.md).

## What this repository is

goat-transformers converts messages between formats. A format is a data file
(a **pack**). Every pack maps the fields of its format to the keys of one
**shared model**, so a conversion is "decode the source to the model, encode
the model to the target". Seven **engines**, one per language, read the same
packs. Each engine is written from the specification and the conformance
vectors only, and all seven must produce the same bytes for every vector.

## Layout

| Path | Holds |
|---|---|
| `spec/engine-spec.md` | the pack grammar, the wire types, decode, encode, errors; one section per version |
| `spec/shared-model.md` | the model: modules, keys, types, units, lists, distribution |
| `spec/vector-format.md` | the conformance vector file |
| `spec/interop-and-sharing.md` | why engines are independent |
| `model/<module>.def` | one model module: `key`, `list` and `derive` lines |
| `packs/<format>/pack.def` | one format |
| `packs/<format>/pack.md` | what the pack maps and what it does not |
| `packs/<format>/PROVENANCE.md` | where each source can be obtained, its version, its SHA-256, its license |
| `packs/<format>/vectors/*.json` | conversion vectors: `from`, `to`, `input`, `expect` |
| `packs/conformance/load-vectors/*.json` | load vectors: modules and a pack that must load or fail with a named error |
| `packs/conformance*`, `packs/demo-*` | synthetic formats that exercise the rules of the specification |
| `engines/<language>/` | `rust` (the reference), `go`, `python`, `java`, `cpp`, `erlang`, `zig` |
| `bindings/c`, `bindings/wasm` | the Rust engine as a C library and as a WebAssembly module |
| `adapters/` | transports around the Rust engine (`goat-xf-pipe`); the engine does not depend on it |
| `tools/boundary-gate` | refuses content that is not public |
| `tools/goat-pkg` | plans the smallest package for a set of constraints |
| `tools/repo-stats` | prints the counts that `README.md` quotes |
| `tools/gen/` | generators that write a pack from a machine-readable definition |
| `docs/` | design, decision records (`docs/adr/`), coverage, roadmap |

## Rules that are not negotiable

1. **An engine is written from `spec/` and the vectors only.** When you work on
   `engines/<language>/`, do not open, search or quote any other directory
   under `engines/`. The engines check one another only while they are
   independent. If the specification does not answer a question, the fix is a
   sentence in the specification and a vector, not a look at another engine.
2. **A change to the pack language lands in this order:** the text in
   `spec/engine-spec.md`; the reference engine (`engines/rust`); vectors whose
   expected bytes were worked out by hand or by an independent program; then
   each of the other six engines, each from the specification and the vectors.
3. **Nothing that is not public enters this repository.** No field name, layout,
   value table, example message or document text from a specification that is
   not public; no file of a type the gate does not list. Run
   `python3 -I tools/boundary-gate` before every commit. It must print
   `boundary-gate: ok`.
4. **Every pack and every model module states `distribution` and at least one
   `source`.** In this repository `distribution` is always `public`. A file
   without either line does not load.
5. **Expected bytes in a vector are derived independently of the engines.**
   Work them from the format's specification, from a message the source
   publishes, or from a program that does not import an engine. Never produce
   `expect` by running an engine and pasting its output.
6. **Generated packs are not edited by hand.** A `pack.def` whose first lines
   say it was generated is written by a generator in `tools/gen/`; change the
   generator and run it again.
7. **A model key is never renamed and never changes type.** The model grows by
   new keys and new modules.
8. **No local absolute path, private organization name or email address** in
   any file. The gate refuses them.

## Ask a human before you do any of these

- Use a source whose license you have not read, or whose license restricts
  reuse (non-commercial, no-derivatives, membership-only, paid standard). State
  the license text you found and wait.
- Add anything derived from a document that carries a distribution statement, a
  handling marking, an export-control notice or a "proprietary" notice, or from
  a document you cannot show to be public. The answer for such a format is an
  overlay (`write-an-overlay` skill), not this repository.
- Copy text, tables or example messages out of a standard. Packs state layouts
  and values in their own words.
- Add a line with `boundary-allow:`, or change `tools/boundary-gate`.
- Add a dependency to an engine. Every engine uses only its language's
  standard library.
- Rename or retype a model key, or delete a vector.
- Commit, push, open or merge a pull request, unless the person asked for it.

## Commands

Run from the repository root unless a directory is named.

| Purpose | Command |
|---|---|
| Boundary gate | `python3 -I tools/boundary-gate` |
| Counts for `README.md` | `python3 -I tools/repo-stats` |
| Rust engine and CLI | `cd engines/rust && cargo build --release` gives `target/release/goat-xf` |
| Rust, every vector | `cd engines/rust && cargo test --release` |
| Go | `cd engines/go && go vet ./... && go test ./...` |
| Python | `cd engines/python && PYTHONPATH=src python3 -m unittest discover -s tests` |
| Java | `cd engines/java && ./build.sh` |
| C++ | `cmake -S engines/cpp -B build/cpp && cmake --build build/cpp && ctest --test-dir build/cpp --output-on-failure` |
| Erlang | `cd engines/erlang && ./build.sh && ./run_tests` |
| Zig 0.13.0 | `cd engines/zig && zig build test -- ../../packs` |
| C library | `cd bindings/c && ./test.sh` |
| WebAssembly module | `cd bindings/wasm && cargo build --release --target wasm32-unknown-unknown` (`--profile small` for the smallest) |
| WebAssembly, vectors | `node --test bindings/wasm/test/vectors.test.mjs` (`GT_PACKS=a,b` chooses packs, `GT_WASM=<file>` chooses the build) |
| Transport adapters | `cd adapters && cargo test --locked` (`adapters/zenoh` is built on its own: `cd adapters/zenoh && cargo test`) |

Each engine test command loads every pack and runs every vector. For a quick
check of one pack, load only the packs you name with `--packs-only`:

```bash
engines/rust/target/release/goat-xf list-formats --packs packs --packs-only geojson,cot-xml
engines/rust/target/release/goat-xf matrix --detail --packs packs --packs-only geojson,cot-xml
```

Every tool reads model modules from `<packs>/../model` unless `--models <dir>`
is given. Where the packs come from when `--packs <dir>` is not given differs:
the Rust `goat-xf` reads `../../packs` relative to the current directory, the
Go `goat-xf` reads `packs`, and the Java tool requires `--packs`. Each engine's
`README.md` states its tool's options. `--packs-only <name>[,<name>…]` loads only the
named packs of that directory; every engine's command-line tool has it.

## How to add a pack

The `add-a-format` skill has the full steps. In short:

1. Confirm the specification is public and read its license.
2. Create `packs/<format>/pack.def`: `format`, `version`, `distribution public`,
   `source` lines, `wire`, then `field` lines binding model keys
   (`model/core.def`, `model/track.def`) to places in the message.
3. A field with no model key needs no line where the wire keeps residue; for a
   catalog, add a module `model/<module>.def` of raw keys and `uses <module>`.
4. Add vectors under `packs/<format>/vectors/`: a round trip, and a conversion
   to and from one or more other formats, with independently derived `expect`.
5. Write `pack.md` and `PROVENANCE.md`; add the source to `NOTICE`.
6. Run all seven engines and the gate.

## How to add a wire type

1. Write the section in `spec/engine-spec.md`: locator grammar, decode, encode,
   canonical output, load errors.
2. Add a `packs/conformance-<name>/` pack with a synthetic format that
   exercises every rule, and load vectors for every load error.
3. Implement it in `engines/rust`, then in each other engine from the
   specification and vectors only (rule 1).

## How to add an engine

1. Create `engines/<language>/` using only the standard library.
2. Implement loading of model modules and packs, `decode`, `encode`, `convert`
   with context, `complete`, and the capability matrix, as
   `spec/engine-spec.md` states them.
3. Add a test runner that loads `model/` and `packs/`, runs every conversion
   vector and every load vector, prints each failure and exits non-zero.
4. Add a job to `.github/workflows/conformance.yml` with a pinned action
   version and a timeout.

## How to add a derive function

A derive function computes one model key from others (`derive course bearing
track.vel_east_ms track.vel_north_ms` in `model/track.def`). The functions are
the table under "Derived keys" in `spec/engine-spec.md`.

1. Add the function to that table: name, arguments, result, the case that
   leaves the target absent.
2. Add a `derive` line that uses it to `model/probe.def`, and vectors in
   `packs/conformance-derive-functions/` that state the result in `model` with
   `"@complete": true`. Use values that derive exactly where the result appears
   in `expect`.
3. Add a load vector for the wrong argument count (`bad-directive`).
4. Implement in `engines/rust`, then in the other six engines (rule 1).

## How to read a vector failure

A failing run names the vector file. Open it and separate three cases:

| The engine | Meaning | Look at |
|---|---|---|
| returns different bytes from `expect` | encode or canonical form differs | the "Canonical output" or "Canonicalisation" text for that wire; field order is `field`-line order |
| fails with a named error, and the vector has `expect` | decode or kind selection failed | the error name: `no-kind` (the `when` values or the `requires` keys of no kind hold), `malformed-wire`, `transform-decode`, `transform-encode`, `missing-root` |
| succeeds, and the vector has `expect_error` | a check is missing | the load or decode rule that names that error |
| passes `expect` and fails a `model` value | decode differs | the transform of that field; floats compare within 1e-9 |

If one engine fails and six pass, the defect is in that engine. If the vector
is new and several engines disagree, the specification is ambiguous: quote the
sentence, propose the ruling, and add it to the specification before changing
an engine. Never change `expect` to make an engine pass.

## Commits and pull requests

- Branch from `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`.
- Conventional Commits with a scope: `feat(pack-geojson): …`, `fix(go): …`,
  `docs: …`. Subject at most 100 characters, imperative.
- Every commit is signed (SSH or GPG) and carries a DCO sign-off:
  `git commit -s`. An assistant does not sign off for a person; the person
  commits, or instructs the assistant to commit with their configured identity.
- One logical change per pull request. A behavior change updates `spec/` or
  `docs/` in the same pull request.
- Required checks: the `conformance` workflow (the boundary gate, each of the
  seven engines, the bindings). A pull request merges by squash when all pass.
- Status words in documents: built (the code exists and runs), measured (a
  command ran and gave the stated result), designed (decided, not implemented),
  not built.
- When packs, vectors or engines change in number, run
  `python3 -I tools/repo-stats` and update the counts in `README.md`.

## Writing style for documents here

Plain international English, American spelling in new text. State what exists
and how to check it. No praise words, no dates or promises, no names of
private repositories or programs.
