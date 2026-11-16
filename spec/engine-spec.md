# Engine specification

Status: Written. Version 0.1. This is what every language's engine implements,
from this document and the vectors, never from another engine's source.

## What an engine does

Three operations:

- `decode(format, bytes) -> Entity` — wire to shared model.
- `encode(format, Entity) -> bytes` — shared model to wire.
- `convert(from, to, bytes) -> bytes` — `encode(to, decode(from, bytes))`.

An engine loads packs at start. A pack is a directory under `packs/<format>/`.
Loading a pack means reading its `pack.def` and its mapping lines. No format
definition is compiled into the engine.

## Pack definition grammar (`pack.def`)

Line-oriented, UTF-8, `#` starts a comment to end of line, blank lines ignored.
Each non-blank line is a directive: a keyword then whitespace-separated
arguments. A locator or value that contains whitespace is wrapped in double
quotes.

```
format    <name>                       # e.g. cot-xml
version   <semver>                     # e.g. 0.1.0
wire      <xml | geojson>              # which codec the engine uses
root      <element-name>               # xml only: the document root element
field     <model-key> <locator> <transform>
typemap   <native-code> <cot-type>     # optional, repeatable
```

`field` binds one shared-model key to one place on the wire through one
transform. Order of `field` lines is the order the encoder writes them.

### Locators

For `wire xml`:

- `@name` — attribute `name` on the root element.
- `path/@name` — attribute `name` on the element reached by `path` (slash
  separated child element names) under the root.
- `path/#text` — the text content of the element at `path`.

For `wire geojson` (the object is a GeoJSON Feature):

- `geometry.lon`, `geometry.lat`, `geometry.alt` — the three coordinate slots of
  a Point geometry's `coordinates` array (`[lon, lat, alt]`).
- `properties.<name>` — a member of the Feature's `properties` object.
- `<name>` — a top-level member of the Feature (e.g. `id`).

### Transforms

A transform is a reversible pair: decode turns a wire value into a typed model
value, encode turns it back. The set in version 0.1:

| Name | Decode | Encode |
|---|---|---|
| `string` | text as-is | text as-is |
| `float` | parse decimal to float | shortest round-trip decimal |
| `int` | parse decimal to integer | decimal |
| `iso8601_ms` | ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SS[.fff]Z`) to epoch ms | epoch ms to `YYYY-MM-DDTHH:MM:SS.fffZ` |

An engine must implement every transform named in a pack it loads, or refuse the
pack with a named error. Unknown directives are a named error, not silent.

## Residue

On decode, any attribute or element (xml) or any `properties` member (geojson)
that no `field` line maps is recorded in `Entity.residue`, keyed by its locator,
with its original string value. On encode, residue entries whose locator belongs
to the target format are written back. Residue is per-format: `encode` ignores
residue whose locator does not match the target wire. This gives same-format
round-trip equality without forcing every field into the model.

## Type mapping

`typemap` lines build a two-way table between a format's native type codes and
CoT type tokens. On decode, the native code in the mapped field is replaced by
its CoT token before it reaches `type`; on encode, the reverse. A native code
with no `typemap` entry passes through unchanged and is also kept in residue.

## Errors

Every failure is a named error with the format and locator involved: unknown
directive, unknown transform, malformed wire, missing required root, transform
decode failure. An engine never returns a partial entity silently; a decode that
cannot satisfy a `field` records the field as absent and lists it in the error
detail, and the vector for that case states the expected behaviour.

## Conformance

A vector is defined in `spec/vector-format.md`. An engine passes a pack when it
reproduces every vector: the decoded model value, the re-encoded bytes (modulo
documented canonicalisation), and each `convert` result. An engine release
requires every loaded pack's vectors to pass, and the engines are run against
each other on generated inputs.

## Canonicalisation

Encoded bytes are compared after canonicalisation so that insignificant wire
differences do not fail a vector:

- xml: attributes in `field`-line order then residue order; one space between
  attributes; self-closing empty elements; UTF-8; `\n` line endings.
- geojson: object members in `field`-line order then residue; `coordinates` as
  `[lon, lat, alt]`; no insignificant whitespace; numbers shortest round-trip.

A vector that tests parsing tolerance supplies non-canonical input and canonical
expected output.

## Version 0.1.1 rulings

Status: Written. These settle points the first five engines read differently.
Each is pinned by a vector under `packs/conformance/vectors/`.

1. **Comments.** `#` starts a comment only at the start of a token (after
   whitespace or at line start). Inside a token it is literal, so
   `detail/remarks/#text` is a locator, not a comment.
2. **Unmapped type code.** A native code with no `typemap` entry passes through:
   `decode` leaves it in `type` unchanged, `encode` writes it back through the
   mapped locator unchanged. It is NOT added to residue (its locator is mapped,
   so residue would duplicate it). This round-trips mapped and unmapped codes
   alike with no residue involvement.
3. **Float text.** A float is written as the shortest decimal that round-trips to
   the same double, in plain notation (never an exponent). An integer-valued
   float has no decimal point (`30.0` is `30`). Negative zero is written `0`.
4. **GeoJSON member order.** `type`, `geometry`, `properties`, then mapped
   top-level members (such as `id`) in field-line order, then top-level residue.
   Inside `properties`: mapped members in field-line order, then residue in input
   order.
5. **GeoJSON geometry absent.** If either `lon` or `lat` is absent, `geometry` is
   written as `null`.
6. **XML residue (v0.1 scope).** Unmapped *attributes* on the root element are
   residue and are written back. Unmapped *child elements* are not carried in
   v0.1: they are dropped on decode. Element-level residue is deferred to a later
   version; until then a pack maps every element whose content must survive.
