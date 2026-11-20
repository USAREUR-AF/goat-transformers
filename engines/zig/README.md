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
`group … count @<name>`, `group … last`, spec Version 0.21), and converts
between formats via the shared model.

## Build and run the conformance harness

```
zig build run          # loads ../../packs, runs every vector
zig build test         # the same, then the malformed-input run below
zig build fuzz         # the malformed-input run alone
zig build-exe src/main.zig && ./main ../../packs
```

Prints `vectors: N/N passed` (conversion vectors), `load vectors: N/N passed`
(`packs/conformance/load-vectors/`) and `capability vectors: N/N passed`
(`packs/conformance/capability-vectors/`), after one `FAIL <pack>/<vector
file>: <why>` line per failing vector; non-zero exit on any failure. A
vector's `max_items` sets the limit on list items for that vector; a `model`
value its grammar refuses makes the vector fail as invalid. Stdlib only.

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
- `bits`, sequential: every read is checked against the end of the input, of
  the stated whole length and of the enclosing `length` extent, with
  arithmetic that cannot wrap.

`gt-engine-zig [<packs-dir>] --fuzz` (`zig build fuzz`, always a
`ReleaseSafe` build) runs each vector's input through `convert` cut at
prefixes and with single bytes replaced (every position of an input up to 96
bytes, 96 evenly spaced positions of a longer one), and once per format text
nested 200000 levels deep and hex of one unit repeated to 700000 digits. Each
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
named packs of a directory and the model modules they use. `zig build
module-test` loads two packs through the module and converts a message. The package manifest that `zig fetch`
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
`<i>+<j>`; transforms `string`, `int`, `float`, `iso8601_ms`, `int:<w>`,
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
