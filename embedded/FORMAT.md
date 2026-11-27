# Compiled pack format (`.gtp`)

Status: Written and Built. Format version 4. Written by `tools/gen/packc.py`,
read by `embedded/gt-core`.

A `.gtp` blob holds one plan: a source format, a target format, or both,
already cut down to the message kinds and model keys the conversion uses. The
device engine reads the blob in place. It never parses pack text, never looks
a key up by name and never allocates.

A blob is build output. It is produced from `model/` and `packs/` each time
and is not kept in the repository.

## Layout

All integers are little-endian. Every reference inside the blob is an index
into a table or an offset inside a section, so the blob can sit at any
address, in flash or in RAM, with no relocation and no alignment requirement.

```
offset  size  field
0       4     magic "GTP1"
4       2     format version (4)
6       2     flags: bit 0 = the blob holds names (sections 12 and 13)
8       4     total length in bytes
12      2     number of sections
14      2     reserved, 0
16      12*n  section directory
...           sections, each padded with zero bytes to a multiple of 4
```

One directory entry:

```
0   2   section id
2   2   size of one entry in bytes
4   4   offset of the section from the start of the blob
8   4   number of entries
```

A reader skips a section id it does not know. A reader refuses a known
section whose entry size is not the one listed below, and a blob whose format
version is not its own: a version 1 reader would read the sentinels of a
version 2 blob as values.

Version 2 adds the sentinels of the `absent` field option (engine-spec 0.9)
to the FIELD operation: byte 3, reserved and 0 in version 1, is the number of
sentinels, and the sentinels follow the field's scale in the pool.

Version 3 adds six-bit armor (engine-spec 0.14): bit 2 of a format's flags,
0 in version 2, marks `armor sixbit`, and transform 8 is `sixbit`. A version 2
reader would ignore the flag and read armored text as bytes, so the version
changed. Nothing else changed.

Version 4 adds the GATE operation (gate blocks on a fixed layout,
engine-spec 0.17). A version 3 reader steps over an operation it does not know
as one operation, so it would read the lines inside a gate block as lines of
the scope; the version changed so that it refuses the blob instead.

| Id | Section | Entry | Holds |
|---|---|---|---|
| 1 | formats | 16 | one entry per compiled format |
| 2 | ops | 16 | the operation table |
| 3 | pool | 8 | 64-bit words: constants, scales, default values, table entries |
| 4 | conds | 4 | the conditions of `if` lines |
| 5 | tables | 8 | value tables (`map` lines, the typemap) |
| 6 | keys | 4 | the key table |
| 7 | derives | 8 | the derivations the plan uses |
| 8 | args | 2 | key ids: the arguments of the derivations |
| 9 | plan | 12 | one entry: which formats, and how they relate |
| 10 | bytes | 1 | text of table entries and defaults |
| 11 | carry | 12 | the conversion plan, one row per carried key |
| 12 | name-index | 4 | optional: offset of each name in section 13 |
| 13 | names | 1 | optional: key, kind and format names |

## Keys

Each model key the plan uses becomes its index in the key table. The device
handles keys only as these ids. A key that neither side of the conversion can
use has no id and does not appear in the blob.

```
0  1  type: 0 int, 1 float, 2 string, 3 list
1  1  flags: bit 0 = the caller may supply it as context
             bit 1 = the plan uses its value
2  2  name id (section 12), or 0xFFFF
```

Names are kept only when the plan is compiled with `--names`. The generated
Rust source carries the ids of the context keys as constants, so firmware
needs no names.

## Formats

```
0   1  flags: bit 0 = bit order msb, bit 1 = layout sequential, bit 2 = `armor sixbit`
1   1  reserved
2   2  word_bytes (fixed layout)
4   4  index of the format's BODY operation
8   2  name id, or 0xFFFF
10  2  number of presence fields the format declares
12  4  reserved
```

## Operations

A format is a tree of operations stored flat, parent before children. An
operation that has children states how many operations follow it inside it,
so a reader steps over a whole block with one addition.

```
0   1  op
1   1  xf: transform, repeat form, count form or value type, by op
2   1  flags, by op
3   1  FIELD: the number of sentinels (0 to 255); other ops: reserved, 0
4   2  key: a key id, a list id, a presence id or a kind number, by op
6   2  len: a bit length or a count, by op
8   4  a: a bit offset (fixed layout), or the number of nested operations
12  2  b: an index into the pool or the conds
14  2  c: a value table, or a name id; 0xFFFF = none
```

