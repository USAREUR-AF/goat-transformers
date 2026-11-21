# Vector format

Status: Written. Version 0.11.

A vector is one conformance case. Every engine runs every vector of every loaded
pack and must reproduce it. Vectors are the single definition of correct
behaviour; engines are written from them and the engine specification, not from
each other.

## File

One JSON object per file under `packs/<format>/vectors/*.json`, where `<format>`
is the pack that owns the input. Fields:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | unique within the pack |
| `from` | yes | source format name |
| `to` | yes | target format name; equal to `from` for a round-trip |
| `input` | yes | source message as a UTF-8 string; for a `bits` or `protobuf` format, hex text |
| `expect` | unless `expect_error` | expected canonical target message as a UTF-8 string; for a `bits` or `protobuf` format, lowercase hex text |
| `expect_error` | in place of `expect` | the error kind `convert(from, to, input)` must fail with (`no-kind`, `missing-root`, `malformed-wire`, `transform-decode`, `transform-encode`, `unknown-format`, and with `context` `undeclared-key`, `key-type-mismatch`; Version 0.34: `bad-directive` and `distribution-violation` raised where decode or encode reaches an `inner` line) |
| `model` | optional | map of shared-model key to expected value in string form, checked against `decode(from, input)`; the key `"@kind"` holds the kind name the decode must select; `"@complete": true` moves the checks to the completed entity (below); `"<list>.#"` and `"<list>[<i>].<key>"` check a list, and `"<list>[<i>].@kind"` the kind of an item (Lists in `model`, below); `"@absent"` holds an array of keys the entity must not have (Version 0.9); `"@inner_kind"` holds the kind name `Entity.inner_kind` must hold, and `"@absent"` may list `"@inner_kind"` (Version 0.34) |
| `context` | optional | map of shared-model key to value in string form: the caller-supplied keys of `convert(from, to, input, context)` (`spec/engine-spec.md`, Version 0.6). Each value is read as its key's declared type. A `context` member that is present is a context given, also when it is `{}` (ruling 10 of 0.6) |
| `max_items` | optional | Version 0.11: an integer of 0 or more, the limit on list items the engine is set to for this vector (`spec/engine-spec.md`, ruling 7 of 0.11). Absent: the default, 100,000 |
| `source` | optional | text for people: where the input and the expected output come from (a published message, a generator and what it reads, `synthetic`). No engine reads it |
| `reference` | optional | text for people: the sections of the format's specification, or the derivation, the expected output rests on. No engine reads it |

## What the engine checks per vector

1. `convert(from, to, input)` equals `expect` after canonicalisation
   (`spec/engine-spec.md`, Canonicalisation). With `context` present the call
   is `convert(from, to, input, context)`.
   With `expect_error`, `convert` must instead fail, and the error message
   must begin with that kind and a colon. A `context` key that no loaded module
   declares fails with `undeclared-key`, and a value that cannot be read as the
   key's type with `key-type-mismatch`. The context is read and checked after
   the decode, so a vector whose input does not decode fails with the decode's
   error whatever its `context` holds.
2. If `model` is present, `decode(from, input)` has each listed key equal to the
   listed value. Float values compare within 1e-9. `"@kind"` is not a model
   key: its value must equal the kind name in `Entity.kind`.
   `"@absent"` (Version 0.9) is not a model key either: its value is an array
   of model keys, and each must be absent from the entity.
3. If `model` holds `"@complete": true`, the checks of step 2 run on the entity
   as `convert` hands it to the encoder: `decode(from, input)`, then the absent
   keys filled from `context`, then the derivations applied (`complete`). This
   is done whether or not `from == to`. Float values then compare within 1e-9
   relative: `|got - want| < 1e-9 * max(|got|, |want|)`, or within `1e-7`
   absolute (Version 0.16), or equal. `"@complete"`
   is not a model key. A vector states a derived float this way and keeps it
   out of `expect`, unless the value derives exactly. `"@kind"` and
   `"<list>[<i>].@kind"` are not moved: with or without `"@complete"`, and
   whether or not `from == to`, they name the kind that `decode(from, input)`
   selected. Clearing the kind for another format is part of `convert`, not of
   what a vector checks (Version 0.30, ruling 34).

