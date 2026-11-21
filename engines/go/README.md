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

`LoadToolProfile(models, packs, maxDistribution, only, profile)` loads as the
command-line tool does, keeping only the modules and packs of one licence
profile (spec 0.29): `"open"`, `"open+copyleft"` or `"everything"`. It first
reads `licences.toml` (the `packs` text followed by `/../licences.toml`), and
each module's `<file>.def.license`, and each pack's `REUSE.toml` when the pack
is reached; a pack the profile does not hold is skipped without being read
further. A licence file that cannot be read as the specification says, or a
profile name that is not one of the three, is `bad-licence`
(`goatxf.ErrBadLicence`). With profile `""` it reads no licence file and
loads as `LoadTool` does. `LoadToolLicences` takes the same arguments, always
reads the licence files, and also returns each loaded pack's directory,
format, licence and own profile (`none` when it is in no profile).

## Command-line tool

The tool `goat-xf` follows the command-line contract of
`spec/engine-spec.md`, Version 0.23, with the licence profiles of Version
0.29: the same subcommands, options, output
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
| `licences [--json]` | one line per loaded pack, in byte order of its directory: directory, format, licence, the pack's own profile (`none` when in no profile), separated by tabs; with `--json`, one object `{"packs":[{"pack":…,"format":…,"licence":…,"profile":…},…]}` and a line feed |
| `help`, `-h`, `--help` | the usage, on standard output |

| Option | Meaning |
|---|---|
| `--packs DIR` | the directory whose subdirectories are packs (default `packs`) |
| `--models DIR` | the directory of model modules (default the `--packs` text followed by `/../model`) |
| `--packs-only A,B` | load only these subdirectories of `--packs`, in the order given; every module of `--models` still loads |
| `--max-items N` | the limit on list items one decode holds (default 100000) |
| `--max-distribution public\|controlled` | refuse modules and packs above this marking (default `controlled`) |
| `--profile open\|open+copyleft\|everything` | load only the modules and packs this licence profile holds (default none: no licence file is read, every module and pack loads) |
| `--json` | `licences` only, and the one option that takes no value |
| `--set KEY=VALUE` | `convert` only, repeatable: the context, its keys checked in the order given |

Arguments come in pairs after the subcommand, an option name then its value
(`--json` alone takes none); each option but `--set` at most once. Exit status 0 on success; 1 for a load
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

`Engine.ConvertOrdered(from, to, input, []KeyValue)`,
`LoadToolProfile(models, packs, maxDistribution, only, profile)` and
`LoadToolLicences` (for `licences`) are the library calls the tool makes.

## Test

The `go` job of `.github/workflows/conformance.yml` runs, in `engines/go`:

```
go test -v ./...
```

`AGENTS.md` adds `go vet ./...` before it. Measured with Go 1.26 on Linux
x86_64, 36 top-level tests and examples, none failing:

| Test | Covers | Measured |
|---|---|---|
| `TestVectors` | every conversion vector of every pack under `../../packs`: output byte-for-byte, `expect_error`, `context`, `model` values | 22962 run, 22962 passed (4433 packs loaded; 2026-11-21) |
| `TestLoadVectors` | every load vector in `packs/conformance/load-vectors`: loads, or fails with the named error | 1249 run, 1249 passed |
| `TestMalformedInputNeverPanics` | the input of every conversion vector cut at prefixes and with single bytes changed, with a fixed seed: no panic, every error begins with a named kind | 97137 inputs fed, 0 failed |
| `TestParseOnceConcurrent` | spec 0.25, rulings 1b and 1c: every conversion vector on one instance, then on a second from four goroutines at once; bytes, decoded entity and errors compared | 22932 vectors (1323 failing conversions), 0 outcomes differ |
| `TestMalformedRulings` | the malformed-input rulings of the specification, such as nesting depth and bytes that are not UTF-8 | pass |
| tool vectors | `python3 -I tools/tool-vectors.py -- engines/go/goat-xf`, from the repository root after the build above: every vector in `packs/conformance/tool-vectors` | 135 run, 135 passed (2026-11-21) |
| `TestLoadToolProfile`, `TestLoadToolLicences`, `TestLicenceFiles`, `TestLicenceTable`, `TestProfileHeader`, `TestDefFilesRegularOnly` | spec 0.29: the library loader with each profile and none, the fixture trees of `packs/conformance/tool-fixtures/licences-*`, the line forms of `REUSE.toml`, `.def.license` and `licences.toml`, the `module` and `uses` lines the profiles read, and the module files of 0.23 Loading 1 (regular files or links to one) | pass |
| `TestHeapPerListItem` | the heap a decode takes per item of a long list; runs only with `GOAT_XF_HEAP=1` | skipped in CI |
| the other tests and `ExampleLoadPacksOnly`, `ExampleEngine_LoadFS` | the tokenizer, float and time formatting, wire errors, kinds, groups, sequential wires, derive functions, the directory and `fs.FS` loaders | pass |

## Parse once, and the benchmark

