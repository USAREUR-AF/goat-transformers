---
name: build-a-minimal-package
description: Plan and build the smallest goat-transformers deliverable for a stated need - only the formats required, in one language, as a static binary, a library, a C library or a WebAssembly module. Use when asked to package, embed, ship, deploy or slim down the library, to pick an engine for a platform (Linux x86_64 or aarch64, a scratch container, a browser, Node, the JVM), to get the WebAssembly or C build, or to load only some packs.
---

# Build a minimal package

Three facts make a small package possible: a pack loads on its own, the
capability report says what carries between the chosen formats, and each
engine uses only its language's standard library.

## 1. Collect the constraints

Ask for, or read from the request: the formats (pack names: `ls packs/`), the
language of the host program, the runtime (native, WebAssembly, JavaScript,
JVM), static or dynamic linkage, operating system and architecture.

## 2. Run the planner

```bash
tools/goat-pkg formats | cut -c1-120          # pack names and the wire of each
tools/goat-pkg plan --formats remote-id,cot-xml --language rust --runtime wasm
tools/goat-pkg plan --formats cot-xml,sapient --language go \
    --runtime native --linkage static --os linux --arch aarch64 | cut -c1-300
```

The plan prints the engine directory, the packs (only those named), the wire
types they use, the build command, and for each ordered pair of the named
formats what carries and what is dropped. For a catalog format the pair lines
are very long: cut or filter the output.

Read the pair lines before building. If a pair the person needs carries too
little, the package is not the problem: the packs share too few keys, and the
fix is a binding in a pack (`add-a-format`, step 3).

## 3. Carry only the packs you need

The package needs `model/` (every module the chosen packs name with `uses`,
and always `core.def`) and the chosen pack directories. Only `pack.def` is read
at run time; `vectors/`, `pack.md` and `PROVENANCE.md` are not needed in a
deployment.

```bash
mkdir -p dist/packs dist/model
for p in remote-id cot-xml; do mkdir -p dist/packs/$p && cp packs/$p/pack.def dist/packs/$p/; done
cp model/core.def model/rid.def dist/model/      # rid: `uses rid` in packs/remote-id/pack.def
goat-xf list-formats --packs dist/packs --models dist/model
```

`grep '^uses' packs/<format>/pack.def` lists the modules a pack needs. A
module may itself name another with `uses`. When `goat-xf` run with no
arguments lists `--packs-only` in its usage, `--packs-only a,b` selects packs
from a full directory without a copy.

An engine that must never load a controlled format is started with
`--max-distribution public` (library: the distribution limit of the engine).

## 4. Build

| Target | Command | Result |
|---|---|---|
| Rust, native | `cd engines/rust && cargo build --release` | `target/release/goat-xf` and the library crate `goat-transformers` |
| Rust, fully static Linux | `cargo build --release --target x86_64-unknown-linux-musl` (or `aarch64-…`), after `rustup target add` | one binary with no shared library, for a `scratch` container |
| Go, fully static | `cd engines/go && CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build ./cmd/goat-xf` | one binary |
| Java | `cd engines/java && ./build.sh` | runs on any JVM |
| Python | no build; ship `engines/python/src/goat_transformers` and a Python 3 runtime | |
| C library (the Rust engine) | `cd bindings/c && ./test.sh` | `target/release/libgoat_transformers_c.{so,dylib,a}` and `goat_transformers.h` |
| WebAssembly (the Rust engine) | `cd bindings/wasm && cargo build --profile small --target wasm32-unknown-unknown` | `target/wasm32-unknown-unknown/small/goat_transformers_wasm.wasm`, no imports, used through `goat_transformers.mjs` |

The planner prints the command for the other combinations (C++, Zig, Erlang,
Go to WebAssembly). `docs/package-configurator.md` has the full matrix.

## 5. Check the package, not the repository

Run the vectors of the chosen packs against what you built:

```bash
# WebAssembly: only the vectors of the loaded packs run; the rest are counted as skipped
GT_WASM=bindings/wasm/target/wasm32-unknown-unknown/small/goat_transformers_wasm.wasm \
GT_PACKS=cot-xml,geojson,canonical-track-v2 node --test bindings/wasm/test/vectors.test.mjs

# a native binary: one known vector
python3 -c "import json,sys;v=json.load(open(sys.argv[1]));print(v['input'])" packs/cot-xml/vectors/01-track-to-geojson.json \
  | goat-xf convert --from cot-xml --to geojson --packs <dir> --models <dir>
```

Compare the output with the vector's `expect`.

## 6. In a host program

- WebAssembly and C take the text of each `.def` file, not a directory: the
  host reads the files and calls load-model (with `core` first) and load-pack.
  `bindings/README.md` has both interfaces, the threading rules and an example
  host (`bindings/wasm/example/translate.mjs`, which reads the release build
  unless `--wasm <file>` is given).
- A binary message is hex text on both sides in the bindings.
- Record the commit of this repository the package was built from. Packs and
  engine come from the same commit.

## 7. Report

State: the formats, the engine and target, the build command used, the size of
the result (`ls -l`), the vectors run and their result, and the pair lines
that matter to the person. Remove build directories you created when disk
space is short (`engines/rust/target`, `bindings/*/target`).