A `from == to` vector checks that decode then encode returns the canonical form
of the input, which proves residue carries unmapped fields.

## Malformed input

Status: Written. An engine reads messages from untrusted senders. An input
that is not a well-formed message of its wire makes `convert` and `decode`
fail with `malformed-wire`, whatever the lines of the pack map. No input makes
an engine crash, read outside the input, or use stack or memory without bound.
The packs `conformance-malformed-*` pin the cases below (`spec/engine-spec.md`,
"Malformed input (0.8)", rulings 35 to 40); each vector there has
`"expect_error": "malformed-wire"`, except the well-formed messages that mark
the edge of a rule: the message each pack starts with, nesting exactly at the
depth limit, hex text with the four whitespace characters, a ten-byte varint
whose last byte is 1, a packed list, a surrogate pair, and a decimal and a
hexadecimal character reference.

| Wire | `malformed-wire` when |
|---|---|
| `xml` | the input is not one well-formed document: it is empty; it ends inside a tag, an attribute name, an attribute value, the content of an element or the XML declaration; a closing tag does not name the open element; an attribute value has no quotes; anything other than whitespace, comments and processing instructions follows the root element |
| `xml` | a document type declaration stands anywhere in the input: before the root element, after it or inside it. No engine declares, expands or fetches an entity other than the five predefined ones and numeric character references |
| `xml` | a numeric character reference holds anything but decimal digits, or `x` and hexadecimal digits (a sign is refused: `&#+65;`), or names a character XML 1.0 does not allow (`&#0;`, `&#x110000;`). `&#65;` and `&#x41;` are the character `A` |
| `json`, `geojson` | the input is not one JSON value (RFC 8259) followed only by whitespace: it ends inside a string, an escape, a number, a literal, an array or an object, or after a colon or a comma; a second value follows the first; a number has a leading zero, a leading `+` or a bare `.`; a string holds an unknown escape or a raw control character |
| `json`, `geojson` | a `\u` escape is half of a surrogate pair without its other half: a high surrogate not followed by a low surrogate escape, or a low surrogate with no high surrogate before it. A pair is one character |
| `xml`, `json`, `geojson` | the nesting is deeper than 64 levels. On `xml` a level is an element and the root element is level 1. On `json` and `geojson` a level is an array or an object and the outermost one is level 1. A message of exactly 64 levels converts |
| `protobuf` | a varint ends before its last byte, is longer than ten bytes, or is ten bytes with a last byte greater than 1 (bits above bit 63); a length-delimited field states more bytes than are left in its message; a fixed64 or fixed32 field is cut short; a varint inside a packed field is cut short; the field number is 0 or above 2^29-1; the wire type is 3, 4, 6 or 7. This holds for a field no line maps, in a pack with or without kinds, and inside a submessage a path of the pack walks into, where it is `malformed-wire` and not a field failure |
| `bits`, `protobuf`, `cbor` | the hex text has an odd number of digits, or holds a character that is neither a hex digit nor whitespace. Whitespace is space, tab, line feed and carriage return only: a form feed, a vertical tab, U+00A0 and a sign are refused |
| `bits` | the input is shorter than the message (`spec/engine-spec.md`, Version 0.5) |

## Lists in `model`

Status: Written. Version 0.7. A `model` key may name a list of the decoded
entity (`spec/engine-spec.md`, Version 0.7) in two ways. Neither is a model
key; a model key never contains `[` and never ends in `.#`.

| Key | Value | Passes when |
|---|---|---|
| `"<list>.#"` | a count in string form, or `"absent"` | the entity has the list with that many items (`"0"`: present and empty); `"absent"`: the entity does not have the list |
| `"<list>[<i>].<key>"` | expected value in string form | item `<i>` (from 0) of the list has `<key>` equal to the value, compared as a top-level key is |
| `"<list>[<i>].@kind"` | a kind name | Version 0.8: item `<i>` recorded that kind (`Item.kind`) when it was decoded |

`<key>` after `[<i>].` is read the same way inside the item, so nested lists
take further steps: `"<list>[<i>].<inner>.#"` is the number of items of the
list `<inner>` of that item, and `"<list>[<i>].<inner>[<j>].<key>"` a value of
one of them. `<list>` and `<key>` are written as in a pack, with their module:
`"probe.items[0].probe.subs[1].probe.val"`.

