# Contributing

Thank you for working on goat-transformers. This page is the whole process; nothing else is required reading before your first pull request.

## The short version

1. Fork, or branch from `main` if you have write access. Branch names: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`.
2. Make the change. Run the gates that apply (below). Update the specification or the design document in the same change when behavior changes.
3. Commit with a [Conventional Commits](https://www.conventionalcommits.org/) subject and a DCO sign-off: `git commit -s -m "fix(rust): …"`.
4. Open a pull request against `main`. A maintainer merges it, by squash, when every check passes.

## Commits

- **Conventional Commits.** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, with a scope in parentheses naming the engine, pack or tool (`feat(pack-geojson): …`, `fix(go): …`). The subject is ≤ 100 characters and says what changed, in the imperative.
- **DCO sign-off on every commit** (`git commit -s`). By signing off you certify the [Developer Certificate of Origin 1.1](https://developercertificate.org/): you wrote the change or have the right to submit it under this project's license. There is no CLA. The policy is in [Policy](#policy).
- **Signed commits** are required on `main`; set up [SSH or GPG commit signing](https://docs.github.com/en/authentication/managing-commit-signature-verification) once.
- One logical change per pull request. Refactors and behavior changes are separate pull requests.

## Gates

Every CI check is a command you can run locally before you push. `.github/workflows/conformance.yml` runs the same commands.

| Change touches | Run |
|---|---|
| anything | `python3 -I tools/boundary-gate` |
| a pack, a model module, the specification | every engine below: each one runs every vector of every pack |
| Rust (`engines/rust`) | `cd engines/rust && cargo test --release` |
| Go (`engines/go`) | `cd engines/go && go vet ./... && go test ./...` |
| a generator or a vector script (`tools/gen`) | `python3 -I -m unittest discover -s tools/gen/tests`; each vector script with `--check` |
| Python (`engines/python`) | `cd engines/python && PYTHONPATH=src python3 -m unittest discover -s tests` |
| Java (`engines/java`) | `cd engines/java && ./build.sh` |
| C++ (`engines/cpp`) | `cmake -S engines/cpp -B build/cpp && cmake --build build/cpp && ctest --test-dir build/cpp --output-on-failure` |
| Erlang (`engines/erlang`) | `cd engines/erlang && ./build.sh && ./run_tests` |
| Zig (`engines/zig`, Zig 0.13.0) | `cd engines/zig && zig build test -- ../../packs` |

## The counts in the README

`README.md` quotes counts of formats, message kinds, model keys, vectors and engines, and the size of the WebAssembly module. They are counted from the tree, never typed from memory. After a change that adds or removes a pack, a vector, a model key or an engine, run

```
python3 -I tools/repo-stats             # the totals
python3 -I tools/repo-stats --formats   # one table row per format
```

and make the table under "What the repository holds" in `README.md` equal its output. The WebAssembly size is printed only when the module has been built (`cd bindings/wasm && cargo build --profile small --target wasm32-unknown-unknown`). The figures under `docs/figures/` are hand-written SVG, one file for a light page and one for a dark page; they carry no counts.

## Working with an AI assistant

[AGENTS.md](AGENTS.md) holds the rules and commands for an assistant, `.claude/skills/` the step-by-step procedures, and `.claude/agents/` the roles. The rules there are the rules on this page; when they differ, this page and the specification are right and the assistant file is to be corrected.

## The conformance suite

A conversion vector is a JSON file `{name, from, to, input, expect}` under `packs/<format>/vectors/`. A load vector under `packs/conformance/load-vectors/` is a set of model modules and one pack that must load, or must fail with a named error. The format is `spec/vector-format.md`. Every engine runs every vector and must reproduce `expect` byte for byte. A change is correct when all seven engines pass; the engine test commands in the table above are the suite.

## Adding a pack

A pack adds a format as data. No engine changes when the format's wire type exists.

1. Create `packs/<format>/pack.def`: `format`, `wire`, `distribution public`, one or more `source` lines naming the public document the pack is written from and its license, and one `field` line per mapped value. The grammar is `spec/engine-spec.md`; the model keys are in `model/` and `spec/shared-model.md`.
2. Add `packs/<format>/pack.md` (notes for a reader: what is mapped and what is not) and `packs/<format>/PROVENANCE.md` (where each source file can be obtained, its version or commit, its SHA-256 and its license statement).
3. Add vectors under `packs/<format>/vectors/`: a round trip in the format, and conversions to and from one or more other formats. State values worked from the standard or from messages the source publishes; do not copy text from a source.
4. Run all seven engines and `python3 -I tools/boundary-gate`.
5. Add the source to [NOTICE](NOTICE).

Only formats whose specification is public belong in this repository. A format whose specification is not public goes in a private overlay ([docs/boundary.md](docs/boundary.md)). The source files themselves (schemas, standards documents) are not committed here.

A pack for a large message catalog is written by a generator in `tools/gen/` (`proto2pack.py`, `xsd2pack.py`, `canboat2pack.py`, `mavlink2pack.py`, `asterix2pack.py`). Change the generator and run it again; do not edit its output by hand. Every generator takes `--out <dir>` and `--check` (write nothing, exit 1 when a file under `--out` differs from what the run writes) and loads its own output with `tools/gen/gtcheck.py`.

## Adding a wire type

A wire type is a codec that every engine implements, so it is a change to the specification and to seven engines.

1. Write the section in `spec/engine-spec.md`: the locator grammar, decode, encode, the canonical output form and the load errors.
2. Add a `conformance-*` pack with a synthetic format that exercises every rule of the section, and load vectors for every load error.
3. Implement it in the Rust engine (the reference), then in each other engine from the specification and the vectors only.

## Adding an engine

An engine is written from `spec/` and the vectors, never from another engine's source. That independence is what lets the engines check each other ([spec/interop-and-sharing.md](spec/interop-and-sharing.md)).

1. Create `engines/<language>/` using only the language's standard library.
2. Implement load (model modules, then packs), `decode`, `encode`, `convert` and the capability matrix as `spec/engine-spec.md` states them.
3. Add a test runner that loads `model/` and `packs/`, runs every conversion vector and every load vector, prints each failure and exits non-zero on any failure.
4. Add a job to `.github/workflows/conformance.yml` with a pinned action version and a timeout.

## Design documents

A change to behavior updates the specification under `spec/` or the design document under `docs/` **in the same pull request**. Status words mean exactly this:

| Word | Means |
|---|---|
| built | the code exists and runs |
| measured | a command ran and produced the stated result |
| designed | decided, not implemented |
| not built | nothing exists |

A decision a later contributor would need the reason for is an ADR under `docs/adr/`, with its row in `docs/adr/INDEX.md` in the same change. ADRs are never rewritten; they are superseded.

## Review

Reviewers look for: the change does what its subject says and nothing else; the gates pass; the specification moved with the code; status words are accurate; every pack names a public source; no local path, private repository name or personal address entered the tree. Review comments are about the change, not the author.

## Reporting a bug or proposing a feature

Open an issue. For a vulnerability, **do not open an issue**; follow [SECURITY.md](SECURITY.md).

## License

Portions written by U.S. Federal government employees within the scope of their employment are not subject to copyright in the U.S.; in countries where copyright is recognized, they and all other contributions are licensed under the [Apache License 2.0](LICENSE). See [INTENT.md](INTENT.md). Contributions are accepted under the [Policy](#policy) below.

**NOTE: This CONTRIBUTING.md is for software contributions. You do not need to follow the Developer's Certificate of Origin (DCO) process for commenting on this repository's documentation, such as CONTRIBUTING.md, INTENT.md, etc. or for submitting issues.**

## Policy

### 1. Introduction

The project maintainer for this Project will only accept contributions using the Developer's Certificate of Origin 1.1 located at [developercertificate.org](https://developercertificate.org) ("DCO"). The DCO is a legally binding statement asserting that you are the creator of your contribution, or that you otherwise have the authority to distribute the contribution, and that you are intentionally making the contribution available under the license associated with the Project ("License").

### 2. Developer Certificate of Origin Process

Before submitting contributing code to this repository for the first time, you'll need to sign a Developer Certificate of Origin (DCO) (see below). To agree to the DCO, add a `Signed-off-by` line to every commit with `git commit -s`. At a high level, signing off tells us that you have the right to submit the work you're contributing and indicates that you consent to our treating the contribution in a way consistent with the license associated with this software (as described in [LICENSE](LICENSE) and [INTENT.md](INTENT.md)) and its documentation ("Project").

### 3. Important Points

Pseudonymous or anonymous contributions are permissible, but you must be reachable at the email address provided in the Signed-off-by line.

If your contribution is significant, you are also welcome to add your name and copyright date to the source file header.

U.S. Federal law prevents the government from accepting gratuitous services unless certain conditions are met. By submitting a pull request, you acknowledge that your services are offered without expectation of payment and that you expressly waive any future pay claims against the U.S. Federal government related to your contribution.

If you are a U.S. Federal government employee and use a `*.mil` or `*.gov` email address, we interpret your Signed-off-by to mean that the contribution was created in whole or in part by you and that your contribution is not subject to copyright protections.

### 4. DCO Text

The full text of the DCO is included below and is available online at [developercertificate.org](https://developercertificate.org):

```txt
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
1 Letterman Drive
Suite D4700
San Francisco, CA, 94129

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.

Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```
