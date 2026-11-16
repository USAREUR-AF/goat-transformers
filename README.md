# goat-transformers

[![conformance](https://github.com/USAREUR-AF/goat-transformers/actions/workflows/conformance.yml/badge.svg)](https://github.com/USAREUR-AF/goat-transformers/actions/workflows/conformance.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

goat-transformers converts messages between formats: Cursor on Target, GeoJSON,
SAPIENT, MAVLink, NMEA 2000, ADS-B and others. A format is described by data
files, not by code. Each of seven languages has one engine that reads those
files, so a format added as data works in every language.

> [!NOTE]
> goat-transformers is pre-1.0: the pack language and the engine interfaces can
> still change.

## Quick start

Build the Rust command-line tool and convert a Cursor on Target event to
GeoJSON. This needs a Rust toolchain and nothing else.

```bash
git clone https://github.com/USAREUR-AF/goat-transformers
cd goat-transformers/engines/rust
cargo build --release
echo '<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>' \
  | ./target/release/goat-xf convert --from cot-xml --to geojson
```

Output:

```json
{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}
```

`goat-xf list-formats` prints the formats that are loaded. `goat-xf matrix
--detail` prints, for every pair of formats, which values carry from one to the
other and which the target cannot represent. The tool reads packs from
`../../packs` unless `--packs <dir>` names another directory.

## How it works

Every format maps its fields to the keys of one shared model
([spec/shared-model.md](spec/shared-model.md)). A conversion from format A to
format B decodes A to the model and encodes the model to B, so N formats need N
descriptions and not N×N converters. A field that the model has no key for is
kept in a per-format residue block and written back when the message returns to
its own format.

A format is a **pack**: a directory with a `pack.def` file (the format name, the
wire type, the sources, and one `field` line for each mapped value), notes, and
conformance vectors. The grammar is [spec/engine-spec.md](spec/engine-spec.md).
The design is [docs/design.md](docs/design.md).

## Engines

Each engine is written from the specification and the vectors, and not from
another engine's source, so a defect in one engine shows as a difference from
the others. Every engine uses only the standard library of its language.

| Language | Directory | Run the conformance suite |
|---|---|---|
| Rust (reference) | `engines/rust` | `cargo test --release` |
| Go | `engines/go` | `go test ./...` |
| Python | `engines/python` | `PYTHONPATH=src python3 -m unittest discover -s tests` |
| Java | `engines/java` | `./build.sh` |
| C++ | `engines/cpp` | `cmake -S . -B build && cmake --build build && ctest --test-dir build` |
| Erlang | `engines/erlang` | `./build.sh && ./run_tests` |
| Zig (0.13.0) | `engines/zig` | `zig build test -- ../../packs` |

All seven engines pass every vector.

Every engine is fully conformant; use whichever fits. The project explores in
any language and settles performance-critical, safety-critical and
run-everywhere code in Rust (`docs/languages.md`).

## Wire types

A wire type is an engine's codec for a family of encodings. A pack names one.

| Wire | For |
|---|---|
| `xml` | attributes and element text by path |
| `geojson` | GeoJSON Feature |
| `json` | members by path in any JSON object |
| `protobuf` | protobuf messages, fields by number |
| `bits` | binary formats with fixed-size words and bit-range fields, in either bit order |

## Packs

A format with a message catalog has one message kind for each message type.

| Pack | Format | Wire | Message kinds |
|---|---|---|---|
| `cot-xml` | Cursor on Target event XML | `xml` | 1 |
| `cot-protobuf` | TAK protocol version 1 `TakMessage`, the protobuf form of a Cursor on Target event | `protobuf` | 2 |
| `geojson` | GeoJSON Feature (IETF RFC 7946) | `geojson` | 1 |
| `nvg` | NATO Vector Graphics 1.5, point | `xml` | 1 |
| `canonical-track-v2` | Canonical Track v2 of [open-billie](https://github.com/USAREUR-AF/open-billie) | `json` | 1 |
| `sapient` | SAPIENT, BSI Flex 335 v2.0 | `protobuf` | 9 |
| `sapient-v1` | SAPIENT, BSI Flex 335 v1.0 | `protobuf` | 9 |
| `isa` | Integrated Sensor Architecture, IPL 3.7 `Event` | `protobuf` | 1 |
| `isa-message` | Integrated Sensor Architecture, IPL 3.7 message union | `protobuf` | 7 |
| `isa-ipl1` | Integrated Sensor Architecture, IPL 1.6 message union | `protobuf` | 7 |
| `isa-xml` | Integrated Sensor Architecture, IPL 4.7 XML form | `xml` | 7 |
| `uci` | Universal Command and Control Interface (UCI) 2.6 | `xml` | 725 |
| `a-gra` | Autonomy Government Reference Architecture (A-GRA) 6.0a | `xml` | 860 |
| `nmea2000` | NMEA 2000 parameter groups, from the CANboat database | `bits` | 473 |
| `mavlink2` | MAVLink 2, common message set | `bits` | 235 |
| `adsb` | ADS-B on Mode S extended squitter (downlink format 17) | `bits` | 29 |
| `asterix-cat062` | ASTERIX Category 062 system track (one record, the items a track encoder writes) | 1 |
| `asterix-cat001` … `asterix-cat247` | 27 ASTERIX categories generated from machine-readable definitions, every item of the first item list | 1 each |
| `remote-id` | ASTM F3411 Remote ID (OpenDroneID) messages | `bits` | 8 |
| `demo-*`, `conformance*` (26 packs) | synthetic formats that exercise each wire type and each rule of the specification | all | |

Each pack's `pack.md` states what the pack maps and what it leaves unmapped.
Each pack's `source` lines and `PROVENANCE.md` name the public document it was
written from; [NOTICE](NOTICE) lists them. `tools/gen/` holds the generators
that write a pack from a machine-readable definition (`proto2pack.py`,
`xsd2pack.py`, `canboat2pack.py`, `mavlink2pack.py`).

## Conformance

A conversion vector is a JSON file with `from`, `to`, `input` and `expect`
([spec/vector-format.md](spec/vector-format.md)). A load vector is a set of
model modules and one pack that must load, or must fail with a named error.
Every engine runs every vector and must reproduce `expect` byte for byte. The
suite is the definition of correct behavior.

This repository holds 3,187 conversion vectors in 91 packs and 314 load vectors.
`.github/workflows/conformance.yml` runs all of them on all seven engines on
every change.

## Formats whose specification is not public

This repository holds only packs written from public sources. A pack for a
format whose specification is not public is kept in a private **overlay**
repository. An overlay pins this repository by commit, adds its own `model/` and
`packs/`, and assembles the two into one tree; the engines run that tree
unchanged. Every pack and model module is marked `distribution public` or
`distribution controlled`, and an engine started with `--max-distribution
public` loads nothing that is marked `controlled`.

[docs/boundary.md](docs/boundary.md) states the rules and the checks.
[goat-transformers-overlay-example](https://github.com/USAREUR-AF/goat-transformers-overlay-example) is a worked overlay with fictional content.

## Layout

```
spec/        the engine specification, the shared model, the vector format
model/       the shared model's modules, one file each
packs/       one directory per format: pack.def, pack.md, vectors/
engines/     one directory per language
bindings/    the Rust engine as a C library and as a WebAssembly module, for other hosts
tools/       goat-pkg       plan the smallest package for a set of constraints
             boundary-gate  refuse content in this repository that is not public
             gen/           pack generators
docs/        design, language guidance, architecture decision records, format coverage, the package planner
```

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) states how to run the conformance suite and
how to add a pack, a wire type or an engine. Report a vulnerability through
[SECURITY.md](SECURITY.md).

## License

Apache License 2.0 ([LICENSE](LICENSE)). Portions written by U.S. Federal
government employees within the scope of their employment are not subject to
copyright in the United States ([INTENT.md](INTENT.md)). [NOTICE](NOTICE) lists
the third-party sources the packs were written from.