`"@kind"` after `[<i>].` is read as `"@kind"` at the top level is, against the
item: it is not a model key, and it fails for an item that recorded no kind.
It takes further steps like a key: `"<list>[<i>].<inner>[<j>].@kind"`.

The check fails when the list is absent, when it has no item `<i>`, or when
the item does not hold `<key>`. With `"@complete": true` the checks still run
on the entity's lists as decoded: derivations and context do not reach into
items.

```json
{
  "name": "several-items",
  "from": "conformance-groups-json",
  "to": "conformance-groups-json",
  "input": "{\"id\":\"u1\",\"title\":\"T\",\"items\":[{\"name\":\"aa\",\"n\":2,\"kind\":\"item\",\"subs\":[{\"t\":\"x\",\"v\":1}]}],\"names\":[]}",
  "expect": "{\"id\":\"u1\",\"title\":\"T\",\"items\":[{\"name\":\"aa\",\"n\":2,\"kind\":\"item\",\"subs\":[{\"t\":\"x\",\"v\":1}]}],\"names\":[]}",
  "model": {
    "probe.items.#": "1",
    "probe.items[0].probe.label": "aa",
    "probe.items[0].probe.subs.#": "1",
    "probe.items[0].probe.subs[0].probe.val": "1",
    "probe.names.#": "0",
    "probe.nums.#": "absent"
  }
}
```

## Example (CoT XML to GeoJSON)

```json
{
  "name": "track-to-geojson",
  "from": "cot-xml",
  "to": "geojson",
  "input": "<event uid=\"J-01334\" type=\"a-f-G-U-C\" time=\"2021-02-27T20:00:00.000Z\" how=\"m-g\"><point lat=\"30.0090027\" lon=\"-85.9578182\" hae=\"-42.6\" ce=\"45.3\" le=\"99.5\"/><detail><contact callsign=\"GATOR\"/></detail></event>",
  "expect": "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[-85.9578182,30.0090027,-42.6]},\"properties\":{\"type\":\"a-f-G-U-C\",\"time_ms\":1614456000000,\"how\":\"m-g\",\"ce\":45.3,\"le\":99.5,\"callsign\":\"GATOR\"},\"id\":\"J-01334\"}",
  "model": { "uid": "J-01334", "lat": "30.0090027", "time_ms": "1614456000000" }
}
```

## Load vectors

Status: Written. Version 0.4. A load vector pins what an engine accepts and
refuses at load (`spec/engine-spec.md`, Version 0.4). One JSON object per file
under `packs/conformance/load-vectors/*.json`:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | unique within the directory |
| `models` | yes | array of model module texts, loaded in order |
| `pack` | unless `packs` | one `pack.def` text, loaded after the modules |
| `packs` | in place of `pack` | Version 0.11: an array of `pack.def` texts, loaded in order after the modules into the one engine |
| `max_distribution` | no | `public` or `controlled`; the engine's distribution limit, set before loading |
| `expect_error` | no | the error kind the load must fail with; absent means every load must succeed |

Error kinds a load vector names: those of Version 0.4, and from Version 0.5
`duplicate-kind` (a kind name declared twice) and `bad-directive` (`requires`
before the first `kind`, `bit_order` on a wire other than `bits`, a bit length
its transform does not allow). `duplicate-field` was withdrawn in Version 0.6:
the vectors that named it now load. Version 0.6 adds causes of `bad-directive`
(`via` naming a table with no `map` line, a field option on a wire or transform
it does not apply to, a `derive` line whose function, argument count, keys or
types do not fit), of `undeclared-key` (a `default` for a key no module
declares) and of `key-type-mismatch` (a key whose type differs from the model
side of its table). A `derive` line is part of a module text in `models`.

Version 0.7 adds, for groups: `bad-directive` (a `group` with no `end`, an
`end` with no open group, `when`, `requires`, `root` or `kind` inside a group,
`count` on a wire other than `bits`, a `bits` group with no `count`, a `field`,
`when` or `const` at or beyond the start of a group counted by a locator, a
list mapped by two groups of one scope), `undeclared-key` (a `group` naming a
list no module declares), `key-type-mismatch` (a `group` naming a scalar key, a
`field` naming a list) and `duplicate-key` (a `list` and a `key`, or two lists,
of one name in a module). A `list` line is part of a module text in `models`.

