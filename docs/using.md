# Using goat-transformers in your program

Status: Built. Every program on this page was run against this repository at
version 0.8.0, from a new project outside it, and printed the output shown.

You add two things to a program: an **engine** for your language, which is one
dependency line, and the **packs** for the formats you convert, which are data
files you copy into your project with one command. This page shows both for
each language, then how to pass context and how to read what a conversion can
carry.

## Versions

The library version is the version of the specification the engines implement:
library 0.8.0 implements `spec/engine-spec.md` Version 0.8. Every engine, both
bindings and every package on this page carry that one version, and
`tools/release-version.py` fails the build when one differs. Packs and model
modules are versioned separately: each `pack.def` and `model/<module>.def` has
its own `version` line, which changes when that file's mapping changes.

The library is pre-1.0. A minor version (0.8 to 0.9) can change the pack
language and an engine's interface; pin the tag.

## Which engine

Every engine passes every conformance vector, so use the one written in your
program's language. A program in a language with no engine uses the C library
or the WebAssembly module, which are builds of the Rust engine.
[languages.md](languages.md) states where the project puts its own effort.

## The packs you need

An engine has no format compiled in. `tools/goat-pkg bundle` writes the packs
for the formats you name, and the model modules those packs use, to a directory
in your project:

```
git clone --branch v0.8.0 https://github.com/USAREUR-AF/goat-transformers
python3 -I goat-transformers/tools/goat-pkg bundle --formats cot-xml,geojson --out vendor/goat
```

```
bundle: vendor/goat
  packs:   cot-xml, geojson
  modules: core, track
  files:   7 (23990 bytes) and manifest.json
```

The directory holds `model/`, `packs/`, `LICENSE`, `NOTICE` and `manifest.json`.
The manifest records the library version, the commit the files were copied
from, and the SHA-256 of each file. `tools/goat-pkg formats` lists the formats.

Each engine has one call that takes the `packs` directory and a list of pack
names, and loads those packs with the model modules they need. It finds the
modules in the `model` directory beside `packs`, so the same call works on a
full checkout of this repository, where it loads only what the named packs
use. Each command-line tool has the same as `--packs-only <name>[,<name>...]`.

With `--embed rust`, `--embed go` or `--embed python` the bundle also holds a
source file that compiles the packs into your program, so the program reads no
file when it runs. The Rust, Go and Python sections show it.

Every pack with its conformance vectors is also attached to each release as
`packs-<version>.tar.gz` (no vectors) and `packs-<version>-with-vectors.tar.gz`.

## The message used on this page

Each program converts this Cursor on Target event to GeoJSON, held in a
variable named `cot`:

```xml
<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>
```

Each prints this line:

```json
{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
```

## Rust

```toml
[dependencies]
goat-transformers = { git = "https://github.com/USAREUR-AF/goat-transformers", tag = "v0.8.0" }
```

The crate is in `engines/rust`; Cargo finds it in the repository by its package
name. It has no dependencies.

```rust
use goat_transformers::Engine;
use std::path::Path;

fn main() -> Result<(), goat_transformers::Error> {
    let mut engine = Engine::new();
    engine.load_model_dir(Path::new("vendor/goat/model"))?;
    engine.load_pack_dir_only(Path::new("vendor/goat/packs"), &["cot-xml", "geojson"])?;
    println!("{}", engine.convert("cot-xml", "geojson", cot)?);
    Ok(())
}
```

`load_model_dir` loads every module of the directory, which in a bundle is the
modules the packs need. `load_pack_dir_only` loads the named packs.

Packs compiled into the binary: bundle with `--embed rust`, which writes
`vendor/goat/goat_packs.rs`, and use it as a module.

```rust
#[path = "../vendor/goat/goat_packs.rs"]
mod goat_packs;

let engine = goat_packs::engine()?;   // reads no file
```

The file is a list of `engine.load_model(include_str!("model/core.def"))?` and
`engine.load_def(include_str!("packs/cot-xml/pack.def"))?` lines in loading
order; `engines/rust/tests/embed.rs` runs the same pattern by hand.