7. **Repeated XML siblings (v0.1 scope).** A locator binds to the first sibling of
   that name; later siblings of the same name are not carried in v0.1. Deferred
   with element-level residue above.
8. **ISO 8601 input.** Requires the `Z` designator; offsets are a decode error.
   Fraction digits beyond milliseconds are truncated, not rounded.
9. **Failed fields.** A field present on the wire whose transform fails makes
   `decode` fail with a named error listing every failed field; `convert` fails.
   A field absent from the wire is absent from the entity, not an error.

---

# Version 0.2: the `bits` wire

Status: Written and implemented in the Rust reference. A `bits` format is a
sequence of fixed-size binary words whose fields are bit ranges. Input and output
are hex text, so the existing text vector harness carries binary cases.

## Directives

```
wire        bits
word_bytes  <n>                 # bytes per word
field       <model-key> <word>:<pos>:<len> <transform>
```

`<word>` is a zero-based word index; the message is `(max word index + 1)` words.
`<pos>` is the bit position within that word and `<len>` the bit length (1..=64).

## Bit order

Bit `i` of a word is bit `i mod 8` of byte `i div 8` (LSB-first within each byte).
Field value = the `len` bits from `pos`, low bit first.

## Transforms for `bits`

| Name | Decode | Encode |
|---|---|---|
| `uint` | the `len` bits as an unsigned integer | low `len` bits of the integer |
| `twos` | the `len` bits as a two's-complement signed integer | low `len` bits |
| `linscale:<maxpos>:<range>` | signed two's-complement value `v`, then `v / maxpos * range` (float) | `round(x / range * maxpos)`, low `len` bits |

A `uint`/`twos`/`linscale` transform is valid only on a `bits` wire; `string`,
`float`, `int`, `iso8601_ms` are valid only on text wires. An engine errors if a
pack uses the wrong kind.

## I/O and canonicalisation

A bits format's `decode` takes hex (whitespace ignored, even length); `encode`
produces lowercase hex with no separators. `encode` writes only mapped fields;
bits covered by no field are zero. So a `bits -> same bits` round-trip is identity
exactly when the input's set bits all fall in mapped fields.

---

# Version 0.3: the protobuf wire

Status: Written and implemented in the Rust reference. A `protobuf` format is a
protobuf message. Fields are addressed by number; a dot-path addresses a field
inside a nested (length-delimited) submessage. Input and output are hex text.

## Directives

```
wire   protobuf
field  <model-key> <path> <transform>
```

`<path>` is one or more field numbers separated by dots: `2` is field 2 of the
top message; `4.1` is field 1 of the submessage in field 4. When a field number
repeats on the wire, the last occurrence wins.

## Transforms for `protobuf`

Each transform fixes the field's protobuf wire type.

| Name | Wire type | Decode | Encode |
|---|---|---|---|
| `pstring` | 2 length-delimited | bytes as UTF-8 string | string as UTF-8 bytes |
| `pvarint` | 0 varint | varint as integer | integer as varint |
| `psint` | 0 varint | zig-zag varint as signed integer | signed integer as zig-zag varint |
| `pdouble` | 1 fixed64 | little-endian IEEE-754 double | double as fixed64 |
| `pfloat` | 5 fixed32 | little-endian IEEE-754 float, widened | double narrowed to fixed32 |

A `p*` transform is valid only on a protobuf wire; text/bits transforms are not.
An engine errors if a pack uses the wrong kind for the wire.

## I/O and canonicalisation

`decode` takes hex (whitespace ignored, even length); `encode` produces lowercase
hex. Encoded output is canonical: fields in ascending field-number order, each
submessage serialised the same way, and only mapped fields are written (protobuf
omits everything else). So a `protobuf -> same protobuf` round-trip returns the
canonical encoding of the mapped fields; it is byte-identical when the input was
already in canonical field order with only mapped fields present.

Unsupported wire types (3/4, the deprecated groups) are a decode error.

---

# Version 0.4: model modules and distribution

Status: Written and implemented in the Rust reference. The shared model is a set
of **modules**. Each module declares typed keys; a pack may map only keys that a
loaded module declares, through a transform that yields the declared type. Every
module and every pack states how far it may be distributed, and the engine
enforces that statement at load.

## Model module grammar (`model/<module>.def`)

Same line rules as `pack.def` (UTF-8, `#` comments at token start, double quotes
around a value with whitespace).

```
module        <name>                         # e.g. track
version       <semver>
distribution  <public | controlled>          # required
source        "<where the definitions come from>"   # required, repeatable
key           <name> <string | float | int> <unit | -> ["meaning"]
```

A key name contains no `.`. An unknown directive is a named error.

## Pack directives added in 0.4

```
distribution  <public | controlled>          # required
source        "<the document the pack was written from>"   # required, repeatable
uses          <module>                       # repeatable; `core` is always used
```

## Model keys in `field` lines

A model key with no `.` is a key of the `core` module (`lat`). A model key
`<module>.<name>` is key `<name>` of that module (`track.confidence`). The text
before the first `.` is the module name.

## Loading

`load_model(text)` loads one module. `load(pack)` checks the pack against the
modules loaded so far, so modules are loaded before the packs that use them. A
directory loader reads `model/*.def` in byte order of file name, then the packs.

A pack loads only if all of these hold. Each failure is a named error whose
message begins with the error kind and a colon.