The vectors that pin rulings 11 to 21 of Version 0.7 add: `bad-directive` (a
`protobuf` group body that mixes `.` with paths, a `const` or a nested group's
count locator beyond `item <bits>`, a fixed-count `bits` group whose items
reach a later group counted by a locator, a directive inside a group other
than `field`, `const`, `default`, `group` and `end`, `item` on a wire other
than `bits`, a list as a `derive` argument or target, a `field` whose locator
passes through a `group`'s path) and `key-type-mismatch` (a `default` naming a
list). A conversion vector with a `context` key that names a list fails with
`key-type-mismatch`.

Version 0.8 adds, for `layout sequential`: `bad-directive` (`word_bytes` or
the field option `optional` in a sequential pack; an `if`, `opt`, `chain`,
`length` or `group` with no `end`, and an `end` with no open block; an `if`
naming a presence that is not visible where it stands, or a bit beyond the
size of the presence; a `<word>:<pos>:<len>` locator in a sequential pack;
`pad`, `align`, `presence`, `if`, `opt`, `chain`, `fx`, `length`, a field with
a bit length for a locator, or a group with `while` in a fixed-layout pack; a
`when` in a body with no `kind`; a `when` or `const` value that does not fit
its bits) and `duplicate-kind` (a kind name declared twice in a group body).
The checks of earlier versions apply to sequential lines unchanged
(`undeclared-key`, `key-type-mismatch`, a bit length its transform does not
allow, `via` naming a table with no `map` line).

The rulings for 0.8 and its model additions add: `bad-directive` (a `when`
after another line of its kind or inside a block, `length ... bits whole`, a
presence name declared twice in one block, `also` anywhere but directly after
a `field` line of a sequential pack, a presence or `const` of more than 64
bits, `layout sequential` on a wire other than `bits`, a `derive` argument of
a module the module does not use, a `derive` target of another module, a
`derive` line whose types do not fit `day_seconds`, `any`, `not`, `parse_int`
or `text_of`), `unknown-module` (a module whose `uses` names a module not
loaded) and `distribution-violation` (a public module that uses a controlled
one). A kind name may repeat across group bodies; within one body it is
`duplicate-kind`. A `uses` line is part of a module text in `models`.

