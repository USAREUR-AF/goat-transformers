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
on the `bits` wire, spec Version 0.8), reads wire values that mean "no value"
as absent keys and writes them for absent keys (the `absent` field option,
spec Version 0.9), reads and writes one-record text formats (the `text` wire,
spec Version 0.10), follows the strict rulings of spec Version 0.11, reads and
writes tag-length-value sets (the `tlv` wire, spec Version 0.13), reads and
writes `bits` messages as six-bit armored text (`armor sixbit` and the
`sixbit` transform, spec Version 0.14), converts values through the
transforms of spec Version 0.15 (exact integer scales, sign and magnitude,
scaled floats, 6- and 7-bit character sets, octal digits on `bits`; `scale`
and `iscale` on the text wires), reads and writes fields that exist only when
other bits hold a value (gate blocks `if [!]<locator> <values>` … `end` on the
fixed `bits` layout, spec Version 0.17), writes a line only when another key
is held (`with`), builds and reads token lists (`tokens`, `has_token`,
`text_if`), writes a time without a zero fraction (`iso8601_short`) and empty
`xml` elements (`element`, spec Version 0.18), reads and writes ASN.1
unaligned PER (`encoding uper`, spec Version 0.19), reads and writes
sequential lists that run to the end of their extent, counts that sit before
other fields and last-item flags (`group … rest`, `count <name>` with
`group … count @<name>`, `group … last`, spec Version 0.21), reads and writes
long and terminated fields (`hex` on `bits` up to 2040 bits, `chars:ascii8`,
`until:<code>`, the field option `stop <code>`, and `bit_order msb-lsb`, spec
Version 0.22), writes a time to the whole second (`iso8601_s`, spec Version
0.26), reads and writes one CBOR data item (the `cbor` wire, spec Version
0.28), binds the label a sequential kind is told apart by to a key (`when
<len> <values> as <key>`, spec Version 0.30: decode sets the key, encode
chooses the kind by it), counts one list from two places that must agree
(`group <list> count @<a> @<b>`, spec Version 0.31), decides a sequential
kind by a field that comes after other fields (`when <len> <values> at
<offset> [as <key>]`, spec Version 0.33: decode looks ahead without moving the
cursor, encode settles the window once the kind's lines are written),
hands the rest of a sequential message, or of a `length` block, to another
loaded `bits` pack (`inner <format> [partial]`, spec Version 0.34: the inner pack decodes into the same entity and encodes from it; the kind it selected
is `Entity.inner_kind_fmt` and `Entity.inner_kind_name`, beside
`Entity.kind_fmt` and `Entity.kind_name`; `loadPacksOnly` also loads, from
the packs directory, the packs `inner` lines name, transitively),
refuses a conversion into a message kind of which the entity holds no key
(spec Version 0.94: `no-kind`, after the kind is chosen and before any line
is written, in `convert` and `convert_run` with `from` different from `to`),
and converts between formats via the shared model.

## Build and run the conformance harness

```
zig build run          # loads ../../packs, runs every vector
zig build test         # the same, then the malformed-input run below
zig build fuzz         # the malformed-input run alone
```

The engine imports the module `build_options` that `build.zig` makes (the
wires of the build, below), so it is built through `zig build`, not with a
bare `zig build-exe src/main.zig`.

Prints `vectors: N/N passed` (conversion vectors), `load vectors: N/N passed`
(`packs/conformance/load-vectors/`) and `capability vectors: N/N passed`
(`packs/conformance/capability-vectors/`), after one `FAIL <pack>/<vector
file>: <why>` line per failing vector; non-zero exit on any failure. A
vector's `max_items` sets the limit on list items for that vector; a `model`
value its grammar refuses makes the vector fail as invalid. Stdlib only.

## Tests

| Command (from `engines/zig`) | What it runs | Result |
|---|---|---|
| `zig build test` | conversion, load and capability vectors, then the malformed-input run | `vectors`, `load vectors`, `capability vectors`, `malformed inputs` lines |
| `zig build module-test` | the module another program imports, one engine converting on eight threads at once (spec Version 0.25, below), the licence profiles (Versions 0.29 and 0.93, below) | `11 passed` |
| `engines/zig/bench.sh` (from the repository root) | the benchmark of spec Version 0.25 (below) | one JSON line per vector, then the load line |
| `engines/zig/reduced-check.sh` (from the repository root) | the reduced-build check of spec Version 0.24 (below) | `reduced-build check: passed` |
| `zig build cli -Doptimize=ReleaseSafe`, then from the repository root `python3 -I tools/tool-vectors.py -- engines/zig/zig-out/bin/goat-xf` | the tool vectors of spec Version 0.23 | `tool vectors: 183/183 passed` |

## Parse once, and the benchmark (spec Version 0.25)

What the engine keeps (ruling 1a). An `Engine` parses each model module and
pack once, when it is loaded, and keeps the result for its life: the
`Module` (keys, lists, resolved `derive` lines), and the `Pack` with every
line already resolved against its wire and its modules (bit offsets and
lengths, protobuf field-number paths, json member paths, xml root index by
element name, `when` value lists and ranges, transforms and their factors,
value tables, gate blocks, each kind's scope with its defaults, the plan of a
sequential layout with its switches and cases, and, new in 0.25, the JSON
text a `when` or `const` value is written as). `convert`, `decode` and
`encode` take the pack as `*const Pack` and only read it: a conversion
parses its input and nothing else, and allocates only from the engine's
`scratch` allocator, so a conversion (failed or not) leaves nothing that a
later one sees (ruling 1b). Loading reads each `pack.def` and each module
file once (ruling 1d); the harness runs every vector on the one engine that
loaded every pack.

Threads (ruling 1c). `convert` writes the engine's `last_error` and
allocates from `scratch`, so it is for one thread at a time. For an engine
shared between threads, `Engine.convertIn(&call, from, to, bytes, context)`
takes an `Engine.Call` holding the call's allocator (and optionally its
`max_items`) and returns the failure message in `call.last_error`; it reads
the engine and writes nothing in it. Load first; do not load while
conversions run. `zig build module-test` checks it: it loads the 13 packs
of the benchmark set other than `uci` and `a-gra` (every wire), runs every
conversion vector of those packs once in order (1377 vectors, failures
included, each checked against its vector), then runs them all again on
eight threads at once, each thread in its own order and three times over,
and requires every output, and every failure message, to be byte-equal to
the first run.

