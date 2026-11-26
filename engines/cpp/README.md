# goat-transformers: C++ engine

A C++17 implementation of the engine specification (`spec/engine-spec.md`),
written from the specification and the conformance vectors. It builds a static
library (`goat_transformers`), the command-line tool `goat-xf`, the benchmark
`goat-bench` and four test programs.

## Requirements

| Tool | Minimum |
|---|---|
| CMake | 3.16 |
| Compiler | C++17, with a standard library that has `std::filesystem` and floating-point `std::to_chars` and `std::from_chars`. Built and tested with Apple Clang 21 |

The library has no dependency outside the C++ standard library.

## Build

Build out of tree, in a directory inside `engines/cpp`:

```sh
cd engines/cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

The tests read the packs of this repository (`packs/`, and the model modules
in `model/` beside it). `-DGT_PACKS_DIR=<dir>` names another packs directory.

## Use the library from another project

The target is `goat_transformers::goat_transformers` in each case.

| Way | How |
|---|---|
| A source directory | `add_subdirectory(<path to engines/cpp>)` |
| `FetchContent` | `FetchContent_Declare(... SOURCE_SUBDIR engines/cpp)` |
| An installed package | `cmake --install build --prefix <prefix>`, then `find_package(goat_transformers 0.8 CONFIG REQUIRED)` with `<prefix>` in `CMAKE_PREFIX_PATH` |

```cmake
target_link_libraries(my_program PRIVATE goat_transformers::goat_transformers)
```

The install holds the static library, the headers under `include/`, the
package files under `lib/cmake/goat_transformers` and `goat-xf`. A package
of one minor version is accepted by a request for that minor version only.

| Option | Default | Effect |
|---|---|---|
| `GT_BUILD_TESTS` | `ON` as the top-level project, `OFF` inside another project | the three test programs and the ctest entries |
| `GT_BUILD_CLI` | the same | the `goat-xf` tool |
| `GT_INSTALL` | the same | the install and package rules |
| `GT_SANITIZE` | `OFF` | the sanitizer build, below |
| `GT_WIRES` | empty: all eight wires | the wires of the build, below |

## Wires of a build

`-DGT_WIRES=<wire>[,<wire>...]` builds the engine with the codecs of only the
wires named (`spec/engine-spec.md`, Version 0.24), from `xml`, `geojson`,
`json`, `bits`, `protobuf`, `text`, `tlv` and `cbor` (0.28 ruling 38); `;`
separates them as well as `,`. A build that does not set it, or sets it
empty, has all eight. A name
that is not a wire stops the configuration.

```sh
cmake -S . -B build-xml -DCMAKE_BUILD_TYPE=Release -DGT_WIRES=xml,json,geojson
cmake --build build-xml -j
```

The set becomes the compile definitions `GT_WIRE_XML` to `GT_WIRE_CBOR`, each
`1` or `0`, on the library alone (`src/wires.hpp`; a compiler run without them
has every wire). The codec of a wire that is `0` is not compiled: its source
file is left out (`xml.cpp`; `protobuf.cpp`; `text.cpp`; `tlv.cpp`; `cbor.cpp`; the JSON
reader `json.cpp` and `jsonwire.cpp` when neither `json` nor `geojson` is in
the set) or its part of a shared file is (`codecs.cpp`: the xml, geojson and
bits codecs; `jsonwire.cpp`: the json codec; `sequential.cpp`: the decoder
and encoder of the sequential layout). The sequential layout, six-bit armor
and `encoding uper` belong to `bits`; `geojson` uses the items of a JSON array
from `jsonwire.cpp` and nothing of the json codec. The pack reader is the
same in every build, so a pack on a wire of the set loads, converts and fails
exactly as with all eight.

A pack whose `wire` is a wire the build lacks is refused at its `wire` line
(line check 6 of 0.11) with `unknown-wire`, and the message names the wire
and says the build does not have it:

```
unknown-wire: format=adsb packs/adsb/pack.def:18: wire 'bits' is a wire of the specification that this build does not have
```

A `wire` value that is no wire at all stays `unknown-wire: ... wire 'foo'`.
`goat_transformers::built_wires()` returns the wires of the build, and
`wire_built(Wire)` tells whether it has one.

In a build with fewer than eight wires, ctest has only `vectors`, and
`goat_transformers_vectors` is the reduced-build check below; the other
tests load every pack of the repository and need all eight.

### Reduced-build check

From the repository's root:

```sh
sh engines/cpp/tests/reduced-build.sh
```

It builds the engine with `xml`, `json` and `geojson` in
`engines/cpp/build-wires-reduced` and runs `goat_transformers_vectors`
there: it loads every model module and the packs on those wires; runs every
conversion, load and capability vector whose formats, and whose pack texts,
are all on them (a vector whose format is no pack directory, which pins
`unknown-format`, runs too); and loads every pack on `bits`, `protobuf`,
`text`, `tlv` and `cbor`, each of which must be `unknown-wire` with the wire named and
the build's lack said, at least one per wire. Then it builds the library and
`goat-xf` with all eight wires in `engines/cpp/build-wires-full` and prints
the sizes of both. It exits non-zero on any failure. `GT_JOBS` sets the
parallel jobs (4).

Measured on 2026-11-24 on Linux x86-64 with GCC 15.2, Release, not stripped:

| File | All eight wires | `xml`, `json`, `geojson` |
|---|---|---|
| `libgoat_transformers.a` | 3,420,664 bytes | 2,415,622 bytes (71%) |
| `goat-xf` | 1,915,376 bytes | 1,364,408 bytes (71%) |

On 2026-11-26 it ran 8519 conversion vectors (8518 passed; the one failure is
`conformance-held-src/40-reqlist-requires-met-by-an-empty-list`, below, so
the check exits 1 before its size step), 402
of 402 load vectors and 16 of 16 capability vectors, and refused 3298 packs
with `unknown-wire` (bits 2317, protobuf 876, text 87, tlv 11, cbor 7). The
sizes are those of 2026-11-24. What stays in the reduced build is the pack reader and the transforms
every wire shares.

### Single-wire check

```sh
sh engines/cpp/tests/single-wire.sh
```

It builds the library and `goat-xf` with each wire alone, and with every wire
but it, and fails on a warning the build with all eight wires does not have.
With the wire alone it also runs `goat_transformers_vectors`, and fails when no
conversion vector between two formats of the wire ran. `GOAT_WIRES="cbor tlv"`
checks fewer wires; `GT_JOBS` sets the parallel jobs (4).

## Test

```sh
cd build && ctest --output-on-failure
```

| ctest name | Program | What it checks |
|---|---|---|
| `vectors` | `goat_transformers_vectors` | every conversion vector under `packs/*/vectors` (each with its `max_items`; a `model` value its grammar refuses makes the vector invalid), every load vector under `packs/conformance/load-vectors` (with `pack` or `packs`) and every capability vector under `packs/conformance/capability-vectors` (`spec/vector-format.md`) |
| `unit` | `goat_transformers_unit` | number formatting, dates, pack grammar errors, residue, and the malformed-input rulings no vector reaches |
| `malformed_input` | `goat_transformers_fuzz` | the malformed-input test, below |
| `parse_once` | `goat_transformers_parse_once` | what an instance keeps (0.25 ruling 1), below: every vector gives the same output, error and decoded entity on a new instance (the benchmark set's vectors), in reverse order after failing conversions, and from eight threads at once |
| `cli_list_formats`, `cli_packs_only` | `goat-xf` | the command-line tool loads the packs |
| `tool_vectors` | `goat-xf`, through `tools/tool-vectors.py` | the tool vectors under `packs/conformance/tool-vectors` (the command-line contract, 0.23, and the licence profiles of 0.29 and 0.93): 183/183 pass (2026-11-26). The entry exists when CMake finds a Python 3 interpreter |

Each program prints its counts on the last line and exits non-zero on any
failure. A program can be run by itself: `./build/goat_transformers_vectors`.

Measured on 2026-11-26 (Release, all eight wires, through Version 0.94, on
top of 0.92's runs): `vectors` ran 25823 of 25823 conversion vectors, 1753 of
1753 load vectors and 29 of 29 capability vectors, none failed; `unit` made
2339 checks, none failed; `malformed_input` made 9705345 convert calls over
25823 vector inputs, 0 failed; `parse_once` ran 25733 vectors, 0 failures;
`tool_vectors` passed 183 of 183.

## What an instance keeps

An `Engine` keeps, for its life, every pack and module it loaded in parsed
form (engine-spec.md 0.25, ruling 1a). When it adds a pack it also computes,
once, the layouts conversions read (`detail::PackPlan`, `src/codecs.hpp`,
held by `Pack::plan`):

- the lines of the message and of each kind, and of every group body, in line
  order;
- every locator parsed by the grammar of its wire: xml paths, geojson members,
  bits ranges, protobuf field numbers, json member paths (the text and tlv
  wires already keep theirs in the lines);
- the kinds by name, the gate blocks of each kind (bits), the placement of the
  `element` lines of each kind (xml), the locators each kind maps (xml and
  json residue), and every `case` by id (`layout sequential`).

None of it is written after the pack is added. The one thing computed later
is the set of keys of each kind that a conversion checks (Version 0.94,
below): it is computed the first time a conversion chooses that kind, kept
behind a mutex, and computed again after the engine adds a pack. A conversion
keeps its own state on its stack (the list-item count of 0.11 ruling 7 is per thread), so a
`const Engine` may be used from several threads at once (ruling 1c). The
setters (`set_max_items`, `set_max_distribution`) and the loading functions
change the instance and are not to be called while another thread converts.
Packs are shared by copies of an `Engine`. Loading reads each file once (1d).

## A message of another pack inside a field

An `inner <format> [partial]` line of a `layout sequential` pack (`spec/engine-spec.md`,
Version 0.34) hands the bytes from the cursor to the end of its extent to the
pack of that format. Bytes at or after the inner message's end (rulings 13 and
14) are `malformed-wire`, unless the line says `partial`; a message decoded on
its own still accepts them. The inner pack is looked up when decode or encode reaches
the line (`detail::InnerHost`, `src/sequential.hpp`, served by the `Engine`),
not when the outer pack loads, so packs load in any order. The kind the inner
pack selected is `Entity::inner_kind`, a `(format, kind name)` pair beside
`Entity::kind`; both are empty when nothing was selected. `Pack::inner_formats`
lists the formats of a pack's `inner` lines.

## A conversion into a kind holds one of its keys

In `convert` and `convert_run` with `from` different from `to`
(`spec/engine-spec.md`, Version 0.94), after the context and the derivations
and once the target kind is chosen, `Engine::check_held` (`src/engine.cpp`)
raises `no-kind` when the target pack has message kinds and the entity holds
no key of the chosen kind: the keys of the common lines and the kind's lines
(every `field`, `also` and `when … as` line, in any block or case, and a
group by its `<list>[]` entry), the `model_keys` of the pack of each `inner`
line among them that passes 0.34's checks, and the kind's own `requires`
keys. A key counts when the entity has a value for it, a list when it has an
item. A pack without message kinds, a same-format conversion, `encode` and a
kind kept by `Entity.kind` or `Entity.inner_kind` are not checked. From a
carrier to a carrier pack the kind of 0.92 ruling 6 is checked once, on the
outer entity joined with the first message.

`requires <list>` holds only for a list with at least one item (0.7, which
0.94 ruling 1 keeps), so a kind with such a `requires` always passes. A
carrier-to-carrier kind without a `run` line makes 0.92's message count
first, then checks the joined entity (0.94 ruling 7). The inner packs'
`model_keys` count only after 0.34's checks 1 to 4, not the `framing self`
check of 0.92 ruling 16.

## Benchmark

`goat-bench` runs the benchmark set `bench/set.json` (engine-spec.md 0.25,
ruling 2). From the repository root:

```sh
cmake -S engines/cpp -B engines/cpp/build-release -DCMAKE_BUILD_TYPE=Release
cmake --build engines/cpp/build-release --target goat-bench -j
engines/cpp/build-release/goat-bench bench/set.json
```

It loads into one instance the packs the set's vectors name (each vector's
`from` and `to`, a format's pack being the directory of that name in
`packs`, and the packs their `inner` lines name, transitively, a name with no
directory there skipped: Version 0.34) with the modules they use (`Engine::load_packs`), and times the
load. For each vector in order it converts the input once and compares the
output with `expect`, then converts it `iterations` times and times that.
Standard output holds one line per vector,
`{"vector": "<path>", "iterations": <n>, "ns_per_op": <integer>}`, then
`{"load": <packs>, "ns": <integer>}`, and nothing else; the lines are written
when every vector has run. A vector whose output differs, or whose conversion
fails, ends the run with exit status 1, nothing on standard output and the
reason on standard error. `--packs <dir>` and `--models <dir>` name other
directories; the set's paths are read from the current directory. Build it
with `-DCMAKE_BUILD_TYPE=Release` and all eight wires: the set covers every
wire, so a build with fewer fails at the load, and the numbers of a build
without optimisation say little. The numbers are measurements of one machine at one
time, and no check fails on them (ruling 2d).

## Malformed-input test

`goat_transformers_fuzz` takes the input of every conversion vector, cuts it
at prefixes and changes one byte at a time, and gives each result to
`convert`. A call passes when it returns, or when it throws
`goat_transformers::Error` with a message that begins with the name of its
kind and a colon (`malformed-wire: ...`). Any other exception fails the test.
The cases are the same on every run.

For each input it tries up to 96 prefixes and up to 96 byte positions, four
replacement bytes at each position. `GT_FUZZ_POSITIONS=<n>` sets another
number, for a slow build or a loaded machine:

```sh
GT_FUZZ_POSITIONS=24 ./build/goat_transformers_fuzz
```

## Sanitizer build

`-DGT_SANITIZE=ON` builds every target with
`-fsanitize=address,undefined`; a finding stops the program that reached it.
Use a build directory of its own:

```sh
cmake -S . -B build-san -DCMAKE_BUILD_TYPE=RelWithDebInfo -DGT_SANITIZE=ON
cmake --build build-san -j
./build-san/goat_transformers_vectors
./build-san/goat_transformers_unit
./build-san/goat_transformers_fuzz
```

The malformed-input test finds out-of-bounds reads and undefined behavior
only in this build: in a normal build it checks the error that is thrown, and
nothing else.

## Command-line tool

`goat-xf` is the command-line tool of the contract every engine shares
(`spec/engine-spec.md`, Version 0.23): the same arguments, output and exit
status as the tool of any other engine. It is built with the library (Build,
above); from the repository's root:

```sh
nice -n 10 cmake -S engines/cpp -B engines/cpp/build -DCMAKE_BUILD_TYPE=Release
nice -n 10 cmake --build engines/cpp/build -j
engines/cpp/build/goat-xf list-formats --packs packs
```

```
goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>
goat-xf list-formats <options>
goat-xf capability --from <format> --to <format> <options>
goat-xf matrix <options>
goat-xf licences [--json] <options>
goat-xf help
```

| Option | Means | Default |
|---|---|---|
| `--packs <dir>` | the directory whose subdirectories are packs | `packs`, in the current directory |
| `--models <dir>` | the directory of model modules | the `--packs` text followed by `/../model` |
| `--packs-only <name>[,<name>...]` | load only these subdirectories of `--packs`, in the order given | every subdirectory |
| `--max-items <n>` | the limit on list items one decode holds (ruling 7 of 0.11) | 100000 |
| `--max-distribution public\|controlled` | the engine's distribution limit | `controlled` |
| `--profile open\|open+copyleft\|everything` | load only the packs and modules of this licence profile (Version 0.29) | none: every pack and module, and no licence file read |

After the subcommand the arguments are pairs of an option name and its value;
`--set` may be repeated, every other option is given at most once. `--json`,
taken by `licences` alone, is the one option without a value.

- `convert` reads standard input to its end and writes the result with
  nothing added (lower-case hex text for the `bits`, `protobuf` and `tlv`
  wires, and no line feed after any result). The `--set` options are the
  context, checked in the order given.
- `list-formats` writes `format<TAB>version<TAB>wire`, one line per pack, in
  byte order of format name.
- `capability` writes the capability report of the pair as one line
  `from<TAB>to<TAB>grade<TAB>carried<TAB>dropped`, the entries of a list
  joined by a space.
- `matrix` writes that header line, then one such line per ordered pair of
  loaded formats.
- `licences` writes `dir<TAB>format<TAB>licence<TAB>profile`, one line per
  loaded pack, in byte order of the pack's directory name: the licence of its
  `REUSE.toml` (`Apache-2.0` when it has none) and the pack's own profile, or
  `none`. With `--json` it writes `{"packs":[{"pack":...,"format":...,
  "licence":...,"profile":...},...]}` and a line feed, with no space. It reads
  every licence file with or without `--profile`.

Exit status: 0 on success; 1 on a load or call failure, with standard output
empty and the failure's message on standard error, its first line beginning
with the kind and a colon (`unknown-format: ...`); 2 on a usage error, which
is reported before anything is loaded or read; a `--profile` value that is
not one of the three is usage error 11. The tool has no option of its own
(`--x-...`).

## Licence profiles

`spec/engine-spec.md`, Version 0.29. `Engine::load_tool` takes an optional
profile, `open`, `open+copyleft` or `everything`:

```cpp
auto eng = goat_transformers::Engine::load_tool(
    "packs", "model", nullptr, goat_transformers::Distribution::Controlled, "open");
for (const auto& p : eng.pack_licences())  // dir, format, licence, profile
    std::cout << p.dir << " " << p.licence << " " << p.profile << "\n";
```

With a profile it reads `<packs>/../licences.toml`, then each module file's
`<models>/<file>.def.license` and its `module` and `uses` lines, before any
module is loaded; a module or pack whose profile the profile does not hold is
not loaded, nor parsed, so a broken pack outside the profile is not an error.
Each pack's `REUSE.toml` is read when the pack is reached, after the checks
of a `--packs-only` name. A text that is not a profile, or a licence file that
cannot be read by the line forms of ruling 1, is the load failure
`bad-licence` (`ErrorKind::BadLicence`). With no profile no licence file is
read and the load is that of 0.23, unless the last argument, `read_licences`,
is true (the `licences` subcommand): then every licence file is read in the
same order and nothing is skipped. `pack_licences()` lists the loaded packs
with their licence and profile when the licences were read, and is empty
otherwise; `Engine::is_profile(name)` tells a profile name. The reader is
`src/licences.cpp`, by the exact line forms of ruling 1, with no TOML library.

A controlled pack is in no profile (Version 0.93). When the licences are read,
a module file or `pack.def` that is not shown public (an exact line
`distribution public` and no doubtful line, ruling 1) has the profile none
whatever its licence, and so has every module and pack that uses it. Each such
file is read once: the text that gave its profile is the text parsed, so a file
that changes during the load cannot be loaded as controlled (the tests reach
that refusal through `detail::def_text_hook`, which changes the text between
the profile and the parse). A load with a
profile makes the engine's distribution limit `public` for good:
`max_distribution()` is then `Public` whatever `set_max_distribution` was given
before or after, and a controlled module or pack loaded later is
`distribution-refused`. `Engine::load_tool_into` is the same load on an
existing instance; with a profile, an instance that already holds a controlled
module or pack is refused with `distribution-refused` before anything is read
(after the check of the profile name). Both refusals leave the limit
unchanged and nothing loaded; after them the limit is public, also when the
load fails later.
The engine has no C interface.