| Check | Error kind |
|---|---|
| the pack has a `distribution` line (same for a module) | `missing-distribution` |
| the pack has at least one `source` line (same for a module) | `missing-source` |
| `core` and every module in a `uses` line is loaded | `unknown-module` |
| the module of every mapped key is `core` or is in a `uses` line | `module-not-used` |
| every mapped key is declared by its module | `undeclared-key` |
| the transform of every `field` yields the key's declared type | `key-type-mismatch` |
| a `public` pack uses only `public` modules | `distribution-violation` |
| a module name is loaded once | `duplicate-module` |
| a key name appears once in its module | `duplicate-key` |
| the module or pack is within the engine's limit (below) | `distribution-refused` |

Order of checks for a pack: line errors as the file is read; then
`missing-distribution`, `missing-source`; then `distribution-refused`,
`unknown-module`, `distribution-violation`, `module-not-used`, `undeclared-key`,
`key-type-mismatch`. Each of the last three runs over every `field` line before
the next check starts, so a `module-not-used` on a later line is reported ahead
of an `undeclared-key` on an earlier one.

Order of checks for a module: line errors as the file is read, `duplicate-key`
among them; then `missing-distribution`, `missing-source`; then
`distribution-refused`; then `duplicate-module`.

Rulings:

1. **What a pack uses.** A pack uses `core` and every module named in a `uses`
   line, whether or not a `field` maps a key of it. `distribution-violation` and
   `unknown-module` are checked against that whole set. A repeated `uses` line
   and `uses core` are accepted.
2. **Core keys are written bare.** `core.lat` passes the load checks as key
   `lat` of `core`, but the entity key is the literal text of the `field` line,
   so it does not convert against `lat`. Packs write core keys bare.
3. **Malformed values.** A `distribution` value other than `public` or
   `controlled`, a key type other than `string`, `float` or `int`, a `.` in a
   key name, or a directive with the wrong number of arguments is a named error.
   Version 0.4 does not pin its kind.
4. **No model directory.** A directory loader that finds no `model/` directory
   loads no modules; the first pack then fails with `unknown-module`.

## The type a transform yields

| Yields | Transforms |
|---|---|
| `string` | `string`, `pstring` |
| `float` | `float`, `linscale:…`, `pdouble`, `pfloat` |
| `int` | `int`, `iso8601_ms`, `uint`, `twos`, `pvarint`, `psint` |

## Distribution limit

An engine instance has a limit, `controlled` by default. Set to `public`
(`set_max_distribution`, CLI `--max-distribution public`), the engine refuses
every `controlled` module and pack with `distribution-refused`. `public` is
below `controlled`; a `controlled` pack may use modules of either marking.

## Conformance

Load behaviour is pinned by load vectors (`spec/vector-format.md`, Load
vectors) under `packs/conformance/load-vectors/`. Conversion behaviour is
unchanged: `decode`, `encode`, `convert`, residue and the capability matrix treat
a model key as an opaque string, as before.

---

# Version 0.5: message kinds and the `json` wire

Status: Written. A format may hold several message layouts, called kinds; the
engine picks the kind from values on the wire. The `json` wire addresses members
of any JSON object by path.

## Message kinds

```
kind      <name>                     # starts a kind; lines up to the next `kind` belong to it
when      <locator> <value>          # this kind applies when the wire holds <value> at <locator>
requires  <model-key> [<model-key>…] # encode picks this kind only when the entity has all of these
field     <model-key> <locator> <transform>
```

A pack with no `kind` line behaves exactly as before. In a pack with kinds:

- `field` and `when` lines before the first `kind` are **common**: they apply to
  every kind. A common `when` must hold for any message of the format.
- `field`, `when` and `requires` lines after a `kind` line belong to that kind.
  `requires` before the first `kind` is `bad-directive`.
- A kind name is unique in its pack (`duplicate-kind`). The same model key may
  be mapped in several kinds, and in common and a kind; within one kind plus
  common a model key is mapped once (`duplicate-field`).
- `typemap` stays pack-wide.

### `when` values, by wire

`<value>` is compared with the raw wire value, before any transform.

| Wire | Locator | `<value>` | Matches when |
|---|---|---|---|
| `bits` | `<word>:<pos>:<len>` | unsigned decimal integer | the bits, read as unsigned, equal it |
| `protobuf` | field-number path | `present` | the field at that path occurs on the wire |
| `protobuf` | field-number path | unsigned decimal integer | the field is a varint equal to it |
| `xml` | an attribute or `#text` locator | text, or `present` | the text equals it; `present`: the attribute or element exists |
| `geojson`, `json` | a member locator | text, or `present` | the member is a string equal to it, or a number or boolean whose canonical text equals it; `present`: the member exists and is not `null` |

To match the literal text `present` on a text wire, write `=present`; a leading
`=` is stripped from any text value.

### Decode

1. Check every common `when`. If one fails: error `no-kind`.
2. Take the kinds in pack order. The first whose every `when` holds is selected.
   A kind with no `when` always holds. None selected: error `no-kind`.
3. Decode the common fields, then the selected kind's fields, by the existing
   rules. Fields of other kinds are not read.
4. The entity records the selected kind: `Entity.kind` is the pair
   `(format, kind name)`.

For a `bits` pack the message length is `(max word index + 1)` words over the
common fields and `when` lines plus those of the selected kind. A `when` whose
word lies beyond the input does not hold.

### Encode

1. If `Entity.kind` names this format, that kind is selected.
2. Otherwise take the kinds in pack order; the first whose every `requires` key
   is present in the entity is selected. A kind with no `requires` always
   qualifies. None qualifies: error `no-kind`.
3. Write the common fields and the selected kind's fields that are present, in
   line order (common first), by the existing rules.
4. Write every common and selected-kind `when` value at its locator, so the
   output decodes as the same kind: `bits` writes the integer into the bit
   range; `protobuf` writes a varint for an integer value and nothing for
   `present`; text wires write the text, and nothing for `present`.

