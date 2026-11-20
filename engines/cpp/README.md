# goat-transformers: C++ engine

A C++17 implementation of the engine specification (`spec/engine-spec.md`),
written from the specification and the conformance vectors. It builds a static
library (`goat_transformers`), the command-line tool `goat-xf` and three test
programs.

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

## Test

```sh
cd build && ctest --output-on-failure
```

| ctest name | Program | What it checks |
|---|---|---|
| `vectors` | `goat_transformers_vectors` | every conversion vector under `packs/*/vectors` (each with its `max_items`; a `model` value its grammar refuses makes the vector invalid), every load vector under `packs/conformance/load-vectors` (with `pack` or `packs`) and every capability vector under `packs/conformance/capability-vectors` (`spec/vector-format.md`) |
| `unit` | `goat_transformers_unit` | number formatting, dates, pack grammar errors, residue, and the malformed-input rulings no vector reaches |
| `malformed_input` | `goat_transformers_fuzz` | the malformed-input test, below |
| `cli_list_formats`, `cli_packs_only` | `goat-xf` | the command-line tool loads the packs |
| `tool_vectors` | `goat-xf`, through `tools/tool-vectors.py` | the tool vectors under `packs/conformance/tool-vectors` (the command-line contract, 0.23): 97/97 pass. The entry exists when CMake finds a Python 3 interpreter |

Each program prints its counts on the last line and exits non-zero on any
failure. A program can be run by itself: `./build/goat_transformers_vectors`.

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
goat-xf help
```

| Option | Means | Default |
|---|---|---|
| `--packs <dir>` | the directory whose subdirectories are packs | `packs`, in the current directory |
| `--models <dir>` | the directory of model modules | the `--packs` text followed by `/../model` |
| `--packs-only <name>[,<name>...]` | load only these subdirectories of `--packs`, in the order given | every subdirectory |
| `--max-items <n>` | the limit on list items one decode holds (ruling 7 of 0.11) | 100000 |
| `--max-distribution public\|controlled` | the engine's distribution limit | `controlled` |

After the subcommand the arguments are pairs of an option name and its value;
`--set` may be repeated, every other option is given at most once.

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

Exit status: 0 on success; 1 on a load or call failure, with standard output
empty and the failure's message on standard error, its first line beginning
with the kind and a colon (`unknown-format: ...`); 2 on a usage error, which
is reported before anything is loaded or read. The tool has no option of its
own (`--x-...`).
