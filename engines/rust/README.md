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
| `Entity` | one decoded message: `fields` (model key to `Value`), `lists`, `residue` (what the model does not hold, kept for a round trip), `kind` and `inner_kind` (the kind the pack of an `inner` line selected, spec 0.34) |
| `Value` | `Str(String)`, `F64(f64)` or `I64(i64)` |
| `Error` | `msg`; a conversion error starts with its kind and a colon, e.g. `undeclared-key: ...` |
| `Distribution` | `Public` or `Controlled` |
| `Capability`, `Grade` | what an ordered pair carries: `carried`, `dropped`, and `Full`, `Partial` or `None` |
| `Profile` | a licence profile: `Open`, `OpenCopyleft` or `Everything` (spec 0.29) |
| `LoadOptions`, `LoadedPack`, `PackLicence` | what `load_tree` is asked to load, and what it loaded |

The methods of `Engine`:

| Method | Does |
|---|---|
| `new()` | an empty engine |
| `set_max_distribution(d)` | refuse modules and packs above `d` with `distribution-refused`; after a load with a licence profile the limit stays `public` (spec 0.93) |
| `set_max_items(n)` | the limit on list items one decode holds (default `DEFAULT_MAX_ITEMS`, 100000); one more is `malformed-wire` |
| `load_model(text)`, `load_model_dir(dir)` | load one model module, or every `*.def` of a directory (`core.def` first, each module after the modules it uses) |
| `load_def(text)`, `load_pack_dir(dir)` | load one pack, or every `<dir>/<name>/pack.def` |
| `load_pack_dir_only(dir, &[names])` | load only the named packs of a directory: the `--packs-only` of the tool |
| `load_tree(packs, &options)` | load a model directory and a packs directory exactly as the tool does, with an optional licence profile (below) |
| `decode(format, bytes)` | message to `Entity` |
| `encode(format, &entity)` | `Entity` to message |
| `convert(from, to, bytes)` | decode, then encode; from one format to another it also applies the derivations |
| `convert_with(from, to, bytes, Some(&[(key, Value)]))` | `convert` with a context: model keys the input lacks |
| `convert_text(from, to, bytes, Some(&[(key, text)]))` | the same, the context as text, read as each key's declared type |
| `decode_limited(format, bytes, n)`, `convert_text_limited(from, to, bytes, context, n)` | `decode` and `convert_text` with the limit on list items given for the call |
| `fill(&mut entity, &context)`, `complete(&mut entity)` | the two middle steps of a conversion on their own: set absent context keys; apply the `derive` lines of the modules |
| `formats()`, `modules()`, `model_keys(format)` | what is loaded |
| `capability(from, to)`, `capability_matrix()` | what carries between formats, computed from the packs without converting a message |
| `try_capability(from, to)`, `try_model_keys(format)` | the same, `unknown-format` for a format that is not loaded |
| `key_type(key)` | the declared type of a model key |

A message of a binary wire (`bits`, `protobuf`, `tlv`, `cbor`) is hex text. A decode, a
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

The Rust examples in this file compile against this crate as a path dependency.

### Loading with a licence profile

Each pack has one licence (`packs/<name>/REUSE.toml`; none means
Apache-2.0), each model module may have one (`model/<file>.def.license`), and
`licences.toml` beside the packs directory says what each licence allows.
From these every pack and module is in one of three profiles, or in none
(spec 0.29):

| Profile | Holds |
|---|---|
| `open` | licences that allow commercial use, with no share-alike and no field-of-use limit |
| `open+copyleft` | `open`, and share-alike licences that allow commercial use |
| `everything` | every public licence: also non-commercial, unknown, or with a field-of-use limit |

A licence marked `distribution = "controlled"` is in none of them, and so is
a module file or `pack.def` that does not itself say `distribution public`
in exactly that form, with no other line beginning with `distribution`
(spec 0.93). A pack's profile is the widest of its own licence, `core`'s,
and those of the modules it uses. `load_tree` takes the profile as text, so a wrong name is
`bad-licence` before anything is read:

```rust
use goat_transformers::{Engine, LoadOptions};
use std::path::Path;

let mut engine = Engine::new();
let options = LoadOptions { profile: Some("open".to_string()), ..LoadOptions::default() };
let loaded = engine.load_tree(Path::new("vendor/goat/packs"), &options)?;
for p in &loaded {
    let l = p.licence.as_ref().unwrap();     // present when a profile was given
    println!("{} {} {}", p.format, l.licence, goat_transformers::profile_name(l.profile));
}
```

A module or pack the profile does not hold is skipped as if it were not
there: its format is `unknown-format`, and a skipped pack is never parsed.
The other fields of `LoadOptions` are `models` (default `<packs>/../model`),
`packs_only` (the tool's `--packs-only`) and `read_licences` (read the
licences with no profile, so that each loaded pack reports its own). With no
profile and no `read_licences`, no licence file is read and everything loads
as before. A licence file that does not follow the forms of the
specification is `bad-licence`.

A load with a profile sets the engine's distribution limit to `public` for
the life of the instance, whatever `set_max_distribution` was given before
or after (spec 0.93): a controlled module or pack loaded later, with or
without a profile, is `distribution-refused`. On an instance that already
holds a controlled module or pack, a load with a profile is
`distribution-refused` before anything is read.

## The command-line tool `goat-xf`

The tool follows the command-line contract of spec 0.23
(`spec/engine-spec.md`, Version 0.23), the same in all seven engines.

```
goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options> < input
goat-xf list-formats <options>
goat-xf capability --from <format> --to <format> <options>
goat-xf matrix <options>
goat-xf licences [--json] <options>
goat-xf help
```

| Option | For every subcommand |
|---|---|
| `--packs <dir>` | the pack directory; default `../../packs` |
| `--models <dir>` | the model modules; default `<packs>/../model` |
| `--packs-only <name>[,<name>...]` | load only these packs of `--packs`, in this order |
| `--max-items <n>` | the limit on list items one decode holds; default 100000, 0 refuses any item |
| `--max-distribution <public\|controlled>` | `public` refuses controlled modules and packs; beside `--profile` the limit is `public` whatever is given (spec 0.93) |
| `--profile <open\|open+copyleft\|everything>` | load only the modules and packs this licence profile holds (spec 0.29); default: no profile, no licence file read |

`convert` reads the message on standard input and writes the result to
standard output, with no line feed added; a binary format reads and writes
hex text. `--set` is repeatable and supplies a model key the input does not
carry. `list-formats` prints one line per loaded format: name, version and
wire, separated by tabs. `capability` prints the capability report of one
pair as a tab-separated line: source, target, grade (`full`, `partial` or
`none`), the keys that carry and the keys dropped, each list joined by
spaces. `matrix` prints a header line and that line for every ordered pair
of loaded formats. `licences` reads every licence file, with or without
`--profile`, and prints one line per loaded pack, sorted by directory name:
directory, format, licence and the pack's own profile (`none` when it is in
no profile), separated by tabs; with `--json`, the only option that takes
no value, it prints one JSON object `{"packs":[{"pack":...,"format":...,"licence":...,"profile":...},...]}`
instead. The exit status is 0 on success, 1 for a load or
conversion error (standard error begins with its kind, then a colon; a
broken licence file is `bad-licence`) and 2 for a usage error, a `--profile`
value that is not one of the three names included. Run in `engines/rust` after `cargo build --release`:

```
$ target/release/goat-xf convert --from cot-xml --to geojson --packs ../../packs --packs-only cot-xml,geojson < event.xml
{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
$ target/release/goat-xf capability --from cot-xml --to geojson --packs ../../packs --packs-only cot-xml,geojson
cot-xml	geojson	partial	uid type time_ms how lat lon hae ce le callsign course speed_ms	track.scoped_id stale_ms access time_text stale_text display_name
$ target/release/goat-xf licences --profile open --packs ../../packs/conformance/tool-fixtures/licences-a/packs
plain	lic-plain	Apache-2.0	open
zz-first-by-format	lic-aa	Apache-2.0	open
```

`event.xml` is the Cursor on Target event of `tests/embed.rs`.

## Test

`cargo test --release` in `engines/rust` (CI runs `cargo test` there, in the
`rust` job of `.github/workflows/conformance.yml`). Measured on 2026-11-24 with rustc 1.99.1:

