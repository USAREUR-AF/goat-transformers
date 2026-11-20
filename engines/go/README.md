# The Go engine

This directory is one of the seven independent engines of goat-transformers.
It was written from `spec/` and the conformance vectors only, without reading
another engine, and it uses only the Go standard library. It loads the model
modules and the packs, decodes, encodes, converts with context, completes
derived keys and reports named errors as `spec/engine-spec.md` states them.
`go.mod` states `go 1.26`; the module path is
`github.com/USAREUR-AF/goat-transformers/engines/go` and the package name is
`goatxf`.

## Use as a library

```
go get github.com/USAREUR-AF/goat-transformers/engines/go@v0.8.0
```

The module is in a subdirectory, so its tag in the repository is
`engines/go/v0.8.0`. The program below loads the model modules from `model/`
and only two packs from `packs/` (run it from the root of a checkout or of a
bundle), then converts a CoT event to GeoJSON:

```go
package main

import (
	"fmt"
	"log"

	goatxf "github.com/USAREUR-AF/goat-transformers/engines/go"
)

const cot = `<?xml version="1.0"?><event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>`

func main() {
	// The model modules from model/, and only two packs from packs/.
	engine, err := goatxf.LoadPacksOnly("model", "packs", goatxf.DistPublic,
		[]string{"cot-xml", "geojson"})
	if err != nil {
		log.Fatal(err)
	}
	out, err := engine.Convert("cot-xml", "geojson", []byte(cot))
	if err != nil {
		log.Fatal(err) // the message begins with a named error kind, such as no-kind:
	}
	fmt.Println(string(out))
}
```

Other entry points: `LoadDirs(models, packs, maxDistribution)` loads every
pack; `Engine.ConvertWith(from, to, input, context)` supplies model keys the
message lacks; `Engine.Decode` and `Engine.Encode` work with an `*Entity`;
`Engine.LoadFS(fsys, packs)` loads from an `fs.FS` such as an `embed.FS`, so a
program can carry its packs and read no file; `IsKind(err, kind)` tests a named
error. `goatxf.DistPublic` refuses every module and pack marked `controlled`.
`Engine.SetMaxItems(n)` sets the limit on list items one decode holds
(default 100000; going over it is `malformed-wire`), and
`Engine.Capability(from, to)` gives the capability report of a pair of
formats: its grade and the carried and dropped keys (spec 0.11, rulings 6
and 7).

## Command-line tool

The tool `goat-xf` follows the command-line contract of
`spec/engine-spec.md`, Version 0.23: the same subcommands, options, output
bytes and exit status as the tool of every other engine. Build it from the
repository root, then start it as `engines/go/goat-xf`:

```
cd engines/go && go build -o goat-xf ./cmd/goat-xf
```

| Subcommand | Does |
|---|---|
| `convert --from F --to F [--set KEY=VALUE]...` | reads standard input to its end, converts it, writes the result with nothing added (lower-case hex text for the `bits`, `protobuf` and `tlv` wires) |
| `list-formats` | one line per loaded pack, in byte order of format: format, version, wire, separated by tabs |
| `capability --from F --to F` | the capability report of the pair (spec 0.11, ruling 6) as one line: from, to, grade, carried, dropped |
| `matrix` | the header `from to grade carried dropped`, then that line for every ordered pair of loaded formats |
| `help`, `-h`, `--help` | the usage, on standard output |

| Option | Meaning |
|---|---|
| `--packs DIR` | the directory whose subdirectories are packs (default `packs`) |
| `--models DIR` | the directory of model modules (default the `--packs` text followed by `/../model`) |
| `--packs-only A,B` | load only these subdirectories of `--packs`, in the order given; every module of `--models` still loads |
| `--max-items N` | the limit on list items one decode holds (default 100000) |
| `--max-distribution public\|controlled` | refuse modules and packs above this marking (default `controlled`) |
| `--set KEY=VALUE` | `convert` only, repeatable: the context, its keys checked in the order given |

Arguments come in pairs after the subcommand, an option name then its value;
each option but `--set` at most once. Exit status 0 on success; 1 for a load
or call failure, with standard output empty and the failure's message on
standard error, its first line beginning with the named kind and a colon;
2 for a usage error, which is checked before anything is loaded. The tool has
no option of its own (`--x-...`). From the repository root, with the input of
`packs/cot-xml/vectors/01-track-to-geojson.json` in `in.xml`:

```
$ engines/go/goat-xf convert --from cot-xml --to geojson --packs packs --packs-only cot-xml,geojson < in.xml
{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
$ engines/go/goat-xf list-formats --packs packs --packs-only cot-xml,geojson
cot-xml	0.6.0	xml
geojson	0.1.0	geojson
```

`Engine.ConvertOrdered(from, to, input, []KeyValue)` and
`LoadTool(models, packs, maxDistribution, only)` are the library calls the
tool makes.

## Test

The `go` job of `.github/workflows/conformance.yml` runs, in `engines/go`:

```
go test -v ./...
```

`AGENTS.md` adds `go vet ./...` before it. Measured with Go 1.26 on Linux
x86_64, 36 top-level tests and examples, none failing:

| Test | Covers | Measured |
|---|---|---|
| `TestVectors` | every conversion vector of every pack under `../../packs`: output byte-for-byte, `expect_error`, `context`, `model` values | 3299 run, 3299 passed (96 packs loaded) |
| `TestLoadVectors` | every load vector in `packs/conformance/load-vectors`: loads, or fails with the named error | 314 run, 314 passed |
| `TestMalformedInputNeverPanics` | the input of every conversion vector cut at prefixes and with single bytes changed, with a fixed seed: no panic, every error begins with a named kind | 13180 inputs fed, 0 failed |
| `TestMalformedRulings` | the malformed-input rulings of the specification, such as nesting depth and bytes that are not UTF-8 | pass |
| tool vectors | `python3 -I tools/tool-vectors.py -- engines/go/goat-xf`, from the repository root after the build above: every vector in `packs/conformance/tool-vectors` | 95 run, 95 passed |
| `TestHeapPerListItem` | the heap a decode takes per item of a long list; runs only with `GOAT_XF_HEAP=1` | skipped in CI |
| the other tests and `ExampleLoadPacksOnly`, `ExampleEngine_LoadFS` | the tokenizer, float and time formatting, wire errors, kinds, groups, sequential wires, derive functions, the directory and `fs.FS` loaders | pass |

## Static binaries and WebAssembly

Both are listed as Measured in `docs/roadmap.md`. CI does not run these
builds; the following were run with Go 1.26:

```
CGO_ENABLED=0 go build -trimpath -o goat-xf ./cmd/goat-xf                  # Linux x86_64, statically linked
GOARCH=arm64 CGO_ENABLED=0 go build -trimpath -o goat-xf ./cmd/goat-xf     # Linux aarch64, statically linked
GOOS=wasip1 GOARCH=wasm go build -o goat-xf.wasm ./cmd/goat-xf             # WebAssembly, WASI preview 1
```

`file` reports both Linux binaries as statically linked. The WASI module, run
under Node 22 `node:wasi` with the repository root preopened, gave the same
`list-formats` and `convert` output as above.

## Read next

- `spec/engine-spec.md`: the pack grammar, the wire types, decode, encode,
  errors.
- `docs/using.md`: every engine as a dependency, bundles of chosen packs, and
  packs compiled into a Go program.
