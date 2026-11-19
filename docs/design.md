# goat-transformers: design

Status: Written. Each section states what is Built and what is Designed.

## Purpose

One library converts messages between formats, any format to any other. A format
is described by data files, and each supported language has one engine that
reads them. A project loads only the formats it needs, in the language and
build it needs.

The library is used from up to three repositories:

| Repository | Holds |
|---|---|
| `goat-transformers` (this one) | engines, specification, public model modules, packs written from public sources |
| `goat-transformers-overlay-example` | a worked overlay with fictional content |
| a private overlay (optional, the user's own) | model modules and packs for formats whose specification is not public |

`docs/boundary.md` states what keeps the first and third apart.

## How any-to-any works

Every format maps its fields to keys of one shared model. A conversion from
format A to format B is "decode A to the model, encode the model to B", so N
formats need N packs, not N×N converters.

The model is a set of modules (`spec/shared-model.md`). A module is a named list
of typed keys with fixed units. Two formats convert to each other exactly the
keys they both map, so the more modules two formats share, the more of a message
carries. A field no module has a key for is kept in a per-format `residue` block
and written back when the message returns to its own format.

Built: modules `core` (13 keys) and `track` (19 keys and one list: the
Canonical Track v2 contract of `USAREUR-AF/open-billie`, and `scoped_id`), and one module of raw
wire values for each catalog format; load-time checks that every
mapped key is declared and correctly typed, in all seven engines.

### Fidelity is measured, not asserted

For every ordered pair of loaded formats the engine reports which keys carry and
which the target cannot represent, graded Full, Partial or None
(`Engine::capability`, `goat-xf matrix --detail`). A pair that must lose nothing
and cannot get there through the modules gets a direct pair rule, which names
its evidence (`docs/adr/0002`). Built: the matrix. Designed: pair rules.

## A pack

A pack is one directory, loaded on its own:

```
packs/<format>/
  pack.def      format name, wire type, distribution, sources, one `field` line per mapped value
  pack.md       notes for a reader
  vectors/      conformance vectors
```

A `field` line binds one model key to one place on the wire through one
transform: `field lat point/@lat float`. The grammar is `spec/engine-spec.md`.
Adding a format whose wire type exists is data only; no engine changes.

## Wire types

A wire type is the engine's generic codec for a family of encodings. A pack
names one.

| Wire | For | Status |
|---|---|---|
| `xml` | attribute and element text by path | Built, seven engines |
| `geojson` | GeoJSON Feature | Built, seven engines |
| `bits` | fixed-size binary words, fields are bit ranges | Built, seven engines |
| `protobuf` | fields by number, dot-path into submessages | Built, seven engines |
| `json` | members by path in any JSON object | Built, seven engines |
| `bits`, sequential layout | fields placed by what came before: presence bits, repeats, extensible items, stated lengths | Built, seven engines |
| text grammar | delimited or positional text records | Designed |
| type-length-value | records of key, length, value | Designed |
| six-bit armor | ASCII-armored bit payloads | Designed |
| framed binary | length-and-checksum framed messages | Designed |

## Pack-language additions

A pack states one or more message layouts for its format. `docs/roadmap.md`
(Pack-language additions) is the list of what the language can state today and
what is designed next; the grammar is `spec/engine-spec.md`.

Built in all seven engines: message kinds chosen by values on the wire, the
`json` wire, both bit orders, fields that run past their word, and scaled,
floating-point and text binary fields (spec 0.5); constants, defaults, value
tables, derived keys, values the caller supplies, per-field byte swap, optional
trailing fields and an XML root per kind (spec 0.6); groups, which map a
repeating part of a message to a list in the model (spec 0.7). Designed: items
layered wires and framing, absent-value sentinels, further value
functions, conditional output, XML namespaces.

### What an encoder does around the copy of a value

An encoder rarely only copies. It writes constants, fills defaults,
looks values up in tables, computes one value from others, and adds values only
the host knows. These are stated as data too:

| Rule | Where | Example |
|---|---|---|
| `const` | pack | CoT `version` is always `2.0` |
| `default` | pack | CoT error is `9999999` when unknown |
| `map` and `via` | pack | a track class name to a CoT type |
| `derive` | model module | course and speed from east and north velocity |
| context | caller | the stale time, the node identifier |

Derivations belong to the model, not to a pack, so every format gains them at
once: a format that carries a velocity vector converts to one that carries
course and speed with no pair rule.

## Engines

| Language | Role | Status |
|---|---|---|
| Rust | reference engine | Built |
| Go, Python, Java, C++, Erlang, Zig | independent native engines | Built |

Every engine is written from `spec/` and the vectors, never from another
engine's source, so a defect in one is caught by the others
(`spec/interop-and-sharing.md`). All seven use only their language's standard
library.

Build targets. Measured: Rust and Go fully static binaries; Rust and Go to
WebAssembly; Java on the JVM. Built: a C-ABI library (shared and static) and a WebAssembly module of the Rust
engine with a dependency-free JavaScript wrapper, in `bindings/`, for hosts in
languages with no native engine (TypeScript, C#, Swift). The module has no
imports and is 346,027 bytes in its small build (`python3 -I tools/repo-stats`
prints the size of a built module); every conversion vector passes through it.

## Conformance

A conversion vector is `{from, to, input, expect}`; a load vector is a set of
modules and one pack that must load or must fail with a named error
(`spec/vector-format.md`). Every engine runs every vector. Built: 3,299 conversion vectors across 96 packs and 314 load vectors (`python3 -I tools/repo-stats` prints the current counts), all passing on all seven engines.

## Separation of pack authors and engine authors

A person who writes a pack from a specification that is not public writes only
pack data and vectors, in a private overlay. A person who writes an engine reads
only the specification, the public modules and the vectors. Engine source
therefore contains nothing taken from a specification that is not public.

## Systems and the options between them

The packs describe formats; a system record (`.rec`) describes a system: the
formats it emits, accepts or converts, each with a status (`proven`,
`available`, `forthcoming`, `unknown`) and its evidence. `tools/goat-options`
merges records from several store directories and lists every path from a
producing system to a consuming one, direct or through up to two conversions,
with what carries taken from the capability report. It lists options and does
not rank them. Built: the record format, the site file and the query, with
fictional records in `examples/` (`docs/system-records.md`). Records of real
systems are kept in private stores (`docs/private-store.md`).

## Packaging

`tools/goat-pkg plan` takes constraints (formats, language, runtime, linkage,
OS, architecture) and returns the smallest package that meets them: the engine,
only the named packs, the wire codecs those packs use, and the build command
(`docs/package-configurator.md`). Built: the planner. Designed: per-wire feature
gates in each engine so an unused codec is not compiled in; an HTTP front end
over the planner.

## Consumers

Public projects that convert messages, and the place the library joins each.
The library runs in open-billie, first-bite and goatstuff as a path beside
their own code, chosen by a setting (Built); in octo-pod and open-entity-gateway
it is Built and in review. The measurements are in
`docs/consumer-proofs.md`. The table below is the original join plan.

| Consumer | Today | Where the library joins | Needs first |
|---|---|---|---|
| open-billie (`USAREUR-AF/open-billie`) | Rust translator with hand-written CoT, ASTERIX CAT062 and SAPIENT encoders behind `runtime/rust/translator/src/dispatch.rs`, fed Canonical Track v2 JSON | the Rust engine as a dependency of the translator, replacing the three encoders | a CAT062 pack (needs presence-indicated items); the `json` wire and the Canonical Track v2 pack are built |
| first-bite (`USAREUR-AF/first-bite`) | Rust; JSON dictionaries drive binary decode; CoT output through `cotify` | the Rust engine as a dependency; its dictionaries become `bits` packs; a new transformer subtype in `flow/src/subpub.rs` | message kinds; a dictionary-to-pack converter |
| octo-pod (`USAREUR-AF/octo-pod`) | Rust arms capture bytes; its ADR 0001 keeps field translation outside the appliance | a separate translator process that subscribes to captured keys and republishes converted ones | a Zenoh subscriber wrapper around the Rust engine |
