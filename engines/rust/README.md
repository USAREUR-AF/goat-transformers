# goat-transformers (Rust)

The reference engine of [goat-transformers](https://github.com/USAREUR-AF/goat-transformers):
it converts messages between formats that are described by data files (packs).
Standard library only.

```toml
[dependencies]
goat-transformers = { git = "https://github.com/USAREUR-AF/goat-transformers", tag = "v0.8.0" }
```

```rust
let mut engine = goat_transformers::Engine::new();
engine.load_model_dir(std::path::Path::new("vendor/goat/model"))?;
engine.load_pack_dir_only(std::path::Path::new("vendor/goat/packs"), &["cot-xml", "geojson"])?;
let geojson = engine.convert("cot-xml", "geojson", cot_event)?;
```

The crate holds the engine. The packs are data: `tools/goat-pkg bundle` in the
repository writes the ones you name, and the model modules they use, to a
directory you vendor. `docs/using.md` in the repository shows the whole path,
including packs compiled into the binary.

The command-line tool: `cargo install --git https://github.com/USAREUR-AF/goat-transformers --tag v0.8.0 goat-transformers`
installs `goat-xf`.

## The library API in brief

Everything is in `src/lib.rs`. The types a caller uses:

| Type | Holds |
|---|---|
| `Engine` | the loaded model modules and packs |
| `Entity` | one decoded message: `fields` (model key to `Value`), `lists`, `residue` (what the model does not hold, kept for a round trip) and `kind` |
| `Value` | `Str(String)`, `F64(f64)` or `I64(i64)` |
| `Error` | `msg`; a conversion error starts with its kind and a colon, e.g. `undeclared-key: ...` |
| `Distribution` | `Public` or `Controlled` |
| `Capability`, `Grade` | what an ordered pair carries: `carried`, `dropped`, and `Full`, `Partial` or `None` |

The methods of `Engine`:

| Method | Does |
|---|---|
| `new()` | an empty engine |
| `set_max_distribution(d)` | refuse modules and packs above `d` with `distribution-refused` |
| `load_model(text)`, `load_model_dir(dir)` | load one model module, or every `*.def` of a directory (`core.def` first, each module after the modules it uses) |
| `load_def(text)`, `load_pack_dir(dir)` | load one pack, or every `<dir>/<name>/pack.def` |
| `load_pack_dir_only(dir, &[names])` | load only the named packs of a directory: the `--packs-only` of the tool |
| `decode(format, bytes)` | message to `Entity` |
| `encode(format, &entity)` | `Entity` to message |
| `convert(from, to, bytes)` | decode, then encode; from one format to another it also applies the derivations |
| `convert_with(from, to, bytes, Some(&[(key, Value)]))` | `convert` with a context: model keys the input lacks |
| `convert_text(from, to, bytes, Some(&[(key, text)]))` | the same, the context as text, read as each key's declared type |
| `fill(&mut entity, &context)`, `complete(&mut entity)` | the two middle steps of a conversion on their own: set absent context keys; apply the `derive` lines of the modules |
| `formats()`, `modules()`, `model_keys(format)` | what is loaded |
| `capability(from, to)`, `capability_matrix()` | what carries between formats, computed from the packs without converting a message |

A message of a binary wire (`bits`, `protobuf`) is hex text. A decode, a
context and an encode by hand:

```rust
use goat_transformers::{Engine, Value};
use std::path::Path;

let mut engine = Engine::new();
engine.load_model_dir(Path::new("vendor/goat/model"))?;
engine.load_pack_dir_only(Path::new("vendor/goat/packs"), &["cot-xml", "geojson"])?;
let ent = engine.decode("cot-xml", cot_event)?;
println!("{:?}", ent.fields.get("callsign"));
let ctx = [("stale_ms".to_string(), Value::I64(1614456060000))];
let cot = engine.convert_with("geojson", "cot-xml", geojson, Some(&ctx))?;
let c = engine.capability("cot-xml", "geojson");   // c.grade, c.carried, c.dropped
```

Both examples in this file compile against this crate as a path dependency.

## The command-line tool `goat-xf`

```
goat-xf convert --from <format> --to <format> [--set <key>=<value>]... < input
goat-xf list-formats
goat-xf matrix [--detail]
```

| Option | For every subcommand |
|---|---|
| `--packs <dir>` | the pack directory; default `../../packs` |
| `--models <dir>` | the model modules; default `<packs>/../model` |
| `--packs-only <name>[,<name>...]` | load only these packs of `--packs` |
| `--max-distribution public` | refuse controlled modules and packs (`public` or `controlled`) |

`convert` reads the message on standard input and writes the result to
standard output; `--set` is repeatable and supplies a model key the input does
not carry. `list-formats` prints the loaded formats, sorted. `matrix` prints
the grade of every ordered pair (`F` all mapped fields carry, `P` some carry,
`.` none); `--detail` adds the keys carried and dropped for each pair. With no
subcommand the tool prints its usage and exits with 2; an error exits with 1.
Run in `engines/rust` after `cargo build --release`:

```
$ target/release/goat-xf convert --from cot-xml --to geojson --packs ../../packs --packs-only cot-xml,geojson < event.xml
{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
$ target/release/goat-xf matrix --detail --packs ../../packs --packs-only cot-xml,geojson
from\to cot-xm geojso 
cot-xml      -      P 
geojson      F      - 

F = all mapped fields carry   P = some carry, some dropped   . = no shared fields   - = same format

Per-pair detail (carried | dropped and why):
         cot-xml -> geojson        PARTIAL  carries: [uid, type, time_ms, how, lat, lon, hae, ce, le, callsign, course, speed_ms]  dropped: track.scoped_id, stale_ms (target `geojson` has no field for them)
         geojson -> cot-xml        FULL     carries: [uid, type, time_ms, how, lat, lon, hae, ce, le, callsign, course, speed_ms]
```

`event.xml` is the Cursor on Target event of `tests/embed.rs`.

## Test

`cargo test --release` in `engines/rust` (CI runs `cargo test` there, in the
`rust` job of `.github/workflows/conformance.yml`). Measured with rustc 1.99.1:

| Test | Covers | Measured |
|---|---|---|
| `tests/vectors.rs` | every conversion vector under `packs/*/vectors/`, with every pack loaded; every load vector under `packs/conformance/load-vectors/` | 3299 conversion vectors, 314 load vectors, 0 failed |
| `tests/api.rs` | what a vector cannot reach: `fill` and `complete` on their own, lists, item kinds, `model_keys`, `capability`, the directory loaders, `load_pack_dir_only` | 12 tests |
| `tests/fuzz.rs` | random, cut and mutated input and hostile shapes for every pack: never a panic, only a named error | 170558 inputs over 96 packs |
| `tests/embed.rs` | packs compiled into the binary with `include_str!` | 1 test |

`GOAT_FUZZ_ITERS=<n>` multiplies the fuzz inputs; `GOAT_FUZZ_SEED=<n>`
changes the seed.

## Static and WebAssembly builds

Each release carries `goat-xf` for `x86_64-unknown-linux-musl` and
`aarch64-unknown-linux-musl`, statically linked, and for `aarch64-apple-darwin`
and `x86_64-apple-darwin` (`docs/using.md`, "What a release holds"). The
library builds for WebAssembly with
`cargo build --release --lib --target wasm32-unknown-unknown`.
`bindings/wasm` wraps this crate as a WebAssembly module with a JavaScript
wrapper, and `bindings/c` as a C library, shared and static; CI tests both
against every conversion vector (`bindings/README.md`).

## Why it is the reference engine

A change to the pack language lands first in `spec/engine-spec.md`, then here,
then in vectors whose expected bytes are derived without an engine, then in
each of the other six engines from the specification and the vectors only
(AGENTS.md, rule 2). Every section of the specification is implemented here
first, and the C and WebAssembly builds in `bindings/` are built from it.