`convert(from, to, …)` decodes, then clears `Entity.kind` unless `from == to`,
then encodes. So a same-format round trip keeps its kind, and a cross-format
conversion chooses the target kind by `requires`.

Residue is unchanged: what no common or selected-kind `field` or `when` maps is
residue under the existing per-wire rules.

### Load checks

Version 0.4 checks apply to every `field` line in every kind. `requires` keys
are checked like mapped keys (`module-not-used`, `undeclared-key`).

### Capability

`model_keys(format)` is the union of keys over common and all kinds, in first
appearance order. The capability matrix is computed from that union as before.

## The `json` wire

```
wire   json
field  <model-key> <path> <transform>
```

The message is one JSON object. `<path>` is one or more member names separated
by `.`; each name but the last addresses a nested object. Member names
containing `.` are not addressable in 0.5.

### Transforms for `json`

| Name | JSON value | Decode | Encode |
|---|---|---|---|
| `string` | string | as-is | string |
| `float` | number | to float | number, shortest round-trip, plain notation |
| `int` | number with no fraction | to integer | integer |
| `iso8601_ms` | string | ISO 8601 UTC to epoch ms | `YYYY-MM-DDTHH:MM:SS.fffZ` |
| `bool` | `true` / `false` | to int 1 / 0 | 1 to `true`, 0 to `false`; other values are an encode error |

`bool` yields `int` and is valid only on the `json` wire. A value of the wrong
JSON type for its transform is a transform decode failure (ruling 9 of 0.1.1).
A member whose value is `null` is absent.

### Residue

Every scalar member (string, number, boolean) at any depth of nested objects
that no `field` or `when` maps is residue, keyed by its path, with its JSON
text. Arrays, and anything inside an array, are not carried in 0.5. `null`
members are not carried.

### Canonical output

