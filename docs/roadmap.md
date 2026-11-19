# Roadmap

Status: Written. This page states what is built and what is designed and not
built. It gives no dates.

## Built

| Part | State |
|---|---|
| Engines | Seven: Rust (reference), Go, Python, Java, C++, Erlang, Zig. Each uses only its language's standard library and passes every vector |
| Wire types | Five: `xml`, `geojson`, `json`, `protobuf`, `bits` (either bit order; scaled, floating-point and text fields) |
| Conformance vectors | 12,910 conversion vectors in 1,324 packs and 505 load vectors; every engine reproduces every one |
| Shared model | Modules `core` and `track`, and one module of raw wire values for each catalog format. Every mapped key is declared and type-checked at load (`spec/shared-model.md`) |
| Packs | The table in `README.md`; coverage by format in `docs/coverage-roadmap.md` |
| Pack generators | `tools/gen/proto2pack.py`, `xsd2pack.py`, `canboat2pack.py`, `mavlink2pack.py`: a pack, its module and its round-trip vectors from a machine-readable definition |
| Capability matrix | `Engine::capability` and `goat-xf matrix [--detail]`: for every pair of formats, which keys carry and which the target cannot represent |
| Public and controlled boundary | `distribution` and `source` on every module and pack, enforced by the engines; `tools/boundary-gate` on this repository (`docs/boundary.md`) |
| Package planner | `tools/goat-pkg`: constraints in, the smallest package out (`docs/package-configurator.md`) |
| System records and the options query | `.rec` records of what a system emits, accepts and converts; `tools/goat-options` lists every path between two systems with its status and evidence, from the records and the capability report (`docs/system-records.md`) |
| CI | `.github/workflows/conformance.yml` builds each engine, runs every vector on it and runs the boundary gate, on every change |

## Pack-language additions

A pack can state only what the pack language has a rule for. Each addition is a
section of `spec/engine-spec.md`, an implementation in the reference engine,
vectors, and the same change in the other six engines.

| Addition | Allows | State |
|---|---|---|
| Message kinds | several message layouts in one format, chosen by values on the wire | Built (spec 0.5) |
| `json` wire | members by path in any JSON object | Built (spec 0.5) |
| `bits` in either bit order, fields past their word, scaled, floating-point and text fields | the binary layouts that public message catalogs use | Built (spec 0.5) |
| Mapping rules: constants, defaults, value tables, derived keys, caller-supplied keys; per-field byte swap, trim, optional trailing fields; an XML root per kind | what an encoder does in addition to copying a value | Built (spec 0.6) |
| Groups | a part of a message that repeats, mapped to a list in the model: repeated XML elements, JSON arrays, repeated protobuf fields, counted binary items; nested | Built (spec 0.7) |
| Sequential binary layouts | fields placed by what came before: presence bits, parts that repeat while an indicator is set, extensible items, blocks that state their own length, list items decoded by kind | Built, seven engines (spec 0.8) |
| Layered wires and framing | one pack's payload is another pack's whole message; declared lengths, trimmed payloads, checksums | Designed |
| Absent-value sentinels | a wire value that means "unknown" decodes to an absent key, and an absent key encodes as that value | Built, seven engines (spec 0.9) |
| A value from presence | the `present` derive function: an integer 1 when another key holds a value of any type, so a pack sets a flag from whether a value is sent (ASTERIX CAT062 MRH) | Built, seven engines (spec 0.12) |
| Strict rulings | one byte sequence and one named error where earlier sections were silent: XML text, number and time grammars, rounding and range on `bits`, a kind for every load failure, the capability report, a limit on list items | Built, seven engines (spec 0.11) |
| Further value functions | character sets, sign-and-magnitude numbers, scales that yield integers, a scale on a text wire, an instant split into seconds and nanoseconds, frame conversions (ECEF, radians, mean sea level) | Designed |
| Encode selection by value | choosing the target message kind from the value of a key, not only from which keys are present | Designed |
| Conditional output and flag tokens | a value written only when another exists; several flags joined into one token list | Designed |
| XML namespaces and prefixes | documents whose elements carry a prefix | Designed |