The benchmark (ruling 2), from the repository root:

```
engines/zig/bench.sh                       # bench/set.json, packs, model
engines/zig/bench.sh <set.json> [--packs <dir>] [--models <dir>]
```

`bench.sh` builds `zig-out/bin/gt-bench-zig` (`zig build bench`, always
`ReleaseFast`; the build's output goes to standard error) and runs it in
the current directory. It reads the set and every vector first, then loads
the packs the vectors name in `from` and `to` and the modules they use into
one engine and times that load (reading the files included). For each
vector in order it converts once and compares with `expect`, then converts
`iterations` times, each conversion allocating from one arena that is reset
(capacity kept) after it, and times the loop. Standard output holds one line
per vector, then the load line, as ruling 2c writes them, and nothing else.
A vector whose output differs, or a conversion that fails, ends the run with
exit status 1 and the reason on standard error; the lines are written only
at the end, so a failed run writes nothing on standard output.

BENCH_NUMBERS

## Builds with fewer wires (spec Version 0.24)

`-Dwires=<wire>,<wire>…` names the wires of the build, any of `xml`,
`geojson`, `json`, `bits`, `protobuf`, `text`, `tlv` and `cbor` (spec Version
0.28, ruling 38). With no `-Dwires` the build has all eight. It applies to every step: the harness, `goat-xf`
(`zig build cli`), the module and its test.

```
zig build cli -Dwires=xml,json,geojson -Doptimize=ReleaseSmall
```

`build.zig` turns the set into one compile-time constant per wire (module
`build_options`). Every place that reads or writes a wire, and the load-time
steps that only a pack on that wire reaches, is guarded by that constant, so
the codec of a wire not in the set is never analysed and is not in the
binary. `bits` takes the sequential layout, six-bit armor and `encoding uper`
with it (ruling 1d); `geojson` needs nothing of the `json` wire (the JSON
reader they share is in the build whenever either is). The checks a pack on a
wire of the build can fail stay whole, so such a pack loads, converts and
fails exactly as in a build with all eight (ruling 1b).

A pack whose `wire` is a wire the build does not have is `unknown-wire` at
line check 6, with the message `line <n>: wire <w> is a wire of the
specification that this build does not have`; a `wire` value that is no wire
stays `unknown-wire: line <n>: unknown wire <w>` (ruling 1c). The harness of a
reduced build loads every pack of the directory on its wires, leaves out each
pack on another wire, and does not run a vector that names such a pack, nor a
load vector one of whose packs is on such a wire; it prints the wires of the
build and how many packs and load vectors it left out.

The reduced-build check, from the repository root:

```
engines/zig/reduced-check.sh
```

builds the engine with all eight wires and with `xml`, `json` and `geojson`
(`-Doptimize=ReleaseSmall`; `OPTIMIZE=` chooses another), runs every vector
of the packs on those three wires through the reduced harness, loads a pack
on `bits` (fixed and sequential), `protobuf`, `text`, `tlv` and `cbor`, each of which
must be `unknown-wire` naming its wire, and prints the sizes of both builds.
It exits non-zero on any failure. Measured on 2026-11-26 (Zig 0.13.0, x86_64
Linux, `ReleaseSmall`):

| Binary | All eight wires | `xml`, `json`, `geojson` | Reduced / full |
|---|---|---|---|
| `gt-engine-zig` (harness) | 881 304 bytes | 471 704 bytes | 53 % |
| `goat-xf` (command-line tool) | 848 536 bytes | 451 224 bytes | 53 % |

The reduced harness loaded 1750 packs and left out 3302; it ran 8519
conversion vectors (8519 passed), 402 load vectors (402 passed) and 16
capability vectors (16 passed), and did not run 1051 vectors that name a
pack it left out nor 1351 load vectors with such a pack.

`goat-xf` of a reduced build loads a whole packs directory as Version 0.23
says, so a directory holding a pack on a wire the build lacks fails with that
pack's `unknown-wire`; name the packs with `--packs-only`.

## Command-line tool (spec Version 0.23)

`goat-xf` is the tool of the command-line contract, a separate executable
from the conformance harness (`src/cli.zig`, built on the engine of
`src/main.zig`). Build it and start it:

```
cd engines/zig && zig build cli -Doptimize=ReleaseSafe    # gives zig-out/bin/goat-xf
engines/zig/zig-out/bin/goat-xf <subcommand> ...          # from the repository root
```

```
goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>
goat-xf list-formats <options>
goat-xf capability --from <format> --to <format> <options>
goat-xf matrix <options>
goat-xf licences [--json] <options>
goat-xf help
```

`<options>`: `--packs <dir>` (default `packs`, relative to the current
directory, so the repository root's packs when started there), `--models
<dir>` (default the `--packs` text followed by `/../model`), `--packs-only
<a>,<b>...`, `--max-items <n>` (default 100000) and `--max-distribution
public|controlled` (default `controlled`) and `--profile
open|open+copyleft|everything` (default no profile; Version 0.29, below). The
tool has no `--x-` options of its own.

Every argument is checked before anything is loaded; a usage error exits 2
with a message and the usage on standard error. The tool then loads every
module of `--models` (`core.def` first, then byte order of file name, each
module after the modules it uses; a `--models` that does not exist or is not
a directory loads none), then the packs: with `--packs-only` the named
subdirectories in the order given (a name given twice is `duplicate-format`;
a name that is not one path component, or not a subdirectory holding
`pack.def`, is `unknown-format`), else every directory or symbolic link to
one not beginning with `.` that holds `pack.def`, in byte order of name. A
failure exits 1 with standard output empty and the engine's message
`<kind>: <detail>` as the first line of standard error; an unreadable
`--packs` prints `error: cannot read the packs directory <dir>: <reason>`.

`convert` checks `--from`, then `--to`, reads standard input to its end,
refuses input that is not UTF-8 as `malformed-wire`, and passes the bytes
unchanged to `Engine.convert`; the result is written with nothing added.
`--set` occurrences form the context, a repeated key taking its last value in
the place of its first. `list-formats` writes `<format>\t<version>\t<wire>`
per pack, `capability` one line `<from>\t<to>\t<grade>\t<carried>\t<dropped>`,
and `matrix` the header `from\tto\tgrade\tcarried\tdropped` and one such line
per ordered pair, formats in byte order of name; each line ends in a line
feed.

## Licence profiles (spec Version 0.29)

The loader takes an optional profile, `open`, `open+copyleft` or
`everything`. In the library it is `Engine.loadTree(.{ .packs_dir = ...,
.profile = "open" })` (`.models_dir`, `.packs_only` and `.read_licences` are
the other options; `src/main.zig`), which loads a tree as `goat-xf` does; on
the command line it is `--profile`. With no profile no licence file is read
and loading is as before. With one, before any module is loaded, the engine
reads `<packs>/../licences.toml`, then for each module file (in the order of
Version 0.23, Loading, 1) its `<models>/<m>.def.license` and its `module` and
`uses` lines, and computes each module's profile; a module the profile does
not hold is not loaded. Each pack reached (after the `--packs-only` name
checks) has its `REUSE.toml` and `uses` lines read, and a pack the profile
does not hold is skipped without being read further. A licence file that
cannot be read by the line forms of ruling 1 is `bad-licence`, as is, in the
library, a profile name that is not one of the three (a usage error, 11, on
the command line). The files are read line by line in `src/licence.zig`; no
TOML library is used.

`goat-xf licences [--json] <options>` always reads the licence files and
writes one line per loaded pack in byte order of directory name:
`<dir>\t<format>\t<licence>\t<profile>`, the profile being the pack's own
(`none` for a pack in no profile, which is listed when no profile is given).
`--json` (no value, at most once) writes `{"packs":[{"pack":...,"format":...,
"licence":...,"profile":...},...]}` instead. `zig build module-test` includes
a test of `loadTree` with each profile against
`packs/conformance/tool-fixtures/licences-*`.

Version 0.93 (a controlled pack is in no licence profile): a module file or
`pack.def` is in a profile only when it is shown public (`licence.shownPublic`:
UTF-8, no NUL, no U+FEFF, no stray carriage return, an exact `distribution
public` line and no doubtful line); otherwise its profile is `none`, and so is
that of everything that uses it. With a profile, a module file whose `module`
line gives no name (`module mx # note`, `module "mx"`) is not loaded, shown
public or not, and what uses it is `unknown-module`. A load with a profile first refuses a bad
profile name (`bad-licence`), then, on an engine that already holds a
controlled module or pack, is `distribution-refused`; both leave the engine as
it was. After those two checks the engine's limit is `public` for the rest of
its life, also when the load fails: `setMaxDistribution(.controlled)` then has
no effect, and a later load without a profile is bounded by it. A file that
reads as controlled when it is loaded is `distribution-refused`; pack files are
read once, so `src/controlled_test.zig` reaches this through the test-only
`Engine.test_load_hook`, and tests the other rulings and a controlled inner
pack (Version 0.34) under each profile.

The module listing of `loadTree`, `loadModelDir` and `loadPacksOnly` takes the
files whose names end in `.def` that are regular files or symbolic links to
one, as Version 0.23, Loading, 1 says; a directory or a link to a directory is
not a module.

## Malformed input (spec Version 0.8, rulings 35 to 40)

An input that is not a well-formed message of its wire fails with
`malformed-wire` before any line of the pack is read.

- `xml`: one document. The input may not end inside a tag, an attribute, the
  content of an element, a comment, a processing instruction or a declaration;
  a closing tag names the open element; an attribute value is quoted; after
  the root element only whitespace, comments and processing instructions
  follow. An input with no element is `malformed-wire`, as is a document type
  declaration anywhere. A numeric character reference is decimal or
  hexadecimal digits and names a character XML 1.0 allows.
- `json`, `geojson`: the input is checked against the RFC 8259 grammar by a
  validator that does not recurse, then parsed. A `\u` escape that is half of
  a surrogate pair needs its other half.
- `xml`, `json`, `geojson`: at most 64 levels of nesting.
- `bits`, `protobuf`: hex digits and whitespace (space, tab, line feed,
  carriage return) only, an even number of digits.
- `bits` with `armor sixbit`: every character is checked to be `0`..`W` or
  `` ` ``..`w` before any line is read; the message is six bits per character,
  and every read is checked against that number of bits.
- `protobuf`: the whole top-level message is parsed before any line is read;
  a submessage a `field` or `group` path walks into is parsed when it is
  reached. Field number 0, a field number above 2^29-1 and wire types 3, 4, 6
  and 7 are refused; a varint is at most ten bytes and its tenth byte at most
  1, in a packed field too.
- `tlv`: the hex text as for `bits`; the key, the length after it, the top
  set read whole and the `sum16` checksum item are checked before any line is
  read; a nested set is read whole when a line of the selected kind walks
  into it. A length is compared with the bytes left, never added to an
  offset first.
- `cbor`: the hex text as for `bits`; the whole input is read as exactly one
  well-formed data item (RFC 8949 Appendix C) before any line is read: heads
  of any length, definite and indefinite lengths, every text chunk valid
  UTF-8 on its own, no two equal keys in a map (keys compared by their core
  deterministic encodings, a hash set for a map of more than eight members),
  at most 64 levels of arrays, maps and tags. A declared length or count is
  compared with the bytes left before any memory is taken for it (an array
  element takes a byte at least, a map member two); an indefinite item that
  never ends meets the end of the input. Then the outermost tag under `tag
  <n>` and the type of the top item. Output is the core deterministic
  encoding of RFC 8949 4.2.1.
- `bits`, sequential: every read is checked against the end of the input, of
  the stated whole length and of the enclosing `length` extent, with
  arithmetic that cannot wrap.

`gt-engine-zig [<packs-dir>] --fuzz` (`zig build fuzz`, always a
`ReleaseSafe` build) runs each vector's input through `convert` cut at
prefixes and with single bytes replaced (every position of an input up to 96
bytes, 96 evenly spaced positions of a longer one), and once per format text
nested 200000 levels deep and hex of one unit repeated to 700000 digits; a
`cbor` format also takes hostile items (arrays, maps, tags and indefinite
items nested 100000 levels and more, lengths and counts up to 2^64-1 with
little after them, indefinite items with no break, arrays and strings of
300000 elements, a map of 65536 keys with and without two equal keys) and
3000 random items of every major type with heads of any length, some cut
short or with a byte changed. Each
must return a message or fail with a named kind; a panic, an error that is
not a named kind, or a `convert` that needs more than 256 MB fails the run
(the run counts what each `convert` allocates and refuses the allocation that
would pass the limit). It prints `malformed inputs: N run, 0 failed` and the
most memory one input took. Last, 200000 one-byte list items of
`conformance-seq-groups` must decode within 128 MB; the run prints the bytes
per item.

Memory per input: a decode holds the input, its parsed form, and one entity
per list item. An item is 112 bytes plus 40 bytes per key and per list it
holds (keys are kept in one array per item, not a hash table, and key names
are not copied); a list read without a known count is gathered in chunks and
moved once into an array of exactly its length. `--convert <from> <to> --peak`
prints on standard error the most bytes the decode held.

## As a module

`src/root.zig` is the module `goat_transformers` for another program: `Engine`,
`Entity`, `Value`, `KV` and `Distribution`; `Engine.loadPacksOnly` loads the
named packs of a directory and the model modules they use;
`Engine.loadTree` loads a whole tree as `goat-xf` does, with an optional
licence profile (Version 0.29, above). `zig build module-test` loads two packs
through the module and converts a message, and loads the licence fixtures
with each profile. The package manifest that `zig fetch`
reads is `build.zig.zon` at the repository root; `docs/using.md` has the
dependency line. `Entity.fields` and `Entity.lists` are arrays in insertion
order with `get(name)` and `contains(name)`; `Entity.put` and
`Entity.putList` set a key and a list.

## Model modules and distribution (spec Version 0.4)

The harness loads `model/*.def` (`core.def` first, then byte order of file
name, each module after the modules its `uses` lines name) and then the packs.
`Engine.loadModel(text)` loads one module; `Engine.loadPack(text)` checks a pack
against the modules loaded so far. `Engine.loadModelDir(dir)` loads every
module of a directory, and `Engine.loadPacksOnly(packs_dir, models_dir, names)`
loads only the named packs (directory names) and, before them, the modules
they need: `core`, the modules their `uses` lines name, and the modules those
use. `Engine.decode(format, bytes)`,
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
`error.@"malformed-wire"`, `error.@"unknown-format"`,
`error.@"transform-encode"`, `error.@"transform-decode"`,
`error.@"bad-directive"`, `error.@"bad-locator"` and every other kind of the
table of ruling 5 of 0.11), and `Engine.last_error` holds the message
`<kind>: <detail>`. `Engine.capability(from, to)` gives the capability report
(ruling 6 of 0.11) and `Engine.setMaxItems(n)` the limit on list items one
decode holds (ruling 7; 100,000 by default).

```
gt-engine-zig [<packs-dir>] [--models <dir>] [--packs-only <a>,<b>...]
              [--max-distribution public|controlled] [--max-items <n>]
              [--model-keys <format>]
              [--convert <from> <to> [--set <key>=<value>]... [--peak]] [--fuzz]
```

`--models` defaults to `<packs-dir>/../model`; `--max-distribution` defaults to
`controlled` (`Engine.setMaxDistribution`); `--max-items` defaults to 100000.
`--packs-only <a>,<b>...` loads
only those packs and the modules they need, and runs their vectors: a vector
that names a pack left out is not run and is counted in a `skipped:` line (a
format that is no directory of the packs directory is not left out: the
vector pins `unknown-format` and runs), and
the load vectors run when `conformance` is one of the named packs. It combines
with `--model-keys` and `--convert`. `--model-keys <format>` prints
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

Rulings 16 to 30 of 0.8 are followed as written: a field with `also` keys
writes the value of the earliest key the entity holds, else the default of the
earliest key that has one; an indicator bit of a `while`, `more` or `fx` group
at the end of a `length` extent reads as 0; `align` stops at the end of the
input or extent; a list may be mapped by two groups of one scope that sit in
different `if` or `opt` blocks; header and table directives are refused inside
every block; an item whose recorded kind the group does not have selects by
`requires`; `parse_int` takes an optional `-` and digits; a module is checked
in the order `missing-distribution`, `missing-source`, `distribution-refused`,
`unknown-module`, `distribution-violation`, the `derive` key checks,
`duplicate-module`. Rulings 31 to 34 likewise: a protobuf `when` whose path
prefix is not a submessage does not hold; two groups of one list are allowed
only when neither group's block encloses the other's, and decode keeps the
later group's items; a group whose first indicator bit lies at or after the
end of the extent gives an absent list.

## ASN.1 unaligned PER (spec Version 0.19)

A sequential pack with `encoding uper` takes the locators `int:<lb>:<ub>[:ext]`,
`int:<lb>:`, `int::`, `enum:<n>[:ext]`, `chars:[<lb>:<ub>]` and
`octets:[<lb>:<ub>]`, the `ext`, `choice <n> [ext]` / `alt <i>` blocks and
`group <list> size [<lb> <ub>]`. `encoding`, and every line only a UPER pack
takes, is checked after the file is read. Bounds and values are computed in
`i128` or as unsigned 64-bit differences, so no constraint can overflow.
Decode checks each length, count and index against the bits left before
reading what it counts. Extension additions and extension alternatives are
skipped. An integer of more than 8 octets is skipped and fails as its key
(`transform-decode`). In a UPER pack no `default` counts as content. Encode
pads to a whole octet and writes `00` for an empty encoding.

## The `text` wire (spec Version 0.10)

`delimiter`, `start` and `checksum` are checked against the wire and one
another after the file is read, before `missing-distribution`. Decode removes
one line terminator, checks every byte is 0x20 to 0x7E, removes the start text
and the `nmea` checksum (`malformed-wire` for each failure, before any `when`),
then splits the body into fields. Locators `<i>`, `<i>:<from>:<len>` and
`<i>+<j>`; transforms `string`, `int`, `float`, `iso8601_ms`, `iso8601_s`, `int:<w>`,
`dec:<f>[:<w>]`, `dm:<d>:<f>:<PN>`, `hms:<f>`, `hms_dmy:<f>`. A pair is absent
when either field is absent. Encode writes field lines, then `when` and
`const` over them (the earlier line's characters stand), residue at fields no
line addresses, drops trailing empty fields only `optional` lines address, and
appends the checksum in uppercase. `group <list> <i> item <n>` reads items to
the end of the record. `--convert` does not trim the input of a `text` format.

## Strict rulings (spec Version 0.11)

- XML text (ruling 1): one leading byte order mark is skipped; line ends are
  read as line feeds before anything else; a literal tab or line feed in an
  attribute value reads as a space; every `&` is a predefined entity or a
  numeric character reference, else `malformed-wire`; CDATA is character
  data as written; an element with no character data has no `#text`; an
  attribute name twice on one element is `malformed-wire`. Output escapes
  `& < > "` tab, line feed and carriage return in attribute values and
  `& < >` and carriage return in text; a character XML 1.0 cannot hold is
  `transform-encode`.
- Numbers (ruling 2): integer text is an optional `-` and digits, number text
  an optional `-`, digits, an optional fraction and exponent; both read
  `default` and context values, value tables, transform parameters, `model`
  values and the `int` and `float` transforms of `xml` and of `geojson`
  strings. `int` on a `json` number takes its exact value. The `text` wire
  keeps the grammar of Version 0.10.
- `iso8601_ms` (ruling 3): real calendar days, no leap second, the instant
  from year 0001 to 9999 on decode and on encode.
- `iso8601_s` (Version 0.26): read exactly as `iso8601_ms`, fraction
  included; written as `YYYY-MM-DDTHH:MM:SSZ`, the second that holds the
  instant (the milliseconds are dropped, not rounded), over the range of
  `iso8601_ms`. Valid on `xml`, `geojson`, `json` and `text`, with no
  parameter, on an `int` key.
- `bits` (ruling 4): a value outside its field's range is `transform-encode`;
  the parameters of `linscale`, `uscale` and `sscale` are checked at load.
- Load (ruling 5): every failure has a kind, and each line is checked in the
  order of ruling 5b; `bad-locator` for the locator forms of 5a;
  `duplicate-format` for a second pack of one format name.
- The capability report (ruling 6) and the limit on list items (ruling 7),
  counted over every list of a decode before the items are read; going over
  it wins over a field that fails: in a fixed layout by a second reading of
  the scope that counts items only, in a sequential layout by reporting a
  field that fails once the whole message has been read.

## Readings where the specification leaves a choice

- Version 0.94: from a carrier to a carrier pack (ruling 7), the check on
  the outer entity joined with the first message is made after that
  entity's context and derivations; the inner kind the first message records
  is not a kept kind there. A kind without a `run` line makes the
  `message-count` of 0.92 ruling 6 first, then checks the joined entity as
  `convert` does, a kept kind (ruling 4) included.

- Version 0.25: the benchmark's load time includes reading the files and
  the scan of the model directory (every module file is read once to learn
  its name and `uses`, only the needed ones are parsed). The packs loaded are
  the formats named by the vectors' `from` and `to`, taken as directory
  names under `--packs`. A failed run prints no result line at all.
- Version 0.25: a `Call`'s `max_items` overrides the engine's for that call
  only; `convertIn` is the thread-safe entry, `convert` stays as it was.

- Version 0.24: the set is named by `-Dwires`, a comma-separated list; a
  name that is not a wire stops the build. An empty set is allowed and has no
  codec. The load-time checks every wire's packs share (for example a
  `delimiter`, an `armor` or a gate block on a wire it does not belong to)
  stay in every build, so that a pack on a wire of the build fails as in the
  full build; only steps that a pack on one wire alone reaches are left out
  with that wire.
- Version 0.24: the reduced harness does not run a load vector one of whose
  packs has a `wire` line naming a wire the build lacks, whatever error the
  vector expects (its first `wire` line with one value decides).
- `bits`: a `const` counts toward the length a decode needs, as a `field` does.
- A key with a `default` both in the common lines and in the kind uses the
  kind's.
- A `default` value that cannot be read as its key's type is
  `key-type-mismatch` at load.
- A `derive` line refused on its own text is `bad-directive`, raised once
  the file is read and before `missing-module` (ruling 5b of 0.11, which
  also moves a key type, a key name holding `.` and `duplicate-key` there): fewer than a target, a function and one
  argument; a function the specification does not name; a parameter where the
  function takes none, or none where it takes one; a `scale` parameter that
  is not a factor, or an `offset` parameter that is not a decimal number; an
  argument count the function does not take. An `offset` parameter that is a
  decimal number and not an integer, on integer keys, is refused with the key
  checks.
- An integer `offset` that overflows leaves the target absent.
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
- Version 0.11, where no vector decides:
  - The argument counts ruling 5e does not list are a line check (step 3):
    `field` takes at least three arguments, `when`, `const`, `default` and
    `typemap` two, `map` three, `group` at least two, `presence` two, `also`
    one or three, `requires`, `if` and `length` at least one, `end`, `opt`,
    `chain` and `fx` none.
  - A failure after the file is read that was found while a line was read
    (a cause not in steps 1 to 10 of ruling 5b) is reported first among the
    checks after the file, after `missing-format`, `missing-version` and
    `missing-wire`; the first one in the file is the error.
- Malformed input, where no vector decides:
  - A protobuf `when` whose path meets a length-delimited field whose bytes
    do not parse as a message does not hold (ruling 31 of 0.8); on a `field`
    or `group` path the same bytes are `malformed-wire` (ruling 38).
  - `xml`: a name may not hold `<`, `&` or a quote; `&#X…;` with a capital
    `X` is `malformed-wire`.
  - A JSON input that is not UTF-8 is `malformed-wire`.
- Sequential layouts, where no vector decides:
  - For rulings 23 and 33 of 0.8 a group's block is the nearest `if` or
    `opt` block around it within its scope; `chain` and `length` blocks do
    not separate two groups. A scope is the common lines plus one kind, or
    one group body likewise; two kinds may each map the list.
  - A header or table directive inside a block is `bad-directive` before its
    own arguments are looked at.
  - The recorded kind of a message that names this format and a kind the pack
    does not have is `no-kind` (ruling 24 of 0.5); ruling 26 of 0.8 is
    applied to items.
  - While presence bits are computed, an item that no kind of a group takes
    is searched in the group's common lines only; the error is raised when
    the group is written.
  - A block has content when a line in it, at any depth of `if`, `opt`,
    `chain` and `length` blocks, would write a present key or a non-empty
    list.
  - A common `when` inside a `length` extent that has ended does not hold.
  - A module whose `uses` names itself needs no other module loaded.