The vectors that pin rulings 16 to 30 of Version 0.8 add: `bad-directive` (a
list mapped by two groups of one sequential scope that are not in different
`if` or `opt` blocks; a header or table directive inside an `if`, `opt`,
`chain`, `length` or `group` block, of either layout; a presence name declared
in two parts of one chain, or named after the chain that declares it; a
`derive` target of a used module; a field on the `xml` wire that addresses the
element of a group's own path) and, for a module, the order of its checks:
`missing-distribution`, `missing-source`, `distribution-refused`,
`unknown-module`, `distribution-violation`, the `derive` checks,
`duplicate-module`. A `when` may follow the `requires` and `default` lines of
its kind, and a field at exactly a group's path loads on `json`, `geojson` and
`protobuf`.

Version 0.11 (rulings 2, 4 and 5) names the load failures that had no kind.
Load vectors 339 to 462 pin them: `unknown-directive` (in a pack and in a
module), `unknown-transform`, `unknown-wire`, `bad-locator` (per wire),
`missing-format`, `missing-version`, `missing-wire`, `missing-module`,
`missing-root` at load, `unterminated-quote` and `duplicate-format` (with
`packs`); and they add causes of `bad-directive` (a transform on a wire it is
not valid for, the wrong number of arguments, a `distribution` value or key
type the grammar does not have, a `.` in a key name, a `format`, `wire` or
`module` line given twice, a fixed-layout `bits` pack with no `word_bytes`,
`linscale`, `uscale` and `sscale` parameters that are not valid, a bit length
above 64 on an integer or scaled transform, a sign or other text where an
unsigned decimal integer stands, a factor or range that reads as zero) and
of `key-type-mismatch` (a `default` value the grammar of its type refuses).
They also pin a directive of the other file type as `unknown-directive`, the
lines that must follow the `wire` line, and which checks are line checks. The load vectors of Version
0.9 (numbered 315 to 338) and of Version 0.10 (named `wire-text-*`) keep their
expected errors: on the `text` wire a locator that is not valid stays
`bad-directive` (`spec/engine-spec.md`, ruling 5a of 0.11).

A conversion vector whose `from` or `to` names a format that is not a
directory under `packs/` pins `unknown-format`. Three such vectors stand in
`packs/conformance/vectors/`; a runner runs them with the packs it has loaded
and does not skip a vector because one of its formats is not loaded.

Version 0.11 (ruling 2c) states how a `model` value is read: a member named by
a model key or an item path `<list>[<i>].<key>` by the grammar of that key's
declared type, `"<list>.#"` as an unsigned decimal integer or `absent`; the
`@` members are not numbers. A vector whose `model` holds a value its grammar
refuses is invalid, and an invalid vector fails the run.

The engine starts empty for each load vector. It loads the modules in order and
then the pack, or each pack of `packs` in order, stopping at the first
failure. With `expect_error` present the vector passes when that first failure
is of the named kind; without it the vector passes when nothing fails.

## Capability vectors

Status: Written. Version 0.11. A capability vector pins the capability report
of one ordered pair of formats (`spec/engine-spec.md`, ruling 6 of 0.11). One
JSON object per file under `packs/conformance/capability-vectors/*.json`:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | unique within the directory |
| `from` | yes | source format name |
| `to` | yes | target format name; may equal `from` |
| `grade` | yes | `full`, `partial` or `none` |
| `carried` | yes | array of entries, in the order of `model_keys(from)` |
| `dropped` | yes | array of entries, in the order of `model_keys(from)` |

The engine loads the model modules and the two packs (and, Version 0.34, the
packs their `inner` lines name), calls
`capability(from, to)`, and passes when the grade and both arrays are equal to
the vector's, entry for entry and in order. The packs `conformance-cap-*` are
the formats these vectors name; they have no conversion vectors.

## Tool vectors

Status: Written. Version 0.23. A tool vector pins one run of an engine's
command-line tool (`spec/engine-spec.md`, Version 0.23). One JSON object per
file under `packs/conformance/tool-vectors/*.json`:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | unique within the directory |
| `args` | yes | array of strings: the arguments after the program, the subcommand first; may be empty |
| `stdin_hex` | no | the bytes on standard input, as lower-case hex; absent means no bytes |
| `exit` | yes | `0`, `1` or `2` |
| `stdout_text` | with `exit` 0, unless `stdout_any` | the UTF-8 text standard output must hold, byte for byte |
| `stdout_any` | with `exit` 0, in place of `stdout_text` | `true`: standard output must not be empty, and is not compared (the text of `help`) |
| `error_kind` | with `exit` 1, optional | the kind the first line of standard error begins with, followed by `:`. Absent: the failure has no kind in the contract (an unreadable `--packs`), and standard error must not be empty |

Every vector that loads packs passes `--packs {packs}`: the default of
`--packs` is each engine's own. In `args`, the text `{packs}` stands for the
absolute path of the repository's `packs/` directory and `{models}` for that
of its `model/` directory; the runner replaces each occurrence before it
starts the tool. Nothing else in a string is replaced. The runner starts the
tool in the repository's root directory.

The runner starts the tool with the arguments, writes the input and closes
standard input (a write the tool refuses because it exited without reading is
not a failure), waits, and checks:

- the exit status equals `exit`;
- with `exit` 0: standard output equals `stdout_text` byte for byte, or with
  `stdout_any` is not empty; standard error is empty;
- with `exit` 1: standard output is empty; standard error is not; and with
  `error_kind`, the first line of standard error begins with `error_kind`
  followed by `:`;
- with `exit` 2: standard output is empty and standard error is not.

A vector with a key the table does not list, with output keys that do not fit
its `exit`, or with both `stdout_text` and `stdout_any`, is invalid, and an
invalid vector fails the run.

`python3 -I tools/tool-vectors.py -- <command> [<arg>...]` runs every tool
vector with `<command> <arg>...` as the program and prints one
`FAIL <file>: <why>` line per failing vector and `tool vectors: N/N passed`
last; it exits 1 on any failure.