| Test | Covers | Measured |
|---|---|---|
| `tests/vectors.rs` | every conversion vector under `packs/*/vectors/`, with every pack loaded; every load vector under `packs/conformance/load-vectors/` | 24611 conversion vectors, 1471 load vectors, 27 capability vectors, 0 failed |
| `tests/api.rs` | what a vector cannot reach: `fill` and `complete` on their own, lists, item kinds, `model_keys`, `capability`, the directory loaders, `load_pack_dir_only` | 15 tests |
| `tests/fuzz.rs` | random, cut and mutated input and hostile shapes for every pack: never a panic, only a named error | 6925424 inputs over 4669 packs and 24608 vectors |
| `tests/embed.rs` | packs compiled into the binary with `include_str!` | 1 test |
| `tests/cbor.rs` | spec 0.28: the `cbor` wire on byte strings built by hand from RFC 8949: heads of every length, the core deterministic encoding (key order, shortest floats), the depth limit, equal keys, UTF-8 across chunks, tags, residue and the `tag` directive | 17 tests |
| `tests/uper.rs` | ASN.1 unaligned PER checks derived by hand (spec 0.19) | 9 tests |
| `tests/parse_once.rs` | spec 0.25, ruling 1: every conversion vector, failing ones included, gives the same output or error on one instance in line order, in reverse order and on four threads at once; the benchmark set and one failing vector of each wire give the same on a new instance; a second load is still a duplicate (the debug build runs the reverse order and the threads on every eighth vector and every failing one, and the new instance for the failing vectors only) | 3 tests |
| `tests/seconds.rs` | spec 0.26, ruling 1: the transform `iso8601_s` loads on the xml, geojson, json and text wires; it is `bad-directive` on another wire and with a parameter; it gives an integer, so on a key of another type it is `key-type-mismatch`; writing drops the milliseconds and keeps to the years 0001 to 9999 | 5 tests |
| `tests/inner.rs` | spec 0.34: keys and lists that the outer and the inner message both hold (Decode step 4, rulings 7, 17, 19, 22 and 23) | 8 tests |
| `tests/licences.rs` | spec 0.29: `load_tree` with a licence profile on the fixture trees of the tool vectors: what each profile loads and skips, the widest profile of a pack and its modules, a skipped broken pack, `bad-licence` for a wrong profile name and for a bad licence file before any module loads, no licence file read without a profile, a non-directory on the path read as an absent file; spec 0.93, ruling 6: the instance's limit after a load with a profile, set before or after, a later direct load and a later load with no profile, an instance that already holds a controlled module or pack, the order of the errors, a failed load that keeps the limit; with spec 0.34, a controlled `inner` pack never loads: not shown public or using a controlled module under a profile, or refused by a `public` limit, while the public outer pack loads alone and is `unknown-format` at its `inner` line | 18 tests |
| `tests/reduced.rs` | spec 0.24: a pack on a wire the build lacks is `unknown-wire`; a value that is no wire keeps its message (run in a reduced build by `reduced-build-check.sh`) | 2 tests |
| `python3 -I tools/tool-vectors.py -- engines/rust/target/release/goat-xf` (from the repository root; CI runs it on the debug build) | the command-line contract of spec 0.23 and the licence profiles of spec 0.29: every tool vector under `packs/conformance/tool-vectors/` | 179 tool vectors, 0 failed |

`GOAT_FUZZ_ITERS=<n>` multiplies the fuzz inputs; `GOAT_FUZZ_SEED=<n>`
changes the seed.

## Benchmark

Spec 0.25, ruling 2. From the repository root:

```bash
cargo run --release --manifest-path engines/rust/Cargo.toml --example bench -- bench/set.json
```

`examples/bench.rs` loads only the packs the set's vectors name (`packs/<format>/pack.def`
for each `from` and `to`), the packs their `inner` lines name (spec 0.34), and the model modules they use (`model/<module>.def`,
`core` first, each module after those it uses) into one `Engine`, and times
that. Then, for each vector in order, it converts the input once and checks the
output against `expect`, then converts it `iterations` times and times that.
Standard output holds one line per vector,
`{"vector": "<path as in the set>", "iterations": <n>, "ns_per_op": <integer>}`,
then `{"load": <number of packs>, "ns": <integer>}`, and nothing else; Cargo's
own lines go to standard error. A vector whose output differs, or a file that
cannot be read, is named on standard error and the exit status is 1. The
numbers are one machine at one time: no check fails on them.

