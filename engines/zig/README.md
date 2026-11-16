# gt-engines: Zig engine

Clean-room Zig 0.13 implementation of the format engine defined in `spec/`.
Decodes/encodes the `xml`, `geojson`, `json`, `bits` (`lsb` and `msb` bit order)
and `protobuf` wires through pack-defined fields and transforms, selects message
kinds (`kind` / `when` / `requires`, spec Version 0.5), applies the mapping rules
of spec Version 0.6 (`const`, `default`, value tables with `map` / `via`, the
field options `swap` / `trim` / `optional`, an xml `root` per kind, `derive`
lines in model modules, caller-supplied keys), maps the repeating parts of a
message to lists (`list` lines in model modules and `group … end` blocks, spec
Version 0.7), reads and writes sequential binary layouts (`layout sequential`
on the `bits` wire, spec Version 0.8), and converts between formats via the
shared model.

## Build and run the conformance harness

```
zig build run          # loads ../../packs, runs every vector
zig build test         # same (the harness is the test)
zig build-exe src/main.zig && ./main ../../packs
```

Prints `vectors: N/N passed` (conversion vectors) and `load vectors: N/N passed`
(`packs/conformance/load-vectors/`), after one `FAIL <pack>/<vector file>: <why>`
line per failing vector; non-zero exit on any failure. Stdlib only.

## Model modules and distribution (spec Version 0.4)

The harness loads `model/*.def` (`core.def` first, then byte order of file
name, each module after the modules its `uses` lines name) and then the packs.
`Engine.loadModel(text)` loads one module; `Engine.loadPack(text)` checks a pack
against the modules loaded so far. `Engine.decode(format, bytes)`,
`Engine.encode(format, entity)` and `Engine.convert(from, to, bytes, context)`
work on the loaded packs; `context` is null or the caller-supplied keys.
`Engine.complete(entity)` applies the derivations on their own and
`Engine.fillContext(entity, context)` sets the context keys the entity lacks.
`Entity.kind_fmt` / `Entity.kind_name` are the recorded kind. `Entity.lists`
maps a list name to its items; an item is an `Entity` with no residue, and may
hold lists of its own. An item of a sequential group whose body has kinds
records its kind in the same two fields (`Item.kind`). Results and the
failure message are allocated from `Engine.scratch` (by default the engine's
allocator; the harness points it at one arena per vector). A
failure the specification names is a Zig error whose name is the spec's kind
(`error.@"unknown-module"`, `error.@"no-kind"`, `error.@"missing-root"`,
`error.@"malformed-wire"`,
`error.@"transform-encode"`, `error.@"transform-decode"`,
`error.@"bad-directive"`, `error.@"duplicate-kind"`), and `Engine.last_error`
holds the message `<kind>: <detail>`.

```
gt-engine-zig [<packs-dir>] [--models <dir>] [--max-distribution public|controlled]
              [--model-keys <format>]
              [--convert <from> <to> [--set <key>=<value>]...]
```

`--models` defaults to `<packs-dir>/../model`; `--max-distribution` defaults to
`controlled` (`Engine.setMaxDistribution`). `--model-keys <format>` prints
`model_keys(format)`, the union of mapped keys over the common lines and every
kind in first appearance order, and runs no vectors. A list is printed as
`<list>[]` and a key of its items as `<list>[].<key>`, nested lists likewise.
`--convert <from> <to>` reads one message on standard input, converts it and
writes the result on standard output, running no vectors; each `--set
<key>=<value>` supplies one context key. A failure prints `error: <kind>:
<detail>` on standard error and exits 1.

## Groups (spec Version 0.7)

A `group` line sits among the lines of its scope, so a list is written at the
position of its line. Each group body is a scope of its own: its lines, its
`default` values, and on `bits` its extent. The vector harness checks
`"<list>.#"` and `"<list>[<i>].<key>"` entries of a vector's `model`, with
further `[<j>].` steps for nested lists.

- `xml`: the items are the children with the last name of the group locator,
  under the first element the names before it match.
