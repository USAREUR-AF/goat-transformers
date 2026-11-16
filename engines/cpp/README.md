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

## Test

```sh
cd build && ctest --output-on-failure
```

| ctest name | Program | What it checks |
|---|---|---|
| `vectors` | `goat_transformers_vectors` | every conversion vector under `packs/*/vectors` and every load vector under `packs/conformance/load-vectors` (`spec/vector-format.md`) |
| `unit` | `goat_transformers_unit` | number formatting, dates, pack grammar errors, residue, and the malformed-input rulings no vector reaches |
| `malformed_input` | `goat_transformers_fuzz` | the malformed-input test, below |
| `cli_list_formats`, `cli_packs_only` | `goat-xf` | the command-line tool loads the packs |

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

```sh
./build/goat-xf list-formats --packs ../../packs
./build/goat-xf convert --packs ../../packs --from cot-xml --to geojson < message.xml
```

`convert` reads the message from standard input and writes the result to
standard output. On an error it prints the message, which begins with the
error kind, to standard error and exits with status 1.