The engine keeps, for each loaded pack, what its lines compute (spec 0.25,
ruling 1; `src/layout.rs`): the field-number path of every protobuf locator and
an index of each scope's lines by first field number, the bit span of every
fixed-layout `bits` locator, every `text` locator, every `tlv` locator and
the tag tree of each kind, and the entity-independent line order of each
`xml` scope. A `layout sequential` pack is resolved at load already. A conversion
reads it and never writes it, so one `Engine` converts on several threads at
once (`tests/parse_once.rs`).

## A message of another pack inside a field

Spec 0.34. An `inner <format> [partial]` line of a `layout sequential` `bits` pack hands
the bytes to the end of its extent to another loaded pack, which decodes them
into the same entity and encodes them back from it. The inner pack is looked
up when decode or encode reaches the line (`src/seq.rs`, the `InnerHost`
the `Engine` implements), never at load, so packs load in any order; a codec
called without an engine (`bits::decode`) finds no inner format. The kind the
inner pack selected is `Entity.inner_kind`. `model_keys` and `capability` of
an outer pack add the inner pack's keys at the line's place when the inner
pack passes the checks. `tests/vectors.rs` loads every pack, so the packs
`inner` lines name are loaded too; `examples/bench.rs` loads them with the
packs the set names.

## Builds with fewer wires

Spec 0.24 (`spec/engine-spec.md`, Version 0.24) lets the engine be built with
the codecs of only some wires. Each wire is a Cargo feature of the same name:
`xml`, `geojson`, `json`, `bits`, `protobuf`, `text`, `tlv`, `cbor` (0.28). The default
features are all eight, so a build that names no set has every wire. To name
a set, turn the defaults off and list the wires:

```
cargo build --release --no-default-features --features xml,json,geojson
```

```toml
[dependencies]
goat-transformers = { git = "https://github.com/USAREUR-AF/goat-transformers", tag = "v0.8.0", default-features = false, features = ["xml", "json", "geojson"] }
```

A wire left out of the set is left out of the build: its decoder, its
encoder, and every helper only they use are compiled out with `#[cfg]`.
`bits` holds the sequential layout, six-bit armor and `encoding uper`;
`geojson` builds without `json`. The pack reader stays whole, so a pack on a
wire the build has loads, converts and fails exactly as in the full build.
A pack whose `wire` is one the build lacks fails at line check 6 with
``unknown-wire: line <n>: this build does not have the `<wire>` wire``; a
`wire` value that is no wire at all is still `` `<value>` is not a wire``.
`goat_transformers::build_wires()` returns the wires of the build, and
`Wire::in_build()` says whether one wire is in it.

### The reduced-build check

From the repository root:

```
engines/rust/reduced-build-check.sh
```

It builds the engine with `xml`, `json` and `geojson` (into
`target/reduced`, so the full build is untouched) and runs on it
`tests/vectors.rs`, which loads every pack on those wires and runs every
conversion, load and capability vector whose packs are on them, and
`tests/reduced.rs`, which loads one pack of the repository on each of
`bits`, `protobuf`, `text`, `tlv` and `cbor` and requires `unknown-wire` with the
wire named in the message. It then builds `goat-xf` both ways and prints the
sizes. It exits non-zero on any failure. `GOAT_WIRES=<w>,<w>...` checks
another set. Measured on 2026-11-24 with rustc 1.99.1 on x86_64 Linux:

| Reduced build (`xml,json,geojson`) | Measured |
|---|---|
| conversion vectors | 8399 run, 0 failed (16212 on other wires left out) |
| load vectors | 396 run, 0 failed (1075 left out) |
| capability vectors | 16 run, 0 failed (11 left out) |
| `unknown-wire` loads | 5 of 5: `adsb` (bits), `apollo-ch` (protobuf), `argo-index-meta` (text), `conformance-cond-tlv` (tlv), `conformance-cbor` (cbor) |

| Release artifact | All eight wires | `xml,json,geojson` |
|---|---|---|
| `goat-xf` | 2468008 bytes | 1809944 bytes |
| `libgoat_transformers.rlib` | 5908080 bytes | 4517634 bytes |

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