An object's members are written in this order: mapped members and `when`
members in line order (common lines first, then the kind's), where a nested
object appears at the position of the first line that addresses into it; then
residue members of that object in input order. A nested object that would have
no members is not written. No insignificant whitespace. Numbers as in ruling 3
of 0.1.1. Strings escape `"`, `\`, and control characters below U+0020 (`\n`,
`\r`, `\t`, `\b`, `\f` by name, others as `\u00XX`); all other characters are
written as UTF-8.

## `bits`: most-significant-bit-first order

```
bit_order  <lsb | msb>      # bits wire only; default lsb
```

`lsb` is the order defined in Version 0.2. With `msb`, bit `i` of a word is bit
`7 - (i mod 8)` of byte `i div 8`, and a field's value is its `len` bits from
`pos` with the first bit most significant. So `0:0:8` is the first byte, and
`0:0:16` is the first two bytes as a big-endian integer. `when` lines on a
`bits` pack read and write in the pack's bit order. `bit_order` on another wire
is `bad-directive`.

## `bits`: fields that run past their word

A field or `when` may extend past the end of its word into the words that
follow: `<word>:<pos>:<len>` addresses `len` bits starting at bit
`word * word_bytes * 8 + pos` of the message, and `pos` may itself exceed the
word's size. The message is as many whole words as the furthest mapped or
`when` bit reaches (over common lines and the selected kind). A pack whose
messages have no natural word size uses `word_bytes 1` and addresses by `0:<bit
offset>:<len>`. On decode, input longer than that is accepted and the extra
bytes are ignored; input shorter is `malformed-wire`.

## `bits`: more transforms

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `uscale:<factor>[:<offset>]` | float | the bits as unsigned `v`, then `v * factor + offset` | `round((x - offset) / factor)`, low `len` bits |
| `sscale:<factor>[:<offset>]` | float | the bits as two's-complement `v`, then `v * factor + offset` | `round((x - offset) / factor)`, low `len` bits |
| `f32` | float | `len` must be 32: the bits as an IEEE-754 single, widened | double narrowed to single |
| `f64` | float | `len` must be 64: the bits as an IEEE-754 double | the double |
| `ascii` | string | `len` is a multiple of 8, from 8 to 2040: the bytes in wire order as text, with trailing NUL bytes removed | the text's bytes, NUL-padded to `len / 8`; longer text is an encode error |

`offset` defaults to 0. `round` is round-half-away-from-zero, as for `linscale`.
A value outside the field's range after rounding is an encode error
(`transform-encode`), for `uscale` and `sscale` only; `linscale` keeps its 0.2
behaviour. `f32`, `f64` and `ascii` take their bytes in the pack's bit order:
with `lsb` an `f32` at a byte-aligned position is a little-endian single, with
`msb` a big-endian one; `ascii` reads its bytes first to last in either order,
each byte's bits in the pack's bit order. `ascii` bytes above 0x7E or below 0x20
(other than the trailing NULs) are a decode error. A `len` these transforms do
not allow is `bad-directive` at load.

## Rulings for 0.5

1. **Scale arithmetic.** `<factor>` and `<offset>` are decimal numbers, read as
   the nearest IEEE-754 double. `<factor>` may instead be a fraction
   `<num>/<den>` of two decimal integers. Decode computes, in doubles and in
   this order: `v * factor` (or `v * num / den` for a fraction), then
   `+ offset`. Encode computes `(x - offset) / factor` (or
   `(x - offset) * den / num`), then rounds. A pack whose scale is an exact ratio writes
   the fraction (`sscale:1/10000000`, `uscale:1/128`), because the division
   returns the nearest double to the exact value and the product does not.
2. **`uint` at 64 bits.** A 64-bit field whose top bit is set decodes to the
   negative model integer with the same bit pattern, and encodes back to the
   same bits.
3. **Empty `ascii`.** A field that is all NUL bytes decodes to the empty
   string, present. The empty string encodes to all NUL bytes.
4. **`requires` keys.** Any key declared by `core` or a module the pack uses,
   whether or not the kind maps it.
5. **Overlapping lines.** Two `field` lines, or a `field` and a `when`, may
   cover the same bits. Decode reads each independently. On encode the earlier
   line takes precedence: where two present fields cover the same bits, the
   bits hold the earlier line's value. `when` values are written over any
   field.
6. **Quotes.** A double-quoted value cannot contain a double quote; there is no
   escape.
7. **Bits vectors.** Input and expected output of a `bits` or `protobuf` format
   are lowercase hex text in the vector's `input` and `expect` keys.
8. **`when` needs kinds.** A `when` line in a pack with no `kind` line is
   `bad-directive`.
9. **`duplicate-field` scope.** Checked only in a pack that has a `kind` line.
10. **Order of `when` output on text wires.** On `xml`, `geojson` and `json`,
    mapped members and `when` members are written in line order, common lines
    first, then the kind's.
11. **Type of a written `when` value on `json` and `geojson`.** A value that is
    canonical JSON number text is written as a number; `true` and `false` as
    booleans; anything else as a string. A leading `=` forces a string
    (`=2` writes `"2"`). Decode comparison is unchanged.
12. **`json` details.** `\u00XX` escapes use lowercase hex. `int` accepts any
    number whose value is integral (`1.0`, `1e3`). Residue stores canonical
    JSON text. A member whose name contains `.` is dropped, not residue.
13. **Transform errors.** Any transform failure on encode is `transform-encode`
    and on decode `transform-decode`. A `bits` `when` value that does not fit
    its `len` is `bad-directive` at load.
14. **`protobuf` `present` on encode.** When the selected kind has
    `when <path> present` and no mapped field under that path is written, the
    encoder writes an empty length-delimited field at that path, so the output
    decodes as the same kind.
15. **`protobuf` integers.** A varint is a 64-bit value: `pvarint` decodes it to
    the model integer with the same bit pattern, and a negative integer encodes
    as a ten-byte varint. A submessage that repeats on the wire is not merged;
    the last occurrence wins as a whole.
16. **Lines on the same locator.** Ruling 5 holds on every wire: two `field`
    lines may bind the same locator to different keys. Decode fills both. On
    encode the value written is that of the earliest line whose key is present.
    A pack that binds a locator to a shared-model key and to a raw key puts the
    shared-model line first, so a consumer that changes the shared value sees
    it on the wire.
17. **Comments and quotes.** `#` inside a double-quoted value is literal.

### Stated, not yet pinned by a vector

Seven engines written independently from this section read the points below
differently, or noted that no vector decides them. Each is ruled here; vectors
that pin them are the next conformance change.

18. **`typemap` is pack-wide on every wire**, not only the text wires.
19. **`ascii` encode.** Text holding a byte outside 0x20–0x7E is
    `transform-encode`.
20. **A model key mapped by two lines in a pack with no kinds.** Decode takes
    the value from the earliest line whose locator is present on the wire.
    Encode writes the value at both locators.
21. **A `bits` `when` any of whose bits lies beyond the input does not hold.**
    Input that satisfies the selected kind's `when` lines but does not reach
    every mapped bit is `malformed-wire`.
22. **`json` input with the same member name twice in one object** is
    `malformed-wire`.
23. **`f32` and `pfloat`.** A value outside single range is `transform-encode`.
    Infinity and NaN on the wire are `transform-decode`.
24. **`Entity.kind` naming this format and a kind the pack does not have** is
    `no-kind`.
25. **Checks that need the whole file** (`when` with no `kind`, `bit_order` on
    another wire, a length a transform does not allow, a `when` value that does
    not fit) run after the file is read and before `missing-distribution`.
26. **A `when` and a `field` on one locator of a text wire.** The value written
    is the `when` value, at the position of the first line naming the locator.
27. **`when <locator> present` on a text wire** does not map the member: a
    scalar there that no `field` maps is residue and is written back. A pack
    that selects a kind this way lists in `requires` a key mapped at or under
    that locator, so an entity encoded into the kind writes the member.
28. **`geojson` keeps its 0.1 behaviour** for residue, `null` and value types;
    the `json` rulings do not apply to it.

## Vector additions

A conversion vector's `model` object may carry the key `"@kind"`; its value is
the kind name `decode(from, input)` must select. A conversion vector may carry
`"expect_error": "<kind>"` in place of `expect`: `convert` must fail with that
named error (`no-kind`).

Load-vector error kinds added in 0.5: `duplicate-kind`, `duplicate-field`.

---

# Version 0.6: mapping rules

Status: Written. A pack so far copies a value between a wire place and a model
key. Version 0.6 adds the rules a real encoder applies around that copy:
constants, defaults, value tables, derived keys, and keys the caller supplies.
Every rule is data; the functions a rule may name are a fixed set.

## Constants

```
const  <locator> <value>
```

Common or inside a kind. On encode the value is written at the locator, typed as
a `when` value is (rulings 5 and 11 of 0.5: written over any field; number,
boolean or string on `json` and `geojson`). On decode a `const` is not checked;
the member it names is treated as mapped, so it is not residue. A pack may have
`const` lines without having kinds.

## Defaults

```
default  <model-key> <value>
```

Common or inside a kind. On encode, when the entity has no value for the key,
`<value>` is used for every `field` of that key in scope. `<value>` is read as
the key's declared type. A default never changes the entity and has no effect on
decode. The key must be declared (`undeclared-key`).

## Value tables

```
map    <table> <native> <model>          # repeatable; pack-wide
field  <model-key> <locator> <transform> via <table>
```

A `field` with `via <table>` passes its value through the table after the
transform on decode and before it on encode. `<native>` is what the transform
yields from the wire; `<model>` is what the key holds. Both are compared as
canonical text (an integer as decimal digits, a float as in ruling 3 of 0.1.1),
and the result is read as the type that side needs: the key's declared type on
decode, the type the transform yields on encode. So a table can map wire
integers to model strings.

- A value with no entry passes through when the two types are the same;
  otherwise it is `transform-decode` or `transform-encode`.
- When several entries share a `<model>` value, encode uses the first; when
  several share a `<native>` value, decode uses the first.
- The load-time type check compares the key's type with the type of the
  table's `<model>` side: `string` unless every `<model>` value in the table is
  an integer (`int`) or every one is a number (`float`).
- `via` naming a table with no `map` line is `bad-directive`.

`typemap` is unchanged and is equivalent to a table applied to the key `type`.

## Field options

After the transform a `field` line may carry options, in any order:

```
field  <model-key> <locator> <transform> [via <table>] [swap] [trim] [optional]
```

| Option | Wire | Meaning |
|---|---|---|
| `via <table>` | any | the value table above |
| `swap` | `bits` | `len` is a multiple of 8; the field's bytes are taken in reverse order before the transform reads them, and reversed again after it writes them. A little-endian field in an `msb` pack, or the reverse |
| `trim` | `bits`, with `ascii` | decode also removes trailing spaces (0x20) after the trailing NULs |
| `optional` | `bits` | a field any of whose bits lies beyond the end of the input is absent, where without the option the message is `malformed-wire`. Encode is unchanged |

An option on a wire or transform it does not apply to is `bad-directive`.

## Two corrections to earlier rulings

- **`iso8601_ms` decode accepts an offset.** Ruling 8 of 0.1.1 is replaced:
  the designator may be `Z`, `z`, or `+hh:mm` / `-hh:mm`, and the `T` may be
  lowercase; the instant is converted to UTC. Encode still writes `Z` and
  uppercase `T`. Two fielded encoders examined write `+00:00`.
- **Not-a-number and infinity.** Ruling 23 of 0.5 also covers `f64` and
  `pdouble`: on the wire they are `transform-decode`. A model float is always
  finite.

## One key at several locators

The `duplicate-field` check of 0.5 is withdrawn: in any pack a model key may be
mapped by several `field` lines. Decode takes the value from the earliest line
whose locator is present on the wire and whose transform succeeds. Encode
writes the value at every such locator.

## XML: a root per kind

On the `xml` wire a `root <element-name>` line may appear inside a kind. Decode
considers a kind only when the document's root element has that name, before
its `when` lines; encode writes that root. A kind with no `root` uses the
pack's. A pack whose every kind has a `root` needs no pack-level `root`. This
lets one pack hold a catalog of XML messages that differ by root element.

## Derived keys

```
derive  <model-key> <function> <argument-key> [<argument-key>…]
```

A line of a model module (`model/<module>.def`). The target and the arguments
are keys of `core` or of the module itself (written as in a pack: bare for
`core`, `<module>.<key>` otherwise). It states that the target follows from the
arguments.

`convert` applies the derivations between decode and encode, to the decoded
entity: taking the loaded modules in byte order of name and each module's
`derive` lines in order, a line whose target key is absent and whose argument
keys are all present sets the target. The pass repeats until a pass sets
nothing, at most 8 times. `decode` alone does not derive; an engine also offers
the step on its own (`complete(entity)`).

Functions (all on floats unless stated; a result that is not finite leaves the
target absent):

| Function | Arguments | Result |
|---|---|---|
| `copy` | a | a (any type; target and argument types must match) |
| `hypot` | a b | `sqrt(a*a + b*b)` |
| `bearing` | east north | `atan2(east, north)` in degrees, reduced to `[0, 360)`; absent when both are 0 |
| `east_of` | speed course | `speed * sin(course°)` |
| `north_of` | speed course | `speed * cos(course°)` |
| `neg` | a | `-a` |
| `scale:<factor>` | a | `a * factor`, factor as in ruling 1 of 0.5 |
| `offset:<n>` | a | `a + n`; on an `int` target and argument, integer addition |
| `join:<sep>` | a b … | the string arguments joined by `<sep>` (target and arguments `string`) |

A function name not in the table, a wrong argument count, an undeclared key or
a type that does not fit is `bad-directive` when the module loads. Degrees to
radians uses `π/180` with `π` as the double nearest to it; `sin`, `cos`, `sqrt`
and `atan2` are the platform's double functions, and a vector compares a
derived float within 1e-9 relative, never as text.

Because derived floats may differ in the last bits between platforms, a
conversion vector whose expected output contains a derived float states it in
`model` (decode side, with `"@complete": true`), not in `expect` bytes; packs
whose targets print floats use values that derive exactly (for example a
velocity of 3 east and 4 north gives a speed of 5).

## Caller-supplied keys

`convert(from, to, bytes, context)` takes an optional `context`: model keys and
values supplied by the caller. After decode and before derivation, each context
key the entity lacks is set from the context. A context key must be declared by
a loaded module (`undeclared-key`) and hold its declared type
(`key-type-mismatch`). The CLI takes `--set <key>=<value>`, repeatable.

A conversion vector may carry `"context": {"<key>": "<value>", …}`, values in
string form, read as each key's type.

## Order inside `convert`

1. `decode(from, bytes)`; clear `Entity.kind` unless `from == to`.
2. Fill absent keys from `context`.
3. Apply derivations.
4. `encode(to, entity)`: select the kind (`requires` sees context and derived
   keys); for each `field`, the entity's value, else the `default`; `via`
   tables; transforms; `const` and `when` values written last.

When `from == to` and no context is given, steps 2 and 3 are skipped, so a
same-format round trip stays byte-exact.

## Load-vector error kinds

`duplicate-field` is no longer raised; load vectors that expected it now expect
a successful load.

## Rulings for 0.6, stated and not yet pinned by a vector

Seven engines written independently from this section chose differently on the
points below, or noted that no vector decides them.

1. **`bearing`.** Radians become degrees by multiplying by `180/π`, the
   quotient computed first as a double.
2. **`default` in common and in a kind for one key.** The kind's is used, for
   common and kind fields alike. A value that cannot be read as the key's type
   is `key-type-mismatch` at load. A key with a default counts as present for
   ruling 16 of 0.5; `requires` looks at the entity only.
3. **`const <locator> present`** is `bad-directive`; `=present` writes the text.
   A `const` on `bits` counts toward the length decode requires.
4. **Tables.** Each entry is canonicalised as the value is before comparing, so
   `01` matches the integer 1. An all-integer table on a `float` key is
   accepted and its model side read as float. A line whose transform succeeds
   and whose table has no entry for a value of a different type fails
   (`transform-decode`); later lines of the key are not tried.
5. **Several lines for one key.** A failed line is an error only when no line of
   that key succeeds, whichever came first.
6. **`via` and `typemap` on the key `type`.** Decode applies the table, then
   the typemap; encode the reverse.
7. **`join`** takes one or more arguments.
8. **`offset` on integers** needs an integer `n`; an overflow leaves the target
   absent. Mixed `int` and `float` is `bad-directive`.
9. **`derive` checks** run after the module file is read and before
   `missing-distribution`; a key of `core` is resolved against `core` as
   loaded, and the directory loader loads `core.def` first whatever its name
   sorts as.
10. **Context.** An empty context counts as given. Context keys are checked
    after decode, every one, including keys the entity already has.
11. **XML root matching no kind** is `no-kind` in any pack that has kinds;
    `missing-root` is for a pack without kinds.
12. **An unknown or repeated field option** is `bad-directive`.
13. **`geojson` residue.** A number keeps its text as written and comes back as
    a string; arrays and objects come back as they were; `null` is dropped. Of
    two members with one name, the last value is used at the first position.
14. **`optional` with multi-byte words.** Decode requires whole words up to the
    furthest bit that is not optional.

---

# Version 0.7: groups

Status: Written. A message may hold a part that repeats: a list of items, each
with the same fields. A `group` block maps such a part to a **list** in the
model. An item is itself a set of model keys, and may hold lists of its own.

## Lists in the model

```
list  <name> ["meaning"]          # a line of a model module
```

A list is named like a key (`<module>.<name>`, bare for `core`) and shares the
key namespace of its module (`duplicate-key`). Its value is an ordered sequence
of items. An item holds model keys and lists exactly as an entity does, without
residue and without a kind. Any declared key may appear in an item.

`Entity.lists` maps a list name to its items. A list that is present and empty
is distinct from an absent list.

## Group blocks

```
group  <list> <locator> [count <count-locator> | count <n>]
  field  …
  const  …
  default …
  group  …            # nested
end
```

A `group` block may appear among common lines or inside a kind, and inside
another group. Lines up to the matching `end` belong to it. Inside a group,
`field`, `const` and `default` behave as outside it, with every locator read
relative to one item; `when`, `requires`, `root` and `kind` are not allowed
(`bad-directive`). A missing `end`, or an `end` with no open group, is
`bad-directive`. The list must be declared (`undeclared-key`); a `group` naming
a scalar key, or a `field` naming a list, is `key-type-mismatch`. Within one
scope (common plus one kind, or one group body) a list is mapped by at most one
`group` (`bad-directive`).

### Group locators and item-relative locators, by wire

| Wire | Group locator | An item is | Locators inside the group |
|---|---|---|---|
| `xml` | a path of element names (`a/b`) | each child element named by the last name, under the first element matched by the names before it | as on the root, relative to the item element: `@name`, `path/@name`, `path/#text`, and `#text` for the item's own text |
| `json` | a member path (`a.b`) whose value is an array | each array element | a member path into the element when it is an object; `.` for the element itself when it is a scalar |
| `geojson` | a `properties.<name>` member or top-level member whose value is an array | each array element | as for `json` |
| `protobuf` | a field-number path | each occurrence of the last field number, in wire order | a field-number path into the occurrence read as a submessage; `.` for the occurrence itself as a scalar |
| `bits` | `<word>:<pos>` where the first item starts, with `item <bits>` after it | consecutive runs of `<bits>` bits | `<word>:<pos>:<len>` counted from the item's first bit |

On `bits` the form is `group <list> <word>:<pos> item <bits> count <count-locator | n>`;
`count` is required. `<count-locator>` is a `<word>:<pos>:<len>` field of the
enclosing scope read as unsigned. The message length is extended by the items.
A counted group whose count is a locator is the last thing in its scope: a
`field`, `when` or `const` of that scope whose bits lie at or beyond the
group's start is `bad-directive`.

On the other wires `count` is not allowed (`bad-directive`).

### Decode

For each group of the scope, in line order: find the items; decode each item's
fields by the scope's rules (transforms, `via`, several lines per key, nested
groups), giving one item per occurrence, in order. The list is present when the
group's container is present: on `json` and `geojson` when the member exists
and is an array (a non-array value is `malformed-wire`; `null` is absent); on
`xml` and `protobuf` when at least one item occurs; on `bits` always, with
`count` items. An item whose field fails its transform fails the decode, as a
field outside a group does. Items carry no residue: unmapped content inside an
item is dropped. On `xml`, ruling 7 of 0.1.1 ("a locator binds to the first
sibling of that name") is unchanged for `field` lines; a `group` is how later
siblings are read.

Repeated scalars on `protobuf`: a `.` field accepts both encodings of a
repeated numeric field, one occurrence per value and the packed form (one
length-delimited occurrence holding the values back to back), for transforms
`pvarint`, `psint`, `pdouble`, `pfloat`.

### Encode

For each group of the selected scope, in line order, when the entity has the
list: write one item per list item, in order, each by the scope's encode rules
(defaults and constants apply per item).

- `xml`: one element per item at the group's position (the position rule of
  ruling 10 of 0.5, the group line counting as a line that addresses its
  locator). An empty list writes nothing.