The command-line tool:

```
cargo install --git https://github.com/USAREUR-AF/goat-transformers --tag v0.8.0 goat-transformers
goat-xf convert --from cot-xml --to geojson --packs vendor/goat/packs --packs-only cot-xml,geojson < event.xml
```

`--packs-only` matters when `--packs` names a directory that holds more packs
than the conversion needs, such as a checkout: the tool then reads two pack
files, not all of them. Each release also carries `goat-xf` built for Linux (x86_64 and aarch64,
statically linked) and macOS (arm64 and x86_64).

## Go

```
go get github.com/USAREUR-AF/goat-transformers/engines/go@v0.8.0
```

The module is in a subdirectory, so its version tag in the repository is
`engines/go/v0.8.0`. `go.mod` states `go 1.26`.

```go
package main

import (
	"fmt"
	"log"

	goatxf "github.com/USAREUR-AF/goat-transformers/engines/go"
)

func main() {
	engine, err := goatxf.LoadPacksOnly("vendor/goat/model", "vendor/goat/packs", goatxf.DistControlled, []string{"cot-xml", "geojson"})
	if err != nil {
		log.Fatal(err)
	}
	geojson, err := engine.Convert("cot-xml", "geojson", []byte(cot))
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(string(geojson))
}
```

Packs compiled into the binary: `Engine.LoadFS` is the same loader for an
`fs.FS`, an `embed.FS` included. Bundling with `--embed go --out goatpacks` writes the package for
you (`--package` names it):

```go
import "example.com/yourmodule/goatpacks"

engine, err := goatpacks.Engine()   // reads no file
```

The generated file holds `//go:embed model packs`, the embedded files and that
function. The command-line tool is `go install
github.com/USAREUR-AF/goat-transformers/engines/go/cmd/goat-xf@v0.8.0`, with
`--packs` and `--packs-only` as above.

## Python

```
pip install "git+https://github.com/USAREUR-AF/goat-transformers@v0.8.0#subdirectory=engines/python"
```

Python 3.9 or later; no dependencies. Each release also carries the wheel and
the sdist.

```python
from goat_transformers import Engine

engine = Engine.from_dir("vendor/goat/packs", packs_only=["cot-xml", "geojson"])
print(engine.convert("cot-xml", "geojson", cot).decode())   # bytes in, bytes out
```

Packs as package data: bundle with `--embed python` into a directory inside
your package, for example `myapp/goatpacks`. The bundle then is a package with
one function, and it finds its files through `importlib.resources`, so it
works from a wheel:

```python
from myapp import goatpacks

engine = goatpacks.engine()
```

List the data files in your `pyproject.toml` so the wheel carries them:

```toml
[tool.setuptools.package-data]
"myapp.goatpacks" = ["model/*.def", "packs/*/pack.def"]
```

The package installs the command-line tool `goat-xf-py`:

```
goat-xf-py convert --from cot-xml --to geojson --packs vendor/goat/packs --packs-only cot-xml,geojson < event.xml
```

## Java

Each release carries `goat-transformers-0.8.0.jar`: the engine classes, Java 17,
no dependencies. `engines/java/build.sh` builds the same file at
`engines/java/build/`. Put it on the class path. With Gradle:

```
implementation files("libs/goat-transformers-0.8.0.jar")
```

With Maven, install the file into your local repository once and depend on the
coordinates you give it (this command is not among the checks this repository
runs):

```
mvn install:install-file -Dfile=goat-transformers-0.8.0.jar -DgroupId=goat.transformers -DartifactId=goat-transformers -Dversion=0.8.0 -Dpackaging=jar
```

```java
import goat.transformers.Engine;
import java.nio.file.Path;
import java.util.List;

public class Convert {
    public static void main(String[] args) {
        Engine engine = Engine.loadOnly(Path.of("vendor/goat/packs"), List.of("cot-xml", "geojson"));
        System.out.println(engine.convert("cot-xml", "geojson", cot));
    }
}
```

