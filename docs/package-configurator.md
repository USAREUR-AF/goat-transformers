# Package configurator

Status: Written. The planner (`tools/goat-pkg`) is Built and runs against the
packs in this repository. Given a caller's constraints, it returns the smallest
package that meets them. It uses three things the project has: packs that load
independently, the capability matrix, and portable engines.

## What it does

A caller brings constraints: the message standards they need to speak, the
language, the runtime, the OS and chip architecture, and static vs dynamic
linkage. The planner returns the smallest package: which engine, which packs
(only the formats asked for), which wire codecs those packs use, the build target
and command, and whether the requested formats actually inter-convert.

```
tools/goat-pkg plan --formats cot-xml,sapient --language rust \
    --runtime native --linkage static --os linux --arch x86_64
```

prints the engine (`engines/rust`), the packs (`cot-xml`, `sapient` only), the
wires used (`protobuf`, `xml` — a minimal build can exclude the rest), the build
command (`cargo build --release --target x86_64-unknown-linux-musl`), and the
convertibility among the requested formats with the reason for anything dropped.

## Writing the packs of a package

`plan` names the packs; `bundle` writes them. It copies the `pack.def` of each
named format and the model modules those packs use (and the modules those
modules use) to a directory, with `LICENSE`, `NOTICE` and a `manifest.json`
that records the library version, the commit, and the SHA-256 of each file.

```
tools/goat-pkg bundle --formats cot-xml,sapient --out vendor/goat
tools/goat-pkg bundle --formats cot-xml,sapient --out vendor/goat --embed rust
```

Every engine loads that directory with one call that takes the directory and
the pack names. `--embed rust|go|python` adds a source file that compiles the
packs into the program. `tools/goat-pkg archive --out <file>.tar.gz
[--vectors]` writes every module and pack as one archive, the same bytes for
the same tree. [using.md](using.md) shows each from the consuming side.

## Why it is computable here

- **Atomic packs.** A format is a directory of data files, loaded on its own. A
  package includes only the formats asked for, nothing else.
- **Capability matrix.** Translatability between any two formats is derived from
  their field maps (`Engine::capability`, `goat-xf matrix`), so the planner states
  up front what carries A→B and what the target cannot represent.
- **Portable engines.** Seven engines, standard-library-only, so the same packs
  run under many runtimes and on any OS and architecture.

## Constraint model

| Constraint | Values | Notes |
|---|---|---|
| `formats` | any loaded pack names | the package carries exactly these |
| `language` | rust, go, python, java, cpp, erlang, zig | picks the engine |
| `runtime` | native, wasm, js, jvm | picks the build target |
| `linkage` | static, dynamic | static = one self-contained binary (scratch container, Firecracker microVM); dynamic = smaller, shared libraries |
| `os`, `arch` | e.g. linux/x86_64, linux/aarch64 | cross-compiled; the JVM and WASM abstract these |

## Runtime and linkage matrix

| Engine | native static | native dynamic | WASM | JVM |
|---|---|---|---|---|
| Rust | `…-linux-musl` (fully static) | `…-linux-gnu` | `wasm32-unknown-unknown` (built) | — |
| Go | `CGO_ENABLED=0` (fully static, built) | default | `GOOS=wasip1` | — |
| Java | — | — | — | portable jar (any OS/arch) |
| C++ | `-static` | shared | Emscripten | — |
| Zig | `-Dtarget=…-musl` | `…-gnu` | `wasm32-wasi` | — |
| Python / Erlang | ship with the runtime (CPython / BEAM) | | | |

A fully static binary needs no libc in the image, so it runs in a `scratch`
container or a Firecracker microVM rootfs. A WASM build runs in a browser, in
Node, or in any WASM runtime at the edge. The JVM build runs on any architecture
with a JVM.

## Planning with an overlay

This repository holds the engines and the packs written from public sources. A
private overlay assembles this repository, pinned by `core.ref`, with its own
packs into one tree (`docs/boundary.md`; the worked example is
`goat-transformers-overlay-example`).

The planner reads the `packs/` directory of the tree it runs in. Run in this
repository, it plans packages of public formats only. Run in an assembled
overlay tree, it plans packages that include that overlay's formats.

## Not yet built

- Wire-codec feature-gating in each engine, so a package that uses only `xml`
  formats compiles without the `bits`/`protobuf` codecs (the "wires used" line
  already reports what a minimal build would keep).
- An HTTP front end over the planner; today it is the `tools/goat-pkg` CLI.