- `json`, `geojson`: an array at the member; an empty list writes `[]`. An item
  with no members written is `{}`.
- `protobuf`: one occurrence per item; a `.` field with a numeric transform
  writes the packed form when the list has at least one item; an empty list
  writes nothing. An item with nothing written is an empty length-delimited
  occurrence.
- `bits`: the items back to back; a count locator is written with the number of
  items (`transform-encode` when it does not fit); a fixed `count <n>` with a
  different number of items is `transform-encode`.

An absent list writes nothing on any wire.

### Other rules

- `requires <list>` holds when the list is present and has at least one item.
- A `default` inside a group applies to items; a common or kind `default` does
  not reach into items.
- Derivations and context apply to the entity's own keys only, not to items.
- `convert` carries a list from A to B when both map the same list name; each
  item carries the keys both groups map. Capability: `model_keys(format)` lists
  a list as `<list>[]` and each item key as `<list>[].<key>`, nested lists
  likewise.
- Same-format round trip: lists re-encode in order; because items have no
  residue, the round trip is exact only when every member of every item is
  mapped.

## Vector additions

In a vector's `model` object, `"<list>.#"` is the expected number of items
(`"0"` for present and empty; the key `"<list>.#"` with value `"absent"` for an
absent list), and `"<list>[<i>].<key>"` an expected item value, with further
`[<j>].` steps for nested lists.