The Designed rows come from generating packs for whole public catalogs
(MAVLink, NMEA 2000, Mode S, Remote ID) and from the comparisons in
`docs/consumer-proofs.md`. Each row names something those sources carry that a
pack cannot yet state. Each pack's `pack.md` lists what it leaves unmapped.

## Wire types

A wire type is a section of the specification, an implementation in each of the
seven engines, and vectors.

| Wire type | Shape | Needed by | State |
|---|---|---|---|
| Text grammar | delimited or positional text records | NMEA 0183 | Built (spec 0.10, `wire text`) |
| Type-length-value | records of key, length and value | KLV / MISB ST 0601, NITF | Built (spec 0.13, `wire tlv`) |
| Six-bit armor | ASCII-armored bit payloads | AIS / AIVDM | Designed |
| ASN.1 UPER | packed-encoding ASN.1 | SAE J2735 (V2X) message sets | Designed |

## Packs

`docs/coverage-roadmap.md` lists the public formats that have no pack and what
each needs. Formats in other domains that the same method fits, none of which
has a pack:

| Domain | Formats |
|---|---|
| Aviation | AIXM, FIXM, ACARS |
| Maritime | VDES, IHO S-100 and S-101 |
| Space | XTCE |
| Internet of things | the Matter data model, LwM2M, Zigbee Cluster Library |
| Vehicles and robots | SAE J1939 |

`CONTRIBUTING.md` states how to add a pack.

## Engines and packaging

| Item | State |
|---|---|
| Fully static binaries from the Rust and Go engines | Measured |
| WebAssembly builds of the Rust and Go engines | Measured |
| A C-ABI library and a WebAssembly module of the Rust engine, in `bindings/`, for hosts in languages with no native engine | Built |
| An embedded profile in `embedded/`: `tools/gen/packc.py` compiles `bits` packs to a binary plan, and `gt-core` (no standard library, no heap) runs it on a microcontroller; equivalence with the Rust engine and the image sizes for `thumbv7em-none-eabihf` in `docs/embedded.md` | Measured |
| Per-wire feature gates in each engine, so that a package for `xml` formats only does not compile the binary codecs | Designed |
| The capability matrix as a checked CI artifact | Designed |
| Parse-once caching for packs and protobuf submessages; a benchmark for each engine | Designed |
| An HTTP front end over the package planner | Designed |
| Transport adapters in `adapters/`: stdin, files, directories, TCP, UDP, serial and MQTT 3.1.1 through `goat-xf-pipe`, standard library only (`docs/adapters.md`) | Built |
| A Zenoh adapter, its own crate outside the adapters workspace | Built; not built in CI |
| A README for each engine: build, library use, the command-line tool, the tests and their counts | Built |

## Use by other projects

`docs/consumer-proofs.md` reports, for each project, where the library runs
in that project's own conversion path and what its own tests measure:

| Project | Library path | Measured in the project's CI |
|---|---|---|
| open-billie | CoT, CAT062, SAPIENT encoders, chosen per format | CAT062 397 of 397 fields, CoT 547 of 594, SAPIENT 579 of 717 (33 inputs) |
| first-bite | the `xf` transform | 443 of 462 fixture fields equal, 18 more in another form |
| goatstuff | `transform-shim`; goat-map CoT to GeoTrackV1 | 353 of 368 members equal, 15 more in another form |
| octo-pod | `gateway/translate` | in review |
| open-entity-gateway | CoT, SAPIENT, CAT062 destinations | 4 inputs; every field equal but 8 named rows (time text, access, callsign, detail, MRH, SRC, I062/080 extents, SAPIENT track_info) |

`docs/consumer-proofs.md` lists what still differs and which Designed row above
removes each difference.