```
javac -cp lib/goat-transformers-0.8.0.jar Convert.java
java -cp lib/goat-transformers-0.8.0.jar:. Convert
```

The jar also runs the command-line tool: `java -jar goat-transformers-0.8.0.jar
list-formats --packs vendor/goat/packs --packs-only cot-xml,geojson` prints one
line for each of the two formats.

## C++

The engine is a static library with the CMake target
`goat_transformers::goat_transformers` (C++17, no dependencies). From the
repository, with no install step:

```cmake
include(FetchContent)
FetchContent_Declare(goat_transformers
  GIT_REPOSITORY https://github.com/USAREUR-AF/goat-transformers
  GIT_TAG v0.8.0
  SOURCE_SUBDIR engines/cpp)
FetchContent_MakeAvailable(goat_transformers)
target_link_libraries(convert PRIVATE goat_transformers::goat_transformers)
```

`add_subdirectory(<checkout>/engines/cpp)` gives the same target. Either way
only the library is built; the tests and the command-line tool are built when
`engines/cpp` is the top-level project. Installed
(`cmake -S engines/cpp -B build && cmake --build build && cmake --install build --prefix <prefix>`):

```cmake
find_package(goat_transformers 0.8 CONFIG REQUIRED)
target_link_libraries(convert PRIVATE goat_transformers::goat_transformers)
```

```cpp
#include <goat_transformers/engine.hpp>
#include <iostream>

int main() {
    auto engine = goat_transformers::Engine::load_packs("vendor/goat/packs", {"cot-xml", "geojson"});
    std::cout << engine.convert("cot-xml", "geojson", cot) << "\n";
}
```

Without CMake: `c++ -std=c++17 -I<prefix>/include convert.cpp <prefix>/lib/libgoat_transformers.a`.
The installed `goat-xf` takes `--packs` and `--packs-only` as the Rust tool does.

## Erlang

In `rebar.config`:

```erlang
{deps, [{goat_transformers, {git_subdir, "https://github.com/USAREUR-AF/goat-transformers",
                             {tag, "v0.8.0"}, "engines/erlang"}}]}.
```

The application is `goat_transformers` (OTP standard library only). Without
rebar3, `engines/erlang/build.sh` compiles the modules to `ebin/` with `erlc`.

```erlang
Engine = gt_engine:load_packs(gt_engine:new(), "vendor/goat/packs", ["cot-xml", "geojson"]),
io:format("~s~n", [gt_engine:convert(Engine, <<"cot-xml">>, <<"geojson">>, Cot)]).
```

`Cot` is a binary. The first argument is the engine to load into, so a second
call adds packs; a module the engine already holds is not loaded again.

## Zig

Zig 0.13.

```
zig fetch --save git+https://github.com/USAREUR-AF/goat-transformers#v0.8.0
```

The package manifest is `build.zig.zon` at the repository root, because `zig
fetch` takes a package from the root of what it fetches; the package holds
`engines/zig/src` and nothing else. In your `build.zig`:

```zig
const gt = b.dependency("goat_transformers", .{ .target = target, .optimize = optimize });
exe.root_module.addImport("goat_transformers", gt.module("goat_transformers"));
```

```zig
const std = @import("std");
const gt = @import("goat_transformers");

pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    var engine = gt.Engine.init(arena.allocator());
    _ = try engine.loadPacksOnly("vendor/goat/packs", "vendor/goat/model", &.{ "cot-xml", "geojson" });
    const geojson = try engine.convert("cot-xml", "geojson", cot, null);
    try std.io.getStdOut().writer().print("{s}\n", .{geojson});
}
```

The engine keeps what it loads and frees nothing on its own, so give it an
arena. After a failure `engine.last_error` holds `<kind>: <detail>`.

## JavaScript and TypeScript (WebAssembly)

Each release carries the npm package as a tarball. It is not on the npm
registry.