## Rulings for 0.7

1. **`#text` at the start of a locator** must be written in double quotes
   (`"#text"`), because an unquoted `#` at token start begins a comment.
2. **A count locator** is a bit range of the enclosing scope and needs no
   `field` line; on encode the count is written over any field there. A count
   locator that reaches the group's start is `bad-directive`.
3. **After a counted group** whose count is a locator, a second group starting
   at or beyond it is `bad-directive`, as a `field` is.
4. **`bits` item bounds.** A field of an item, or a nested group with a fixed
   count, that reaches beyond `item <bits>` is `bad-directive`. A nested group
   whose count is a locator is the last thing in its item and may run past
   `item <bits>`; the next item then starts where it ends.
5. **An absent list under a fixed `count <n>`** is `transform-encode`.
6. **`.` on an element that is an object or array** is `transform-decode`.
7. **`geojson` items** use the `json` locators and `null` rule, and the
   `geojson` value types.
8. **`protobuf` items.** A packed occurrence holding no values leaves the list
   absent. A packed payload whose length does not fit its values, and an item
   that is not a submessage where the group body needs one, are
   `malformed-wire`.
9. **`map` and `typemap` lines inside a group** are `bad-directive`; tables are
   pack-wide and are written outside groups.
10. **Rulings 4 and 5 of 0.6 together.** A line whose transform fails is
    forgiven when another line of its key succeeds. A line whose transform
    succeeds and whose table has no entry is not: it fails the decode.

