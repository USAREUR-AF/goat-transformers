---
name: add-a-format
description: Write a goat-transformers pack for a message format from its public specification. Use when asked to add, support or map a format, write a pack.def, bind fields to shared-model keys, or make a format convertible to the others. Not for formats whose specification is not public (use write-an-overlay) and not for whole catalogs that have a machine-readable schema (use generate-packs-from-a-schema).
---

# Add a format

A pack is data: `packs/<format>/pack.def` plus `pack.md`, `PROVENANCE.md` and
`vectors/`. No engine changes when the format's wire type exists. Read
`AGENTS.md` first; its rules bind every step.

## 0. Before writing anything

1. Find the specification and confirm it is public. Read its license. If the
   license restricts reuse, or the document carries a handling marking, stop
   and ask the person (AGENTS.md, "Ask a human").
2. Record now, for `PROVENANCE.md`: the address of each source, its version or
   commit, its SHA-256, the license statement, the date read.
3. Check that the format is not already covered: `ls packs/` and
   `docs/coverage-roadmap.md`.

## 1. Choose the wire type

| The format is | Wire | Locator form |
|---|---|---|
| XML | `xml` (needs `root <element>`) | `@attr`, `path/@attr`, `path/#text` |
| a GeoJSON Feature | `geojson` | `geometry.lat`, `properties.<name>`, `<name>` |
| any other JSON object | `json` | `member.member` |
| protobuf | `protobuf` | field numbers, `2.6.1` |
| binary with fixed positions | `bits` (needs `word_bytes`, `bit_order lsb` or `msb`) | `<word>:<bit>:<len>` |
| binary where earlier fields decide what follows | `bits` with `layout sequential` | lengths in order; `presence`, `if`, `chain`, `length` |

If none fits (delimited text records, type-length-value, ASCII-armored bits),
the format needs a new wire type: stop and use `extend-the-pack-language`.
`docs/coverage-roadmap.md` lists the wire types that are designed and not built.

Read the section of `spec/engine-spec.md` for the wire you chose, and one
existing pack of that wire as a model: `packs/nvg` (xml), `packs/demo-track-json`
(json), `packs/remote-id` (bits with kinds), `packs/asterix-cat062` (sequential).

## 2. Write pack.def

```
# One-line description. Public.
format  waypoint-json
version 0.1.0
distribution public
source  "<title, edition, address, license>"
wire    json
field   uid       name          string
field   lat       position.lat  float
field   lon       position.lon  float
field   hae       position.alt  float
```

- `field <model-key> <locator> <transform>`: one line per mapped value.
- Keys of module `core` are bare (`lat`); keys of another module are
  `<module>.<key>` and need `uses <module>`. The keys and their units are in
  `model/core.def` and `model/track.def`.
- Convert units in the pack, not in the caller: `sscale:1/10000000` turns a
  1e-7 degree integer into degrees. Write a decimal factor as a fraction.
- Several message layouts: `kind <name>`, `when <locator> <value>`,
  `requires <keys>` (spec, Version 0.5).
- What an encoder writes besides copies: `const`, `default`, `map` with `via`
  (spec, Version 0.6). Repeating parts: `group` (0.7).

## 3. Bind shared-model keys, with evidence

A binding claims that the format's field means what the key means, in the key's
unit. For every `field` on a `core` or `track` key, write down the sentence of
the specification that supports it: the reference frame (WGS 84 or not), the
height reference (ellipsoid or mean sea level), the unit, the time base.

- If the meaning differs (barometric altitude is not `hae`; magnetic course is
  not `course`), do not bind it. Leave it to residue, or declare a raw key in a
  module of the format's own (`model/<module>.def`, `distribution public`,
  `source`).
- Put the evidence in `pack.md` as a table: wire field, model key, note.

## 4. Check that it loads

```bash
cd engines/rust && cargo build --release && cd ../..
P="--packs packs --packs-only <format>,geojson,cot-xml"
engines/rust/target/release/goat-xf list-formats $P
engines/rust/target/release/goat-xf matrix --detail $P
```

A load failure names its cause: `undeclared-key` (the key is in no module the
pack uses), `key-type-mismatch` (the transform yields a different type from the
key's), `missing-source`, `missing-distribution`, `bad-directive`. The matrix
shows what carries to and from the other loaded formats.

## 5. Derive vectors independently

A vector is `{name, from, to, input, expect}` (`spec/vector-format.md`). Write:

- a round trip (`from` = `to`), including a field the pack does not map, to
  show residue carries it (text wires);
- a conversion to one or more other formats, and one from another format;
- error cases the format defines (`expect_error`).

Work `expect` by hand from the specification, or take a message and its decoded
values that the source publishes, or compute it with a program that imports no
engine. State where the values came from in the vector's `source` and
`reference` members. Do not run an engine and paste its output: then the vector
proves nothing. Only after `expect` is written, run the engine and compare:

```bash
python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['input'])" packs/<format>/vectors/01-x.json \
  | engines/rust/target/release/goat-xf convert --from <format> --to geojson $P
```

A difference means the pack, the vector or the engine is wrong. Find which
from the specification before changing anything.

## 6. Run every engine

The commands are in `AGENTS.md` (Commands). All seven must pass every vector.
An engine that disagrees with the others on your vector has found either an
ambiguity in the specification or a defect in that engine: report it, do not
weaken the vector.

## 7. Write pack.md and PROVENANCE.md

- `pack.md`: what the format is, the mapping table with the evidence from step
  3, what is not mapped and why, any message convention (what bytes a
  "message" of the pack is).
- `PROVENANCE.md`: for each source, where it can be obtained, version or
  commit, SHA-256, the license statement quoted. State that no source file is
  copied into the tree. Model: `packs/remote-id/PROVENANCE.md`.
- Add the source to `NOTICE`.

## 8. Finish

```bash
python3 -I tools/boundary-gate        # must print: boundary-gate: ok
python3 -I tools/repo-stats           # update the counts and the pack table in README.md
```

Add the format's row to `docs/coverage-roadmap.md`. Commit as
`feat(pack-<format>): …` with `git commit -s` when the person asks.