```
npm install https://github.com/USAREUR-AF/goat-transformers/releases/download/v0.8.0/usareur-af-goat-transformers-0.8.0.tgz
```

The package is `@usareur-af/goat-transformers`: an ES module with TypeScript
types, the WebAssembly module (362 kB, no imports) beside it, and no
dependencies. In Node 18 or later:

```js
import { loadTree } from "@usareur-af/goat-transformers/node";

const gt = await loadTree("vendor/goat", ["cot-xml", "geojson"]);
console.log(gt.convert("cot-xml", "geojson", cot));
```

In a browser there is no directory to read, so the host fetches the texts and
loads them in order: the model modules, then the packs (`loadTree` does this
for a directory in Node). The bundle's
`manifest.json` lists both in loading order, as `modules` (the file of a module
is `model/<module>.def`) and `packs`.

```js
import { GoatTransformers } from "@usareur-af/goat-transformers";

const gt = await GoatTransformers.load(wasmBytes);   // the file "@usareur-af/goat-transformers/goat_transformers.wasm"
gt.loadModel(coreDefText);
gt.loadModel(trackDefText);        // cot-xml uses the module `track`
gt.loadPack(cotXmlPackText);
gt.loadPack(geojsonPackText);
```

To build the tarball yourself: `bindings/wasm/build.sh`, then `npm pack` in
`bindings/wasm`. A message of a binary wire (`bits`, `protobuf`) is hex text on
both sides.

## C

Each release carries the C library for Linux (x86_64 and aarch64) and macOS
(arm64 and x86_64). Under `usr/local/` the archive holds
`include/goat_transformers.h`, the shared and the static library in `lib/`, and
`lib/pkgconfig/goat_transformers.pc`; `tar -xzf <archive> --strip-components=1
-C /` puts them there. `bindings/c/install.sh <prefix>` builds and installs the
same layout under any prefix from a checkout.

```
cc convert.c $(pkg-config --cflags --libs goat_transformers) -o convert
```

The C interface takes texts, not paths: the program reads the bundle's files
and passes them in loading order.

```c
#include <goat_transformers.h>

gt_engine *e = gt_engine_new();
gt_buf out = {0};
gt_load_model(e, core_def, core_def_len, &out);      /* vendor/goat/model/core.def */
gt_load_model(e, track_def, track_def_len, &out);    /* vendor/goat/model/track.def: cot-xml uses track */
gt_load_pack(e, cot_def, cot_def_len, &out);         /* vendor/goat/packs/cot-xml/pack.def */
gt_load_pack(e, geo_def, geo_def_len, &out);         /* vendor/goat/packs/geojson/pack.def */
int32_t rc = gt_convert(e, (const uint8_t *)"cot-xml", 7, (const uint8_t *)"geojson", 7,
                        (const uint8_t *)cot, strlen(cot), NULL, 0, &out);
puts((const char *)out.data);                        /* the result, or the error text when rc != GT_OK */
gt_buf_free(&out);
gt_engine_free(e);
```

[bindings/README.md](../bindings/README.md) states the rules of the interface.

## Passing context

A target format can need a value the source message does not carry. A GeoJSON
Feature has no stale time, and a CoT event needs one. The caller supplies such
values as context: model keys and their values, given as text and read as each
key's declared type. A key the source message does carry keeps the message's
value.

Converting the GeoJSON line above back to CoT with `stale_ms` supplied:

| Language | Call |
|---|---|
| Rust | `engine.convert_text("geojson", "cot-xml", geojson, Some(&[("stale_ms".to_string(), "1614456180000".to_string())]))` |
| Go | `engine.ConvertWith("geojson", "cot-xml", geojson, map[string]string{"stale_ms": "1614456180000"})` |
| Python | `engine.convert("geojson", "cot-xml", geojson, {"stale_ms": "1614456180000"})` |
| Java | `engine.convert("geojson", "cot-xml", geojson, Map.of("stale_ms", "1614456180000"))` |
| C++ | `engine.convert_text("geojson", "cot-xml", geojson, {{"stale_ms", "1614456180000"}})` |
| Zig | `engine.convert("geojson", "cot-xml", geojson, &[_]gt.KV{.{ .key = "stale_ms", .value = "1614456180000" }})` |
| JavaScript | `gt.convert("geojson", "cot-xml", geojson, { stale_ms: 1614456180000 })` |
| C | the `context` argument of `gt_convert`: `"stale_ms=1614456180000\n"` |
| Command line | `--set stale_ms=1614456180000`, repeatable |