An `Engine` keeps, for its life, what it parsed and computed at load
(`spec/engine-spec.md`, Version 0.25, ruling 1): each pack and module as a
parsed structure, each layout with its lines and locators already read, the
value tables of `via` indexed in both directions, the canonical values of
`requires` and `case`, the gate value an open `if` block encodes, and the
list of `derive` lines in application order. A conversion only reads them; it
parses no pack or module text and writes nothing an instance keeps, so one
`Engine` may be used by several goroutines at once once loading is done.
Loading and the setters (`LoadModel`, `AddModule`, `LoadPack`, `AddPack`,
`LoadFS`, `SetMaxItems`, `SetMaxDistribution`) must not run while another
goroutine uses the instance. Loading reads each module file and each
`pack.def` once.

The benchmark (ruling 2) is the command `goat-bench`. From the repository
root:

```
go -C engines/go run ./cmd/goat-bench ../../bench/set.json
```

or build it once and run it from the root:

```
cd engines/go && go build -o goat-bench ./cmd/goat-bench && cd ../..
engines/go/goat-bench bench/set.json
```

The argument is the benchmark set (default `bench/set.json`); the paths of
its vectors are relative to the directory above the set's directory, whose
`packs` and `model` directories are read. It loads only the packs that the
vectors name in `from` and `to`, and the modules they use, then converts each
vector's input once, checks it against `expect`, and converts it `iterations`
times. Standard output gets one JSON line per vector and then one for the
load (ruling 2c), written when every vector has passed; a failure writes
nothing on standard output, its message on standard error, and exits 1.

`TestParseOnceConcurrent` checks rulings 1b and 1c: it runs every conversion
vector on one instance, then on a second instance from four goroutines at
once, each starting elsewhere in the list, and compares the bytes, the
decoded entity and every error message. `go test -race -short -run
TestParseOnceConcurrent` runs it on every sixteenth vector under the race
detector.

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

## Builds with fewer wires

The engine can be built with the codecs of only some wires
(`spec/engine-spec.md`, Version 0.24). The switch is a Go build tag. A build
with no tag has all eight wires. A build with the tag `goat_wires` has only
the wires named by a tag `goat_wire_<wire>`, from `goat_wire_xml`,
`goat_wire_geojson`, `goat_wire_json`, `goat_wire_bits`,
`goat_wire_protobuf`, `goat_wire_text`, `goat_wire_tlv` and `goat_wire_cbor`
(0.28 ruling 38):

```
go build -tags goat_wires,goat_wire_xml,goat_wire_json,goat_wire_geojson -o goat-xf ./cmd/goat-xf
```

A program that uses the module as a library passes the same `-tags` to its
own `go build`. The codec of each wire is in files whose build constraint is
`!goat_wires || goat_wire_<wire>`, and `wire_<wire>.go` registers it. The
reader and writer of `json` and `geojson` that both wires use are in the files
`*_jsonfamily.go`, in a build that has either one, so `geojson` needs nothing
of `json`. The sequential layout, six-bit armor and `encoding uper` are part
of `bits`. The pack language, with all its line checks, is in every build
(the files `*_shared.go` hold the parts of a wire's files that the loader
uses), so a pack on a wire of the build loads, and fails, as in a full build.
A pack whose `wire` is a wire the build lacks is `unknown-wire` at its `wire`
line, and the message says so:

```
unknown-wire: wire "bits" is a wire of the specification, but this build does not have it (built with the wires geojson, json, xml) [format=adsb at=packs/adsb/pack.def:18]
```

`goatxf.BuiltWires()` returns the wires of the build.

### The reduced-build check

From the repository root:

```
sh engines/go/reduced-check.sh
```

It builds the engine with `xml`, `json` and `geojson` only and runs
`TestReducedBuild` in that build (`reduced_test.go`, built only with the tag
`goat_wires`): it loads every pack on those three wires, runs every
conversion vector whose `from` and `to` are among them, and checks that every
pack on `bits`, `protobuf`, `text`, `tlv` and `cbor` is `unknown-wire` at its `wire`
line with the wire named. Then it builds `goat-xf` with all eight wires and
with the three, loads one pack of each missing wire with the reduced tool
(each must exit 1 with `unknown-wire` naming the wire), checks with
`go tool nm` that the reduced tool holds no decoder or encoder of those five
wires, and prints both sizes. It exits non-zero on any failure.

Measured with Go 1.26.8 on Linux x86_64:

| | Measured |
|---|---|
| packs loaded in the reduced build | 1646 |
| conversion vectors on `xml`, `json` and `geojson` | 8208 run, 8208 passed |
| packs refused with `unknown-wire` | `bits` 1705, `protobuf` 876, `text` 77, `tlv` 9, `cbor` 7 |
| `goat-xf`, all eight wires | 5227776 bytes |
| `goat-xf`, `xml`, `json` and `geojson` | 4689345 bytes (538431 bytes less) |

## Read next

- `spec/engine-spec.md`: the pack grammar, the wire types, decode, encode,
  errors.
- `docs/using.md`: every engine as a dependency, bundles of chosen packs, and
  packs compiled into a Go program.
