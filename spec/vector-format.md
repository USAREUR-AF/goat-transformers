# Vector format

Status: Written. Version 0.1.

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
| `expect_error` | in place of `expect` | the error kind `convert(from, to, input)` must fail with (`no-kind`, `missing-root`, `malformed-wire`, `transform-decode`, `transform-encode`, and with `context` `undeclared-key`, `key-type-mismatch`) |
| `model` | optional | map of shared-model key to expected value in string form, checked against `decode(from, input)`; the key `"@kind"` holds the kind name the decode must select; `"@complete": true` moves the checks to the completed entity (below); `"<list>.#"` and `"<list>[<i>].<key>"` check a list, and `"<list>[<i>].@kind"` the kind of an item (Lists in `model`, below) |
| `context` | optional | map of shared-model key to value in string form: the caller-supplied keys of `convert(from, to, input, context)` (`spec/engine-spec.md`, Version 0.6). Each value is read as its key's declared type. A `context` member that is present is a context given, also when it is `{}` (ruling 10 of 0.6) |

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
3. If `model` holds `"@complete": true`, the checks of step 2 run on the entity
   as `convert` hands it to the encoder: `decode(from, input)`, then the absent
   keys filled from `context`, then the derivations applied (`complete`). This
   is done whether or not `from == to`. Float values then compare within 1e-9
   relative: `|got - want| < 1e-9 * max(|got|, |want|)`, or equal. `"@complete"`
   is not a model key. A vector states a derived float this way and keeps it
   out of `expect`, unless the value derives exactly.

A `from == to` vector checks that decode then encode returns the canonical form
of the input, which proves residue carries unmapped fields.

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
| `pack` | yes | one `pack.def` text, loaded after the modules |
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

The engine starts empty for each load vector. It loads the modules in order and
then the pack, stopping at the first failure. With `expect_error` present the
vector passes when that first failure is of the named kind; without it the
vector passes when nothing fails.
