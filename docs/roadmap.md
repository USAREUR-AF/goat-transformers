# Roadmap

Status: Written. This page states what is built and what is designed and not
built. It gives no dates.

## Built

| Part | State |
|---|---|
| Engines | Seven: Rust (reference), Go, Python, Java, C++, Erlang, Zig. Each uses only its language's standard library and passes every vector |
| Wire types | Five: `xml`, `geojson`, `json`, `protobuf`, `bits` (either bit order; scaled, floating-point and text fields) |
| Conformance vectors | 25,845 conversion vectors in 4,930 packs and 1,753 load vectors; every engine reproduces every one |
| Shared model | Modules `core` and `track`, and one module of raw wire values for each catalog format. Every mapped key is declared and type-checked at load (`spec/shared-model.md`) |
| Packs | The table in `README.md`; coverage by format in `docs/coverage-roadmap.md` |
| Pack generators | `tools/gen/proto2pack.py`, `xsd2pack.py`, `canboat2pack.py`, `mavlink2pack.py`: a pack, its module and its round-trip vectors from a machine-readable definition |
| Capability matrix | `Engine::capability` and `goat-xf matrix` and `goat-xf capability` (spec 0.23): for every pair of formats, which keys carry and which the target cannot represent |
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
| Whole-second time | `iso8601_s`: a time read as `iso8601_ms` reads it and written to the whole second, for formats that allow nothing finer (C2SIM) | Built, seven engines (spec 0.26) |
| A discriminator that is also a key | `when … as <key>` in a sequential layout: the bits that choose a kind also give a key on decode, and that key chooses the kind on encode, so a label field crosses to another format | Built, seven engines (spec 0.30) |
| One list counted from two places | `group <list> count @<a> @<b>` in a sequential layout: two count fields describe one list, such as a transport header's word count and the carried message's own count; they must agree, else `malformed-wire` | Built, seven engines (spec 0.31) |
| A kind decided by a field after other fields | `when … at <offset>` in a sequential layout: a kind's `when` looks ahead past fixed-width fields, so fields before the deciding one keep their own names in each kind | Built, seven engines (spec 0.33) |
| A message of another pack inside a field | `inner <format> [partial]` in a sequential layout: a transport pack hands the bytes of a length block to another loaded pack, which decodes them into the same entity and encodes them back from it, so a carrier's payload is a whole message of its own format | Built, seven engines (spec 0.34); not on the embedded profile |
| A discriminator key the entity need not hold | `when … as <key> optional` in a sequential layout: a kind qualifies on encode also when the entity does not hold the key, so a pack can bind its discriminator in every kind and still be a target for other formats. Also settled: an empty counted group and a layout with no counted bit on a fixed layout, and a key that an outer and an inner pack both map is refused | Built, seven engines (spec 0.52); on the embedded profile the two fixed-layout rules only |
| A length given by an earlier count | `length @<count> units <u>` in a sequential layout: a header's word count, with other header fields between it and the payload, sizes the payload's block (a JREAP-C or Link 16 transport header) | Built, seven engines (spec 0.83); not on the embedded profile |
| A run of inner messages | `inner <format> run` in a sequential layout: one field holds several messages of another pack back to back, each ending where its own lines or `framing self` say (a JREAP-C carrier with several messages) | Built, seven engines (spec 0.92); `convert_run` not in the C library or WebAssembly; not on the embedded profile |
| A conversion refuses a message that holds nothing | `convert` into a pack with message kinds gives `no-kind` when the entity holds no key of the chosen kind, so an entity that shares nothing with the target no longer becomes a message of constants and zeros (an acknowledgement or an abort); a pack without kinds opts in with kinds that hold only `requires` | Built, seven engines (spec 0.94); a device plan encodes what it is given, as `encode` does, so the check is not on the embedded profile |
| Value transforms | scales that yield integers, a scale on a text wire, sign-and-magnitude numbers, scaled IEEE floats, 6-bit and 7-bit character sets, octal digits | Built, seven engines (spec 0.15) |
| Derive functions for time, distance and frames | an instant split into seconds and nanoseconds, meters to degrees at a latitude, radians, sums and differences (mean sea level from a geoid separation), ECEF | Built, seven engines (spec 0.16) |
| Gated fields on a fixed layout | a field that exists only when other bits of the message hold a value: validity bits, multi-bit modes, one bit choosing between two meanings of the same bits | Built, seven engines and the embedded profile (spec 0.17) |
| Encode selection by value | choosing the target message kind from the value of a key, not only from which keys are present | Built, seven engines (spec 0.20) |
| Sequential extents and counts | a list that fills the rest of a message or of a stated length, a count placed before other fields, a flag on the last item | Built, seven engines (spec 0.21) |
| Conditional output and flag tokens | a value written only when another exists; several flags joined into one token list | Built, seven engines (spec 0.18) |
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
| Six-bit armor | ASCII-armored bit payloads | AIS / AIVDM | Built (spec 0.14, `armor sixbit` on `bits`) |
| ASN.1 UPER | packed-encoding ASN.1 | V2X message sets (ETSI ITS CAM; SAE J2735 is a paid standard) | Built (spec 0.19, `encoding uper` on sequential `bits`) |

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
| Per-wire feature gates in each engine, so that a package for `xml` formats only does not compile the binary codecs | Built, seven engines (spec 0.24): each engine's README names its switch; `tools/goat-pkg plan` prints it |
| Licence profiles `open`, `open+copyleft` and `everything`: every pack and model module belongs to the profiles its licence allows (`licences.toml`, `LICENSING.md`), and each engine loads only the files of a profile when asked; a file is in a profile only when it says itself that it is public, so a controlled pack is in none | Built, seven engines and `tools/licences.py` (spec 0.29, 0.93) |
| The capability matrix as a checked CI artifact: one command-line contract for all seven engines' tools (spec 0.23), pinned by tool vectors, and the matrix of the formats in `tools/matrix-formats.txt` produced by every engine's tool and compared byte for byte | Built, seven engines (spec 0.23): 97 tool vectors; the matrix is a CI artifact all seven write alike |
| Parse-once caching for packs and protobuf submessages; a benchmark for each engine | Designed |
| An HTTP front end over the package planner (`tools/goat-pkg serve`) | Built |
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