| Op | Name | Fields |
|---|---|---|
| 1 | BODY | `a` nested operations; fixed layout: `b` → pool (reach, decode need, encode need) in bits |
| 2 | KIND | `a` nested operations; `key` = the kind's number: in the message body its position in the pack; in a group body one number per kind name across all groups of that list, from 0; flags bit 0 = not compiled in; `b` as BODY; `c` name |
| 3 | WHEN | `len` bits equal pool[`b`]; fixed layout: at bit `a` |
| 4 | REQ | a `requires` key in `key`; flags bit 0 = a list |
| 5 | DEFAULT | key `key` defaults to pool[`b`], of type `xf` |
| 6 | FIELD | key `key`, `len` bits, transform `xf`, scale at pool[`b`], table `c`; fixed layout: at bit `a`; flags 1 `swap`, 2 `trim`, 4 `optional`; byte 3 sentinels (below) |
| 7 | ALSO | another key on the bits of the FIELD before it, table `c` |
| 8 | CONST | write pool[`b`] in `len` bits; fixed layout: at bit `a` |
| 9 | PAD | `a` bits |
| 10 | ALIGN | to a multiple of `a` bits |
| 11 | PRESENCE | presence `key`; `len` bits, 0 = `fx` octets; pool[`b`] = mask of the bits some `if` names |
| 12 | IF | `a` nested operations; `len` conditions from conds[`b`] |
| 13 | OPT | `a` nested operations after one presence bit |
| 14 | CHAIN | `a` nested operations: `len` PART blocks; flags bit 0 = the chain ends with an `fx` line |
| 15 | PART | `a` nested operations: the lines between two `fx` lines |
| 16 | LENGTH | `len`-bit length of the `a` nested operations; flags bit 0 = counted in bits; pool[`b`] = `plus` |
| 17 | WHOLE | `len`-bit length of the whole message; pool[`b`] = `plus` |
| 18 | GROUP_SEQ | list `key`; `xf` 0 `count` (`len` bits), 1 `while`, 2 `more`, 3 `fx`; the next operation is the item BODY; flags bit 0 = read and drop |
| 19 | GROUP_FIX | list `key`, first item at bit `a`; pool[`b`] = item bits; `xf` 0: pool[`b`+1] items, `xf` 1: a `len`-bit count at bit pool[`b`+1]; then the item BODY |
| 20 | GATE | `a` nested operations: a gate block (spec 0.17, below); `key` = its number in its scope; `len` gate bits; `c` listed values; flags 1 `!`, 2 = step 3 of Encode gives the gate a value; pool[`b`] = the gate's bit offset, pool[`b`+1..`b`+3] = (reach, decode need, encode need) of the block's own lines, pool[`b`+4] = the gate value, then the `c` values |

Transforms (`xf` of FIELD): 0 `uint`, 1 `twos`, 2 `linscale`, 3 `uscale`,
4 `sscale`, 5 `f32`, 6 `f64`, 7 `ascii`, 8 `sixbit` (spec 0.14); the value
transforms of spec 0.15: 9 `uiscale`, 10 `siscale`, 11 `smag`,
12 `smscale`, 13 `f32scale`, 14 `f64scale`, 15 `chars:icao6`, 16
`chars:ais6`, 17 `chars:ascii7`, 18 `octal`. A transform number the engine
does not know is `bad-plan`, so the numbers 9 to 18 needed no version of
their own; version 3 is the one six-bit armor set.

### Six-bit armor

A format with flag bit 2 (`armor sixbit`, engine-spec 0.14; the compiler
requires `bit_order msb` with it) reads and writes its message as armored
text, one byte a character.

