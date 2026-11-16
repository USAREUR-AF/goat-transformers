---
name: generate-packs-from-a-schema
description: Generate a goat-transformers pack, its model module and its round-trip vectors from a machine-readable definition with the generators in tools/gen. Use when a format has protobuf files, an XML Schema (XSD), a CANboat-style JSON database, ASTERIX category definitions or MAVLink XML message definitions, when asked to regenerate an existing generated pack (sapient, isa, cot-protobuf, uci, a-gra, isa-xml, nmea2000, mavlink2, the asterix-cat packs), or when a message catalog is too large to write by hand.
---

# Generate packs from a schema

A catalog with hundreds of message kinds is written by a generator, not by
hand. The generator reads the schema and writes the pack, a model module of raw
keys, `pack.md` and one round-trip vector per kind. A `pack.def` whose first
lines say it was generated is never edited: change the generator or its
arguments and run it again. Read `AGENTS.md` first.

## 0. Sources stay outside the tree

Schema files are not committed. Keep them in a directory outside the
repository. Confirm each is public and read its license before use; ask the
person if the license restricts reuse. Record address, commit or version,
SHA-256 and license for `PROVENANCE.md`.

## 1. Pick the generator

| Schema | Generator | Worked invocation |
|---|---|---|
| protobuf (`.proto`, proto2 or proto3) | `tools/gen/proto2pack.py` | `tools/gen/proto2pack-run.sh` (six packs) |
| XML Schema (`.xsd`) | `tools/gen/xsd2pack.py` | `tools/gen/xsd2pack-run.sh` (three packs) |
| CANboat `canboat.json` | `tools/gen/canboat2pack.py` | `--out <dir> --commit <sha> --fetch`; reads `<dir>/sources/canboat.json` |
| ASTERIX category definitions (the JSON of `zoranbosnjak/asterix-specs`) | `tools/gen/asterix2pack.py` | `--out <dir> --commit <sha> --fetch --cats 048,062` or `all`; reads `<dir>/sources/asterix-specs/` |
| MAVLink message XML | `tools/gen/mavlink2pack.py` | `--root <dir> --core-def model/core.def`; reads `<dir>/sources/{common,standard,minimal}.xml` |

Every generator is Python standard library only. Run each with `python3 -I`
and read its `--help`; the docstring at the top of each file states its inputs
and outputs. The two `-run.sh` files are the record of how the packs in this
repository were produced: copy the nearest block for a new format.

## 2. The arguments that matter

For `proto2pack.py`:

| Argument | Meaning |
|---|---|
| `--proto <files>` `--envelope <Message>` | the schema and the top message |
| `--format <name>` `--module <name>` `--out <checkout>` | pack name, model module name, where to write |
| `--source "<text>"` | repeatable; becomes the pack's `source` lines |
| `--kinds-from-fields` | one message kind per member of the envelope |
| `--map <path>=<key>` | bind a field (by number path, `2.10`) to a shared key (`lat`) in place of a raw key |
| `--bind`, `--table`, `--const` | a transform with a value table; a constant |
| `--default-kind`, `--default-requires` | which kind encode chooses for an entity from another format |
| `--names-file tools/gen/names/<format>.json` | pins the key name of every path |
| `--cross`, `--cross-text` | also write a vector to or from another pack |
| `--notes-file tools/gen/notes/<format>.md` | hand-written notes placed into `pack.md` |

`xsd2pack.py` takes `--xsd`, `--format`, `--module`, `--title`, `--out`,
`--model-dir`, `--names-file`, and `--map <Root>:<locator>=<key>`.

## 3. Names files keep keys stable

A model key is never renamed (`AGENTS.md`, rule 7). `tools/gen/names/<format>.json`
records the name the generator gave each path. Always pass `--names-file`, and
commit the file: the next run with a newer schema then keeps every existing
name and only adds new ones. Do not delete or hand-edit a names file.

## 4. Bind the few shared keys by evidence

By default every field becomes a raw key in the format's own module
(`sapient.…`), which round-trips and converts to nothing else. A `--map` line
is a claim that the field means what the shared key means, in its unit. Make
that claim only with the sentence of the schema or standard that supports it
(frame, unit, height reference), and put the reason in the notes file. The
`DETECTION` block of `proto2pack-run.sh` is an example.

## 5. Run, then check

```bash
python3 -I tools/gen/proto2pack.py --help
# run your invocation, writing into the checkout
git status --short model packs tools/gen/names      # what changed
```

Each generator re-reads its own output and checks it (grammar, key
declarations, types) and stops on a problem. Then load the result in an
engine, with only a few packs:

```bash
engines/rust/target/release/goat-xf list-formats --packs packs --packs-only <format>,geojson,cot-xml
```

Round-trip vectors that a generator writes are computed by the generator's own
encoder, which imports no engine. That is what makes them independent. A
conversion vector into another format (`--cross`) takes its expected side from
an existing hand-written vector.

Then run all seven engines (`AGENTS.md`, Commands) and
`python3 -I tools/boundary-gate`.

## 6. What a generator leaves to you

- `PROVENANCE.md` for the pack (not generated by `xsd2pack.py` or
  `proto2pack.py`), and the entry in `NOTICE`.
- The row in `docs/coverage-roadmap.md`; the counts in `README.md`
  (`python3 -I tools/repo-stats`).
- `pack.md` states what was not mapped and why. Read it: a large "not mapped"
  count for one reason usually names a pack-language addition
  (`docs/roadmap.md`), which is a finding to report, not to work around.

## 7. A new kind of schema

For a definition language with no generator, write `tools/gen/<x>2pack.py` on
the pattern of `canboat2pack.py`: standard library only, re-runnable, every
output rewritten from the source, a self-check that re-reads the output, key
names that stay the same from run to run, and vectors computed by code in the
generator. Written from
`spec/` only, never from an engine.