Each prints:

```xml
<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" start="2021-02-27T20:00:00.000Z" stale="2021-02-27T20:03:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>
```

A context key that no loaded module declares is the error `undeclared-key`; a
value that cannot be read as the key's type is `key-type-mismatch`.
`spec/engine-spec.md`, Version 0.6, states the rules.

## Reading the capability report

Before you rely on a conversion, the capability report says which model keys
carry from one format to another and which the target has no field for. It is
computed from the packs, not from a message.

```
goat-xf matrix --detail --packs vendor/goat/packs --packs-only cot-xml,geojson
```

```
from\to cot-xm geojso
cot-xml      -      P
geojson      F      -

F = all mapped fields carry   P = some carry, some dropped   . = no shared fields   - = same format

Per-pair detail (carried | dropped and why):
         cot-xml -> geojson        PARTIAL  carries: [uid, type, time_ms, how, lat, lon, hae, ce, le, callsign, course, speed_ms]  dropped: track.scoped_id, stale_ms (target `geojson` has no field for them)
         geojson -> cot-xml        FULL     carries: [uid, type, time_ms, how, lat, lon, hae, ce, le, callsign, course, speed_ms]
```

| Grade | Means |
|---|---|
| `FULL` | every key the source maps has a field in the target |
| `PARTIAL` | some keys carry; the dropped keys are listed, and the target has no field for them |
| `NONE` | the two formats share no key |

`geojson -> cot-xml` is `FULL` and still needed `stale_ms` as context above:
the report lists what the source can give the target, not what the target
requires. A key the target requires and the source lacks comes from context or
from a `derive` line of a model module.

In a Rust program the same report is `engine.capability("cot-xml", "geojson")`,
a `Capability` with `grade`, `carried` and `dropped`, and
`engine.capability_matrix()` for every pair. `tools/goat-pkg plan --formats
cot-xml,geojson` prints it for the formats of a planned package without
building anything ([package-configurator.md](package-configurator.md)). In the
other engines, `model_keys(format)` (`ModelKeys` in Go, `modelKeys` in Java)
lists the keys a format maps, from which the same comparison follows.

## What a release holds

A tag `v<version>` runs `.github/workflows/release.yml`, which attaches these
files to the GitHub Release with a `SHA256SUMS` file and a build provenance
attestation (`gh attestation verify <file> --repo USAREUR-AF/goat-transformers`).
Nothing is published to crates.io, PyPI, the npm registry or Maven Central.

| File | Holds |
|---|---|
| `goat-xf-<version>-<target>.tar.gz` | the command-line tool: `x86_64-unknown-linux-musl`, `aarch64-unknown-linux-musl`, `aarch64-apple-darwin`, `x86_64-apple-darwin` |
| `goat-transformers-c-<version>-<target>.tar.gz` | the C library, header and pkg-config file: `x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu`, `aarch64-apple-darwin`, `x86_64-apple-darwin` |
| `goat_transformers-<version>.wasm`, `goat_transformers-<version>-small.wasm` | the WebAssembly module, built for speed and for size |
| `usareur-af-goat-transformers-<version>.tgz` | the npm package |
| `goat_transformers-<version>-py3-none-any.whl`, `goat_transformers-<version>.tar.gz` | the Python wheel and sdist |
| `goat-transformers-<version>.jar` | the Java engine |
| `packs-<version>.tar.gz`, `packs-<version>-with-vectors.tar.gz` | every model module and pack, without and with the conformance vectors |