- `json`, `geojson`: the items are the elements of the array; `.` addresses a
  scalar element. Items of a `geojson` group use member paths and the `geojson`
  value types.
- `protobuf`: the items are the occurrences of the last field number. A body
  of `.` lines only reads each occurrence as a scalar and accepts the packed
  form for `pvarint`, `psint`, `pdouble` and `pfloat`; encode writes those
  packed and `pstring` as one occurrence per item.
- `bits`: `item <bits>` and `count`. The message grows with its items and is
  padded to whole words. An item holding a nested group counted by a locator
  ends where that group ends when it runs past `item <bits>`.

## Sequential layouts (spec Version 0.8)

A pack that holds `wire bits` and `layout sequential` is read by its own
parser into a tree of lines: `field`, `also`, `const`, `pad`, `align`, `when`,
`presence` with `if` blocks, `opt`, `chain` with `fx` lines, `length` blocks,
`length … whole`, and `group` with `count`, `while`, `more` or `fx`, whose body
may hold kinds. Decode walks the tree with a cursor; inside a `length` extent
a line that starts at or after its end reads as absent. Encode computes each
presence, `opt` and `fx` bit from the entity before writing it, writes a
`length` after its block, and a `length … whole` after the message. The vector
harness checks `"<list>[<i>].@kind"`.

Model modules take `uses` lines and the derive functions `day_seconds`, `any`,
`not`, `parse_int` and `text_of`.

## Readings where the specification leaves a choice

- `bits`: a `const` counts toward the length a decode needs, as a `field` does.
- A key with a `default` both in the common lines and in the kind uses the
  kind's.
- A `default` value that cannot be read as its key's type is
  `key-type-mismatch` at load.
- A `derive` line is checked after the whole module file is read and before
  `missing-distribution`; integer `offset` that overflows leaves the target
  absent.
- A field with both a `typemap` entry and `via` on the key `type`: decode
  applies the table, then the typemap; encode the reverse.
- A context that is given but empty still runs the derivations when
  `from == to`.
- Groups, where no vector decides:
  - A scalar item (`.`) with no value is written `null` on `json` and
    `geojson`, an empty element on `xml`, an empty length-delimited occurrence
    for `pstring`, and is left out of a packed `protobuf` field.
  - An array element that is not an object, under a body that addresses
    members, is an item with no keys (as a `null` element is).
  - On `bits` a group with no item adds nothing to the message length.
  - A `default` naming a list, and a context key naming a list, are
    `key-type-mismatch`.
  - `item` on a wire other than `bits` is `bad-directive`, as `count` is.
  - A `geojson` group at the top of the pack is at `properties.<name>` or a
    top-level member other than `type`, `geometry` and `properties`; another
    locator is `bad-directive`.
  - `geojson` residue: an array or object comes back with no insignificant
    whitespace and with each number as it was written.
- Sequential layouts, where no vector decides:
  - The `length` options `bytes` or `bits`, `plus <n>` and `whole` are taken
    in any order.
  - A block has content when a line in it, at any depth of `if`, `opt`,
    `chain` and `length` blocks, would write a present key or a non-empty
    list. A `const` is not content.
  - Inside a `length` extent that has ended: `const`, `pad`, `opt`, a
    presence and a nested `length` read as absent (a presence as all zero);
    a common `when` does not hold.
  - `pad` and `const` past the end of the input are `malformed-wire`; `align`
    past it is not, until a later line reads.
  - A `default` inside an `if`, `opt`, `chain` or `length` block belongs to
    the enclosing message, kind or group body.
  - `map` and `typemap` are refused inside a group, and accepted inside the
    other blocks.
  - An item's recorded kind selects on encode only when it was recorded for
    the format being written.
  - `parse_int` takes an optional sign (`+` or `-`) and decimal digits; a
    value outside 64 bits leaves the target absent.
  - A module whose `uses` names a module that is not loaded is
    `unknown-module` after `missing-distribution`, `missing-source` and
    `distribution-refused`; a `derive` argument of such a module is
    `unknown-module` where the derive lines are checked.