Not in 0.7: an item decoded by kind (a `when` inside a group). A list whose
items differ in layout by a discriminator is carried as raw item fields.

### Stated, not yet pinned by a vector

Seven engines written independently from this section chose differently on the
points below, or noted that no vector decides them.

11. **A scalar (`.`) item with no value.** On `json` and `geojson` it is
    written `null`, and a `null` element decodes to an item with no keys. On
    `xml` it is an empty element. On `protobuf` a `pstring` item is an empty
    occurrence; in a packed numeric field the item is left out, and a list
    whose items all lack the value writes nothing.
12. **A `json` or `geojson` array element that is not an object**, where the
    group body addresses members, is an item with no keys.
13. **A `protobuf` group body** is scalar only when every line is `.`; a body
    mixing `.` with paths is `bad-directive`. A path prefix that is not a
    submessage is `malformed-wire`. When the names before the last repeat, the
    last occurrence is the container.
14. **An absent list under a count locator on `bits`** writes a count of 0.
    Ruling 5 covers a fixed count only.
15. **Inside a `bits` item**, a `const` and a nested group's count locator are
    bounded by `item <bits>` as a field is. On encode the order of writes over
    the same bits is fields, then `const`, then `when`, then counts.
16. **After a locator-counted group**, a fixed-count group that starts before
    it and whose items reach its start is `bad-directive`.
17. **`optional` on a field inside a `bits` item** has no effect: every item
    lies wholly inside the input.
18. **A list where a scalar key is expected** (`default`, a context key, a
    `derive` argument or target) is `key-type-mismatch`; in `derive` it is
    `bad-directive`. `const .`, and `item` on a wire other than `bits`, are
    `bad-directive`, as is any directive inside a group other than `field`,
    `const`, `default`, `group` and `end`.
19. **`typemap`** applies to the key `type` inside items.
20. **An empty or absent list on `xml`** does not create the container
    elements on the way to the group's path.
21. **A `field` whose locator passes through a `group`'s path** in the same
    scope is `bad-directive`.