- Decode: every character is checked first; one outside `0` to `W` and
  `` ` `` to `w` is `malformed-wire`. The message is 6 bits a character, most
  significant first, read in place: the engine never copies it. In the fixed
  layout the input must reach every bit of the lines in force that are not
  `optional` (the decode need of the BODY and KIND extents), not whole words;
  a group's items are checked as they are read. In the sequential layout the
  end of the message is the last bit of the last character.
- Encode: the message is laid out as for bytes, then its first `L` bits,
  with zero bits to a multiple of 6, are written over the output buffer as
  characters, the last character first, so no second buffer is needed. In
  the sequential layout `L` is the cursor after the last line. In the fixed
  layout `L` is the furthest of: the decode need of the BODY and of the
  selected KIND (every line but the `optional` fields, the lines the plan
  left out included), the end of the groups' items and count fields, and each
  `optional` field that writes a value, a default or a sentinel.
- `sixbit` (FIELD transform 8, `len` a multiple of 6 from 6 to 1530): decode
  gives a text whose characters are read from the input when used (each six
  bits, in the format's bit order: 0 to 31 as `@` to `_`, 32 to 63 as space
  to `?`), less the trailing `@` (with `trim`, `@` and space). Encode writes
  each character's six bits, padded with `@`; a character outside 0x20 to
  0x5F, or a text longer than the field, is `transform-encode`. It is valid
  with either armor.

### Value transforms (spec 0.15)

- `uiscale` and `siscale` take three pool words at `b`, as integers: the
  factor's numerator (signed) and denominator in lowest terms, and the
  offset. Decode is `round(v * num / den) + offset` and encode
  `round((x - offset) * den / num)`, exact in 128-bit integers, rounding half
  away from zero; a decoded value outside 64 bits is `transform-decode`, an
  encoded one outside the field `transform-encode`.
- `smscale`, `f32scale` and `f64scale` take the three doubles of `sscale`
  and its arithmetic (ruling 1 of 0.5); a result that is not finite fails.
  `smag` and `smscale` put the sign in the field's highest bit.
- `chars:<set>` and `octal` give text read from the input when used, never
  copied, as `ascii` does. A sentinel of `absent` follows the three words
  of a scaled transform, as for `sscale`.

Order inside a block. A BODY holds its DEFAULT operations, then its common
lines, then its KIND blocks. A KIND holds its WHEN, REQ and DEFAULT
operations, then its lines. In a fixed-layout scope the FIELD and GATE
operations come first and together, in line order, then WHEN, CONST and
GROUP_FIX, because the engine passes over such a scope once for each kind of
line. A GATE holds its DEFAULT operations, then its FIELD and nested GATE
operations in line order, then its CONST operations. In a sequential scope the
lines keep their file order, because the order is the layout.

### Gate blocks (spec 0.17)

A gate block is a GATE operation in a fixed-layout scope: the common lines and
a kind of the message, or a group's item, where its offset is item-relative.
The blocks of a scope are numbered from 0 in line order, depth first: the
common lines first, each kind after them. A scope holds at most 256 blocks
(`too-many-gates` otherwise). The extents of BODY and KIND hold the lines
outside any block only; a block's extent holds its own lines, the lines the
plan left out included, and not those of the blocks nested in it.

- Decode: the gate's bits are read as a WHEN reads them; the block holds when
  they equal one of the values (with `!`, none of them), and a gate any of
  whose bits lies beyond the input does not hold. A block that holds is read
  as its lines, its nested blocks evaluated in turn, and its decode need
  counts toward the length; a block that does not hold sets no key.
- Encode, for each scope: the lines outside any block are written first, as
  without blocks (step 2). In line order, depth first, a block that is open
  (one of its fields, or of the blocks nested in it, maps a key the entity or
  item holds) and has a gate value gets it when none of its gate bits is
  written: by a line outside any block with a present key, a CONST, a WHEN, a
  group count, or the gate value of an earlier block (step 3). Each block is
  then evaluated on those bits, a nested one only when the block enclosing it
  holds (step 4). The scope is written again with the lines of the held
  blocks: sentinels, then fields later lines first, then the gate values of
  the held blocks on the bits no line with a present key covers, then CONST,
  WHEN and counts (ruling 7). The output is decoded again for the blocks:
  every held block must hold and every other must not, and no key the entity
  holds may be mapped only by lines of blocks that are not held, or the
  encode is `transform-encode` (step 6).
- Length: the held blocks' encode need and gate locators count toward the
  message's words. Under six-bit armor `L` counts the held blocks' decode
  need and gate locators, and an `optional` field of a held block only when
  it writes a value, a default or a sentinel (ruling 14). Step 6 reads the
  output as it will be read: `L` bits, then zeros to a multiple of 6.
- Where gt-core differs from the text: the step 6 check of a group item runs
  right after that item is written, not on the whole output (ruling 9 of
  0.17). The two differ only for a pack whose `const`, `when` or count lies
  inside the bits of an item; no pack does, and every vector and fuzz run
  agrees with the reference engine.
- A default inside a block applies to the fields of that block and of the
  blocks nested in it, before the defaults of the kind and the body; the
  innermost wins (ruling 5).

### Scales are rationals

A scale is three pool words, each the bits of a double: numerator,
denominator, offset. Decode computes `v * num / den + offset`, encode
`round((x - offset) * den / num)`, in doubles and in that order, rounding half
away from zero. A scale written in the pack as a plain decimal factor has
denominator 0 and is applied as `v * num + offset` and `(x - offset) / num`.
`linscale:<maxpos>:<range>` stores `maxpos` and `range` in the first two
words. These are rulings 1 of engine-spec 0.5 and the 0.2 text, unchanged.

### Sentinels

The `absent` option of a field (engine-spec 0.9) is compiled into its FIELD
operation. Byte 3 holds the number of sentinels `n`. They are `n` pool words,
in the order the pack writes them, starting at pool[`b` + 3] for `linscale`,
`uscale` and `sscale` (after the three words of the scale) and at pool[`b`]
for every other transform. Each word is the raw unsigned integer below
2^`len` that the pack names.

- Decode: the field's `len` bits are read as `uint` reads them, then `swap`
  is applied. When the integer equals one of the sentinels the line gives no
  value: neither its key nor the keys of its ALSO operations are set, the
  transform and the table are not run, and the line does not fail (an
  `ascii` field of NUL bytes matches `absent 0`; ruling 2 of 0.9). A fixed
  layout field beyond the input under `optional` is absent before any
  sentinel is compared (ruling 3).
- Encode: when the key, and in a sequential layout every key of its ALSO
  operations, has no value and no DEFAULT, the first sentinel is written:
  its low `len` bits, then `swap`. In a sequential layout it takes the place
  of the zero bits an absent key writes. In a fixed layout every sentinel of
  a scope is written before any field with a value, later lines first, so a
  line with a value wins over a sentinel on the same bits whatever their
  order, and of two sentinels the earlier line's stays (ruling 16).
- A sentinel is never content: it does not set a presence bit, an `opt` bit,
  an `fx` bit or a repeat indicator, and a block that would hold only
  sentinels is not written (ruling 4).

### Value tables

```
0  1  type of the wire side
1  1  type of the model side
2  2  number of entries
4  4  pool index of the first entry
```

An entry is three pool words: flags, wire value, model value. Flags: 1 = the
wire value is of the wire type, 2 = the model value is of the model type,
4 = used on decode, 8 = used on encode. An integer is the word, a float is its
bits, text is `offset | length << 32` into the bytes section. The compiler
reads each `map` entry as the two types of the field that uses the table and
writes one table per pair of types, so the device compares typed values and
never text. The pack-wide `typemap` is compiled as a text-to-text table on the
key `type`.

### Kind selection

Decode takes the KIND blocks in order and selects the first whose WHEN
operations all hold. Encode selects the first whose REQ keys are all present.
When a format is compiled for some of its kinds, each kind left out before the
last one kept is still present as a KIND with the "not compiled in" flag and
only its WHEN and REQ operations. Selecting it is `no-kind`. A message of a
kind that was left out is therefore refused, never read as a later kind.

## The conversion plan

Section 9 holds one entry:

```
0   2  source format index, or 0xFFFF (an encode-only plan)
2   2  target format index, or 0xFFFF (a decode-only plan)
4   1  flags: bit 0 = source and target are one format
5   1  deepest nesting of blocks in the plan
6   2  number of keys
8   4  reserved
```

The plan is decided when the blob is compiled:

- A source field whose key the target does not read, directly or through a
  derivation, is not in the blob. In a sequential layout it is a PAD of the
  same length, because the bits still have to be stepped over.
- A target field whose key the source, the context and the derivations can
  never supply is not in the blob, or is a PAD. A field with sentinels stays
  in the blob, on its first key, with no table and the key's "uses its value"
  flag clear: it always writes its first sentinel.
- A list the target does not map is read and dropped (GROUP flag bit 0): its
  items take no room in the value store.
- A derivation is in the blob only when its target is read by the target
  format or by another kept derivation, and its arguments can be present.
- A source field whose decode can fail (`ascii`, `f32`, `f64`, or a table
  between two types) stays in the blob although the target does not read it.
  The reference engine refuses a message whose field fails; the device does
  the same.

Section 11 states the result, one row per key that reaches the target:

```
0  2  key id
2  2  how: bit 0 = read from the source, bit 1 = context, bit 2 = derived
4  4  index of the first source operation that reads it, or 0xFFFFFFFF
8  4  index of the first target operation that writes it
```

Derivations (section 7):

```
0  1  function
1  1  number of arguments
2  2  target key id
4  2  index of the first argument in section 8
6  2  pool index of the function's constant
```

| Function | Id | gt-core feature |
|---|---|---|
| `copy` | 0 | |
| `hypot` | 1 | `sqrt` |
| `bearing` | 2 | `trig` |
| `east_of` | 3 | `trig` |
| `north_of` | 4 | `trig` |
| `neg` | 5 | |
| `scale:<factor>` | 6 | |
| `offset:<n>` on floats | 7 | |
| `offset:<n>` on integers | 8 | |
| `day_seconds` | 9 | |
| `any` | 10 | |
| `not` | 11 | |
| `parse_int` | 12 | |
| `present` | 13 | |
| `sec_of` (0.16) | 14 | |
| `nsec_of` | 15 | |
| `ms_of` | 16 | |
| `deg` | 17 | |
| `rad` | 18 | |
| `add` on integers | 19 | |
| `add` on floats | 20 | |
| `sub` on integers | 21 | |
| `sub` on floats | 22 | |
| `deg_lon_of` | 23 | `sqrt` and `trig` |
| `m_lon_of` | 24 | `sqrt` and `trig` |
| `ecef_x` | 25 | `sqrt` and `trig` |
| `ecef_y` | 26 | `sqrt` and `trig` |
| `ecef_z` | 27 | `sqrt` and `trig` |
| `lon_of_ecef` | 28 | `trig` |

The integer functions of 0.16 (`sec_of`, `nsec_of`, `ms_of`, and `add` and
`sub` on integers) are exact, in 128-bit integers where a step needs it;
`deg`, `rad`, and `add` and `sub` on floats take one IEEE operation, as the
reference engine does. The WGS 84 functions follow the reference engine's
order of operations with gt-core's square root (the host's bits) and its
sine, cosine and arctangent (within 2.3e-16 relative of the host's).

The compiler prints which features a plan needs. An engine built without a
feature refuses a plan that uses it (`bad-plan`).

## What the compiled form supports

| Pack-language feature | Status |
|---|---|
| `bits` wire, fixed layout: `word_bytes`, `bit_order`, fields past their word (0.2, 0.5) | Built |
| `uint`, `twos`, `linscale`, `uscale`, `sscale` with a decimal or fraction factor, `f32`, `f64`, `ascii` | Built |
| `armor sixbit` and the `sixbit` transform (0.14), fixed and sequential layout | Built |
| `uiscale`, `siscale`, `smag`, `smscale`, `f32scale`, `f64scale`, `chars:icao6`, `chars:ais6`, `chars:ascii7`, `octal` (0.15) | Built |
| kinds: `kind`, `when`, `requires`, common lines; slicing to named kinds | Built |
| `const`, `default`, `map` / `via`, `typemap`, `swap`, `trim`, `optional` (0.6) | Built |
| several lines for one key; overlapping lines | Built |
| groups: `group ... item ... count <n | locator>`, nested (0.7); an empty group and a layout with no counted bit (0.52 rulings 18 and 19) | Built |
| `layout sequential`: `field`, `also`, `const`, `pad`, `align`, `when` (0.8) | Built |
| `presence <n>`, `presence fx`, `if`, `opt` | Built, up to 64 bits per presence |
| `group ... count | while | more | fx`, items by kind | Built |
| `chain` / `fx`, `length ... bytes | bits | plus`, `length ... whole` | Built |
| context keys | Built; the keys are named when the plan is compiled |
| `derive`: the functions in the table above | Built |
| `absent` (0.9): fixed and sequential layout, with `swap`, `optional`, `also`, in kinds and groups | Built, up to 255 sentinels per field |
| gate blocks on a fixed layout (`if [!]<locator> <values>` ... `end`, 0.17): in common lines, kinds and group items, nested, with `field`, `const` and `default`, with six-bit armor | Built, up to 256 blocks per scope |

## What the compiler refuses

`packc.py` exits with status 2 and prints `packc: refused: <reason>: <detail>`.

| Reason | Refused |
|---|---|
| `wire-not-bits` | a format on the `xml`, `geojson`, `json` or `protobuf` wire |
| `derive-function` | a derivation the conversion needs that uses `join` or `text_of` (they build new text; the device has no text store), or has more than 8 arguments |
| `target-unreachable` | a conversion in which no kind of the target can ever be selected, with the keys that are missing |
| `via-with-typemap` | a field on the key `type` that has both `via` and a pack-wide `typemap` |
| `presence-too-wide` | a presence field of more than 64 bits, or an `if` naming a bit beyond 64 |
| `too-many-presences` | more than 16 presence fields in one format |
| `too-many-wholes`, `whole-in-group` | more than 4 `length ... whole` lines, or one inside a group |
| `nesting-too-deep` | blocks and groups nested more than 12 deep |
| `too-many-gates` | more than 256 gate blocks (spec 0.17) in one scope: the common lines and one kind of a message, or one item |
| `length-plus-range` | a `plus` outside 32 bits |
| `value-range`, `table-overflow` | an offset, count or table index beyond what an entry holds; more than 255 sentinels on one field |
| `unknown-format`, `unknown-kind`, `unknown-key`, `bad-arguments` | a name the inputs do not have |
| `unsupported-feature` | a pack line of the specification that the device profile does not implement. Refused this way, when a conversion needs one: the derive functions of spec 0.16 `deg_lat_of` and `m_lat_of` (the meridional radius takes the power x^1.5) and `lat_of_ecef` and `hae_of_ecef` (Heikkinen's closed form takes a cube root). gt-core has neither function, and an approximation would not give the platform library's results bit for bit. Refused this way too: the field option `with` and the derive functions `tokens`, `has_token` and `text_if` of spec 0.18, and `encoding uper` (spec 0.19), and the kind selection of spec 0.20 (`when` lists and ranges, `requires <key>=<value>`, `switch`), and the sequential extents and counts of spec 0.21 (`group … rest`, `group … last`, `count` lines and `group … count @<name>`), and a length given by an earlier count (`length @<name> units <u>`, spec 0.83), and `framing self` (a pack whose messages may stand in a run, spec 0.92), and the long and terminated fields of spec 0.22 (`bit_order msb-lsb`, `hex` on `bits`, `chars:ascii8`, the field option `stop` and the `until:` locator), and a `when` bound to a key (`when … as`, spec 0.30) or looking ahead (`when … at`, spec 0.33), and a core key written with its module (`core.lat`, ruling 2 of 0.4), and the character-coded identifiers of spec 0.46 (`charset`, `code`, `codenum`), and the decimal places of `uscale` and `sscale` and `utf8` on `bits` (spec 0.55), and the field option `range <min> <max> [wrap]` and the `absent` sentinels `>=` and `<=` (spec 0.56) |
| `bad-pack`, `bad-model` | text the compiler cannot read; it compiles packs the reference engine loads and does not repeat that engine's load checks |

The text wires are out of scope for the device profile. A text format needs a
parser, a writer and number formatting on the device, which is what the
profile removes.

## Differences from the reference engine

The device engine gives the reference engine's bytes and error kinds
(`docs/embedded.md`, "How equivalence is checked"). It differs in these
stated ways:

- Residue is not carried. A `bits` format has none.
- Three errors belong to the device: `output-full`, `scratch-full` and
  `bad-plan`. A message with more values or list items than the caller's
  scratch holds is `scratch-full` where the reference engine would allocate.
- A context key the plan was not compiled with is `undeclared-key`, also when
  a model module declares it.
- `east_of` and `north_of` leave the target absent for a course beyond
  ±94 million degrees. `sin`, `cos` and `atan2` are computed in the engine and
  agree with a platform library to the last bit or the one before it; the
  specification compares derived floats within 1e-9 relative.
- Input longer than 512 MiB is `malformed-wire`.
