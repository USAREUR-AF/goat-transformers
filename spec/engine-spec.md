# Engine specification

Status: Written. Version 0.12. This is what every language's engine implements,
from this document and the vectors, never from another engine's source. The
document grows by one section per version; a later section that replaces an
earlier sentence says so, and the later section holds.

Versions merge in number order, with these exceptions: 0.32 merged before
0.23, 0.29 before 0.27 and 0.28, and after 0.34 come 0.93, 0.52, 0.83, 0.92, 0.46
and 0.64, in that order. "Later" above
means merged later. A number between them that has no section is not yet
built.

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
requires every loaded pack's vectors to pass.

What compares the engines today is the vectors: every engine runs every vector
and must give the stated bytes, so two engines that pass agree on those inputs
(built: the `conformance` workflow runs each engine's vector runner). Some
engines also run their own malformed-input tests, each against itself. A
harness that feeds generated inputs to all engines and compares their outputs
with one another is Designed, not built.

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

---

# Version 0.8: sequential binary layouts

Status: Written. In many binary formats the place of a field depends on what
came before it: an item is present only when a presence bit says so, a part
repeats while an indicator bit is set, a block states its own length. A `bits`
pack with `layout sequential` describes such a message as lines read in order
from a cursor.

```
wire    bits
layout  sequential          # default: fixed (Version 0.2 addressing)
```

`word_bytes` is not used (`bad-directive` if given); `bit_order` applies as in
0.5. A message is a whole number of bytes: after the last line, decode ignores
the remaining bits of the last byte and encode writes them as zero.

## Lines

Inside a sequential pack a locator is a bit length, not a position. Lines are
read, and written, in file order: the common lines, then the selected kind's.

| Line | Decode | Encode |
|---|---|---|
| `field <key> <len> <transform> [options]` | read `len` bits at the cursor through the transform | write the value; an absent key writes zero bits, or the `default` |
| `const <len> <value>` | read `len` bits and ignore them | write the unsigned value |
| `pad <len>` | skip `len` bits | write zero bits |
| `align <n>` | skip to the next multiple of `n` bits from the message start | zero bits to that multiple |
| `when <len> <value>` | read `len` bits; the kind holds when they equal the value | write the value |

`when` lines of a kind are its first lines, and every kind's `when` lines are
read from the cursor position where the common lines ended; the first kind
whose `when` lines all hold is selected, and decoding continues after them. A
kind with no `when` always holds. Field options `via`, `swap` and `trim` apply;
`optional` is `bad-directive`.

## Presence

```
presence <name> <n>            # n presence bits, read as one field
presence <name> fx             # octets of 7 presence bits, each followed by an extension bit
if <name>.<i> [<name>.<j>…]
  …
end
```

`presence` reads the bits at the cursor and numbers them from 1 in reading
order. With `fx`, an octet is 7 presence bits then one bit that is 1 when
another octet follows; the bits of octets not on the wire are 0. An `if` block
is read only when every bit it names is 1; a name is visible from its
`presence` line to the end of the enclosing block. `if !<name>.<i>` requires
the bit to be 0.

On encode a presence bit is 1 when some `if` block naming it (without `!`)
would write a present key, a non-empty list, or a nested presence that is not
all zero; blocks whose bits are 1 are written. With `fx`, trailing octets that
are all zero are not written, and at least one octet is. Because presence is
computed before it is written, the encoder lays out a scope in two passes.

A one-bit indicator before a single part is the same thing written shortly:

```
opt                            # one presence bit, then the block when it is 1
  …
end
```

## Repeats

```
group <list> count <len>       # a count of `len` bits at the cursor, then that many items
  …
end
group <list> while             # each item is preceded by one bit: 1 = an item follows, 0 = the list ends
  …
end
group <list> more              # each item is preceded by one bit: 1 = another item follows this one
  …
end
group <list> fx                # each item ends with one bit: 1 = another item follows
  …
end
```

Group bodies are sequential lines and may hold presence, `opt`, `if` and
nested groups. With `while`, a list of no items is one 0 bit. With `more` and
`fx` a list has at least one item on the wire; an absent or empty list is
`transform-encode` unless the group sits in an `if` or `opt` block, which is
then not written. Rulings of 0.7 on lists apply otherwise.

## Chains

```
chain
  field … 
  fx                           # one bit: 1 = the lines after it, up to the next `fx` or `end`, follow
  field …
  fx
  …
end
```

An extensible item: on decode, at each `fx` line a 0 bit ends the chain. On
encode an `fx` bit is 1 when any line after it in the chain would write a
present key. A chain's last part needs no `fx` line; when the chain ends with
an `fx` line, that bit is written 0.

## Lengths

```
length <len> [bytes|bits] [plus <n>]
  …
end
```

A length field of `len` bits at the cursor, counting the block that follows in
bytes (default) or bits, plus `n` (for a length that counts itself or a header;
`n` may be negative). Decode reads the block within that extent: lines beyond
it read as absent, and content of the extent no line reads is skipped. Encode
writes the block, then the length. A block counted in bytes is padded with zero
bits to a whole byte.

`length … whole` instead of a block: the field holds the length of the whole
message in bytes plus `n`; decode ignores input beyond it, and input shorter
than it is `malformed-wire`.

## Items by kind

```
group <list> … 
  kind <name>
  when <len> <value>
  …
  kind <name>
  …
end
```

In a sequential pack a group body may hold kinds: lines before the first `kind`
are common to every item, then each item selects a kind by its `when` lines as
a message does. The item records its kind (`Item.kind`), and encode selects by
it, or by `requires` lines, as for a message. This is how a list of
differently laid out records is read.

## Errors

Reading past the end of the input, or past a `length` extent where a line
requires bits, is `malformed-wire`. An unbalanced `if`, `opt`, `chain`,
`length` or `group`, an `if` naming an unknown presence or a bit beyond its
size, a positional (`<word>:<pos>:<len>`) locator in a sequential pack, and a
sequential line in a fixed-layout pack are `bad-directive`.

## Vector additions

`"<list>[<i>].@kind"` in a vector's `model` is the kind an item must select.

## Rulings for 0.8

1. **A presence bit that is 1 and that no `if` block names** is
   `malformed-wire`: the message holds a part the pack does not describe.
2. **Defaults and presence.** A key with a `default` in scope counts as present
   when presence bits and `fx` bits are computed.
3. **A chain that ends with an `fx` line** whose bit is 1 on the wire is
   `malformed-wire`.
4. **`!` bits.** A presence bit is computed only from the blocks that name it
   without `!`. A bit named only with `!` is written 0. A block naming `p.3 !p.4`
   sets p.3 when its content is present; when p.4 is then also 1 the block is
   not written.
5. **A present, empty list** under `count` or `while` inside an `if` or `opt`
   block does not set the bit, and decodes back as absent.
6. **`more` or `fx` with an absent or empty list** in a block that is written
   for another reason is `transform-encode`.
7. **`length` extents.** A line that starts at or after the end of the extent
   reads as absent (a group gives an absent list); a line that straddles the
   end is `malformed-wire`. Encode writes every line.
8. **`length <len>` then, in any order and each at most once, `bytes` or
   `bits`, `plus <n>` and `whole`.** `bits` with `whole` is `bad-directive`. A
   stated whole length shorter than what was already read is `malformed-wire`,
   and a whole length is the end of the input, not an extent: a line beyond it
   is `malformed-wire`.
9. **Input beyond the last line**, whole bytes included, is ignored.
10. **`when` placement.** A `when` before the first `kind` is a common `when`
    of 0.5. A `when` after another line of its kind, or inside a block, is
    `bad-directive`.
11. **Kind names** are unique within one body: the message's kinds, or one
    group's item kinds.
12. **Presence names.** Declaring a name twice in one block is `bad-directive`;
    a nested block may declare the name again and hides the outer one to its
    end. A message presence may be named inside a group item: any item with the
    content sets the bit.
13. **More keys on one field.** An `also <key> [via <table>]` line directly
    after a `field` line, or after another `also` of that field, binds another key to the same bits through the same
    transform. Decode fills both; encode writes the value of the earliest of
    them that is present (ruling 16 of 0.5). `also` anywhere else is
    `bad-directive`.
14. **Limits.** Presence, `const`, `when`, count and length fields are 1 to 64
    bits. `layout` on a wire other than `bits` is `bad-directive`. A count
    larger than the bits left is `malformed-wire` before any item is read.
15. **Ruling 21 of 0.7** applies to `field` lines only.

## Model additions in 0.8

```
uses  <module>              # a line of a model module, repeatable
```

A module may name other modules; its `derive` lines may then use their keys as
arguments. The directory loader loads `core.def` first and then each module
after the modules it uses; a cycle is `bad-directive`. `load_model` of a module
whose used module is not loaded is `unknown-module`. A public module uses only
public modules (`distribution-violation`).

Derive functions added:

| Function | Arguments | Result |
|---|---|---|
| `day_seconds` | a (`int`, epoch ms) | seconds since UTC midnight of that instant, as a float |
| `any` | a b … (`int`) | 1 when any present argument is not 0, else 0; needs at least one argument present, not all |
| `not` | a (`int`) | 1 when a is 0, else 0 |
| `parse_int` | a (`string`) | the decimal integer the text holds; absent when it is not one |
| `text_of` | a (`int`) | the integer as decimal text |

`any` is the one function whose target is set when only some arguments are
present.

### Stated, not yet pinned by a vector

Seven engines written independently from the 0.8 sections chose differently on
the points below, or noted that no vector decides them.

16. **`also` and defaults.** Encode writes the value of the earliest of the
    field's keys that the entity holds; when it holds none, the default of the
    earliest key that has one.
17. **Which `if` blocks name a presence bit** (ruling 1): every `if` in the
    pack that can see the name, in any kind, with or without `!`.
18. **`when` placement.** `requires` and `default` lines do not count as lines
    of the kind: a `when` may follow them.
19. **A `default` inside a block** belongs to the enclosing message kind or
    group body.
20. **Skips.** `pad` and `const` past the end of the input are
    `malformed-wire`. `align` stops at the end of the input or extent without
    error.
21. **At the end of a `length` extent.** An indicator bit of a `while`, `more`
    or `fx` group, an `fx` line of a chain, and a presence field that start at
    or after the end read as 0; a continuation octet of an `fx` presence there
    is `malformed-wire`. `const`, `pad`, `opt` and a nested `length` there read
    as absent.
22. **Content for a presence, `opt` or `fx` bit** is a present key or non-empty
    list at any depth of nested `if`, `opt`, `chain` and `length` blocks,
    without evaluating the nested conditions. A `const` is not content.
23. **A list in two groups of one sequential scope** is allowed when the two
    groups sit in different `if` or `opt` blocks, and `bad-directive` otherwise.
24. **Header and table directives** (`format`, `version`, `distribution`,
    `source`, `uses`, `wire`, `layout`, `bit_order`, `map`, `typemap`) inside
    any block are `bad-directive`.
25. **A count** (ruling 14) is compared with the bits left, not with count
    times item size.
26. **`Item.kind`** holds the format with the kind name. Encode selects by it
    only when it names the format being written and a kind the group has;
    otherwise by `requires`.
27. **A `when` before the first `kind` of a group body** is a common `when` of
    every item; an item that fails it is `no-kind`.
28. **`parse_int`** accepts an optional `-` and then digits, leading zeros
    included, within 64 bits; anything else leaves the target absent.
29. **Module checks.** For a module: `missing-distribution`, `missing-source`,
    `distribution-refused`, `unknown-module`, `distribution-violation`, the
    `derive` checks, `duplicate-module`. A `derive` target is a key of `core`
    or of the module itself. A chain is one block for presence names.
30. **Ruling 13 of 0.7** applies to every protobuf path: a prefix that is not a
    submessage is `malformed-wire`, inside or outside a group. **Ruling 21 of
    0.7**: a field at exactly the group's own path is refused on `xml` and
    allowed on `json`, `geojson` and `protobuf`.
31. **Ruling 30 and `when`.** A `when` path whose prefix is not a submessage
    does not hold; it is not an error. Ruling 13 of 0.7 is about `field` and
    `group` paths.
32. **Ruling 9 of 0.6 and ruling 29 together.** A `derive` line refused on its
    own text (function name, parameter, number of arguments) is a line error,
    raised as the file is read. The checks that need keys (declared, typed,
    used module loaded) run in the place ruling 29 gives.
33. **Ruling 23, further.** Two groups of one list are allowed only when
    neither group's block encloses the other's. When both are on the wire,
    decode keeps the later group's items.
34. **Rulings 7 and 21 together.** A group whose first indicator bit lies at or
    after the end of the extent gives an absent list. Ruling 21 applies to the
    indicators after the first.

## Malformed input (0.8)

An engine reads messages from untrusted senders. No input makes an engine
crash, read outside the input, or use stack or memory without bound. An input
that is not a well-formed message of its wire fails with `malformed-wire`,
whatever the pack maps. `spec/vector-format.md` lists the cases per wire and
the packs `conformance-malformed-*` pin them.

35. **Nesting limit.** On `xml` (elements, root is level 1) and on `json` and
    `geojson` (arrays and objects, outermost is level 1) a message nested
    deeper than 64 levels is `malformed-wire`. Exactly 64 levels converts.
36. **Hex text.** Hex input with an odd number of digits, or any character
    that is not a hex digit or whitespace (a sign included), is
    `malformed-wire` on `bits` and `protobuf`.
37. **Empty XML input.** An input with no element is `malformed-wire`.
    `missing-root` is for a well-formed document whose root has another name.
38. **Protobuf syntax.** A truncated varint, a varint longer than 10 bytes, a
    length or fixed-width value that runs past the input or past its enclosing
    submessage, wire types 3 and 4, and a field number above 2^29-1 are
    `malformed-wire`. The whole message is checked, whether or not the pack
    maps the field or has kinds. Bytes of a submessage a path walks into that
    do not parse are `malformed-wire`, not a field failure.
39. **JSON grammar.** Numbers, escapes and string characters follow RFC 8259:
    a leading zero, a leading `+`, a bare `.`, an unknown escape or a raw
    control character in a string is `malformed-wire`.
40. **Details of rulings 36 to 39, pinned by `conformance-malformed-*`.**
    - Whitespace in hex text is space, tab, line feed and carriage return
      only. Any other character that is not a hex digit is `malformed-wire`.
    - Protobuf field number 0 and wire types 3, 4, 6 and 7 are
      `malformed-wire`.
    - A ten-byte varint whose last byte is greater than 1 (bits above bit 63)
      is `malformed-wire`.
    - A truncated varint inside a packed field is `malformed-wire`.
    - A `\u` escape that is half of a surrogate pair without its other half
      is `malformed-wire` on `json` and `geojson`.
    - A document type declaration anywhere in an `xml` input is
      `malformed-wire`. No engine declares, expands or fetches an entity
      other than the five predefined ones and numeric character references.
    - A numeric character reference takes decimal or hexadecimal digits only
      (no sign) and must name a character XML 1.0 allows.

    Not ruled: invalid UTF-8 inside a text input. A vector input is JSON
    text and cannot carry it.

---

# Version 0.9: absent-value sentinels

Status: Written. Many formats reserve a wire value to mean "no value": all
bits set in a binary field, `0` for a latitude that is not known, `9999999.0`
for an altitude, an empty text. Before 0.9 such a value decoded as a number.
A field option names the wire values that mean absent.

```
field  <model-key> <locator> <transform> [options] absent <value>[,<value>…]
```

`absent` is a field option (Version 0.6, Field options) and takes one
argument: one or more values separated by commas. It is valid on every wire,
in fixed and sequential `bits` layouts, in kinds and inside groups. It is not
a `default`, and it does not change `when`, `requires` or `const`.

## The raw value

A sentinel is compared with the raw wire value of the field, before `via`,
`typemap` and the transform, in the way a `when` value is (Version 0.5):

| Wire | Raw value | A sentinel is written as | Matches when |
|---|---|---|---|
| `bits` (fixed and sequential) | the field's `len` bits read as an unsigned integer, as `uint` reads them, after `swap` | an unsigned decimal integer below `2^len` | the integers are equal |
| `protobuf`, `pvarint` and `psint` | the varint as an unsigned 64-bit integer, before zig-zag | an unsigned decimal integer below `2^64` | the integers are equal |
| `protobuf`, `pdouble` and `pfloat` | the 8 or 4 bytes as an unsigned little-endian integer | an unsigned decimal integer below `2^64` or `2^32` | the integers are equal |
| `protobuf`, `pstring` | the bytes as text | text | the texts are equal |
| `xml` | the attribute value or element text after character references are resolved, not trimmed | text | the texts are equal |
| `json`, `geojson` | a string member's text, or a number's or boolean's canonical text (ruling 11 of 0.5 for the reverse) | text | the texts are equal |

On a text wire a leading `=` is stripped from each value, as for `when`
(`=present` is the text `present`). The quoted empty token `""` is the one
value "the empty text". A value cannot hold a comma.

## Decode

For each field whose wire place is present, the raw value is compared with
the field's sentinels before the transform runs. When it equals one, the field
yields no value: the key is not set by this line, the transform is not run, and
the line is not a failed field (ruling 9 of 0.1.1). Otherwise decode is
unchanged.

A wire place that holds a sentinel is mapped: it is not residue.

## Encode

When the entity has no value for the key and no `default` applies (Version
0.6, Defaults), a field with `absent` writes its first sentinel as the raw
value at its locator:

- `bits`: the integer into the field's bits, low `len` bits, then `swap`.
  In a sequential layout this replaces the zero bits an absent key writes.
- `protobuf`: the integer as a varint for `pvarint` and `psint` (no zig-zag
  is applied to it), as 8 or 4 little-endian bytes for `pdouble` and
  `pfloat`, the text for `pstring`.
- `xml`: the text at the attribute or element.
- `json`, `geojson`: the text, typed as a `when` value is written (ruling 11
  of 0.5): canonical JSON number text is a number, `true` and `false` are
  booleans, anything else a string; `=` forces a string.

When the entity has a value, it is written as before, even when the result
equals a sentinel.

## Load errors

`bad-directive`:

- `absent` with no argument, or given twice on one line (ruling 12 of 0.6);
- an empty value in the list (`1,,2`), except the single value `""`;
- on `bits` and on the integer forms of `protobuf`, a value that is not an
  unsigned decimal integer or does not fit the raw value's width;
- on a `bits` field longer than 64 bits;
- on `protobuf`, a value that is `""` on a transform other than `pstring`.

## Rulings for 0.9

1. **Several lines for one key.** A line whose raw value is a sentinel counts
   as a line whose locator is absent (Version 0.6, One key at several
   locators): decode goes on to the next line of the key. Encode writes the
   first sentinel at every line of an absent key that has `absent`; a line of
   that key without `absent` writes what an absent key wrote before 0.9:
   nothing on text wires and `protobuf`, zero bits on `bits`.
2. **Order with other options.** On decode the sentinel check comes after
   `swap` and before `trim`, `via`, `typemap` and the transform; on encode the
   sentinel is written in place of all of them. On `bits` a sentinel is an
   integer, so an `ascii` field that is all NUL bytes matches `absent 0`.
3. **`optional`.** A field beyond the end of the input is absent by `optional`
   and the sentinel is not consulted. Encode writes the sentinel as for any
   absent key.
4. **Presence.** In a sequential layout, a sentinel written for an absent key
   is never content: not for a presence bit, an `opt` bit, an `fx` extension
   bit of a chain, or a repeat indicator (Version 0.8). A block that would
   write only sentinels is not written and its bit is 0.
5. **Groups.** Inside a group the option applies per item: an item whose
   field holds a sentinel lacks the key, and an item that lacks the key writes
   the sentinel. An item whose every field holds a sentinel is still an item.
   A scalar item field (`.`) with `absent` writes the sentinel for an item
   that lacks the value, on every wire, in place of ruling 11 of 0.7 (no
   `null`, no empty element, not left out of a packed field). On decode a
   `null` array element is an item without the value, before any sentinel
   check.
6. **Context and derivations.** A key left absent by a sentinel is absent for
   `convert` step 2 and 3 (Version 0.6, Order inside `convert`): context may
   supply it and a derivation may set it.
7. **Same-format round trip.** A field holding a sentinel other than the first
   re-encodes as the first. A wire place missing from the input gains the
   sentinel on re-encode (`<e/>` becomes `<e alt="9999999"/>`), and a block
   left out by ruling 4 is dropped. A pack with one sentinel per field
   round-trips byte-exact when every field with `absent` is on the input
   wire and no presence block holds only sentinels.
8. **Capability.** `absent` does not change `model_keys(format)`.

9. **Numbers on `json` and `geojson`.** A sentinel that is JSON number text
   (RFC 8259 grammar) is read as a double at load and held as its canonical
   text (ruling 3 of 0.1.1): `9999999.0` is held as `9999999`. It is compared
   with the canonical text of the wire number and written as that number. A
   sentinel that is not number text is compared and written as a string,
   except `true` and `false`, which are booleans.
10. **`geojson` coordinates.** A `geometry.lon`, `geometry.lat` or
    `geometry.alt` slot compares the canonical text of its number. On encode
    a sentinel written for `lon` or `lat` counts as a value for ruling 5 of
    0.1.1, so `geometry` is written; a sentinel for `alt` is written as the
    third element.
11. **Tokens.** The token after `absent` is always its argument, even when it
    is the name of an option (`absent optional` names the text `optional`).
    The quoted empty token `""` is a token whose value is the empty text, on
    every directive. The argument is split on commas; a value cannot contain
    a comma or a double quote, so `"",0` is `bad-directive`.
12. **`=`.** A leading `=` is stripped on `xml`, `json` and `geojson` only;
    on `pstring` it is part of the text. A value empty after stripping is
    `bad-directive`; only `""` names the empty text.
13. **Values a transform cannot hold.** On `json` and `geojson`, `null` is
    `bad-directive` as a sentinel. On the `json` `bool` transform a sentinel
    other than `true` or `false` is `bad-directive`.
14. **XML text.** The raw value is the text after the predefined entity
    references and the character references are resolved: `absent "a&b"`
    matches `a="a&amp;b"`. It is not trimmed, also where an engine trims
    element text before the transform: `<e> 0 </e>` does not match
    `absent 0`.
15. **Protobuf wire type.** A field whose wire type is not the one its
    transform fixes is `transform-decode`, before any sentinel check.
16. **Precedence on one place.** A sentinel is written only where no line
    whose key is present, or has a `default`, writes: on `bits` such a line
    wins over a sentinel whatever their order (ruling 5 of 0.5), and on a
    text wire it is the value of ruling 16 of 0.5. A sentinel write is a
    field write for the order of ruling 15 of 0.7, and a written field for
    ruling 14 of 0.5 (`when <path> present` on `protobuf`).

### Stated, not yet pinned by a vector

17. **Forced strings on `json`.** On the `bool` transform `=true` and
    `=false` are strings, so they are `bad-directive` (ruling 13). `=null`
    is the string `null` and loads.
18. **Number text out of range.** A `json` or `geojson` sentinel that is
    number text but does not fit a finite double (`1e400`) is
    `bad-directive`.
19. **Wire integers on `json`.** A wire number is put in canonical text
    through a double, also when it is an integer; this differs from its
    written digits only above 2^53.
20. **Same place.** On text wires and `protobuf`, two lines write the same
    place when their locators are the same text.
21. **`"@absent"` clash.** Only a listed entry that is, as text, a member of
    `model` makes the vector invalid; a list name beside `"<list>.#"` is not
    a clash.
22. **A sentinel and a `default` on one key.** A wire sentinel decodes as
    absent, so a round trip writes the default in its place.

### Rulings from the seven implementations

23. **Position on a text wire.** A member or attribute that several lines
    name is written once, at the position of the first line that names its
    locator, whichever line's value or sentinel is written there (ruling 26
    of 0.5 for `when`). Pinned by `conformance-absent-place-json` and
    `conformance-absent-place-xml`.
    The ruling places one member or attribute that several lines name; it
    does not move elements, nested objects or groups, whose order stays that
    of ruling 10 of 0.5 and Version 0.7. A `when <locator> present`
    line names no position: it writes nothing and does not map the member
    (ruling 27 of 0.5), so only `field`, `const` and valued `when` lines
    count as naming the locator.
24. **`also` (ruling 13 of 0.8).** The keys of `also` lines share their
    `field` line's sentinels: a sentinel on the bits leaves every key of the
    line absent, and when no key of the line has a value or a `default`, the
    field's first sentinel is written. Pinned by `conformance-absent-seq-also` and vector 13 of `conformance-absent-json`.
25. **`geojson` coordinates** take only number text as a sentinel; any other
    value on a `geometry.*` locator outside a group is `bad-directive`. Inside
    a group the locator is a member path, as on `json`.
26. **`=` and `null` on `bool`.** Ruling 13 holds before ruling 17: on the
    `bool` transform every value other than the bare `true` and `false` is
    `bad-directive`, `=null` included.
27. **One `=`.** Only one leading `=` is stripped: `absent ==` on `xml` is
    the text `=`.
28. **`""` on `json` and `geojson`** is the empty string, compared with a
    string member and written as `""`.

## Vector additions

A conversion vector's `model` may hold `"@absent": ["<key>", …]`: each listed
key must be absent from the decoded entity (from the completed entity under
`"@complete": true`). `"@absent"` is not a model key. An entry may be an
item path `"<list>[<i>].<key>"` (the item exists and lacks the key) or a list
name (the entity has no such list, as `"<list>.#": "absent"`). A listed key
that is also a member of `model` makes the vector invalid, and an invalid
vector fails the run.
---

# Version 0.10: the `text` wire

Status: Written. A `text` format is one record of ASCII text: fields separated
by a delimiter, optionally framed by a start marker and a checksum. A field may
also be read as character columns, which covers fixed-width records. Input and
output are the record's text.

```
wire       text
delimiter  <character | none>     # default ","
start      <text>                 # optional: every record begins with this text
checksum   <none | nmea>          # default none
field      <model-key> <locator> <transform> [options]
```

`delimiter` takes one character from 0x21 to 0x7E other than `"` (quoted
where `#` would otherwise begin a comment), or `none`: the record is then one
field. `start` is one or more characters from 0x21 to 0x7E that do not include
the delimiter. Each of the three directives appears at most once, before the
first `kind`. On another wire, more than once, or with another value they are
`bad-directive`; so is `delimiter "*"` with `checksum nmea`, and a locator of a
field other than 0 under `delimiter none`.

Every rule that Versions 0.5 to 0.8 state for "text wires" (`xml`, `geojson`,
`json`) holds for `text` as well, unless this section states otherwise: the
leading `=` of a `when` or `const` value, ruling 26 of 0.5 (a `when` and a
`field` on one locator), ruling 27 of 0.5 (`when … present` does not map), and
nothing written for `present`.

## Reading a record

Decode takes the input text through these steps, in order. Each failure is
`malformed-wire`.

1. One line terminator at the end, `\r\n` or `\n`, is removed. No other
   character is removed.
2. Every remaining character is from 0x20 to 0x7E.
3. With `start`, the text begins with it; the start text is removed.
4. With `checksum nmea`, the text ends with `*` and two hexadecimal digits
   (`0-9`, `A-F`, `a-f`). Those digits are the XOR of every byte of the text
   before the `*`, as an 8-bit value. The `*` and the digits are removed. A
   `*` left in the text is `malformed-wire`.
5. The text that remains is the body. It splits at every delimiter into fields,
   numbered from 0. A body with no delimiter is one field; an empty body is one
   empty field. With `delimiter none` the body is field 0.

## Locators

| Locator | Addresses |
|---|---|
| `<i>` | field `i`, its whole text |
| `<i>:<from>:<len>` | a column: `len` characters of field `i` from character `from` (both from 0; `len` from 1) |
| `<i>+<j>` | a pair: fields `i` and `j` as one value, for the transforms that take two parts (`dm`, `hms_dmy`) and only for them |

A field that is empty, or that the record does not have, is absent. A column
is absent when its field has no character at `from`; when the field ends
inside the column, the column is the characters the field has from `from` on
(a fixed-width record whose trailing spaces were cut reads as it would with
them). A column's text has its trailing spaces removed, and for the numeric
transforms its leading spaces too; a column that is then empty is absent. The
numeric transforms are exactly `int`, `int:<w>`, `float`, `dec:<f>` and
`dec:<f>:<w>`, here and in "Writing a record". A pair is absent when either
of its fields is absent (a receiver that has a time and no date yet sends one
half). The two fields of a pair may be in either order; the first index
named is always the transform's first part (`2+1` reads the `dm` digits or
the `hms_dmy` time from field 2). A pair whose two indexes are equal, a
pair on a transform that does not take two parts, and a field or column on one
that does, are `bad-directive`.

`when` and `const` take a field or a column, not a pair (`bad-directive`). A
`when` compares the field's or the column's text, as read above (the column's
trailing spaces removed), with its value; `present` holds when the field or
column is not absent. A `when` or `const` value is not empty, holds no
delimiter, no `*` under `checksum nmea`, only characters from 0x20 to 0x7E,
and no space at its start or end; on a column it is at most `len` characters.
Anything else is `bad-directive`.

## Transforms for `text`

`string`, `int`, `float` and `iso8601_ms` apply, with these readings on this
wire:

- `string` decodes the text as it is.
- `int` decodes an optional `+` or `-` and one or more digits, leading zeros
  allowed, from -2^63 to 2^63-1; anything else is `transform-decode`.
- `float` and `dec` decode an optional `+` or `-`, then digits with at most
  one `.`, at least one digit in all (`5.`, `.5` and `05.50` are numbers). An
  exponent is not accepted. The value is the double nearest the decimal; a
  decimal whose nearest double is not finite is `transform-decode`.
- On encode, text from any transform that holds the delimiter, a `*` under
  `checksum nmea`, or a character outside 0x20 to 0x7E is `transform-encode`.

The transforms below are valid only on the `text` wire (`bad-directive`
elsewhere), and the bits, protobuf and `bool` transforms are `bad-directive`
on it.

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `int:<w>` | int | as `int` | the decimal digits, zero-padded to at least `w` digits after any `-` |
| `dec:<f>` | float | as `float` | `n = round(x * 10^f)`; the digits of `|n|`, zero-padded on the left to at least `f + 1` digits, with a `.` before the last `f` (none when `f` is 0); `-` first when `n < 0` |
| `dec:<f>:<w>` | float | as `float` | as `dec:<f>`, then zeros after any `-` until the text without the sign is at least `w` characters, the `.` counted |
| `dm:<d>:<f>:<PN>` | float | a pair: the first field is exactly `d` digits of degrees and two digits of minutes, then optionally `.` and digits; the second is the letter `P` or `N`. The value is `degrees + minutes / 60`, negated for `N` | `m = round(|x| * 60 * 10^f)`; the degrees `m div (60 * 10^f)` as `d` digits, the minutes `m mod (60 * 10^f)` as two digits, `.` and `f` digits (no `.` when `f` is 0); the second field `N` when `x < 0` and `m > 0`, else `P` |
| `hms:<f>` | float | `hhmmss` then optionally `.` and digits: seconds since midnight, `h * 3600 + m * 60 + s` | `n = round(x * 10^f)`, `0 <= n < 86400 * 10^f`; `hh`, `mm`, `ss` of `n div 10^f`, then `.` and the `f` digits of `n mod 10^f` (no `.` when `f` is 0) |
| `hms_dmy:<f>` | int | a pair: a time as for `hms` and a date `ddmmyy`, as epoch milliseconds UTC. `yy` from 80 to 99 is 19yy, from 00 to 79 is 20yy. Fraction digits beyond milliseconds are truncated | the time as for `hms` with `f` fraction digits, truncated from the milliseconds; the date as `ddmmyy`. A year outside 1980 to 2079 is `transform-encode` |

Rules for these transforms:

1. **Parameters.** `w` is 1 to 20; `f` is 0 to 9 for `dec` and `dm`, 0 to 3
   for `hms` and `hms_dmy`; `d` is 1 to 3; `P` and `N` are two different
   letters `A` to `Z`. Anything else, bare `dec` included, is
   `bad-directive`. An empty quoted value (`""`) is a token, and is refused
   wherever a value must not be empty.
2. **Arithmetic.** `10^f` is the exact double. Products are computed in
   doubles from left to right; `round` is half away from zero, as for
   `linscale`. A rounded `|n|` or `m` of 2^53 or more, or a value that is not
   finite, is `transform-encode`.
3. **Decode ranges.** `dm` minutes of 60 or more, `hms` hours of 24 or more,
   minutes or seconds of 60 or more, a date that does not exist, a `dm` letter
   other than `P` or `N` (case counts), and text not of the stated shape are
   `transform-decode`. A `.` in `dm`, `hms` and `hms_dmy` text is followed by
   at least one digit. `dm` decode reads the minutes, fraction included, as
   the double nearest their decimal, divides by 60 and then adds the degrees;
   `hms` decode computes `h * 3600 + m * 60` as an integer and then adds the
   seconds as the double nearest their decimal.
4. **Out of range on encode.** An `hms` value whose rounded `n` falls outside
   `0 <= n < 86400 * 10^f` is `transform-encode`.
5. **Degrees too large.** A `dm` value whose degrees do not fit `d` digits is
   `transform-encode`.

## Writing a record

Encode builds the fields of the selected scope (common lines, then the kind's)
and then the record.

1. Every `field` whose key is present (or has a `default`), every `const` and
   every `when` writes its text at its locator; `when` and `const` are written
   last, over any field (ruling 5 of 0.5). A pair writes its two fields. Where
   two lines write the same field or overlapping columns, the earlier line's
   characters stand, and `when` and `const` are written over both.
2. A column writes into its field at `from`. Text shorter than `len` is padded
   to `len`: on the left with `0` (after any `-`) for the numeric transforms,
   on the right with spaces for the others. Text longer than `len` is
   `transform-encode`. Characters of a field that no column writes are spaces,
   up to the end of the furthest column written; a field no column writes is
   empty.
3. Residue of this format (below) is written at its field, unless a line of
   the selected scope addresses that field. Here and below, a line addresses
   a field as the Residue section states: `when … present` does not.
4. The record has as many fields as one more than the highest field index that
   a line of the selected scope other than a group addresses, that a group's
   items write, or that residue written in step 3 names, whichever is highest.
   Fields not written are empty.
5. While the last field is empty, at least one line addresses it, and every
   line that addresses it carries the `optional` option, that field is
   removed. A field no line addresses stops the removal. So a pack reads a
   record with or without trailing fields that later versions of a format
   added, and writes the shorter form when the entity lacks their values.
6. The fields are joined by the delimiter; the `start` text is put first.
   With `checksum nmea`, `*` and the XOR of every byte after the start text,
   as two uppercase hexadecimal digits, are put last. No line terminator is
   written.

Field options on `text`: `via`, and `optional` with the meaning of step 5
only (it does not change decode). `swap` and `trim` are `bad-directive`.

## Residue

Every field of the record that is not empty and that no line of the common
scope or the selected kind addresses (a field, a column, a part of a pair, a
`when` other than `when … present`, a `const`, a group's fields) is residue of
the format, keyed by its index in decimal, with its text. A field that a line
addresses by columns is mapped whole: characters no column covers are not
carried. No field at a group's index `i` or beyond is residue.

## Groups

```
group  <list> <i> item <n>
  field  <model-key> <k> <transform>        # k from 0 to n-1: relative to the item
  …
end
```

Items start at field `i`; each is `n` fields long (`n` from 1). Inside the
group the locators `<k>`, `<k>:<from>:<len>` and `<k>+<m>` count from the
item's first field, and `k` (and `m`) is below `n` (`bad-directive`
otherwise). The items run to the end of the record: their number is the number
of fields from `i` on, divided by `n` and rounded up, so a last item that the
record cuts short has its missing fields absent. The list is present when the
record has a field at index `i` or beyond, and absent otherwise. On encode the
items are written back to back from field `i`, each item `n` fields long
whether or not its keys are present, so the record ends at field
`i + items * n - 1`; an empty or absent list writes no fields.

The group is the last thing in its scope: a `field`, `when` or `const` of the
scope at index `i` or beyond, a second group in the scope, a nested group,
`count`, and `optional` inside the group are `bad-directive`. Rulings of 0.7 on
lists apply otherwise.

## Kinds

Kinds select by `when` lines as on the other text wires (Version 0.5). The
record is read through steps 1 to 5 of "Reading a record" before any `when` is
checked, so a record that fails its checksum is `malformed-wire`, not
`no-kind`.

## Vectors

`input` and `expect` of a `text` format are the record's text in a JSON
string; a line terminator in `input` is written `\r\n` or `\n`.

## Rulings for 0.10

1. **Same-format round trip.** A record converts to itself unchanged when its
   numbers are in the form the transforms write, its checksum digits are
   uppercase, it has no line terminator, and it has exactly the fields the
   selected scope writes (step 5 removes trailing `optional` fields that are
   empty).
2. **Load order.** Locator syntax and transform parameters are checked as the
   file is read. The checks that relate `wire`, `delimiter`, `start` and
   `checksum` to one another and to the locators, the `when` and `const`
   value checks, and the group and scope checks run after the file is read and
   before `missing-distribution`, as ruling 25 of 0.5 states for the other
   whole-file checks.
3. **A column and a whole-field line on one field** are allowed. Decode reads
   each. Encode writes the whole-field line's text when its key is present or
   has a `default`, and the columns only otherwise; `when` and `const` columns
   are written over the field's text in either case, the text first padded
   with spaces to reach them.
4. **Terminator.** Step 1 removes `\r\n` when the text ends with it, and
   otherwise `\n`.
5. **Which error.** When one record has several failing fields, decode fails
   with `transform-decode` (ruling 9 of 0.1.1); `malformed-wire` is decided
   by steps 1 to 5 of "Reading a record" before any field is read.
6. **A `when` on a column** that its field does not reach does not hold.
7. **Empty items.** A record whose field `i` is empty and last decodes to a
   list of one item with no keys, and that list writes `n` empty fields from
   field `i`. A list of no items writes no field, so the record ends before
   field `i`.
8. **Earlier sections.** On `text`, `item` is part of the group line (ruling
   18 of 0.7 is about the other wires), `optional` has the meaning of step 5
   (the table of field options in 0.6 is about `bits`), and residue is written
   only into the format it was decoded from, as on every wire (the
   per-format rule of Residue in 0.1).
9. **`when` values on `text`** are compared with the field's text, or the
   column's text with its trailing spaces removed, before any transform: a
   row of the table in "`when` values, by wire" of 0.5.
10. **Checks that need the wire.** A check that depends on the wire (a pair
    against its transform, a transform valid on another wire, a directive of
    another wire) runs after the file is read, wherever the `wire` line stands.
11. **Overlap among `when` and `const`.** Where two `when` or `const` lines
    write the same characters, the earlier line's stand.
12. **`delimiter none` and groups.** A `group` in a pack with `delimiter none`
    is `bad-directive`.
13. **`iso8601_ms` on `text`** reads as on the other text wires (0.6).
14. **Locator syntax.** A `text` locator that is not one of the three forms
    of "Locators" (`1:x`, `1:0:0`, `+2`, an index with a sign) is
    `bad-directive`.
15. **Minutes and seconds of 60.** The range checks of rule 3 of the
    transforms compare the two digits of `dm` minutes and of `hms` hours,
    minutes and seconds as integers, before any fraction: `59.99999999999999999`
    minutes are accepted, and read as the double nearest them (60.0).

16. **`absent` (0.9) on `text`** is `bad-directive` in 0.10: an empty field
    is already absent on this wire, and the raw value of a sentinel, column
    padding and the removal of trailing `optional` fields with it are not
    stated yet.

---

# Version 0.11: strict rulings

Status: Written. Version 0.11 adds no directive to the pack language. It rules
on the places where the earlier sections were silent, so that seven engines
written apart give the same bytes and the same named error. The direction of
every ruling is strict: a value that is not exactly what a rule accepts fails
with a named error. Nothing is trimmed, clamped, wrapped or skipped silently.
Where a ruling replaces an earlier sentence, it says so. Each ruling names the
packs or vectors that pin it; the generators
`tools/gen/conformance-rulings011-vectors.py` (rulings 1 to 5) and
`tools/gen/conformance-rulings011b-vectors.py` (rulings 6, 7 and 9) derive every
expected value from the rule text and import no engine.

Version 0.9 (absent-value sentinels) and Version 0.10 (the `text` wire) stand
before this section. Where a ruling below names wires, it names them; a ruling
that does not name the `text` wire does not change it, and the readings of
Version 0.10 hold there. Each place where a ruling meets the `absent` option of
0.9 or the `text` wire of 0.10 is stated in the ruling, and the vectors of 0.9
and 0.10 keep their expected bytes and errors.

## Rulings for 0.11

### Ruling 1: XML text

Pinned by `conformance-xml-text`, `conformance-xml-text-json` and, for a
`when` and a `const` of `""` (1m; `""` is the token of ruling 11 of 0.9),
`conformance-xml-empty`.

Output:

- **1a. Attribute values** are written between double quotes. Inside one,
  `&` is `&amp;`, `<` is `&lt;`, `>` is `&gt;`, `"` is `&quot;`, a tab is
  `&#9;`, a line feed is `&#10;` and a carriage return is `&#13;`.
- **1b. Text content** writes `&` as `&amp;`, `<` as `&lt;`, `>` as `&gt;`
  and a carriage return as `&#13;`. A tab, a line feed, `"` and `'` are
  written as themselves.
- **1c. Nothing else is escaped.** The apostrophe is never escaped. Every
  other character is written as UTF-8, never as a reference. An engine writes
  no CDATA section, no XML declaration and no byte order mark.
- **1d. A character XML 1.0 cannot hold** in a string that is to be written
  (below U+0020 other than tab, line feed and carriage return; U+FFFE;
  U+FFFF) is `transform-encode`.
- **1e. The empty string** as text content writes the element with no content
  (`<name/>`); as an attribute value it writes `name=""`.
- **1f. Residue** attribute values are held decoded and are written by 1a.
  A sentinel of the `absent` option (0.9) that is written on `xml` is written
  by 1a and 1b as well, and 1d holds for it: `absent "a&b"` on element text
  writes `a&amp;b`.

Input:

- **1g. Byte order mark.** One U+FEFF at the very start of the input is
  skipped. Anywhere else it is a character like any other, so a second one,
  or one after the root element, is `malformed-wire` by the rules for content
  outside the root.
- **1h. Line ends.** Before anything else is read, each carriage return
  followed by a line feed, and each carriage return that stands alone, is
  read as one line feed (XML 1.0, section 2.11). A carriage return reaches a
  value only as the reference `&#13;`.
- **1i. Attribute values** may stand between double quotes or between
  apostrophes. A tab or line feed written literally inside one is read as a
  space (XML 1.0, section 3.3.3); one written as a reference is kept. A `<`
  inside an attribute value is `malformed-wire`. An attribute with no
  characters is the empty string, present.
- **1j. References.** The five predefined entities (`&amp;`, `&lt;`, `&gt;`,
  `&quot;`, `&apos;`, in lower case) and numeric character references (ruling
  40 of 0.8) are decoded in attribute values and in text. The text a
  reference gives is not read again. Every other `&` is `malformed-wire`: an
  unknown name, a name with no `;`, a `&` with nothing after it. This holds
  anywhere in the document, whether or not a line maps the place.
- **1k. CDATA.** A CDATA section inside the root element is character data
  exactly as written; references inside it are not decoded. One with no end,
  or one outside the root element, is `malformed-wire`. An empty CDATA
  section (`<![CDATA[]]>`) is no character data: an element whose only
  content it is has no text (1m).
- **1l. Comments and processing instructions** inside the root element are
  skipped, and their content is not read. The text on both sides of one is
  one text. One with no end is `malformed-wire`.
- **1m. `#text`** of an element is all character data directly inside it,
  text and CDATA sections joined in document order, without the character
  data of its child elements. It is kept exactly: no trimming, no collapsing
  of whitespace, and text that is only whitespace is text. An element with no
  character data has no text: `#text` is absent, not the empty string. `when
  <locator> present` is unchanged (the element exists). A `when` with a
  value on such a text does not hold, the empty text `""` included, and a
  `const` of `""` on an element's `#text` writes the element with no content
  (`<e/>`, as 1e). For the `absent` option (0.9) such an element's text is a
  wire place that is not present, so no sentinel is compared with it. This
  replaces the reading of Version 0.9 for element text: `absent ""` can no
  longer match the text of an element, and the key is absent either way. It
  still matches an attribute with no characters (1i).
- **1n. No transform trims.** `string` hands the text on as it is; `int`,
  `float` and `iso8601_ms` refuse text with whitespace before or after the
  value (rulings 2 and 3). The field option `trim` (0.6) is unchanged: it is
  valid on `bits` with `ascii` only. Ruling 14 of 0.9 (a sentinel is compared
  with the text before any trimming) holds, and since no engine trims XML text
  its clause about an engine that trims has no case left.
- **1o. An attribute name twice on one element** is `malformed-wire`, on any
  element, mapped or not.

### Ruling 2: numbers in text

Pinned by `conformance-numbers`, `conformance-numbers-json`,
`conformance-numbers-geojson` and `conformance-numbers-f64`, and by load
vectors 425 to 428 and 436 to 441. `conformance-numbers-absent` pins a
sentinel written with leading zeros (2c).

- **2a. Integer text** is an optional `-` and then one or more of the ASCII
  digits `0` to `9`, and nothing else: no `+`, no whitespace, no fraction, no
  exponent, no digit separator, no digit of another script. Leading zeros are
  allowed and `-0` is 0. The value must lie within a signed 64-bit integer.
- **2b. Number text** is an optional `-`, one or more ASCII digits, then
  optionally `.` and one or more digits, then optionally `e` or `E`, an
  optional `+` or `-`, and one or more digits; and nothing else. So `+1`,
  `.5`, `5.`, `0x10`, `Infinity`, `NaN` and text with whitespace are refused.
  The value is the double nearest to the exact decimal value, a tie going to
  the double whose last bit is 0. A text whose nearest double is infinite
  (`1e400`, `1.7976931348623159e308`) is refused. A text nearer to zero than
  to the smallest subnormal reads as 0. A text that begins with `-` and reads
  as zero (`-0`, `-0.0`, `-1e-400`) is negative zero, -0.0: a `bits` `f64`
  field written from it holds `8000000000000000`.
- **2c. Where the grammars apply.** The list below is complete: a number in a
  file or a call that it does not name is read by the rule of the version
  that states it, or by the unsigned grammar at the end of this ruling.
  The `int` and `float` transforms on the `xml` wire, and on the `geojson`
  wire when the member is a JSON string: text that 2a or 2b refuses is
  `transform-decode`. The same two grammars read every other number this
  specification says is read as a key's type or as a parameter: a `default`
  value and a context value (`key-type-mismatch` when refused), a vector's
  `model` value (below), the entries of a value table (an entry is an integer
  when 2a accepts it and a number when 2b does), and these parameters
  (`bad-directive` when refused): the `<range>` of `linscale`, a factor or
  offset of `uscale` and `sscale` written as number text, the parameter of
  the `scale` and `offset` derive functions (number text, or for `scale`
  `<num>/<den>` as ruling 1 of 0.5 states, where `<num>` is integer text (2a,
  so `scale:-1/2` loads) and `<den>` an unsigned decimal integer that is not
  zero), and the `<n>` of `plus <n>` on a `length` line, which is integer
  text (2a).

  **An unsigned decimal integer** is one or more ASCII digits `0` to `9` and
  nothing else: leading zeros are allowed (`007` is 7); a sign, whitespace, a
  fraction and an exponent are not. Its value must lie below the width it is
  written for. It is the form of a sentinel of the `absent` option on `bits`
  and on the integer forms of `protobuf` (0.9), of a `when` and a `const`
  value on `bits` and on `protobuf`, and of every other integer in a pack
  that the list above does not name: bit lengths and positions, `word_bytes`,
  `count`, `item`, `pad`, `align`, `presence` sizes, `length` sizes, the
  `<maxpos>` of `linscale`, the `<num>` and `<den>` of a `uscale` or `sscale`
  factor, and the numeric parameters of `int:<w>`, `dec`, `dm`, `hms` and
  `hms_dmy`.
  Anything else in its place is `bad-directive`: `absent +7`, `absent 0256`
  on 8 bits, `when 0:0:8 +1` and `dec:+2` are refused, and `word_bytes 01`
  loads.

  **A vector's `model` value** is read by 2a or 2b only where the member is
  named by a model key or an item path `<list>[<i>].<key>`: it is read as
  that key's declared type. A `"<list>.#"` value is an unsigned decimal
  integer or the text `absent`. `"@kind"`, `"@complete"`, `"@absent"` and
  `"<list>[<i>].@kind"` are not numbers. A `model` value its grammar refuses
  makes the vector invalid, and an invalid vector fails the run.

  Two kinds of number text keep the grammar of the version that states them.
  On the `text` wire the `int`, `float` and `dec` transforms read the grammar
  of Version 0.10, "Transforms for `text`" (an optional `+` or `-`; for `float`
  and `dec`, `5.` and `.5` are numbers and an exponent is refused), after the
  spaces that Version 0.10 removes from a column; 2a and 2b do not apply to
  them. A sentinel of the `absent` option is read as Version 0.9 states it:
  an unsigned decimal integer (above) on `bits` and on the integer forms of
  `protobuf`, and JSON number text on `json` and `geojson` (ruling 9 of 0.9).
  On `text` the `absent` option is `bad-directive` (ruling 16 of 0.10).
- **2d. JSON numbers** (the `json` wire, and number members on `geojson`)
  follow the JSON grammar (ruling 39 of 0.8). Through `float` the value is the
  nearest double as in 2b; one whose nearest double is infinite is
  `transform-decode`. Through `int` the exact value of the number text must be
  an integer within a signed 64-bit integer, else `transform-decode`: `1.0`,
  `1e3` and `9.223372036854775807e18` are integers, and an integer above 2^53
  keeps every digit, with or without a fraction of zero. This states ruling 12
  of 0.5 exactly. On the `json` wire a number held as residue (a member no
  line maps) whose nearest double is infinite has no canonical text and is
  `malformed-wire`; this applies to residue members only.

  The `absent` option (0.9) compares a sentinel with a number's canonical
  text, which ruling 19 of 0.9 forms through a double; that comparison is
  unchanged, and the value `int` gives when no sentinel matches is the exact
  integer above. A mapped number whose nearest double is infinite has no
  canonical text, so it matches no sentinel (ruling 18 of 0.9 refuses such a
  sentinel at load), and the field fails as this ruling states for its
  transform.
- **2e. A byte order mark** at the start of a `json` or `geojson` input is
  `malformed-wire`.
- **2f. Float text written.** The digits are the shortest decimal digit
  string that 2b reads back as the same double; of several of that length,
  the one nearest to the double's exact value. They are laid out with no
  exponent, whatever the magnitude: the integer digits, then, only when the
  fraction is not zero, `.` and the fraction digits. One `0` stands before a
  `.` that would otherwise come first; there is no other leading zero, no
  trailing zero after the `.`, and no `+`. Negative zero is `0`. So 1e21 is
  `1` and 21 zeros, 1e-7 is `0.0000001`, and the smallest subnormal is `0.`,
  323 zeros and `5`. This is ruling 3 of 0.1.1, stated exactly; it holds for
  XML text, for JSON numbers, and for the `float` transform on the `text` wire
  (`int:<w>`, `dec`, `dm`, `hms` and `hms_dmy` write as Version 0.10 states).
- **2g. Integer text written** is the decimal digits, with `-` before a
  negative value, no leading zero and no `+`. On `text`, `int:<w>` adds the
  zeros of Version 0.10.

### Ruling 3: `iso8601_ms`

Pinned by `conformance-time` and `conformance-time-json`. This ruling states
the grammar that ruling 8 of 0.1.1 and its correction in 0.6 left open. It
holds on every wire `iso8601_ms` is valid on, the `text` wire included (ruling
13 of 0.10). A sentinel of the `absent` option is compared before the
transform (0.9) and is not read by this grammar.

- **3a. Grammar.** `YYYY-MM-DD`, then `T` or `t`, then `hh:mm:ss`, then
  optionally `.` and one or more digits, then `Z`, `z`, or an offset
  `+hh:mm` or `-hh:mm`. Each field has exactly the digits shown, ASCII digits
  only, and nothing stands before or after. A date alone, a time without
  seconds, a space in place of `T`, `,` in place of `.`, a `.` with no digit,
  an offset without its colon or its minutes, no designator, a year of other
  than four digits or with a sign, the basic format, week dates and ordinal
  dates are refused.
- **3b. Ranges.** Year 0001 to 9999; month 01 to 12; day 01 to the last day
  of that month in the proleptic Gregorian calendar (a year is a leap year
  when it is divisible by 4 and not by 100, or divisible by 400); hour 00 to
  23; minute 00 to 59; second 00 to 59, so a leap second (`:60`) is refused
  and `24:00:00` is refused; offset hour 00 to 23 and offset minute 00 to 59.
  `-00:00` is UTC.
- **3c. Fraction.** Any number of digits. The first three, with zeros added
  on the right when there are fewer, are the milliseconds; the digits after
  the third are dropped, not rounded, in every year. So
  `1969-12-31T23:59:59.9999Z` is -1.
- **3d. The value** is the count of milliseconds from `1970-01-01T00:00:00Z`
  to the written time less its offset, every day 86,400,000 ms long, negative
  before 1970. The instant must lie from `0001-01-01T00:00:00.000Z` to
  `9999-12-31T23:59:59.999Z`: an offset that moves it outside is refused.
- **3e. Every refusal on decode is `transform-decode`.**
- **3f. Encode** writes `YYYY-MM-DDTHH:MM:SS.fffZ`: 24 characters, four year
  digits, three fraction digits, upper-case `T` and `Z`. A value below
  -62135596800000 or above 253402300799999 is `transform-encode`.

### Ruling 4: scaled and integer transforms of the `bits` wire

Pinned by `conformance-scale`, `conformance-scale-json`,
`conformance-scale-widths-lsb`, `conformance-scale-widths-msb` and load
vectors 371 to 375, 404 to 424 and 448 to 449.

- **4a. Rounding.** `round(q)` is the integer nearest to the double `q`; when
  `q` lies exactly halfway between two integers it is the one further from
  zero, at both signs: 0.5 gives 1, -0.5 gives -1, 2.5 gives 3, -2.5 gives -3.
  The result is exact for every `q`: the largest double below 0.5 gives 0,
  and an odd integer above 2^52 gives itself. An engine that adds 0.5 and
  truncates does not conform. This is also the `round` of `dec`, `dm` and
  `hms` on the `text` wire, which Version 0.10 (rule 2 of its transforms)
  defines as the rounding of `linscale`.
- **4b. A value that does not fit is `transform-encode`.** The rounded value
  is compared with the field's range as an integer of any size, before it is
  narrowed to any machine type. An engine never writes the low bits of a
  value that does not fit, and never writes the nearest value that does. A
  quotient `q` that is not finite (an infinity or NaN, as `1e300` through
  `sscale:1e-10` gives) is `transform-encode`.

  | Transform | Range of the integer written |
  |---|---|
  | `uint`, `len` below 64 | 0 to 2^len - 1 |
  | `uint`, `len` 64 | every model integer; the bits are its two's-complement pattern (ruling 2 of 0.5) |
  | `twos` | -2^(len-1) to 2^(len-1) - 1 |
  | `uscale` | 0 to 2^len - 1, after rounding |
  | `sscale`, `linscale` | -2^(len-1) to 2^(len-1) - 1, after rounding |

  This replaces "low `len` bits" in the tables of 0.2 and 0.5, and the
  sentence of 0.5 that `linscale` keeps its 0.2 behaviour. A value that rounds
  to an integer inside the range fits (-0.4 through `uscale:1` writes 0).
  A sentinel of the `absent` option (0.9) is not a value through the
  transform: it is written as the raw integer that 0.9 checks at load, and
  this table does not apply to it.
- **4c. Decode.** `uint` reads the bits as an unsigned integer. `twos`
  extends the sign from the field's highest bit at every `len` from 1 to 64:
  a 1-bit `twos` field is 0 or -1. For the scaled transforms the integer
  becomes the nearest double (a tie to the double whose last bit is 0) before
  the arithmetic of ruling 1 of 0.5. `linscale` computes `v / maxpos * range`
  on decode and `x / range * maxpos` on encode, in doubles, in that order.
- **4d. Parameters are checked at load;** each failure is `bad-directive`.
  `linscale:<maxpos>:<range>` takes exactly two: `<maxpos>` is an unsigned
  decimal integer (2c) and at least 1, `<range>` is number text (2b) and not
  zero. `uscale` and `sscale` take a factor and an optional offset: the
  factor is number text and not zero, or `<num>/<den>` of two unsigned
  decimal integers (2c), neither zero; the offset is number text. "Zero"
  means the double that 2b reads: `uscale:1e-400` and `linscale:32768:1e-400`
  are `bad-directive`. A `len` above 64 on `uint`, `twos`, `uscale`,
  `sscale` or `linscale` is `bad-directive`, with or without the `absent`
  option (0.9 refuses `absent` on any `bits` field longer than 64 bits). That
  `bad-directive` is raised by the check after the file of ruling 25 of 0.5
  (a length a transform does not allow), not as the line is read (ruling 5b).
  On such a field the values of its `absent` option are not checked as the
  line is read: the after-file length check raises the `bad-directive`, so
  `field time_ms 0:0:65 uint absent 7` followed by `bogus` is
  `unknown-directive`, while `absent +7` on an 8-bit field followed by
  `bogus` is `bad-directive`.
- **4e. Placement.** A field of any `len` from 1 to 64 may start at any bit
  and cross byte boundaries and the multiples of 64 bits of the message, in
  both bit orders and with any `word_bytes`.

### Ruling 5: load and call failures that had no kind

Pinned by load vectors 339 to 424, 429 to 447 and 450 to 462, and by the vectors
`packs/conformance/vectors/unknown-*-format*.json`.

Every load failure and every call failure has a kind from this table, and its
message begins with the kind and a colon. The table lists every kind of the
specification up to and including 0.11; the kinds of versions 0.4 to 0.10 keep
their meaning. Version 0.9 and Version 0.10 add no kind: every load error they
name is `bad-directive` or a kind of 0.4 to 0.8.

| Kind | Raised by | When |
|---|---|---|
| `unterminated-quote` | load of a pack or a module | a value that begins with `"` has no closing `"` on its line; a `#` after the opening quote is part of the value |
| `unknown-directive` | load of a pack or a module | the first word of a line is not a directive of this file type. A pack's directives are `format`, `version`, `distribution`, `source`, `uses`, `wire`, `root`, `field`, `when`, `const`, `kind`, `requires`, `default`, `map`, `typemap`, `group`, `end`, `word_bytes`, `bit_order`, `layout`, `also`, `pad`, `align`, `presence`, `if`, `opt`, `chain`, `fx`, `length`, `delimiter`, `start` and `checksum`; a module's are `module`, `version`, `distribution`, `source`, `uses`, `key`, `list` and `derive`. So `key` or `derive` in a pack and `wire` in a module are `unknown-directive` |
| `bad-directive` | load of a pack or a module | a directive this specification has, used wrongly: the causes named in 0.5 to 0.10 (among them the load errors of the `absent` option, 0.9, and every `bad-directive` of the `text` wire, 0.10, its locator syntax included), and from 0.11: the wrong number of arguments; a `distribution` other than `public` or `controlled`; a key type other than `string`, `float` or `int`; a key name holding `.`; a second `format`, `version`, `wire`, `distribution` or `module` line; a transform on a wire it is not valid for; transform parameters 4d refuses; a fixed-layout `bits` pack with no `word_bytes` line |
| `unknown-wire` | load of a pack | the `wire` value is not exactly `xml`, `geojson`, `json`, `bits`, `protobuf` or `text` |
| `unknown-transform` | load of a pack | the transform's name, the text before its first `:`, is not a transform of this specification |
| `bad-locator` | load of a pack | the locator does not have the form its line takes on the pack's wire (below) |
| `missing-format`, `missing-version`, `missing-wire` | load of a pack | the pack has no such line; `missing-wire` also when a line that needs the wire stands before the `wire` line |
| `missing-module`, `missing-version` | load of a module | the module has no such line |
| `missing-root` | load of a pack; decode | load: an `xml` pack with no `root` for the pack or for one of its kinds. Decode: the document's root element has another name, in a pack without kinds |
| `missing-distribution`, `missing-source`, `unknown-module`, `module-not-used`, `undeclared-key`, `key-type-mismatch`, `distribution-violation`, `distribution-refused`, `duplicate-module`, `duplicate-key`, `duplicate-kind` | load | as in 0.4 to 0.10 |
| `duplicate-format` | load of a pack | a pack with the same `format` name, compared byte for byte, is already loaded. The second pack is refused and the first stays loaded |
| `unknown-format` | `convert`, `decode`, `encode`, `model_keys`, the capability report | a format name that is not loaded. `convert` checks `from`, then `to`, before it reads the input |
| `undeclared-key`, `key-type-mismatch` | `convert` with context | as in 0.6 |
| `no-kind`, `malformed-wire`, `transform-decode`, `transform-encode` | `decode`, `encode`, `convert` | as in 0.1.1 to 0.10 and rulings 1 to 4, 7 and 9 |

- **5a. Locator forms.** `bad-locator` is raised for:
  - `xml`: an empty step (`a//b`, a leading or trailing `/`), on every line
    that has a locator, `group` lines included; an empty attribute name
    (`@`); a step after `@name` or `#text`; on a `field`,
    `when` or `const` line, a locator that does not end in `@name` or
    `#text`.
  - `json`: an empty member name (`a..b`, a leading or trailing `.`), other
    than the locator `.` itself.
  - `geojson`: `geometry.` followed by anything but `lon`, `lat` or `alt`; an
    empty member name.
  - `protobuf`: a step that is not digits only, or a field number of 0 or
    above 536870911 (2^29 - 1); an empty step.
  - `bits`, fixed layout: on a `field`, `when` or `const` line, text with a
    `:` that is not three digit-only parts joined by `:` (two parts, four
    parts, a letter, a sign); text with no `:` that is not digits only
    (`abc`); a bit length of 0.
  - `bits`, sequential layout: text with no `:` that is not digits only; a
    bit length of 0.

  The cases earlier versions name stay `bad-directive`: `.` outside a group,
  a `<word>:<pos>:<len>` locator in a sequential pack, a bit length as the
  locator in a fixed-layout pack. On the `text` wire `bad-locator` is not
  raised: a locator that is not one of the three forms of Version 0.10
  (ruling 14 of 0.10), a pair whose two indexes are equal (Version 0.10,
  Locators), and an index of a group's body at or beyond its item length
  (Version 0.10, Groups) stay `bad-directive`.
- **5b. Order.** As a file is read, each line is checked in this order, and
  the first failure is the error of the load:
  1. `unterminated-quote`;
  2. `unknown-directive`;
  3. the number of arguments (`bad-directive`; 5e);
  4. `missing-wire` (below);
  5. a repeated header line (`format`, `version`, `wire`, `distribution`,
     `module`: `bad-directive`);
  6. the `wire` value (`unknown-wire`) and the `distribution` value
     (`bad-directive`);
  7. the transform's name (`unknown-transform`) and its parameters
     (`bad-directive`: 4d, and the parameters of the `text` transforms);
  8. the locator form (`bad-locator`, 5a; on `text`, `bad-directive`);
  9. the syntax of the field options: an option this specification does not
     have, an option given twice, an option without its argument
     (`bad-directive`);
  10. the values of an `absent` option (`bad-directive`), except on a
      field whose bit length is above 64 (4d).

  Every cause not in steps 1 to 10 is checked after the file is read, among
  them a group's options, the names of a presence, `duplicate-kind`, an
  `end` with no open block, the form of a `when` or `const` value (a sign, a
  character that is not a digit, a value that does not fit its bits),
  whether a field option fits its wire or its transform (`swap`, `trim`,
  `optional`), and a bit length against its transform (ruling 25 of 0.5).
  So `field time_ms 0:0:65 uint`, a `group` line with an option its wire does
  not have, a second `kind k`, a stray `end`, `when 0:0:8 +1` and `swap` on an
  `xml` field, each followed by a line `bogus`, are `unknown-directive`. The
  locator form is a line check on every line that has one: a `group` with the
  `xml` locator `a//b` followed by `bogus` is `bad-locator`.

  The `wire` line stands before every `root`, `field`, `when`, `const`,
  `group`, `end`, `word_bytes`, `bit_order`, `layout`, `also`, `pad`, `align`,
  `presence`, `if`, `opt`, `chain`, `fx` and `length` line; such a line before
  it is `missing-wire`, `layout fixed` included. This check is reported before
  a later line's error, before `missing-format`, and before an unknown
  transform on the same line. `kind`, `requires`, `default`, `map`,
  `typemap`, `uses`, `format`, `version`, `distribution` and `source` may
  stand before the `wire` line. `layout sequential` stands before every line
  of that list; such a line before it is `bad-directive`.
  `layout fixed`, the default, may stand after such a line (load vector 206).
  The `text` directives `delimiter`, `start` and `checksum` are not in that
  list: they may stand before the `wire` line, and whether their wire is
  `text` is checked after the file is read (ruling 10 of 0.10, "wherever the
  `wire` line stands").

  After the file is read: `missing-format`, `missing-version`,
  `missing-wire`; then the checks that need the whole file (ruling 25 of 0.5;
  the load-time `missing-root`; the missing `word_bytes`; the checks that need
  the wire, ruling 10 of 0.10, among them a transform on a wire it is not
  valid for and a directive of another wire; and the checks of ruling 2 of
  0.10); then the order of 0.4 from `missing-distribution` on; and last
  `duplicate-format`, so a second pack with a taken name that fails a check
  of its own reports that check. For a module: the line checks 1 to 3, 5 and
  6 (`distribution`); then, after the file is read, every other cause of a
  module line: a key type other than `string`, `float` or `int`, a key name
  holding `.`, `duplicate-key`, and a `derive` function name or parameter
  that this specification does not have; then `missing-module`,
  `missing-version`; then the order of ruling 29 of 0.8. So `key x bool - "x"`
  followed by a line `bogus 1` is `unknown-directive`. This replaces the
  sentence of 0.4 that `duplicate-key` is among the line errors, and ruling
  32 of 0.8 for a function name and a parameter; since these checks still
  come before `missing-distribution`, load vector 131 (an unknown function in
  a module with no `distribution` line) stays `bad-directive`.
- **5c. This pins ruling 3 of 0.4,** which left the kind of a malformed value
  open: each case there is `bad-directive`.
- **5d. Load vectors with several packs.** A load vector may carry `packs`,
  an array of pack texts loaded in order, in place of `pack`
  (`spec/vector-format.md`).
- **5e. Argument counts.** In a pack, `format`, `version`, `distribution`,
  `source`, `uses`, `wire`, `root`, `kind`, `word_bytes`, `bit_order`,
  `layout`, `pad`, `align`, `delimiter`, `start` and `checksum` take exactly
  one argument. In a module, `module`, `version`, `distribution`, `source` and
  `uses` take exactly one. A quoted value is one argument, so `source "a b"`
  loads and `source a b` is `bad-directive`.

### Ruling 6: the capability report

Pinned by `packs/conformance/capability-vectors/*.json` over the packs
`conformance-cap-*`.

`capability(from, to)` is computed from the two packs alone, never from a
message. It gives a grade and two lists.

- **6a. Mapped keys.** `model_keys(format)` is the list of the keys the pack
  maps, each once, in the order of first appearance reading the file top to
  bottom, common lines and every kind alike. A key is mapped by a `field`
  line and by an `also` line, in a fixed or a sequential layout, inside or
  outside `if`, `opt`, `chain` and `length` blocks. The entry is the key as
  the pack writes it (`lat`, `probe.n`).
- **6b. Lists.** A `group` line adds the entry `<list>[]` at its place. A key
  mapped inside the group is the entry `<list>[].<key>`, and a nested group
  `<list>[].<inner>[]` with its keys `<list>[].<inner>[].<key>`. An item key
  and an entity key of one name are two entries. A list mapped by groups in
  several kinds is one entry, and its item keys are joined the same way.
- **6c. What is not a mapped key.** A key named only by `requires` or
  `default`; a place named by `when` or `const`; a count locator, a presence
  or a length; a `typemap` or `map` line. `derive` lines and caller context
  are not consulted: a key the target maps that `convert` could derive from
  keys the source maps is not carried by the report. The `absent` option does
  not change the list (ruling 8 of 0.9). On the `text` wire a pair (`<i>+<j>`)
  maps its one key, and a column maps its key as a field does.
- **6d. The lists.** `carried` is the entries of `model_keys(from)` that are
  also entries of `model_keys(to)`, compared as exact text; `dropped` is the
  other entries of `model_keys(from)`. Both keep the order of
  `model_keys(from)`.
- **6e. The grade,** in lower case: `none` when `carried` is empty (also when
  the source maps no key); else `full` when `dropped` is empty; else
  `partial`. A format against itself is graded by the same rule.
- **6f.** A format that is not loaded is `unknown-format`.

### Ruling 7: the limit on list items

Pinned by `conformance-limit-json`, `conformance-limit-bits`,
`conformance-limit-protobuf` and `conformance-limit-xml`
(`conformance-limit-n` holds the small target of two of the vectors), and by
`conformance-limit-text`, `conformance-limit-bits-fail` and
`conformance-limit-seq` and `conformance-limit-seq-fail` (rulings 7d, 7f and
7g).

- **7a.** One decode holds at most `max_items` list items, counted over every
  list of the message at every nesting level: each item of a list is one, and
  each item of a list inside an item is one more. An item with no keys is
  counted, also one whose every field holds a sentinel (ruling 5 of 0.9) and a
  `text` item that the record cuts short (Version 0.10, Groups). The decode
  that would hold one item more fails with `malformed-wire`.
- **7b.** The limit is 100,000 unless the caller sets another: an engine
  option in the API (a command-line tool takes it as `--max-items <n>`), the
  member `max_items` in a vector. The value is an integer of 0 or more; with 0
  any item is refused.
- **7c.** Only items of lists a `group` of the common lines or the selected
  kind maps are counted. A JSON array no group maps is not counted.
- **7d.** A count read from the wire (`count` on `bits`, in either layout) is
  compared with what the limit still allows before any item is read or any
  memory is taken for the items. On the `text` wire the number of items of
  the group is compared with the limit after step 5 of "Reading a record"
  (Version 0.10) and before any field is read.
- **7e.** The limit is on decode, and so on `convert`. `encode` of an entity
  a program built is not limited.
- **7f.** Going over the limit is a failure of the wire: it is
  `malformed-wire` also when a field of the same decode would fail, and it
  wins over that field's `transform-decode` (ruling 9 of 0.1.1). In a
  sequential layout this holds also when the field that fails is read before
  the group that goes over the limit.
- **7g.** The limit counts the items the decoded entity holds, not the items
  read. Where two groups of one list are both on the wire and decode keeps
  the later group's items (ruling 33 of 0.8), the earlier group's items are
  not counted once the later group replaces them, and a count is compared
  with the limit less the items the entity holds outside the list it
  replaces.

### Ruling 8: reserved

A command-line contract is not part of 0.11, and no vector runs a tool.

### Ruling 9: `when` paths on the `protobuf` wire

Pinned by `conformance-pbwhen` and `conformance-pbwhen-json`. Rulings 31 and
38 of 0.8 read against each other for a `when` path whose prefix bytes are not
a message; this ruling replaces the last sentence of ruling 38 and holds.

- **9a. The top level** of the message is checked whole by ruling 38,
  whatever the pack maps.
- **9b. A `when` path never fails a decode.** It does not hold when a field
  of its prefix is absent, is not length-delimited, or holds bytes that do
  not parse as a message by ruling 38; it holds or not by its value
  otherwise. Kind selection then goes on to the next kind.
- **9c. A `field` or `group` path** of the common lines or of the selected
  kind whose prefix is present and is not length-delimited, or holds bytes
  that do not parse as a message, is `malformed-wire`. So is an item of a
  group whose body addresses into it and whose bytes do not parse. Lines of
  kinds that were not selected are not read.
- **9d. Which occurrence.** Where a field number of a prefix repeats, the
  last occurrence is the one walked into (ruling 15 of 0.5), for `when`,
  `field` and `group` alike; earlier occurrences are not parsed.
- **9e. A submessage no line walks into is not parsed.** The bytes of a
  length-delimited field are read as a message only when a `when` path, or a
  `field` or `group` path of the common lines or the selected kind, walks
  into it. Otherwise they are opaque: bytes that would not parse there are
  not an error.

### Not ruled in 0.11

- Not ruled: whether a residue integer on `json` above 2^53 is written back
  with every digit or through a double.
- Not ruled: how a value-table entry on a `string` side is read when it looks
  like a number.
- Not ruled: what `pstring` gives for bytes that are not UTF-8.
- Not ruled: the locator forms an `xml` group line may end in (`@name`,
  `#text`), `geometry` with no dot, `properties` alone and `properties.a.b`
  on `geojson`, `protobuf` steps with leading zeros, and `bits` positions or
  lengths at or above 2^32.
- Not ruled: XML namespaces, an XML declaration after the start or naming an
  encoding, `]]>` in text, `--` inside a comment, references inside comments,
  processing instructions and CDATA against 1j, and `&#;`.
- Not ruled: an upper bound for the `<maxpos>` of `linscale`.
- Not ruled: the form of the `max_items` member of a vector beyond "an
  integer of 0 or more" (a JSON number with a fraction or exponent, a
  string).
- Not ruled: where `unknown-format` stands in the order of the capability
  report's checks when both formats are not loaded.
- Not ruled: quotes inside a token and a quote that is not the first
  character of a token.
- Not ruled: a raw control character in a `const` or `when` value on `xml`.
- Not ruled: which of two shortest digit strings 2f writes when they are
  equally near the double.
- Not ruled: the form of a `version` value.
- Not ruled: the argument count of the directives 5e does not list (`field`,
  `when`, `const`, `default`, `map`, `typemap`, `end`, `requires`, `group`,
  `also`, `length`, `presence`, `if`).
- Not ruled: whether a `when` on a `json` number whose nearest double is
  infinite holds, fails or is `malformed-wire`.
- Not ruled: a `linscale` `<maxpos>` too large for a double.
- Not ruled: in a model module, whether a `module` or `uses` name that holds
  `.` or is empty, the argument count of `key` and `list`, and a `derive`
  line whose argument count does not fit its function are line checks or
  checked after the file.
- Not ruled: on `protobuf`, which error a decode gives when a field fails
  and a later submessage does not parse.
- Not ruled: the error kind of a `protobuf` encode in which one path is both
  a value and a submessage.
- Not ruled: whether the locator form of a `bits` fixed-layout `group` line
  is a line check, and whether `layout sequential` placed after a line it
  must precede is a line check or checked after the file.

# Version 0.12: the `present` derive function

Status: Written. A format sometimes sets a value from whether another value is
sent at all: ASTERIX CAT062 sets the MRH bit of I062/080 when it writes the
geometric altitude of I062/130. No derive function of 0.6 or 0.8 gives that:
`any` takes `int` arguments and reads their values.

| Function | Arguments | Result |
|---|---|---|
| `present` | a (any scalar type) | 1 |

The target is an `int` key. Like every function but `any`, `present` sets its
target only when its argument is present and the target is absent (Version
0.6, Derived keys). `present` writes only 1; a target the entity already
holds, 0 included, is kept. A format that needs 0 for "not sent" states it
with a `default` on the target in the pack.

## Rulings for 0.12

1. **Presence, not value.** The argument is present when the entity holds a
   value for the key, whatever the value: `0`, `0.0`, the empty string and
   `false` decoded by `bool` (the value 0) all give 1. A `json` member whose
   value is `null` is absent (Version 0.5) and leaves the target absent.
2. **What counts as present.** Here present means held by the entity, not the
   present-with-default of ruling 2 of 0.6 and ruling 2 of 0.8. A key set by
   decode, by context (step 2 of `convert`), or by any derivation in an
   earlier pass or an earlier line of the same pass is present; the pass
   repeats until it sets nothing, so the order of `derive` lines does not
   change the result. A key left absent by a sentinel (Version 0.9) is
   absent. A `default` is not a value of the entity (it applies on encode,
   after derivation), so a key that only a default would write is absent.
3. **Argument.** Exactly one argument. A wrong count is a line error raised
   as the file is read (ruling 32 of 0.8): `bad-directive`. The argument is a
   key of `core`, of the module itself, or of a module it `uses`, as for every
   function; the checks on the argument key and the target type run where
   ruling 29 of 0.8 places them. A list as the argument is `bad-directive`
   (ruling 18 of 0.7).
4. **Target type.** The target must be `int`; another type is `bad-directive`,
   as for the other functions whose result type is fixed.
5. **Same-format round trip.** As for every derivation, `present` is not
   applied when `from == to` and no context is given (Version 0.6, Order
   inside `convert`), so a round trip keeps the decoded value of the target.

---

# Version 0.13: the `tlv` wire

Status: Written. A `tlv` format is a set of items, each a tag, a length and a
value: a local set in the sense of SMPTE ST 336 and MISB ST 0601, or any record
of that shape. A value may itself be a set. The set may follow a fixed key and
a length, and may end with a checksum item. Input and output are hex text, as
for `bits` and `protobuf`.

```
wire      tlv
tag       <ber-oid | 1 | 2 | 4>        # how a tag is written; default ber-oid
length    <ber | 1 | 2 | 4>            # how a length is written; default ber
key       <hex>                        # optional: the message begins with these bytes
checksum  sum16 <tag>                  # optional: the last item of the set is a checksum
field     <model-key> <path>[:<n>] <transform> [options]
```

`tag`, `length`, `key` and `checksum` appear at most once each, before the
first `kind`. The forms above are `bad-directive` on another wire, more than
once, or with another value; the `length` block of 0.8 and `checksum nmea` of
0.10 keep their meaning on their wires and are `bad-directive` on `tlv`.
`<hex>` is 1 to 64 bytes as an even number of lowercase hex digits. `<tag>`
and every tag in a path is a decimal integer from 0 to 2^28-1 with no leading
zero, and under a fixed `tag <n>` below 2^(8n). Every check in this paragraph
and in "`when` and `const`" runs after the file is read and before
`missing-distribution` (ruling 2 of 0.10).

## Encodings

- **`tag ber-oid`.** The tag in base 128, most significant group first, every
  byte but the last with its high bit set; at most four bytes. A first byte of
  `0x80` (a group of zero before others) and a fifth byte are
  `malformed-wire`.
- **`tag <n>`.** The tag as an unsigned big-endian integer of `n` bytes.
- **`length ber`.** A first byte below `0x80` is the length. A first byte
  `0x81` to `0x88` is followed by that many bytes (1 to 8) holding the length
  as an unsigned big-endian integer. `0x80` and `0x89` to `0xFF` are
  `malformed-wire`. Encode writes the short form for a length below 128 and
  otherwise the long form with the fewest bytes; decode accepts a long form
  with more bytes than needed.
- **`length <n>`.** The length as an unsigned big-endian integer of `n` bytes.

A length is compared with the bytes left in its set (or input), never added
to an offset first, so a length of 2^64-1 is `malformed-wire`, not a wrapped
offset.

## Reading a message

Each failure below is `malformed-wire`.

1. The input is hex text (rulings 36 and 40 of 0.8 apply).
2. With `key`, the input begins with the key's bytes, followed by a length
   (as `length` states). The set is the next that many bytes; a set that runs
   past the input is `malformed-wire`, and bytes after it are ignored. Without
   `key`, the whole input is the set.
3. A set is a sequence of items to its last byte: a tag, a length and that
   many bytes of value. An item that runs past its set is `malformed-wire`. The
   top set is read whole whatever the pack maps. The kind is selected next
   (Kinds, below); then a value is read as a set only when a line of the
   selected scope walks into it, and its items are then read whole. An empty
   input, without `key` and `checksum`, is an empty set.
4. With `checksum sum16 <t>`, the last item of the top set has tag `t` and a
   value of two bytes; otherwise `malformed-wire`. Its value, big-endian, is
   the sum of every byte of the input from the first (the first byte of the
   key when there is one) to the last byte of the checksum item's length: a
   byte at an even offset from the first counts `b * 256`, a byte at an odd
   offset `b`, and the sum is taken modulo 65536. A different value is
   `malformed-wire`. The checksum item is neither mapped nor residue. An item
   of tag `t` before the last is `malformed-wire`.

## Locators

A path is one or more tags separated by `.`: `13` is the item of tag 13 in the
top set, `48.2` the item of tag 2 in the set that is the value of the item of
tag 48. Every nested set uses the pack's `tag` and `length` encodings. When a
tag occurs more than once in one set, a path takes its first occurrence, at
every level; later occurrences of a tag that a line names are neither mapped
nor residue. `:<n>` after the path is the size of the value in bytes, from 1
to 8, where the transform needs one (below). A `field`, `when` or `const`
whose first tag is the checksum tag is `bad-directive`; a tag in a nested set
may equal it.

For a `field`, an item that is not in its set is absent, and so is an item
whose value is empty, except under `utf8` and `hex`, where it is the empty
string. A key holding the empty string writes an item of length 0.

## Transforms for `tlv`

| Name | Yields | Size | Decode | Encode |
|---|---|---|---|---|
| `uint` | int | `:<n>` required | the value bytes, 1 to 8, as an unsigned big-endian integer | `n` bytes; a value that does not fit is `transform-encode` |
| `twos` | int | `:<n>` required | the value bytes, 1 to 8, as a big-endian two's-complement integer | `n` bytes; a value that does not fit is `transform-encode` |
| `uscale:<factor>[:<offset>]` | float | `:<n>` required | the value as for `uint`, then as on `bits` (rulings 1 of 0.5) | as on `bits`, into `n` bytes; out of range is `transform-encode` |
| `sscale:<factor>[:<offset>]` | float | `:<n>` required | the value as for `twos`, then as on `bits` | as on `bits`, into `n` bytes; out of range is `transform-encode` |
| `f32` | float | none, or `:4` | exactly 4 bytes, an IEEE-754 single, big-endian, widened | as on `bits` (ruling 23 of 0.5) |
| `f64` | float | none, or `:8` | exactly 8 bytes, an IEEE-754 double, big-endian | the double |
| `utf8` | string | none | the value bytes as UTF-8 text; invalid UTF-8 is `transform-decode` | the text's UTF-8 bytes |
| `hex` | string | none | the value bytes as lowercase hex text | hex text (an even number of digits, either case) to bytes; anything else is `transform-encode` |

Decode reads an integer value at its own length, whatever `:<n>` states;
`twos` and `sscale` take the sign from the value's first byte. A value longer
than 8 bytes for `uint`, `twos`, `uscale` or `sscale`, and a value of another
size for `f32` or `f64`, is `transform-decode`. A `uint` value of 8 bytes
follows ruling 2 of 0.5, whatever `n` is. A size missing where it is required, given
where it is not allowed, or out of range is `bad-directive`. `utf8` and `hex`
are valid only on `tlv`; the text, protobuf and `bool` transforms, `linscale`
and `ascii` are `bad-directive` on it: on `tlv`, any transform not in this
table is `bad-directive`. The sentence of 0.2 that `uint`, `twos` and
`linscale` are valid only on `bits` reads, from 0.13, "on `bits` and, for
`uint` and `twos`, on `tlv`". Field options: `via`. `swap`, `trim`
and `optional` are `bad-directive`.

## `when` and `const`

| Line | Decode | Encode |
|---|---|---|
| `when <path>:<n> <value>` | holds when the item is in its set and its value, 1 to 8 bytes read as unsigned at its own length, equals the unsigned decimal `<value>`; a value that is empty or longer than 8 bytes does not hold | the value as `n` bytes |
| `when <path> present` | holds when the item is in its set, an empty value included | an empty item, unless a line or residue writes an item at the path |
| `const <path>:<n> <value>` | not checked; the item is mapped | the value as `n` bytes |

A numeric `when` or `const` without a size, a value that does not fit `n`
bytes, `present` with a size, and `const <path> present` are `bad-directive`.
A `when` whose item lies in a value that is not a well-formed set does not
hold. As ruling 27 of 0.5 states for the text wires, `when … present` does not
name its path: the item there is residue unless another line names it.

## Writing a message

1. Each set is written as its items in this order: the items of the lines of
   the selected scope (common, then the kind's) in line order, where an item
   holding a nested set stands at the position of the first line of the scope
   that names its path or a path under it, `when` and `const` included; then
   the residue of that set in input order. An absent
   key writes no item; a key with a `default` writes the default. `when` and
   `const` items are written at their line's position, and where a `field` and
   a `when` or `const` name the same path, the item is written once, at the
   first line's position, with the `when` or `const` value. Two `field` lines
   on one path write the earliest present key (ruling 16 of 0.5). A nested set
   with no items is not written.
2. Every item is its tag, its length and its value in the pack's encodings. A
   length or tag that does not fit a fixed size is `transform-encode`.
3. With `key`, the output is the key, the length of the set, then the set.
   With `checksum sum16 <t>`, an item of tag `t` with a two-byte value is the
   last item of the top set and counts in the set's length. Its value is
   computed last, as in step 4 of "Reading a message", over the output from
   its first byte (the key's, when there is one) to the checksum item's
   length.

Output is lowercase hex. A same-format round trip is exact when the input's
items are in the order the pack writes them, its lengths are in the shortest
form, and its integer values have the sizes the lines state.

## Residue

Every item of the top set, and of each nested set a line of the selected
scope walks into, whose tag no line of the selected scope names at that place,
is residue, keyed by its path, holding its value as hex (the empty string for
an empty value). Every occurrence is kept: a tag that occurs twice gives two
residue entries, written back in input order. Residue is written back only
into the format it was decoded from. A nested set no line of the selected
scope walks into is one residue item.

## Kinds and groups

Kinds select by `when` lines as Version 0.5 states, after steps 1 and 2 of
"Reading a message", the reading of the top set in step 3, and step 4; so a
malformed nested set that only a kind's lines walk into gives `no-kind` when
that kind is not selected. `group` on `tlv` is `bad-directive` in 0.13.

## Vectors

`input` and `expect` of a `tlv` format are lowercase hex text (ruling 7 of
0.5).

## Rulings for 0.13

1. **Empty values.** An empty value is absent under every transform but
   `utf8` and `hex`, `f32` and `f64` included.
2. **`when … present` and residue.** When residue of the set holds an item of
   the path's tag, no empty item is written; the residue item stands at the
   residue position, after the mapped items.
3. **Integers that do not fit.** On encode, a `uint` value below 0 or at or
   above 2^(8n), and a `twos` value outside its `n` bytes, are
   `transform-encode`; ruling 2 of 0.5 covers only an 8-byte `uint`.
4. **Scales read unsigned.** `uscale` reads its value as unsigned whatever its
   length; ruling 2 of 0.5 does not apply to it.
5. **A path that is both a value and a set.** A `field`, `when` or `const` at
   a path and another line at a path under it (`48` and `48.2`), in one scope
   (the common lines with one kind's lines), is `bad-directive`; two kinds may
   read the same item differently.
6. **Sizes.** `:<n>` is one digit from 1 to 8.
7. **What a line walks into.** Every set on the path of a `field`, `when`
   (`present` included) or `const` line is walked into; `when … present`
   does not name only the last tag of its path.
8. **Malformed parameters.** On `tlv`, a `uscale` or `sscale` whose
   parameters do not parse, and any transform name not in the table, are
   `bad-directive`, checked after the file is read with the other checks of
   this section.
9. **Several `when` or `const` lines on one path.** The item holds the value
   of the earliest of them that carries a value, as ruling 11 of 0.10 states
   for the text wire; `when … present` carries none. A `field` on that path
   is not encoded.
10. **`absent` (0.9) on `tlv`** is `bad-directive` in 0.13: an empty value is
    already absent on this wire, and the raw value of a sentinel is not
    stated for it yet.
11. **`key` lines in a pack.** Only a `key` line with exactly one argument is
    the directive of this section, on any wire: on `tlv` it is checked as
    above, and on another wire it is `bad-directive`. A `key` line with any
    other number of arguments is the model-module form, and in a pack it
    stays `unknown-directive` (ruling 5 of 0.11), whatever the wire.
12. **The argument count of `checksum`.** 5e of 0.11 gives `checksum`
    exactly one argument; this section adds one form with two, `checksum
    sum16 <tag>`. As a line is read (step 3 of 5b), a `checksum` line with
    one argument, or with two whose first is `sum16`, passes; any other count
    is `bad-directive` there. Whether a passing line fits its wire (`sum16`
    with no tag, `sum16` on another wire, a one-argument value `tlv` does not
    name) is checked after the file is read, as the other checks of this
    section, and is `bad-directive`.
13. **The `tlv` lines and the `wire` line.** `length` is in the list of 0.11
    (5b) of lines that stand after the `wire` line, so `length ber` before
    `wire tlv` is `missing-wire`. `tag`, `key` and `checksum` are not in that
    list: they may stand before the `wire` line, and whether their wire is
    `tlv` is checked after the file is read.
14. **When `absent` on `tlv` is checked.** Step 10 of 5b (0.11) checks the
    values of an `absent` option; whether the option fits its wire is
    checked after the file is read (5b). So `absent` on a `tlv` field
    (ruling 10) is `bad-directive` after the file, and a later line's error
    comes first: `field probe.n 4:1 uint absent 255` followed by a line
    `bogus` is `unknown-directive`.

---

# Version 0.14: six-bit armor

Status: Written. Some binary messages travel as printable text in which each
character carries six bits: the payload of an AIS `AIVDM` or `AIVDO` sentence
is one. A `bits` pack with `armor sixbit` reads and writes that text instead of
hex. Every other rule of the `bits` wire, in either layout, applies to the bits
the text carries. A text field inside the message whose characters are six-bit
codes is read with the transform `sixbit`, which any `bits` pack may use.

```
wire       bits
bit_order  msb
armor      <hex | sixbit>     # default hex
```

`armor` is valid only on the `bits` wire, at most once, before the first
`kind`; `armor sixbit` needs `bit_order msb`. Anything else is
`bad-directive`, checked after the file is read (ruling 10 of 0.10).

## Reading the armored text

Each character of the input stands for six bits, first character first, the
most significant of its six bits first. A character `c` from `0` (0x30) to `W`
(0x57) stands for `c - 0x30`, and from `` ` `` (0x60) to `w` (0x77) for
`c - 0x38`; together they give the 64 values 0 to 63. Any other character,
whitespace and a line terminator included, is `malformed-wire`. Every
character is checked before any `when` or field is read, so a bad character
is `malformed-wire` and not `no-kind`, wherever it stands. The message is the
`6 * <characters>` bits so obtained, any number of bits: the whole-byte rule
of 0.8 and ruling 14 of 0.6 do not apply under `armor sixbit`. An empty input
is a message of no bits.

The `bits` rules then apply unchanged, with these readings of the message
length:

- **Fixed layout.** The input must reach every bit of each `field` line of
  the selected scope that is not `optional`, of each `when` and `const` line,
  and of a group's items, whatever `word_bytes` is; whole words are not
  required. Input shorter than that is `malformed-wire` (ruling 21 of 0.5:
  a `when` beyond the input does not hold). An `optional` field beyond the
  input is absent.
- **Sequential layout.** Bits after the last line are ignored, as in 0.8.

## Writing the armored text

The encoder lays out the message as for hex output, and then takes its first
`L` bits, where `L` is:

- in the fixed layout, one more than the highest bit of any `field`, `when`
  or `const` line of the selected scope, or of a group's items, whether or
  not its key is present, except an `optional` field whose key is absent
  (with no `default`);
- in the sequential layout, the position of the cursor after the last line,
  not rounded to a byte.

The `L` bits, followed by zero bits up to the next multiple of 6, are written
as `L / 6` characters (rounded up), each six bits as the character that stands
for them above: values 0 to 39 as `0x30 + v`, values 40 to 63 as `0x38 + v`.
The count of zero bits added (0 to 5) is not part of the output.

So a same-format round trip of armored text is exact when the input has no
characters beyond those the pack's lines reach, and its last character's bits
beyond `L` are zero.

## The `sixbit` transform

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `sixbit` | string | `len` is a multiple of 6, from 6 to 1530: each six bits, in the pack's bit order, as one character: values 0 to 31 as `@` to `_` (`0x40 + v`), 32 to 63 as space to `?` (`v`); then trailing `@` characters removed | each character of the text as its value, `@` to `_` as `c - 0x40` and space to `?` as `c`; padded with `@` (value 0) to `len / 6` characters. A character outside 0x20 to 0x5F, or text longer than `len / 6`, is `transform-encode` |

`sixbit` is valid on the `bits` wire in either layout and with either armor.
Its characters are read first to last, each one's six bits in the pack's bit
order, as `ascii` reads its bytes (0.5): with `lsb` the first character is the
low six bits of the field. With the field option `trim`, decode removes the
whole trailing run of `@` and space characters, in any mix. `swap` on
`sixbit` is `bad-directive`. A `len` that is not a multiple of 6, or outside
6 to 1530, is `bad-directive`.

## Vectors

`input` and `expect` of a format with `armor sixbit` are the armored text in a
JSON string, with no fill-bit count and no sentence around it.

## Rulings for 0.14

1. **What `armor` does not carry.** The `AIVDM` sentence around a payload, the
   fill-bit count, and the joining of a payload split across sentences belong
   to a layered wire. A pack with `armor sixbit` reads one whole payload.
2. **Fill bits on decode.** Bits in the last character beyond what the lines
   read are ignored, like any bits past the last line.
3. **`length … whole`** (0.8) in a pack with `armor sixbit` is
   `bad-directive`: the armored text has no whole-byte length.
4. **Short input and kinds.** The length rule of "Fixed layout" applies to
   the lines of the selected kind, once a kind is selected; an input too
   short for every kind's `when` lines is `no-kind` (ruling 21 of 0.5).
5. **Earlier tables.** `trim` applies to `sixbit` as to `ascii` (the field
   options table of 0.6 reads "`bits`, with `ascii` or `sixbit`"), and `armor`
   joins the header directives of ruling 24 of 0.8 that are `bad-directive`
   inside any block.
6. **Empty `sixbit`.** A field that is all `@` decodes to the empty string,
   present, as ruling 3 of 0.5 states for `ascii`.
7. **What counts toward `L`.** An `optional` field whose key has a `default`
   counts, since encode writes the default. A count locator counts whether
   the list is present, empty or absent (ruling 14 of 0.7 writes 0).
8. **Byte padding inside the message.** Only the rule that a whole message is
   a number of bytes is set aside; a `length … bytes` block is still padded
   to a whole byte.
9. **Nothing to write.** A scope that writes no bit gives the empty text.
10. **A group's items in `L` and on decode** count at their full extent,
    `item <bits>` each (longer where a nested group runs past it), not at the
    last bit a line inside them reads.
11. **"Before the first `kind`"** counts every `kind` line, a `kind` inside a
    group body included.
12. **`absent` (0.9) with armor.** A `bits` pack with `armor sixbit` takes
    `absent` as any `bits` pack does: the raw value is the field's bits as an
    unsigned integer, `sixbit` fields included. A field with `absent` whose
    key is absent writes its first sentinel, so it counts toward `L`, whether
    or not it is `optional`.
13. **The argument count of `armor`.** `armor` takes exactly one argument,
    checked as the line is read (step 3 of 5b of 0.11, as for `checksum` in
    ruling 12 of 0.13): a bare `armor`, or `armor sixbit hex`, is
    `bad-directive` there. Whether a one-argument `armor` fits its pack (its
    value, its wire, `bit_order msb`, once, before the first `kind`) is
    checked after the file is read. `armor` is not in the list of 0.11 (5b)
    of lines that stand after the `wire` line.
14. **When the length of a `sixbit` field is checked.** A `len` that is not a
    multiple of 6, or outside 6 to 1530, is a bit length against its
    transform, which 5b of 0.11 checks after the file is read: `field s
    0:0:8 sixbit` followed by a line `bogus` is `unknown-directive`.

---

# Version 0.15: value transforms

Status: Written. Transforms for values that 0.5 can only carry as raw bits: a
scale whose result is an integer (microseconds to `time_ms`), a scale on a
number of a text wire (an integer of 1e-7 degrees in JSON), numbers in
sign-and-magnitude form, IEEE floats with a scale, text in a 6-bit or 7-bit
character set, and integers written as octal digits.

## Exact factors

The integer scales below read `<factor>` and `<offset>` as exact numbers, not
as doubles:

- `<factor>` is a decimal (`[-]digits[.digits]`, no exponent) or a fraction
  `<num>/<den>` of two decimal integers, `den` not 0. A decimal is the exact
  fraction its digits state: `0.001` is 1/1000. The factor in lowest terms
  must have a numerator and a denominator each at most 2^32, and must not be
  0; otherwise `bad-directive`.
- `<offset>` is a decimal integer (`[-]digits`) with absolute value below
  2^63; anything else is `bad-directive`.

`round` is round-half-away-from-zero of the exact value. Engines compute with
integers wide enough to hold the exact products (128 bits suffice for every
`bits` field), never through a double.

## `bits`: integer scales

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `uiscale:<factor>[:<offset>]` | int | the bits as unsigned `v`, then `round(v × factor) + offset` | `round((x − offset) / factor)`, which must fit the field as unsigned |
| `siscale:<factor>[:<offset>]` | int | the bits as two's-complement `v`, then `round(v × factor) + offset` | `round((x − offset) / factor)`, which must fit the field as two's-complement |

A decoded result outside the signed 64-bit range is `transform-decode`. An
encoded value that does not fit is `transform-encode`. `len` is 1 to 64.

## `bits`: sign and magnitude

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `smag` | int | the most significant bit of the field's value (as `uint` reads it) is the sign, 1 negative; the other `len − 1` bits are the magnitude | sign 1 when `x < 0`; magnitude `|x|` |
| `smscale:<factor>[:<offset>]` | float | the `smag` value `v`, then `v × factor + offset` as `sscale` computes it (ruling 1 of 0.5) | `round((x − offset) / factor)` as `sscale` computes it, then as `smag` |

`len` is 2 to 64. Sign 1 with magnitude 0 decodes as 0; 0 encodes with sign
0. A magnitude of `2^(len−1)` or more is `transform-encode`.

## `bits`: scaled floating point

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `f32scale:<factor>[:<offset>]` | float | as `f32`, then `v × factor + offset` (ruling 1 of 0.5) | `(x − offset) / factor` (ruling 1 of 0.5), then as `f32` |
| `f64scale:<factor>[:<offset>]` | float | as `f64`, then `v × factor + offset` | `(x − offset) / factor`, then as `f64` |

`len` must be 32 and 64 respectively. Factor and offset are read as for
`sscale`. A decoded value that is not finite is `transform-decode`.

## `bits`: character sets

```
field  <key> <locator> chars:<set>
```

Yields `string`. The field is a sequence of characters of the set's width
`w`: character `i` is the `w` bits that start at bit `i × w` of the field,
read as `uint` reads a `w`-bit field at that place in the pack's bit order.
`len` is a multiple of `w`, from `w` to 2040.

| Set | `w` | Codes | Padding |
|---|---|---|---|
| `icao6` | 6 | 1–26 `A`–`Z`, 32 space, 48–57 `0`–`9`; every other code is `transform-decode` | space |
| `ais6` | 6 | code `c` below 32 is the character `c + 64` (`@`, `A`–`Z`, `[`, `\`, `]`, `^`, `_`); code `c` from 32 is the character `c` (space to `?`) | `@` |
| `ascii7` | 7 | 0 is NUL; 32–126 are themselves; every other code is `transform-decode` | NUL |

Character 0 starts at the field's first bit, `pos`, in either bit order, so
the first character on the wire is the first character of the text.
Decode removes trailing padding characters, and with `icao6` and `ais6` also
trailing spaces; with `ascii7` a NUL followed by a character that is not NUL
is `transform-decode`. Encode writes the text's characters and fills the
remaining characters with the padding. A character the set cannot hold, or
text longer than `len / w` characters, is `transform-encode`.

## `bits`: octal digits

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `octal` | string | the bits as unsigned, written as exactly `len / 3` octal digits with leading zeros | text of exactly `len / 3` characters `0`–`7`, read as an octal number; anything else is `transform-encode` |

`len` is a multiple of 3, from 3 to 63.

## Text wires: scales

On `xml`, `json` and `geojson`:

| Name | Yields | Decode | Encode |
|---|---|---|---|
| `scale:<factor>[:<offset>]` | float | the number as `float` decodes it, `v`, then `v × factor + offset` (ruling 1 of 0.5) | `(x − offset) / factor` (ruling 1 of 0.5), written as `float` writes it |
| `iscale:<factor>[:<offset>]` | int | the number's text read as an exact decimal `r`, then `round(r × factor) + offset` | `(x − offset) / factor` exactly, written as an exact decimal |

`scale` reads `<factor>` and `<offset>` as `sscale` does; `iscale` as the
integer scales do (Exact factors). On `json` and `geojson` the member must be
a number, as for `float`.

`iscale` decode reads the number's text, on `json` as written in the input:
`-?digits(.digits)?([eE][+-]?digits)?`. On `xml` the text must have that form
exactly, without surrounding whitespace. An exponent whose absolute value is
above 400, other text, or a result outside the signed 64-bit range is
`transform-decode`.

`iscale` encode writes the exact quotient in plain decimal notation: a `-` for
a negative value, the integer digits (`0` when there are none), and, when the
quotient is not an integer, a `.` and the fraction digits with no trailing
zero. A quotient that does not terminate within 18 fraction digits is
`transform-encode`. On `json` and `geojson` the text is written as a number.

## Load errors

`bad-directive`: one of these transforms on a wire it does not list; a `len`
it does not allow; a parameter that does not parse; an unknown character set;
`swap` with `chars` or `octal`.

## Rulings for 0.15

1. **`absent` (0.9)** compares the raw value as before: the field's bits on
   `bits`, the number's text on text wires. A `chars` field longer than 64
   bits takes no `absent`.
2. **`via` tables** see what the transform yields: an integer for the integer
   scales and `smag`, a string for `chars` and `octal`.
3. **Sequential layouts** (0.8) take every `bits` transform of this version.
4. **Rounding of a negative half.** `round(-2.5)` is `-3`; `round(2.5)` is
   `3`.
5. **`ais6` and spaces.** Decode removes trailing `@` and trailing spaces in
   any mix: `AB @ @` decodes `AB`.
6. **`absent` on `json` and `geojson`** compares the canonical text of ruling
   9 of 0.9, whatever the transform; `iscale` does not change it.
7. **Exact digits on `json` and `geojson`.** `iscale` reads the digits as
   written and writes the exact digits, never through a double, on both
   wires and on `geometry.*` slots: `9007199254740993` stays itself.
8. **No rounding for float scales.** `scale`, `f32scale` and `f64scale` take
   the arithmetic and order of ruling 1 of 0.5 and never round: `scale:1/10`
   writes 1.25 as `12.5`.
9. **Exact means exact.** A factor is the value its text states whatever its
   number of digits; it loads when its lowest terms fit the bounds. An
   `iscale` text with an exponent of at most 400 in absolute value decodes to
   its exact rounded value (`1e-400` is 0, `0e400` is 0). Engines use big
   integers or an equivalent bound.
10. **Range.** `uiscale` reads the true unsigned value in `[0, 2^64)` (ruling
    2 of 0.5 does not apply). Only the final value, after the offset, is
    checked against the signed 64-bit range.
11. **Signs in factors.** A fraction takes an optional `-` before `num` only;
    `den` is unsigned and not 0; a `+` anywhere is `bad-directive`.
12. **`smscale`** reads factor and offset as `sscale` does, not as the
    integer scales.
13. **Empty text.** As ruling 3 of 0.5: a `chars` field that is all padding
    decodes to `""`, present, and `""` encodes to all padding.
14. **Not finite.** A `scale` result that is not finite is `transform-decode`
    on decode and `transform-encode` on encode.
15. **Sign of zero.** `smag` and `smscale` take the sign from the integer
    after rounding: a value that rounds to 0 writes sign 0.
16. **An absent `chars` key** writes zero bits, as every `bits` field does; a
    pack that wants padding there uses `absent` with that value.
17. **NUL in `ascii7` text** is `transform-encode`.
18. **`trim`** with any transform of this version is `bad-directive`.
19. **Bounds.** A factor of `4294967296` loads and `4294967297` is
    `bad-directive`; an offset of `-9223372036854775807` loads and
    `-9223372036854775808` is `bad-directive`; `uiscale:-0` is
    `bad-directive` (factor 0).
20. **IEEE zero.** The float scales compute exactly the operations stated,
    the offset included when it is 0: a wire `-0.0` through `f64scale:10`
    gives `-0 × 10 + 0`, which is `+0`; a model `-0` encodes as
    `(-0 − 0) / 10`, which is `-0`.
21. **18 digits.** A quotient that needs more than 18 fraction digits is
    `transform-encode` even when it terminates: `2^-19` fails, `2^-18`
    writes.
22. **Leading zeros on `xml`.** The `iscale` text form allows them: `007`
    decodes 7. (On `json` they are already `malformed-wire`.)
23. **`geojson` strings.** `scale` and `iscale` refuse a string member on
    `geojson` as on `json` (`transform-decode`), although `float` there keeps
    its 0.1 typing.
24. **`xml` whitespace.** An empty element has no `#text`. Text that is only
    whitespace is text (ruling 1m of 0.11), and `iscale` reads every text
    untrimmed, so `<v>  </v>` and `<v> 1</v>` are `transform-decode`.
    This is about field decode only: `when <path>/#text present` keeps its
    0.5 meaning and holds when the element exists, whatever its text.
25. **Fractions are unsigned.** Every fraction factor of a float scale
    transform — `uscale`, `sscale`, `scale`, `smscale`, `f32scale`, `f64scale`
    — has unsigned `num` and `den`, on every wire that has them (`tlv` of
    0.13 included); `sscale:-1/10` and `scale:-1/10` are `bad-directive`. A negative factor is written as a decimal
    (`scale:-0.1`). The derive function `scale:` is not a transform: its
    `<num>` is integer text (ruling 2c of 0.11), so `scale:-1/4` loads. This states what ruling 1 of 0.5 meant by "two
    decimal integers"; no pack used a signed fraction. Ruling 11 is for the
    exact factors.
26. **Older transforms** keep their wire checks; apart from ruling 25 this
    version adds checks for its own transforms only.
27. **JSON numbers outside the double range.** A number is outside the
    double range when its magnitude rounds above the largest finite double
    (overflow); a number that rounds to 0 (`1e-400`) is inside it and reads
    as 0. On `json` and `geojson` a number outside the range that a field
    maps is read by that field's transform: `iscale` reads it exactly (ruling
    9), and `float`, `int` and `scale` fail with `transform-decode`. On
    `json` one that no field reads, anywhere in the document (arrays,
    unmapped members of group items, `when` members included; a member at a
    field line's locator counts as read even when an earlier line of the
    same key already gave the value, and so does one holding a sentinel), is
    `malformed-wire`, as ruling 39 of 0.8 is extended here; on `geojson` an unmapped number stays residue with its
    text as written (ruling 13 of 0.6).
28. **On `tlv`** (Version 0.13) every transform of this version is
    `bad-directive`, checked after the file as ruling 8 of 0.13 states for
    any transform the `tlv` table does not hold: `iscale:10` on a `tlv` field
    is `bad-directive`, and with a later line `bogus` the error is
    `unknown-directive`.

---

# Version 0.16: derive functions for time, distance and frames

Status: Written. Derive functions (Version 0.6, Derived keys) for an instant
split into seconds and nanoseconds, a distance in meters as degrees at a
latitude, radians, sums and differences (a height above mean sea level from
a height above the ellipsoid and a geoid separation the caller supplies), and
Earth-centred, Earth-fixed coordinates.

## Functions

Arguments and results are floats unless the table says `int`. A result that
is not finite, or an integer result outside the signed 64-bit range, leaves
the target absent.

| Function | Arguments | Result |
|---|---|---|
| `sec_of` | ms (`int`) | `int`: `floor(ms / 1000)` |
| `nsec_of` | ms (`int`) | `int`: `(ms − 1000 × floor(ms / 1000)) × 1000000`, from 0 to 999000000 |
| `ms_of` | sec nsec (`int`) | `int`: `sec × 1000 + floor(nsec / 1000000)` |
| `deg` | rad | `rad × (180 / π)`, the quotient computed first |
| `rad` | deg | `deg × (π / 180)`, the quotient computed first |
| `add` | x0 x1 | `x0 + x1`; on `int`, integer addition |
| `sub` | x0 x1 | `x0 − x1`; on `int`, integer subtraction |
| `deg_lat_of` | dist lat | `(dist / M) × (180 / π)` |
| `deg_lon_of` | dist lat | `(dist / (N × |cos φ|)) × (180 / π)`; absent when `|cos φ| ≤ 1e-12` |
| `m_lat_of` | ang lat | `ang × (π / 180) × M` |
| `m_lon_of` | ang lat | `ang × (π / 180) × N × |cos φ|` |
| `ecef_x` | lat lon hae | `(N + hae) cos φ cos λ` |
| `ecef_y` | lat lon hae | `(N + hae) cos φ sin λ` |
| `ecef_z` | lat lon hae | `(N (1 − e²) + hae) sin φ` |
| `lat_of_ecef` | x y z | φ of the closed form below, in degrees |
| `lon_of_ecef` | x y z | `atan2(y, x)` in degrees, in `(−180, 180]`; absent when x and y are both 0 |
| `hae_of_ecef` | x y z | h of the closed form below |

Every function takes exactly the arguments listed.

`floor` rounds toward negative infinity: `sec_of(-1)` is `-1` and
`nsec_of(-1)` is `999000000`.

## The ellipsoid

WGS 84: `a = 6378137` m, `f = 1 / 298.257223563`, `e² = f (2 − f)`,
`b = a (1 − f)`. For a latitude `lat` in degrees, `φ = lat × (π / 180)` and
`λ = lon × (π / 180)` (the quotient first), and

- `N = a / sqrt(1 − e² sin² φ)` (prime vertical radius),
- `M = a (1 − e²) / (1 − e² sin² φ)^1.5` (meridional radius).

ECEF to geodetic is Heikkinen's closed form, computed in this order:

```
p  = sqrt(x² + y²)
F  = 54 b² z²
G  = p² + (1 − e²) z² − e² (a² − b²)
c  = e⁴ F p² / G³
s  = cbrt(1 + c + sqrt(c² + 2c))
k  = s + 1 + 1/s
P  = F / (3 k² G²)
Q  = sqrt(1 + 2 e⁴ P)
r0 = −P e² p / (1 + Q) + sqrt(a²/2 × (1 + 1/Q) − P (1 − e²) z² / (Q (1 + Q)) − P p² / 2)
U  = sqrt((p − e² r0)² + z²)
V  = sqrt((p − e² r0)² + (1 − e²) z²)
z0 = b² z / (a V)
h  = U (1 − b² / (a V))
φ  = atan2(z + (a² − b²)/b² × z0, p)
```

`sin`, `cos`, `sqrt`, `cbrt`, `atan2` and powers are the platform's double
functions. A vector states every result of these functions in `model` under
`"@complete": true` and compares as Vector additions below state, except
the integer functions, which are exact.

## Rulings for 0.16

1. **Never an error.** An intermediate that is not finite, a division by
   zero or a square root of a negative number leaves the target absent; no
   derive function fails a conversion. `cbrt` is the real cube root.
2. **Near the centre.** `lat_of_ecef` and `hae_of_ecef` are absent when
   `G ≤ 0`, which covers the Earth's centre.
3. **Exact integers.** `floor` is exact integer division rounding toward
   negative infinity; no step goes through a float. Integer results are the
   exact mathematical value, and only the final result is range-checked:
   `nsec_of(-9223372036854775808)` is `192000000`.
4. **Types.** For `add` and `sub`, the target and both arguments are all
   `int` or all `float`. Every other function of this version takes and gives
   the types the table states; an `int` key where it states a float is
   `bad-directive`. There is no promotion.
5. **Longitude.** `lon_of_ecef` gives `180` where `atan2` gives `-180`.
6. **Latitude range.** A `lat` argument outside `[-90, 90]` leaves the target
   absent.
7. **`ms_of`** accepts any `nsec` and applies the formula: `ms_of(0, -1)` is
   `-1`, `ms_of(1, 999999)` is `1000`, `ms_of(1, 1500000000)` is `2500`.
8. **Degrees.** Radians become degrees as `x × (180 / π)`, the quotient
   first, for every function here (ruling 1 of 0.6).
9. **The square root in `r0`.** Its argument is 0 in exact arithmetic on
   the polar axis and comes out slightly negative or positive in doubles; a
   negative argument there is taken as 0, so a point on or near the axis
   gives latitude ±90 and its height (ruling 1 applies to every other
   square root).
10. **Negative zero on input.** A `float` decoded from `-0.0` keeps its
    sign; `lon_of_ecef` of `(-a, -0.0, 0)` is 180 by ruling 5.
11. **Longitude** arguments have no range check; only `lat` does (ruling 6).

## Vector additions

A float compared in `model` passes when it is within 1e-9 relative, as
before, or within `1e-7` absolute: `|got − want| < 1e-7`. Results that are 0
in exact arithmetic (a height of 0 from ECEF, `ecef_x` at longitude 90) are
tiny but not 0 in doubles.

## Load errors

As for every derive function: a wrong number of arguments, an undeclared key,
or a type that does not fit (ruling 4) is `bad-directive`.

---

# Version 0.17: gated fields on a fixed layout

Status: Written. In many fixed-layout binary messages a field exists only
when other bits of the message hold a value: a validity bit, a two-bit mode,
a bit that chooses between two meanings of the same bits. The gating bits may
come after the field they gate. Version 0.8's `presence` reads its bits at a
cursor and cannot express this. A gate block on a fixed layout can.

```
if  <locator> <value>[,<value>…]      # the block holds when the bits equal one of the values
if  !<locator> <value>[,<value>…]     # the block holds when they equal none
  field …                             # field, const, default and nested gate blocks
end
```

A gate block is valid in a `bits` pack with the fixed layout, in common
lines, in a kind and inside a group's item. `<locator>` is a fixed-layout
locator (`<word>:<pos>:<len>`, item-relative inside a group, `len` 1 to 64)
and may lie before, inside or after the fields it gates, and may overlap
them. Each `<value>` is an unsigned decimal integer below `2^len`. In a
`layout sequential` pack `if` keeps its 0.8 meaning (presence names); a gate
locator there is `bad-directive`.

## Decode

The gate's bits are read as unsigned, as a `when` reads them. The block holds
when the value equals one of the listed values (with `!`, when it equals
none of them). A gate any of whose bits lies beyond the input does not hold,
and neither does its `!` form. When a block holds, its lines are decoded by
the existing rules; when it does not, those lines set no
key. Gates nested in a block are evaluated only when the outer
block holds.

A gate locator does not itself count toward the length decode requires; it is
read like a `when` (ruling 21 of 0.5). A block's fields and `const` lines count only
when it holds (ruling 3 of 0.6 for `const`). A field of a held block beyond the input is `malformed-wire` unless it
is `optional`.
A line in a block that does not hold counts as a line whose locator is absent
(Version 0.6, One key at several locators): decode goes on to the key's next
line.

## Encode

Encode chooses the blocks that hold, writes them, and checks that the output
decodes the same way.

1. A block is **open** when one of its `field` lines, or a line of
   a nested open block, maps a key the entity holds (inside a group, the
   item holds). A `default` or a
   sentinel (0.9) does not open a block.
2. The bits are first written by the lines outside any block, by the 0.5
   and 0.6 rules (`const` and `when` included). Bits that a line with a
   present key, a `const`, a `when` or a group count wrote are **written**.
   The zero bits an absent key leaves are not written, and neither are the
   bits of a `default` or a sentinel: a gate value of step 3 replaces them.
3. In line order, depth first (a block, then the blocks nested in it,
   then the next block), each open
   block none of whose gate bits is written gets its gate value: the first
   listed value, or for `!` the smallest value not listed (none when the
   list names every value). Those bits are then written. A gate any of
   whose bits is already written gets no value; the block is evaluated on
   the bits as they are.
4. Each block is evaluated on the bits as written, as decode evaluates it
   (a nested block only when the block enclosing it holds), on the bits of
   step 3 together with the bits an outside `default` or sentinel wrote
   where no gate value replaced them; bits nothing wrote read as 0,
   wherever they lie. The blocks that hold are the **held** blocks.
5. The output is the 0.5 encode of the lines outside any block and the
   lines of the held blocks, in line order (ruling 5 of 0.5 for overlaps;
   `const` and `when` written last), with the gate value of step 3 of each
   held block written over the bits of a `default` or a sentinel and under
   the bits of a line with a present key, a `const` or a `when`. A block
   that is not held writes nothing, its `const` lines and its gate value
   included; a held block's `const` lines are written and count toward the
   length.
6. The output must decode to the same choice: every held block holds on the
   output and every other block does not. Otherwise, and when a key the
   entity holds is mapped only by lines of blocks that are not held, the
   encode is `transform-encode`.

The encoded length is the furthest bit over the lines outside any block, the
held blocks' lines and their gate locators. A block that is not open can be
held by the zero bits of its gate (a validity bit whose value 0 means valid);
it is then written, with its sentinels and defaults, and its bits count toward
the length.

A key mapped in two blocks of opposite gates (one bit choosing between two
meanings) opens both; step 3 gives the earlier block its gate, step 4 holds
that block only, and the round trip keeps the value when a raw key outside the
blocks maps the gate bits, because then those bits are written in step 2.

## Load errors

`bad-directive`: a gate on a wire other than `bits`, a gate locator in a
sequential layout, a presence name (`if p.1`) in a fixed layout, a value that
is not an unsigned decimal integer or does not fit `len`, an empty value list
or a value listed twice, `if` without `end`, or a line in a block other than
`field`, `const`, `default` or a nested gate block (`when`, `group`, `kind`,
`requires`, `typemap` and `also`, which is for sequential layouts, are not
allowed inside). A list that can
never hold (`if !0:0:1 0,1`) loads.

## Rulings for 0.17

1. **Kinds.** A block inside a kind is evaluated after the kind is
   selected; a kind's `requires` sees the entity only.
2. **Groups.** Inside a group's item the gate locator is item-relative and
   the block is evaluated per item. A gate or a gated field that lies
   outside its item (`item <bits>`), or at or beyond the start of a
   locator-counted group in the same scope, is `bad-directive`, as for a
   field (0.7). A bit outside the item cannot gate a field of every item.
3. **Overlap** between fields is always allowed (ruling 5 of 0.5).
4. **Capability.** `model_keys(format)` lists the keys inside blocks as it
   lists every other mapped key.
5. **Defaults inside a block** apply to the fields of that block and of
   the blocks nested in it; the innermost default wins, and a block's
   default wins over a kind or common default. They are written only when
   the block is held. This differs on purpose from ruling 2 of 0.8, where a default is
   content for a presence bit.
6. **Sentinels.** A block whose fields all decode absent through a sentinel
   loses its gate on re-encode (it is not open) unless a raw key outside the
   blocks maps the gate bits; this extends ruling 7 of 0.9.
7. **Precedence on one bit** in the output of step 5, highest first:
   `const`, `when` and group counts; field lines, between which ruling 5 of
   0.5 holds as before (the earlier line wins, a line written from a
   `default` included); a gate value; a sentinel. A gate value is written
   over a bit that only a `default` or a sentinel wrote; a bit that a line
   with a present key covers keeps the field lines' value, even when an
   earlier `default` line won that bit.
8. **Gate values of blocks that end up not held** (their enclosing block
   does not hold) still count as written for the later gates of step 3 and
   for step 4, and are not part of the output.
9. **Group items.** A gate of a scope any of whose bits lies within the items of a
   group of that scope (a fixed `count <n>` group whose item bits are
   known) is `bad-directive`; a gate inside an item sees the item's bits.
   Step 6 is checked once, on the final output, for every scope and item.
10. **Errors of blocks that are not held.** A line of a block that is not
    held raises no encode error (a value that does not fit that block's
    transform is not an error when another block of the key is held).
11. **Written bits** in step 2 are the union of the ranges of the lines
    that count as writing, whatever line wrote last.
12. **Malformed gate lines.** Any `if` line that is not one locator and one
    value list (a space after a comma, a third token, a malformed locator,
    `len` 0 or above 64) is `bad-directive`.
13. **When these errors are found.** Every load error of this version is a
    check after the file is read (ruling 5b of 0.11), except an `if` line with
    no argument at all, which the line check refuses as the line is read
    (5b, step 3). So `if 0:0:2 4` (a value that does not fit) followed by a
    line `bogus` is `unknown-directive`, and so is a gate on the `json` wire
    followed by `bogus`.
14. **Gates under six-bit armor** (Version 0.14). The `L` of 0.14 is the
    encoded length of this version: the furthest bit over the lines outside
    any block, the held blocks' lines and their gate locators, an `optional`
    field counted only when it is written; lines of a block that does not
    hold do not count. On decode, "beyond the input" is measured in the bits
    the armored text carries. Step 6 decodes the output as it will be read:
    `L` rounded up to a multiple of 6 bits, padded with zeros. Without armor
    the encoded length is unchanged: every line of a held block counts, an
    `optional` one included (`conformance-gates-edge` vector 05).

---

# Version 0.18: conditional output and flag tokens

Status: Written. Encoders often write a value only when another exists (a
confidence only beside a classification), build one text from several flags
(a status list of tokens), write a time without a zero fraction, or write an
element that has no content (an always-present empty `detail`). Version 0.18
adds a field option, three derive functions, a transform and an `xml`
directive for these.

## Written only with another key

```
field  <model-key> <locator> <transform> [options] with <other-key>
```

`with` is a field option (Version 0.6, Field options) on every wire. On
encode, the line writes only when the entity (inside a group, the item) holds
`<other-key>`; otherwise the line is treated as a line whose key is absent and
that has neither a `default` nor a sentinel: nothing on text wires and
`protobuf`, zero bits on `bits`. Decode is unchanged. `<other-key>` must be
declared (`undeclared-key`) and is checked like a `requires` key
(`module-not-used`). `with` given twice on one line is `bad-directive`.

## Derive functions

| Function | Arguments | Result |
|---|---|---|
| `tokens:<sep>:<t1>,<t2>,…` | a1 a2 … (`int`), one per token | `string`: the tokens whose argument is present and not 0, in order, joined by `<sep>`; absent when no argument is present and not 0 |
| `has_token:<sep>:<t>` | a (`string`) | `int`: 1 when `<t>` is one of the parts of `a` split at `<sep>` (empty parts ignored), else 0 |
| `text_if:<text>` | a (`int`) | `string`: `<text>` when a is not 0; absent when a is 0 or absent |

Whitespace here is space, tab, line feed and carriage return. `<sep>` is one
character other than `:`, `,` or whitespace, or one of the
names `space` (U+0020), `comma` and `colon`. A token is one or more characters
other than `:`, `,`, whitespace and the separator character. `<text>` is one
or more characters other than whitespace, and may contain `:`. The number of
arguments of `tokens` must equal the number of tokens; a duplicate token, an
empty token, a wrong argument count or type is `bad-directive`.

## A time without a zero fraction

| Name | Wires | Decode | Encode |
|---|---|---|---|
| `iso8601_short` | `xml`, `json`, `geojson` | that of `iso8601_ms`: fraction digits beyond the third are truncated; the designator is as Version 0.6 states | `YYYY-MM-DDTHH:MM:SSZ` when the milliseconds are 0; otherwise `YYYY-MM-DDTHH:MM:SS.` and the three digits of the milliseconds with trailing zeros removed (`.5`, `.12`, `.123`), then `Z` |

It yields `int` (epoch milliseconds), as `iso8601_ms` does.

## `xml`: an element written when empty

```
element  <path>
```

A line of an `xml` pack, common or in a kind. `<path>` is a path of element
names under the root (`detail`, `a/b`). On encode the element at `<path>`, and
each element on the way to it, is written even when nothing inside it is
written: `<detail/>`. Its position is that of the line, as for a field (ruling
10 of 0.5). Decode ignores the line. `element` on another wire, or a path with
`@` or `#text`, is `bad-directive`.

## Rulings for 0.18

1. **A line suppressed by `with` is absent everywhere.** It is not content
   for a presence, `opt`, `fx` or chain bit (Version 0.8), and neither is its
   default; it does not open a gate block, its bits are not written, and its
   key does not count as mapped for step 6 (Version 0.17); it is not a
   candidate for ruling 16 of 0.5 or ruling 16 of 0.9, so a later line on the
   same locator whose key is present is written. It still names its locator
   for ruling 23 of 0.9: the member is written at the position of the first
   line naming the locator, suppressed or not.
2. **Holding.** `<other-key>` is checked on the entity (or the item) only,
   never on a `default`: a scalar holds when it is present, whatever its
   value (0 and the empty text included); a list holds when it is present
   with at least one item. Inside a group only the item is checked; the key
   must be declared, not necessarily mapped by the group.
3. **`with` on its own key** (`field a … with a`) has no effect when the
   entity holds `a`; when it does not, the line writes nothing, its default
   included.
4. **Scalar items.** A `.` field suppressed by `with` writes its item as an
   item without the value (ruling 11 of 0.7: `null` on `json`, an empty
   element on `xml`). `with` on a `.` field of a packed `protobuf` group is
   `bad-directive`.
5. **Other lines.** `with` on a `const`, `group` or `also` line is
   `bad-directive`. When a sequential `field` line is suppressed, its `also`
   keys stay candidates for the bits (ruling 13 of 0.8). An undeclared `<other-key>` is checked as a `requires`
   key is, in the same order of errors.
6. **Round trips.** Decode is unchanged, so a wire value whose companion key
   is missing decodes and is dropped on re-encode: a same-format round trip
   is byte-exact only when every `with` key is held.
7. **`tokens` and partial arguments.** With `any` (Version 0.8), `tokens` is
   a function whose target is set when only some of its arguments are
   present; its target is set in the first derive pass in which one of them
   is present and not 0, and stays absent until then. The 0.8 sentence that
   names `any` alone is amended.
8. **Lossy flags.** `has_token` gives 0 or 1, so a round trip through
   `tokens` and `has_token` turns an absent flag into a present 0, and a
   token not listed is dropped.
9. **Separators.** The names `space`, `comma` and `colon` are lowercase and
   exact, and apply to `tokens` and `has_token` only; `join:space` still
   joins with the text `space`. A character is one Unicode code point.
10. **`has_token` compares exactly**: case-sensitive, no trimming. `a, b`
    split at `comma` has the parts `a` and ` b`.
11. **Negative and far instants.** `iso8601_short` takes the milliseconds as
    `ms − 1000 × floor(ms / 1000)`: −1 is `1969-12-31T23:59:59.999Z`. An
    instant before 0000-01-01 or after 9999-12-31 is `transform-encode`.
    `iso8601_short` on `bits` or `protobuf` is `bad-directive`.
12. **`element` and groups.** `element` inside a group, or whose path
    equals or passes through a group's path, is `bad-directive` (rulings 18
    and 21 of 0.7). A path that is a strict prefix of a group's path is
    allowed and writes the container even when the list is absent.
13. **`element` position and duplicates.** An element is placed at the
    first line, of any kind, that addresses it or a path under it (ruling 10
    of 0.5). A second `element` line for the same path loads and adds
    nothing. An empty path, an empty step (`a//b`), or a leading or
    trailing `/` is `bad-directive`.
14. **Context and derivations** fill keys before encode (Version 0.6, Order
    inside `convert`), so `with` sees context and derived keys.
15. **Whitespace between tokens.** On every line of a pack or a model
    module, the whitespace that separates tokens (Version 0.1, "a keyword
    then whitespace-separated arguments") is space, tab, line feed and
    carriage return only; any other character, U+00A0 included, is part of
    a token.
16. **`element` path steps** are element names: a step that contains `@` or
    `#` anywhere (`a#b`, `x@y`) is `bad-directive`.
17. **A packed `protobuf` group** (ruling 4) is a group whose body is `.`
    fields with `pvarint`, `psint`, `pdouble` or `pfloat` only; `default`
    lines in the body do not change that.
18. **Numbers written in a pack or module** (`default`, the model side of
    `map`, `requires =`, `case`) are read as written, without trimming: a
    quoted `"5 "` on an `int` key is `key-type-mismatch`.
19. **`element` placement** (ruling 13) does not count `when <locator>
    present` lines, which name no position (ruling 23 of 0.9).
20. **A suppressed sequential line** whose `also` keys give no value writes
    zero bits, not its sentinel (ruling 1).
21. **`iso8601_short` on `text` and `tlv`** (Versions 0.10 and 0.13) is
    `bad-directive`, as on `bits` and `protobuf`: it is valid on `xml`,
    `json` and `geojson` only.
22. **`with` on `text` and `tlv`.** A line that `with` suppresses writes what
    a line whose key is absent writes on that wire: on `text` an empty field
    (Version 0.10), on `tlv` no item (Version 0.13).
23. **`with` under six-bit armor** (Version 0.14, ruling 14 of 0.17). A
    suppressed line writes zero bits, so it counts toward `L` as any line of
    the scope does; an `optional` field that `with` suppresses is not written
    and does not count.
24. **Year 0000.** `iso8601_short` writes the instants of year 0000
    (ruling 11), and its decode is that of `iso8601_ms`, which refuses them
    (ruling 3d of 0.11). A round trip of such an instant fails with
    `transform-decode`; this is accepted.
25. **`element` with a wrong number of arguments** is refused by the line
    check as the line is read (ruling 5b of 0.11, step 3); its other errors
    are checks after the file. So `element a b` followed by a line `bogus`
    is `bad-directive`.

---

# Version 0.19: ASN.1 unaligned PER

Status: Written. Many message sets are defined in ASN.1 and sent in the
unaligned Packed Encoding Rules (UPER, ITU-T X.691): every value takes the
fewest bits its constraint allows, with no padding between fields. A
sequential `bits` pack (Version 0.8) with `encoding uper` describes such a
message. It adds locators that compute the bit length of a field from its
ASN.1 constraint, the blocks for SEQUENCE extension markers and CHOICE, and
the X.691 forms of a length.

```
wire       bits
layout     sequential
bit_order  msb
encoding   <none | uper>        # default none
```

`encoding uper` needs `layout sequential` and `bit_order msb`; elsewhere, more
than once, after the first `kind`, or with another value it is
`bad-directive`, checked after the file is read (ruling 10 of 0.10). Every
line of 0.8 keeps its meaning in a UPER pack. A pack writes the ASN.1
structure of its message as lines in the order X.691 encodes the
components: SEQUENCE components as written, CHOICE alternatives by `alt`
index in the canonical order of their tags (the order written, under
AUTOMATIC TAGS), and ENUMERATED root values by index in ascending order of
their values. The pack, not the engine, holds the ASN.1 definition.

## Terms of X.691 used here

- **Constrained whole number** in `lb..ub`: the value minus `lb` as an unsigned
  number of `b` bits, `b` the fewest bits that hold `ub - lb` (0 bits when
  `lb = ub`).
- **Length determinant** (unconstrained length `n`): when `n < 128`, 8 bits
  `0` and `n` in 7 bits; when `128 <= n < 16384`, 16 bits `10` and `n` in 14
  bits. A first bit pair `11` (a fragmented length) is `malformed-wire` on
  decode and `transform-encode` on encode.
- **Normally small non-negative whole number** `n`: when `n <= 63`, a `0` bit
  and `n` in 6 bits; otherwise a `1` bit, a length determinant of the octet
  count, and `n` in that many octets, big-endian, fewest octets (at least one).
- **Open type**: a length determinant of an octet count, then that many
  octets. It holds the complete encoding of one value, padded with zero bits
  to a whole octet.

## Locators

In a UPER pack a `field` locator may be a bit length as in 0.8, or one of the
forms below; its bit length then follows from the constraint and the value.

| Locator | ASN.1 | On the wire |
|---|---|---|
| `int:<lb>:<ub>` | `INTEGER (lb..ub)` | a constrained whole number |
| `int:<lb>:<ub>:ext` | `INTEGER (lb..ub, ...)` | one bit, 0 for a value in `lb..ub`, then the constrained whole number; 1, then a length determinant of an octet count and the value as a two's-complement number of that many octets |
| `int:<lb>:` | `INTEGER (lb..MAX)` | a length determinant of an octet count, then the value minus `lb` as an unsigned number of that many octets, fewest octets (at least one) |
| `int::` | `INTEGER` | a length determinant of an octet count, then the value as a two's-complement number of that many octets, fewest octets |
| `enum:<n>` | `ENUMERATED` with `n` root values | the index, `0..n-1`, as a constrained whole number |
| `enum:<n>:ext` | the same, extensible | one bit, 0 then the index as above; 1 then a normally small non-negative whole number, the index of an extension value |
| `chars:<lb>:<ub>` | `IA5String`, `VisibleString` or `PrintableString (SIZE (lb..ub))`, with no `FROM` constraint | the character count as a constrained whole number in `lb..ub`, then each character in 7 bits |
| `chars:` | the same, no size constraint | a length determinant of the character count, then each character in 7 bits |
| `octets:<lb>:<ub>` | `OCTET STRING (SIZE (lb..ub))` (not `UTF8String`, whose size X.691 ignores) | the octet count as a constrained whole number, then the octets |
| `octets:` | `OCTET STRING`, `UTF8String` | a length determinant of the octet count, then the octets |

`<lb>` and `<ub>` are decimal integers, `-2^63 <= lb <= ub <= 2^63-1` (for
`chars` and `octets`, `0 <= lb <= ub < 65536`); `n` is 1 to 65536. Anything
else is `bad-directive`. A count equal for `lb` and `ub` takes 0 bits, so
`chars:8:8` is eight characters with no count. A `BOOLEAN` is a 1-bit field,
`NULL` takes no line, and a `BIT STRING (SIZE (n))` is an `n`-bit field.

## Transforms on UPER locators

| Locator | Transforms | Decode | Encode |
|---|---|---|---|
| `int:…` | `uint`, `twos`, `uscale:<f>[:<o>]`, `sscale:<f>[:<o>]` | the integer value `v` (not the raw bits): `uint` and `twos` give `v`; the scales give `v * f + o` (ruling 1 of 0.5) | the value, or `round((x - o) / f)`; a value outside the constraint is `transform-encode` (for `:ext`, outside the root it is written in the extension form) |
| `enum:…` | `uint` | the index; an extension index decodes to `n + index` | an index below `n` in the root form, `n` or more in the extension form (`:ext` only, else `transform-encode`) |
| `chars:…` | `ascii` | the characters, each 7 bits as a code from 0 to 127 | each character's code; a character above 127, or a count outside `lb..ub`, is `transform-encode` |
| `octets:…` | `hex`, `utf8` | the octets as lowercase hex text, or as UTF-8 text | hex text or the text's UTF-8 bytes; a count outside `lb..ub` is `transform-encode` |

`hex` and `utf8` behave as on `tlv` (0.13). `ascii` on a `chars` locator does
not remove NULs or check printable characters; codes below 32 decode as those
characters. `via` applies to every form. Another transform is `bad-directive`.

## Extension markers on a SEQUENCE

```
ext
  …                 # the root components of the SEQUENCE
end
```

An `ext` block is a SEQUENCE whose definition has an extension marker
(`...`). Decode reads one bit before the block. When it is 0, the block is
read. When it is 1, the block is read, and then the extension additions after
it: their number `m` as a normally small length (ruling 16), then `m` presence
bits, then one open type for each bit that is 1. The additions are skipped; they are
not mapped and not residue. Encode writes 0 and the block.

The presence bits of the OPTIONAL and DEFAULT root components are a
`presence <name> <n>` line, first in the block, with an `if` block for each
component (0.8); a component that has a DEFAULT and is absent is the bit 0.

## CHOICE

```
choice <n> [ext]
  alt <i>
    …
  alt <j>
    …
end
```

A CHOICE of `n` root alternatives. With `ext`, decode first reads one bit.
The index is a constrained whole number in `0..n-1`; decode reads it, then the
lines of the `alt` with that index. An index with no `alt` is
`malformed-wire`. With `ext` and the bit 1, decode reads a normally small
non-negative whole number (the index of an extension alternative) and an open
type, and skips them: no `alt` is read.

Encode writes the first `alt`, in line order, that has content (a present key
or a non-empty list, at any depth, as ruling 22 of 0.8 states for presence),
with its index and, under `ext`, the bit 0 first. When no `alt` has content,
the first `alt` is written. An `alt` index outside `0..n-1`, an index given
twice, a line between `choice` and the first `alt`, and an `alt` outside a
`choice` are `bad-directive`.

## SEQUENCE OF

```
group <list> size <lb> <ub>      # SEQUENCE (SIZE (lb..ub)) OF: the count as a constrained whole number
group <list> size                # SEQUENCE OF with no size constraint: a length determinant
```

The count is followed by that many items. A list whose item count is outside
`lb..ub` is `transform-encode`; an absent list is written with the count `lb`
of items with no keys when `lb > 0`, else as an empty list. `size` is valid
only in a UPER pack (`bad-directive` elsewhere); the other group forms of 0.8
keep their meaning.

## The whole message

Decode reads the lines from bit 0. After the last line, the rest of the input
is ignored (ruling 9 of 0.8). Encode pads the bits to a whole octet with zero
bits; an encoding of no bits is one octet `00` (X.691 10.1.3).

## Errors

Every rule of 0.8 on reading past the input applies. A length determinant, a
count or an index that the input cannot hold is `malformed-wire` before any
item is read (ruling 14 of 0.8). A value read that lies outside its
constraint (a constrained whole number whose `ub - lb` is not a power of two
minus one, read as a value above `ub`) is `malformed-wire`.

## Vectors

`input` and `expect` of a UPER pack are lowercase hex text (ruling 7 of 0.5).
Expected bytes may be derived with an ASN.1 compiler or library that does not
import an engine, from a public ASN.1 module, as long as the vector names the
tool and its version.

## Rulings for 0.19

1. **Absent keys.** An absent key with no `default` writes `lb` for
   `int:<lb>:<ub>`, `int:<lb>:<ub>:ext` and `int:<lb>:` (the last in one
   octet), 0 in one octet for `int::`, index 0 for `enum`, `lb` characters of
   code 0 for `chars`, and `lb` zero octets for `octets`.
2. **DEFAULT components.** In a UPER pack a `default` does not set a presence
   bit (ruling 2 of 0.8 does not apply): an absent key under an `if` writes
   the bit 0, and decode with the bit 0 leaves the key absent; the default is
   used only where a line writes the key.
3. **Content** for a presence, `opt` or `choice` decision (ruling 22 of 0.8)
   is looked for inside `ext`, `choice` and `alt` blocks as well.
4. **Signed values.** On UPER locators `uint` and `twos` both give the signed
   value; only the constraint limits it. `ub - lb` and `v - lb` are computed
   without overflow (as unsigned 64-bit or wider).
5. **Integers beyond 64 bits.** An `int::` or `int:<lb>:` value of more than 8
   octets, or one whose value does not fit a signed 64-bit integer, is
   `transform-decode`. An integer with an octet count of 0 is `malformed-wire`.
6. **No alignment.** Octets, open types and characters are read and written at
   the cursor; nothing in a UPER pack aligns to an octet but the end of the
   whole message.
7. **Non-minimal forms on decode** are accepted: a two-octet length
   determinant for a short length, an integer in more octets than needed, a
   normally small number in its long form, an extensible integer in the
   extension form with a value inside the root. Encode writes the minimal
   form, and the extension form of `int:…:ext` in the fewest octets.
8. **Extension additions all absent.** An extension bit 1 whose addition
   presence bits are all 0 is accepted; nothing is skipped.
9. **UPER lines elsewhere.** `int:`, `enum:`, `chars:` and `octets:`
   locators, `ext`, `choice`, `alt` and `group … size` outside a UPER pack are
   `bad-directive`, checked after the file is read. `encoding` joins the
   header directives of ruling 24 of 0.8.
10. **Options and lines.** `swap` and `trim` on a UPER locator are
    `bad-directive`; `also` is allowed. `when`, `const` and count fields take
    bit lengths only.
11. **With armor.** `encoding uper` and `armor sixbit` in one pack are
    `bad-directive`.
12. **Group sizes.** `size <lb> <ub>` needs `0 <= lb <= ub < 65536`
    (`bad-directive` otherwise). A count of 0 decodes to a present, empty
    list.
13. **Empty strings.** A `chars` or `octets` count of 0 decodes to the empty
    string, present.
14. **NULL alternatives.** An `alt` with no lines has no content, so a
    message holding such an alternative re-encodes with the first `alt` that
    has content, or the first `alt`: the round trip is not exact.
15. **Numbers in locators**, and the numbers of `choice`, `alt` and
    `group … size` lines, are an optional `-` (locators only) and digits with
    no leading zero (`-0` refused); `choice <n>` takes 1 to 65536; inside an `ext` block a
    `presence` line, when there is one, is the first line.
16. **The extension bitmap length.** The number of extension additions `m` is
    written as a normally small length: when `m <= 64`, a `0` bit and `m - 1`
    in 6 bits; otherwise a `1` bit and a length determinant of `m`.
17. **Not stated by a UPER pack** in 0.19: an extensible SIZE constraint, an
    extensible semi-constrained integer, a permitted-alphabet (`FROM`)
    constraint, and fragmented lengths (16384 or more). A pack whose ASN.1
    needs one of them leaves that component unmapped.
18. **Smaller points.** An absent key on `octets:` writes zero octets. The
    `encoding` directive, whatever its value, on a wire other than `bits` is
    `bad-directive`; `encoding none` is allowed in any `bits` pack. A negative
    value for an `enum` locator is `transform-encode`. An `ext` block or an
    `alt` with no lines is allowed.
19. **Further points.** A `choice` with no `alt` line is `bad-directive`.
    Ruling 9 applies to `bits` packs; on `xml` and `json` a locator such as
    `int:x` is a path as before. In a UPER pack no `default` counts as
    content anywhere (presence, `opt`, chain `fx`, `choice`). A normally small
    number in its long form with an octet count of 0 is `malformed-wire`, and
    one of more than 8 octets, like an extension `enum` value that does not
    fit 64 signed bits, is `transform-decode`; ruling 5 applies to the
    extension form of `int:<lb>:<ub>:ext` as well. "Another transform" means a
    known transform the locator does not take; an unknown name keeps its
    error of 0.1.
20. **Points from the implementations.** A list may be mapped by groups in
    different `alt`s of one `choice`, as ruling 23 of 0.8 allows for
    different `if` and `opt` blocks. The `presence` rule of ruling 15 holds
    for lines directly in the `ext` block; a `presence` nested deeper is a
    nested SEQUENCE's. For an integer read from octets the checks run in this
    order: the input holds the octets (`malformed-wire`), the count is not 0
    (`malformed-wire`), the value fits (`transform-decode`, a failure of the
    field's key as ruling 9 of 0.1.1 states; for a CHOICE extension index,
    which has no key, the decode fails with it).
21. **The UPER directives on other wires.** `ext`, `choice`, `alt` and
    `encoding` are directives of the language on every wire: outside a UPER
    pack (any wire, any layout) they are `bad-directive`, not
    `unknown-directive`, checked after the file is read. Ruling 19 is about
    locators only.
    Each `alt` is a block of its own for presence names (ruling 12 of 0.8):
    two `alt`s of one `choice` may each declare `presence p`.
22. **`absent` (0.9) in a UPER pack.** On a field with a UPER locator
    (`int:`, `enum:`, `chars:`, `octets:`) `absent` is `bad-directive` in
    0.19: the bits of such a field depend on its value, so 0.9's raw value is
    not stated for it. A field with a bit-length locator in a UPER pack takes
    `absent` as in any sequential `bits` pack.
23. **The argument counts of the UPER lines.** As a line is read (step 3 of
    5b of 0.11), `encoding` takes exactly one argument, `ext` none, `choice`
    one or two, and `alt` one; any other count is `bad-directive` there, as
    for `armor` in ruling 13 of 0.14. Their values (`encoding per`, `choice
    0`, `choice 2 foo`) are checked after the file is read.
24. **UPER locators outside a UPER pack** are `bad-directive` after the file
    is read (rulings 9 and 19), in a fixed-layout `bits` pack as in a
    sequential one, not `bad-locator` as the line is read (5a of 0.11). A
    locator is a UPER locator when it begins `int:`, `enum:`, `chars:` or
    `octets:`.
25. **The UPER lines and the `wire` line.** `encoding`, `ext`, `choice` and
    `alt` are not in the list of 0.11 (5b) of lines that stand after the
    `wire` line; `end` is, so a block they open before the `wire` line is
    `missing-wire` at its `end`.
26. **The other UPER checks are after the file.** The pack is known to be a
    UPER pack only once its `encoding uper` line is read, which may follow its
    fields. So the numbers of a UPER locator (`int:5:4`, `int:0:07`), a UPER
    locator on a `when` or `const` line (ruling 10), the value of a `choice`
    (`choice 0`), an `alt` out of range, repeated or outside a `choice`, a line between a
    `choice` and its first `alt`, and
    `absent` on a UPER locator (ruling 22; step 10 of 5b of 0.11 does not
    apply, the field having no bit width) are `bad-directive` after the file
    is read. "After the first `kind`" for `encoding` counts every `kind`
    line, as ruling 11 of 0.14 states for `armor`.
27. **0.19 beside 0.15 and 0.17.** In a UPER pack, a field with a UPER
    locator takes only the transforms of the 0.19 table; a 0.15 transform
    there (`uiscale:10`, `smag`, `chars:icao6`, `octal`, the text wires'
    `iscale`) is a known transform the locator does not take, `bad-directive`
    after the file (ruling 19). A field with a bit length in a UPER pack takes
    the `bits` transforms of 0.15, as ruling 3 of 0.15 states for sequential
    layouts. A UPER pack is sequential, so its `if` is 0.8's; a gate locator
    there is `bad-directive` after the file (ruling 13 of 0.17). `ext`,
    `choice` and `alt` inside a 0.17 gate block, which only a fixed layout
    has, are `bad-directive` after the file.

---

# Version 0.20: kind selection

Status: Written. Version 0.5 picks a kind on decode from `when` values that
each equal one value, and on encode from which keys the entity holds. Real
formats need three more things: a kind that covers a range or a list of wire
values, an encode kind chosen by the value of a key (a track environment), and
a record whose later part is laid out according to a value read earlier in the
same record, after other fields.

## Lists and ranges in `when`

```
when  <locator> <value>[,<value>…]
```

Each `<value>` is a value as in 0.5, or, on `bits` and on a `protobuf` varint,
a range `<lo>..<hi>` of unsigned decimal integers with `lo ≤ hi`. The `when`
holds when the wire value matches any of the listed values or lies in any of
the ranges (both ends included). On encode the first listed value is written;
for a range listed first, its `lo`. `present` may not be combined with other
values. On `bits` and `protobuf` a value is digits or digits`..`digits;
anything else (`5..`, `..5`, `1..2..3`, `0x10`), a range with `lo > hi`, a
range end that does not fit the field, a third token (`1, 2`) or an empty value
in the list is `bad-directive`. On text wires `..` has no meaning and the text
is literal. A comma now separates values; no pack had a `when` text with a
comma. `""` alone is the empty text (Version 0.9, ruling 11).

## Encode kind by value

```
requires  <model-key>=<value>[,<value>…]  [<model-key>…]
```

A `requires` key may carry `=` and a list of values. The kind qualifies only
when the entity holds the key and its value, as canonical text (ruling 3 of
0.1.1 for floats, decimal digits for integers, the text itself for strings),
equals one of the listed values. A plain key keeps its 0.5 meaning (present).
A value is read as the key's declared type at load: one that cannot be is
`key-type-mismatch`. A list key with `=` is `bad-directive`.

## A switch on a decoded value (sequential layouts)

```
switch  <model-key>
  case  <value>[,<value>…]
    …
  case  …
    …
  else
    …
end
```

Valid in a `layout sequential` pack, in common lines, in a kind and inside a
group body or an `if`, `opt` or chain block. `<model-key>` must be mapped by
a `field` (or `also`) line of the same scope that comes before the `switch`
line in reading order; otherwise `bad-directive`.

Decode: when the cursor reaches `switch`, the key's decoded value (after `via`
and `typemap`), as canonical text, selects the first `case` whose list holds
it; its lines are read at the cursor. When no `case` holds it, the `else`
lines are read; with no `else`, the message (or the item) is `no-kind`. When
the key is absent (its line was in a block not read, or held a sentinel), the
`else` lines are read, or `no-kind`.

Encode: the case is the one decode would select from the bits the key's line
wrote: the value is read back through the transform, `via`, `typemap` and the
sentinels, so a `default`, a sentinel, the zero bits of an absent key or of a
line suppressed by `with`, and the value an `also` line chose all select as
decode would. A key whose line wrote nothing is absent: `else`, or `no-kind`.
A value that no `case` holds selects `else`, or, with no `else`, is
`no-kind`, on encode as on decode.

Lines inside a case are `field`, `also`, `const`, `pad`, `align`, `default`,
`presence`, `if`, `opt`, `chain`, `length`, `group` and nested `switch`
blocks; `kind`, `when`, `requires` and the header and table directives are
`bad-directive` there, and so is `fx` directly inside a case. Presence names
declared before the `switch` are visible inside every case. Rulings 1, 17 and
22 of 0.8 count only the selected case of each switch: a presence bit is set
on encode only by the selected case's lines, and on decode a bit that is 1
and that no `if` of the lines read names is `malformed-wire`. An `fx` bit
likewise counts the selected case only.

## Load errors

`bad-directive`: `switch` outside a sequential layout; a `switch` key not
mapped earlier in the scope (any line of common plus the kind, or of the same
group body, at any block depth, that precedes the `switch` in reading order,
cases of an earlier switch included; a message-level key is not visible in a
group body); a `case` or `else` outside a `switch`; a
`switch` with no `case`; two `else`; `else` before a `case`; a value listed
in two cases of one switch, or twice in one case; `switch` without `end`. A
`case` value that cannot be read as the key's type is `key-type-mismatch`;
an `int` value is an optional `-` then digits (`1.0` and `+1` are
`key-type-mismatch`).

## Rulings for 0.20

1. **Canonical text** of a `requires =` value and of a `case` value is
   computed at load, so `01` and `1` are one integer value and `2.50` and
   `2.5` one float value. `when` values compare as 0.5 states (text as
   written on text wires, numbers on `bits` and `protobuf`).
2. **Overlap.** `when` lists and ranges may overlap other kinds' lists and
   ranges on every wire; the first kind in pack order whose `when` lines hold
   is selected, as in 0.5. Lists and ranges are valid in every `when` on
   `bits` (fixed and sequential layouts, item kinds) and on an integer
   `protobuf` `when`. A value repeated in one `when` list loads.
3. **Encode of a `when` with a list or a range.** When a field line with a
   present key covers exactly the `when`'s bits and its value matches the
   `when`, that value is written; otherwise the first value is written over
   the field. This amends ruling 5 of 0.5 for lists and ranges only.
4. **`requires` with `=` and `Entity.kind`.** A kind recorded on the entity
   (same format) is used as in 0.5; `=` is checked only when the kind is
   chosen by `requires`. Every `requires` term of a kind must hold, across
   lines (`requires env=1` and `requires env=2` never both hold). The term
   is split at the first `=`; the rest is the value list, with no `=`
   stripped; `k=` with nothing after `=`, and `=v` with nothing before it,
   are `bad-directive`. Load errors of a
   term come in this order: `undeclared-key` or `module-not-used`, then
   `bad-directive` for a list key, then `key-type-mismatch`.
5. **Nested switches** are allowed; each switch is read where the cursor is.
6. **Empty cases.** An empty `case` or `else` reads and writes nothing;
   there is no fall-through.
7. **Defaults in a case** apply only to that case's lines and only when the
   case is selected; they are content for presence only then.
8. **Presence names declared in a case** belong to that case: each `case`
   and `else` body is a block for ruling 12 of 0.8, and the names are not
   visible after `end`.
9. **The key read again.** Selection uses the value the key holds when the
   cursor reaches `switch`; later lines of the key are read as usual and do
   not reselect.
10. **Groups in cases.** Two cases are different blocks for ruling 23 of
    0.8, so one list may be grouped in two cases.
11. **An item that is `no-kind`** fails the whole decode or convert.
12. **Error order.** Of encode errors, the one raised by the line earliest
    in reading order is reported.
13. **Capability.** Keys mapped only inside a `case` or `else` are listed by
    `model_keys` as every other mapped key.
14. **Extents.** A switch whose key line lies past the end of a `length`
    extent sees the key absent (ruling 7 of 0.8) and reads `else`; with no
    `else` it is `no-kind` (the switch is still evaluated past the end).
15. **Ruling 3 on text wires.** Ruling 3 applies to `bits` (the same offset
    and length) and `protobuf` (the same path); on `xml`, `json` and
    `geojson` a `when` with a list writes its first value (ruling 26 of
    0.5). "A present key" there means the entity holds it; a `default` does
    not count.
16. **Empty items.** An empty item in any list (`a,,b`, `a,`) is
    `bad-directive` on every wire; only a lone `""` is the empty text.
17. **Integer values** in `requires =` and `case` alike are an optional `-`
    then digits; `+1` is `key-type-mismatch`.
18. **Duplicates** in two cases of one switch are compared as canonical
    values (`1` and `01` are one value): `bad-directive`.
19. **Order of load errors** across lines: `module-not-used` and
    `undeclared-key` over every line; then `bad-directive` for a list key
    with `=` over every line; then the field and `default` type checks; then
    the `requires =` and `case` value checks in line order, each line's
    types before that line's duplicates.
20. **Lines between `switch` and its first `case`** are `bad-directive`. A
    key mapped in an earlier case of the same switch counts as mapped
    earlier for a nested switch.
21. **Presence names and cases** (ruling 8 with ruling 17 of 0.8): an `if`
    naming a presence counts only when the innermost case it sits in is the
    one read; `if` lines in other kinds count as before.
22. **Defaults in nested cases** apply inside the cases nested in their
    case; the innermost wins.
23. **A third token** on a `when` line (`when @t a, b`) is `bad-directive` on
    every wire.
24. **Float values** in `requires =` and `case` are `-?digits[.digits]` with
    an optional exponent, as JSON numbers are; a leading `+` is
    `key-type-mismatch`. On a float key an integer value compares as the
    float it equals.
25. **`present` in a list** of two or more values is `bad-directive` on
    every wire.
26. **Repeated values in one `requires =` list** load; only `case` values
    may not repeat.
27. **`case` structure.** A `case` after the switch's `else`, a `case` with
    no value, a `case` with more than one token (`case 1 2`), and an `else`
    with an argument are `bad-directive`.
28. **Commas in `const`.** A `const` value is one literal value; a comma in
    it is text, and `const` takes no ranges.
29. **Ruling 3 on `bits` and `protobuf`** counts only a key the entity
    holds, never a `default` (as ruling 15). On `protobuf` the raw varint
    the field wrote is compared, with no zig-zag; a field that does not
    write a varint is not compared.
30. **A presence declared inside a case** (ruling 21): an `if` counts when
    the innermost case that holds the `if` and not the presence is read;
    the search crosses group-body boundaries.
31. **A switch key that does not read back** on encode (its value fails its
    transform or table when decoded from the bits written) is
    `transform-encode`: the output would not decode.
32. **Leading `=`** in a text-wire `when` list is stripped from each item;
    the first item's `=` decides whether `json` writes a string.
33. **Settling encode.** An engine may compute presence, `opt` and `fx` bits
    by predicting the selected cases and encoding again until the
    prediction holds; the result must equal what decode selects from the
    output, and a prediction that never settles is `transform-encode`.
34. **Error order** (ruling 12): errors of a prediction pass that is
    discarded are not reported; only the final encode reports.
35. **A switch key whose line fails its transform** on decode fails the
    decode with `transform-decode` (ruling 9 of 0.1.1), whatever the
    switch would read.
36. **Presence bits across items.** A bit named only inside cases is
    satisfied by such a case read anywhere later in the same decode, a later
    group item included.
37. **The first prediction** (ruling 33) for each switch is the case decode
    would select from what the first line mapping its key would write; the
    prediction that settles from it is the result.
38. **The `text` wire** (Version 0.10) is not one of the text wires of this
    version: its `when` value stays one literal value, a comma included, and
    a value holding the record's delimiter is `bad-directive` as 0.10 states
    (load vector `wire-text-25`). The `tlv` wire (Version 0.13) takes no list
    or range either: `when 5:1 1,2` is `bad-directive`. Lists and ranges are
    for `bits` and `protobuf`, and lists for `xml`, `json` and `geojson`.
39. **Argument counts of `switch`, `case` and `else`** are line checks
    (ruling 5b of 0.11, step 3), as for `element` (ruling 25 of 0.18):
    `switch` and `case` take one argument and `else` none. So `else x`
    followed by a line `bogus` is `bad-directive`. Their other errors
    (ruling 27) are checks after the file.
40. **`switch` and the blocks of Version 0.19.** In a `uper` pack a `switch`
    may stand inside an `ext` or an `alt`, and an `ext` or a `choice` inside
    a `case` or `else`: they nest as the other blocks of 0.8 do. A `switch`
    on a key that a UPER locator maps reads the key back as 0.19 decodes it,
    at the length that line wrote. A key mapped in an earlier `alt` of an
    open `choice` counts as mapped earlier, as one in an earlier `case` does
    (ruling 20).
41. **Presence bits inside a `choice`** keep the rules of Version 0.19: this
    version's "only the selected case of each switch" is about `switch`
    alone. Stated, not yet pinned by a vector (40 and 41).

---

# Version 0.21: sequential extents and counts

Status: Written. Three list forms that sequential binary messages use and 0.8
cannot state: a list that fills the rest of the message or of a stated
length, with no count or indicator; a count that sits earlier in the message
than the list it counts, with other fields between; and an indicator bit of
the opposite sense to `more`, set on the last item.

```
group <list> rest              # items until the end of the enclosing extent
  …
end
count <name> <len> [plus <n>]  # a count field of `len` bits at the cursor, named
…
group <list> count @<name>     # that many items, here
  …
end
group <list> last              # each item is preceded by one bit: 1 = this is the last item
  …
end
```

All three are lines of a `layout sequential` pack (Version 0.8). On a wire
other than `bits`, `rest` and `last` after a list name are the group locator,
as before 0.21; a `count` line, `count @` and all three forms on a fixed
`bits` layout are `bad-directive`.

## A list to the end of its extent

The **enclosing extent** of a `rest` group is the innermost `length` block
around it, or else the message. A `rest` group must be the last line of its
extent: any line after it in the same extent is `bad-directive`.

Decode: items are read one after another while bits remain in the extent:
at least 8 bits when the extent is counted in bytes (the message, `length …
bytes`, `length … whole`), at least 1 bit when it is counted in bits. Fewer
bits that remain are padding and are skipped, whatever their value. An item
that reads no bits is `malformed-wire`. A list of no items is present and
empty.

Encode: the items are written back to back; an empty or absent list writes
nothing. The extent's length, where one is written, counts them.

## A count before other fields

`count <name> <len> [plus <n>]` reads `len` bits (1 to 64) at the cursor as
an unsigned integer and names it; the number of items is that value minus
`n` (default 0). The name is visible from its line to the end of the
enclosing block, as a presence name is (Version 0.8), and must be referenced
by exactly one `group <list> count @<name>` line in that range; a count
named twice in one block, a reference to a name not visible, or a count with
no reference is `bad-directive`.

Decode: when the group is reached, that many items are read. A value below
`n` is `malformed-wire`, checked at the count line. If the `count` line lay
at or past the end of a `length` extent, the group is absent.

Encode: the field holds the number of items plus `n`: the engine writes the
count after the group is laid out, at the count's own place. An absent list
writes `n`. A value outside `0 … 2^len − 1`, absent and empty lists
included, is `transform-encode`. A count is fixed-width, so filling it in
never changes the layout before the group.

## The last-item flag

With `last`, every item is preceded by one bit that is 1 for the last item
and 0 for the others. A list has at least one item on the wire; an absent or
empty list is `transform-encode` unless the group sits in an `if` or `opt`
block, which is then not written, as for `more` (Version 0.8).

## Load errors

`bad-directive`: the forms on a layout that does not allow them (above); a
`rest` group that is not the last line of its extent (ruling 11); a `count`
whose `len` is outside 1 to 64; a malformed `plus` (ruling 16); a count line
with any option other than `plus`, or `plus` twice; the name errors of
rulings 2, 9, 12 and 15; two modes on one group (`rest last`).

## Rulings for 0.21

1. **An item that reads no bits** in a `rest` group is `malformed-wire`.
2. **One reference per reading path.** In each reading path (common lines
   plus one kind, one case of each switch) exactly one group references a
   count name; a path with none or with two is `bad-directive`. So a header
   count in common lines may be referenced by the list in every kind.
3. **An empty `rest` at the end of a `length` extent** is present and empty:
   this amends ruling 7 of 0.8 for `rest`. A `rest` group whose block is not
   read stays absent.
4. **Sub-byte items.** Decode keeps "at least 8 bits" in a byte-counted
   extent; encode is `transform-encode` when it would write an item that
   starts with fewer than 8 bits left before the byte-padded end of the
   extent.
5. **Lines at the end of a `length` extent.** Inside a `length` extent
   rulings 7 and 21 of 0.8 apply to the lines of an item: a line starting at
   the extent's end reads as absent (an indicator as 0), and only a line
   that straddles the end is `malformed-wire`. At message level, reading past
   the input stays `malformed-wire`.
6. **A count read whose group is not reached** (in a block or case not read,
   or past an extent's end): the list is absent and the count's value is
   ignored, after the below-`n` check. Encode writes `n`.
7. **`plus` arithmetic.** The field is items + `n`; `n` is a signed 64-bit
   integer (a negative `n` is a count stored as items − 1, for example).
   `value − n` is computed without overflow.
8. **Other wires** keep `rest` and `last` as locators (see above).
9. **Count references stay in their group body.** A `count @` reference
   must be in the same group body as its count line (nested `if`, `opt`,
   `length` and `case` blocks of that body included); across a group-body
   boundary it is `bad-directive`.
10. **`rest` inside an item** is allowed only within a `length` block of the
    item's body, or as the last line of an outer `rest` item; in the second
    case encoding is `transform-encode` when an item before the last holds
    the inner `rest` (with item kinds, only the kinds that end in it count).
11. **"Last line"** is in reading order within one path: every wire line
    after the block holding the `rest`, up to the end of the extent, is
    `bad-directive`, whatever case is selected. `default` and `requires` are
    not wire lines; `align`, `pad` and `const` are. A `rest` at the end of
    one kind followed by another kind's lines loads.
12. **Visibility.** A count name is visible from its line to the end of the
    enclosing block only; a group after the end of an `if` holding the
    count cannot see it (`bad-directive`).
13. **`last` at the end of an extent.** An indicator after the first that
    starts at the extent end is `malformed-wire`; ruling 34 of 0.8 applies
    to the first (an absent list).
14. **`length … whole`.** When a whole length is read, the message extent
    ends at the stated length.
15. **Names.** Counts and presences share one namespace under ruling 12 of
    0.8: the same name twice in one block, `@x` naming a presence, or
    `if x.1` naming a count is `bad-directive`.
16. **The `plus` value** is an optional `-` then digits (leading zeros
    allowed) within signed 64 bits; `+2` or a value out of range is
    `bad-directive`.
17. **Padding** after the last item is ignored whatever its value; encode
    writes 0.
18. **Within `if` or `opt`.** "Sits in an `if` or `opt` block" means any
    enclosing `if` or `opt` at any depth within the same group body; ruling
    5 of 0.8 extends to `rest`, `count @` and `last`, and ruling 6 to
    `last`. A count line is never content.
19. **Capability.** Count names are not model keys; `model_keys` lists
    `<list>[]` as in Version 0.7.
20. **Bits left.** For `count @`, ruling 14 of 0.8 counts the bits left at
    the group, not at the count line.
21. **Ruling 4 on encode** is checked after the extent is laid out, against
    the end of the padded block or message; an item that writes no bits at
    that end starts with 0 bits left (`transform-encode`).
22. **A count and its group past an extent's end** are written on encode as
    every line is (ruling 7 of 0.8): the count holds `n` for an absent list,
    and the length counts it.
23. **"An absent list writes `n`"** also covers a group whose `if` or `opt`
    block is not written.
24. **Count names** are names as presence names are: no `.`, `!` or `@`. A
    name declared again in a nested block hides the outer one there (ruling
    12 of 0.8), and references in that block name the inner one.
25. **Counts in kinds.** Each kind is its own block for count names: two
    kinds may each declare a count of the same name.
26. **Wire lines** (ruling 11) are lines that read or write bits; an `if`,
    `switch` or `chain` whose body holds no wire line is not a wire line.
27. **`rest` and `last` in item kinds** follow the same rules inside the
    item kind's body.
28. **A `last` group with an empty list** inside an `if` or `opt` written for
    another reason is `transform-encode` (ruling 6 of 0.8).
29. **A `rest` item that writes no bits** is `transform-encode` (its output
    would not decode).
30. **The range check of a count** runs when the message is finished, after
    the group has filled it; a count whose group is never reached holds `n`
    and is `transform-encode` when `n` does not fit.
31. **At the end of a `length` extent** an `if` or a chain is still walked,
    so a `rest` inside an `if` whose bits hold is present and empty; an
    `opt` there reads as absent (ruling 21 of 0.8) and its block is not read.
32. **Wire lines** (ruling 26): `opt`, `length`, `count`, `presence`,
    `const` and a `group` line of any mode always are; an `if` or `switch` is one only when it holds one; a
    kind's `when` lines are wire lines, so a `rest` in common lines followed
    by a kind with `when` lines is `bad-directive`.
33. **Reading paths** (ruling 2) split only at kinds and `switch` cases; an
    `if` or `opt` does not split a path, so references in two `if` blocks
    are two references.
34. **The byte-padded end** (ruling 4) is measured from the first bit of the
    extent: 0 for the message, the first bit of the block for
    `length … bytes`.
35. **Ruling 10 is judged by what is written.** An item counts as holding
    the inner `rest` when it writes the inner `rest` group (the group is
    reached and its block written, empty or not); an inner `rest` inside an
    `if` or `opt` not written for that item does not count.
36. **Common lines and kinds** are one block for count names, as for
    presence names: a count in common lines and a count or presence of the
    same name in a kind is `bad-directive`; two kinds may each declare it
    (ruling 25).
37. **A group locator that is not valid for its wire** is `bad-directive` on
    every non-sequential wire (on `protobuf`, `rest` and `last` are such a
    locator).
38. **Chains.** A `rest` in a chain part followed by an `fx` line is
    `bad-directive`: an `fx` line is a wire line.
39. **A `rest` nested in a block** of an outer `rest` item (`if`, `opt`,
    `chain`, `case`) is allowed when no wire line follows it in reading
    order within the item.
40. **Reading paths and Version 0.19.** The `alt`s of a `choice` do not split
    a reading path (ruling 33 splits only at kinds and `switch` cases): a
    `count` before a `choice` named by `group … count @<name>` in two `alt`s
    is two references, `bad-directive`.
41. **Wire lines of 0.19 blocks** (rulings 26 and 32). An `ext` is a wire
    line (it reads its extension bit). A `choice` is one when it has `ext`,
    more than one root alternative, or an `alt` holding a wire line.
42. **`rest` inside `ext` and `alt`.** An `ext` body is the extent of the
    block around it, as an `if` body is; each `alt` is checked as a `switch`
    case is (ruling 39).
43. **`rest` under six-bit armor** (Version 0.14). The message stays counted
    in bytes for `rest` (8 bits at least to start an item, and the ruling 4
    check before the byte-padded end), not in the armored bit length.
    Rulings 40 to 43 are stated, not yet pinned by a vector.
44. **Ruling 37 and 5a of 0.11.** On `protobuf` the group locators `rest` and
    `last` are `bad-directive`, a check after the file (ruling 37, load vectors
    906 and 1004: `group probe.nums rest` followed by a line `bogus` is
    `unknown-directive`); any other step
    that is not digits only stays `bad-locator` (5a of 0.11), and the group
    locators of `xml` and `json` keep 5a (load vector 456).

---

# Version 0.22: long and terminated fields

Status: Written. Three things binary messages carry that earlier versions
cannot state: a field longer than 64 bits that is not text (a key, a hash, a
block of reserved bits kept as it is), a character field whose length is not
fixed but ends at a terminator code, and a bit numbering that counts
positions from the high bit of each byte while assembling a field's value
from its low bit up.

## Fields longer than 64 bits

| Name | Wire | Yields | Decode | Encode |
|---|---|---|---|---|
| `hex` | `bits` | string | `len / 4` lowercase hexadecimal digits; digit `k` is the 4-bit field at bit `4k` of the field, read as `uint` reads a 4-bit field there in the pack's bit order | each digit (either case) written as `uint` writes a 4-bit field at its place; text of another length or with a character that is not a hex digit is `transform-encode` |

`len` is a multiple of 4, from 4 to 2040; another `len` is `bad-directive`.
Valid in fixed and sequential layouts; takes no `swap`. Unlike `octal`, the
digits are not those of the field's `uint` value, and under `lsb` and
`msb-lsb` they are not the wire's hex either: `0102` in an `lsb` pack is
`"1020"`. This is accepted: `hex` keeps bits through a round trip; it does not
give a value that compares across bit orders. `absent` on a `hex` field of
more than 64 bits is `bad-directive` (Version 0.9, Load errors); on a shorter
one the sentinel is the field's `uint` raw value, not its hex text.

## Character fields that end at a code

```
field  <key> until:<code> chars:<set>     # sequential layouts only
field  <key> <locator> chars:<set> stop <code>   # a fixed-size field whose text ends early
```

Version 0.22 also adds the set `ascii8` to `chars` (Version 0.15): width 8,
code 0 is NUL, codes 32–126 are themselves, every other code is
`transform-decode`, padding NUL. So an 8-bit text that ends at NUL is
`until:0 chars:ascii8`.

In a `layout sequential` pack the locator `until:<code>` in place of a bit
length reads characters of the set (Version 0.15, `chars`) one after another
until it reads the character whose code is `<code>`, an unsigned decimal
integer that fits the set's width. The terminator is consumed and is not part
of the text. Decode yields the text read before it; trailing padding is not
removed (the field has no fixed length to pad). Reading past the end of the
enclosing extent before the terminator is `malformed-wire`. At most 2040 bits
of characters are read before the terminator; more is `malformed-wire`.

Encode writes the text's characters, then the terminator. A character the set
cannot hold, a character whose code equals `<code>`, or text longer than
`2040 / w` characters is `transform-encode`. An absent key writes the
terminator alone.

`until:` is valid only with `chars:<set>`, only in sequential layouts, and
takes no `absent`, `swap` or `trim`; anything else is `bad-directive`. A
`<code>` that is not plain digits or is `2^w` or more is `bad-directive`.

The field option `stop <code>` on a fixed-size `chars` field (either layout)
makes the text end at the first character whose code is `<code>`: decode
yields the characters before it and ignores the rest of the field; encode
writes the text, the terminator, then padding to the field's size. A text
that does not leave room for the terminator, or holds the terminator's
character, is `transform-encode`; without `stop` the 0.15 rules apply.

## A bit order with high-bit-first positions and low-bit-first values

```
bit_order  msb-lsb
```

Bit `i` of a word is bit `7 − (i mod 8)` of byte `i div 8`, as with `msb`;
a field's value is its `len` bits from `pos` with the first bit least
significant, as with `lsb`. So `0:0:4` is the high four bits of the first byte
read with the highest of them as the value's bit 0. `when`, `const`, gate,
count and presence values read and write in this order. Valid on `bits`, in
fixed and sequential layouts.

## Rulings for 0.22

1. **`hex` and residue.** A `hex` field maps its bits; it keeps reserved or
   unknown bits through a round trip.
2. **Every integer** the pack reads or writes uses the pack's bit order:
   fields, `when`, `const`, gate, `length`, group counts (0.7 and 0.8),
   0.21 count lines, and the raw values sentinels compare. Presence bits
   keep their reading-order numbering.
3. **`ascii`, `chars`, `f32`, `f64` and the scaled floats under `msb-lsb`.**
   Each byte of `ascii`, each character of `chars`, and the bit pattern of
   a float is read as `uint` reads a field of that width at its place, so
   under `msb-lsb` an `ascii` "A" is `82` on the wire and an `f32` 1.0 is
   `000001fc`. Under `msb-lsb` the sign of `twos` and `smag` is the last
   bit read.
4. **`until:` at an extent's end.** A field starting at or after the end of
   a `length` extent is absent (ruling 7 of 0.8); one that starts before it
   and finds no terminator is `malformed-wire`; at message level, starting
   at the end of the input is `malformed-wire`.
5. **Errors under `until:`.** The terminator is found first, from the codes
   alone; none is `malformed-wire`, and that wins. Then the characters are
   decoded; a bad one is `transform-decode`, and the cursor resumes after
   the terminator so later fields still decode.
6. **NUL under `until:`.** The `ascii7` NUL rules of 0.15 (rulings on
   trailing NUL and ruling 17) do not apply unless NUL is the terminator.
7. **Nothing is removed under `until:`**: neither padding nor trailing
   spaces.
8. **The 2040 limit** counts only the characters before the terminator,
   `floor(2040 / w)` of them.
9. **A terminator code** may be any code below `2^w`, whether or not the set
   gives it a character; it is compared before the set's validity check.
10. **`default`** applies to an absent key first; the terminator alone is
    written only when no default applies.
11. **An immediate terminator** decodes as `""`, present; an absent key does
    not survive a round trip (it comes back as `""`).
12. **Extents** for `until:` are those of Version 0.21: the innermost
    `length` block, else the message; a group item is not an extent.
13. **`swap`** reverses 8-bit chunks of the field taken from its first bit,
    whatever its alignment; for an aligned field this is its bytes.
14. **`hex` text** compares exactly (`case`, `requires =`, `via`): packs
    write lowercase. On `json` and `geojson` it is a string of `len / 4`
    digits, leading zeros kept.
15. **`until:` in groups and kinds** follows these rules inside the scope.
16. **`stop` and `until:`** cannot be combined on one line
    (`bad-directive`); `stop` with a code of `2^w` or more is
    `bad-directive`.
17. **Load vector 559** (`transforms-unknown-character-set`) used `chars:ascii8` as its unknown set; with
    `ascii8` defined it now uses `chars:ascii9`.
18. **`stop` text is exact.** Decode yields exactly the characters before the
    terminator; the 0.15 removal of padding and spaces does not apply.
19. **A `stop` field with no terminator** decodes as the same field without
    `stop` would (Version 0.15 rules).
20. **NUL under `until:N`** with `N` not 0 is an ordinary character on decode
    and on encode (ruling 6).
21. **NUL in a `stop` field** follows ruling 6 as well: with a terminator
    other than 0, NUL is an ordinary character.
22. **`until:` with `via`** loads: the options refused with `until:` are
    `absent`, `swap` and `trim` only.
23. **Terminator codes** are plain decimal digits (`until:00` is 0); a
    `stop` code that is not plain digits (`stop x`) is `bad-directive`, as
    for `until:`.
24. **`msb-lsb` is not `msb`.** `armor sixbit` (Version 0.14) and `encoding
    uper` (Version 0.19) need `bit_order msb`; with `msb-lsb` they are
    `bad-directive`.
25. **`until:` and `with`** (Version 0.18). A suppressed `until:` line writes
    the terminator alone; it has no fixed width to fill with zero bits, and,
    as ruling 1 of 0.18 states, it has no default (a `default` of its key is
    not written; vector `conformance-long-json` 59).
26. **`until:` in a `uper` pack** (Version 0.19) is allowed: it is not a UPER
    locator, and it is read at the cursor with no alignment.
27. **A parameter on a transform that takes none** (`hex:4`, `ascii:8`) is
    `bad-directive`: the name before the first `:` is a transform of this
    specification, so it is not `unknown-transform` (0.11, Load errors), and
    the parameter fails 4d of 0.11.
28. **When `stop` is checked** (0.11, 5b). Its syntax is a line check (step
    9): `stop` without a code, or given twice. Everything else is checked after
    the file is read, as `until:` is: `stop` on a transform other than
    `chars:<set>`, on a wire other than `bits`, with `until:`, and a code that
    is not plain digits or not below `2^w` (step 10 names the values of
    `absent` only). So `field … uint stop 0` followed by a line `bogus` is
    `unknown-directive`, and `field … chars:ascii8 stop` followed by `bogus`
    is `bad-directive`.

---

# Version 0.23: the command-line contract

Status: Written. Every engine ships a command-line tool with the same
arguments, the same output and the same exit status, so a script, a pipeline
or a test written against one engine's tool runs against any other. The tool
also prints the capability report (ruling 6 of 0.11) of one pair and of every
pair of the loaded formats, in one text form that all seven engines produce
byte for byte. Tool vectors (`spec/vector-format.md`, Tool vectors) pin the
contract, and CI runs them against the tool of each engine.

The program's name and how it is built belong to each engine; its README
names them. This section calls it `<tool>`.

## Invocation

```
<tool> convert --from <format> --to <format> [--set <key>=<value>]... <options>
<tool> list-formats <options>
<tool> capability --from <format> --to <format> <options>
<tool> matrix <options>
<tool> help
```

`<options>` are, in any order:

| Option | Means | Default |
|---|---|---|
| `--packs <dir>` | the directory whose subdirectories are packs | the engine's own; the contract does not fix it |
| `--models <dir>` | the directory of model modules | the `--packs` text as given, followed by `/../model`, resolved by the operating system |
| `--packs-only <name>[,<name>...]` | load only these subdirectories of `--packs`, in the order given | every subdirectory (Loading) |
| `--max-items <n>` | the limit on list items one decode holds (ruling 7 of 0.11) | 100000 |
| `--max-distribution <public \| controlled>` | the engine's distribution limit (Version 0.4, Distribution limit) | `controlled` |

**Arguments.** The first argument is the subcommand. After it the arguments
come in pairs: an option name, then its value. An option name is exactly one
of the names the subcommand takes: `--from`, `--to` and `--set` for
`convert`; `--from` and `--to` for `capability`; and `<options>` for the
four subcommands. The argument after an option name is its value, whatever
it begins with, so in `capability --from --to --to x` the source format is
`--to`. `--set` may be given more than once, its occurrences applied in the
order given; every other option is given at most once.

**Usage errors.** Each of these exits 2:

1. no argument;
2. a first argument that is not `convert`, `list-formats`, `capability`,
   `matrix`, `help`, `-h` or `--help`;
3. at a place where an option name stands, an argument that is not one of
   the names the subcommand takes: an unknown name, a name with `=value`
   appended, a prefix of a name, a single-dash name, `--` alone, or a word
   that does not begin with `-`;
4. an option name that is the last argument, with no value after it;
5. an option other than `--set` given twice;
6. `convert` or `capability` without `--from` or without `--to`;
7. a `--set` value with no `=`, or with nothing before its first `=`;
8. a `--max-items` value that is not one or more digits `0` to `9` alone,
   or whose value is above 2^63 − 1 (`+1`, `-1`, `1.0` and the empty text
   are usage errors; leading zeros are not, so `0000000000000000000000001`
   is 1);
9. a `--max-distribution` value other than `public` or `controlled`;
10. an empty `--packs-only` value, or an empty name in it (`a,,b`, `a,`).

The tool checks every argument before it loads anything, so a usage error is
reported whatever else is wrong. An empty `--from`, `--to` or `--set` key,
or one that holds whitespace, is not a usage error: it reaches the call and
fails there (`unknown-format`, `undeclared-key`). Text on the command line is
UTF-8.

**Help.** `help`, `-h` or `--help` as the first argument prints the usage on
standard output and exits 0, whatever arguments follow; the contract does not
fix its text. Anywhere else these words are arguments like any other, so
`convert --help` is a usage error (3).

## Loading

After the arguments are checked, the tool loads, stopping at the first
failure:

1. **Modules.** From `--models`: `core.def` first, then every other file
   whose name ends in `.def`, in byte order of file name, compared case
   sensitively, not recursing into subdirectories (Version 0.4, Loading, and
   ruling 9 of 0.6; a module is still loaded after the modules it uses). A
   file is a regular file or a symbolic link to one; a directory whose name
   ends in `.def` is not a module. A `--models` that does not exist, or is
   not a directory, loads no modules (ruling 4 of 0.4). The modules are
   loaded before `--packs` is read at all, so a failing module is the
   error even when `--packs` cannot be read.
2. **Packs.** With `--packs-only`, the named subdirectories of `--packs`, in
   the order given; a name given twice is loaded twice, so the second is
   `duplicate-format`. A name that is not one path component (it holds `/`
   or `\`, or is `.` or `..`) or that is not a subdirectory of `--packs`
   holding a file `pack.def` is `unknown-format`, raised when the tool
   reaches that name. Without `--packs-only`, every entry of `--packs` that
   is a directory, a symbolic link to one included, and holds `pack.def`,
   other than names that begin with `.`, in byte order of name.

Without `--packs-only`, a `--packs` that does not exist, is not a directory
or cannot be read exits 1; the contract does not give this case a kind, so
its first line of standard error is the engine's. With `--packs-only`,
`--packs` is not listed: each name is looked up in it, so when `--packs` does
not exist the first name is `unknown-format`. The format names are the `format` lines of the loaded
packs; a directory's name is never compared with them, so a pack in
directory `d` whose `format` line says `f` is the format `f`, and `--from d`
is `unknown-format`. `help` loads nothing.

## Output and exit status

| Exit status | When | Standard output | Standard error |
|---|---|---|---|
| 0 | the subcommand succeeded | its result (below) | empty |
| 1 | a load failure or a call failure | empty | with a kind: the failure's message (ruling 5 of 0.11) as its first line, which begins with the kind and a colon |
| 2 | a usage error | empty | any text, at least one byte |

Every failure that is not a usage error exits 1:

- a load failure of a module or a pack, with its kind;
- a `--packs-only` name the tool cannot load as a pack (Loading, 2);
- a `--from` or `--to` that is not loaded: `unknown-format`, `--from` checked
  first, before standard input is read;
- for `convert`, every failure of `convert(from, to, bytes, context)`;
- a `--packs` that cannot be read (Loading).

## The subcommands

**`convert`** reads standard input to its end and passes it to
`convert(from, to, input, context)` (Version 0.6, Order inside `convert`)
unchanged: for a format whose input is hex text (`bits`, `protobuf`, `tlv`)
standard input is that hex text, and the whitespace hex text allows (ruling
36 of 0.8) may surround it. Input that is not valid UTF-8 is
`malformed-wire` on every wire (on a hex wire such bytes are not hex digits,
ruling 36 of 0.8). A byte-order mark is not removed. The context is the `--set` options: the text before the first `=` is
the key, the rest (possibly empty, possibly holding `=`) the value in string
form, read as the key's declared type as a vector's `context` value is. A key
given twice takes its last value and keeps the place of its first. The context
keys are checked (ruling 10 of 0.6) in that order, so the first failing key
names the kind. With no `--set`, no context is given. The
result is written to standard output exactly, with nothing added: a hex
wire's result is its lower-case hex text, and no line feed follows any
result.

**`list-formats`** writes one line per loaded pack, in byte order of format
name: the format, a tab, the `version` value, a tab, the `wire` value. A value
written in double quotes in the pack is written without them.

**`capability`** writes the report of `capability(from, to)` as one line of
the matrix form below, without the header line.

**`matrix`** writes the header line

```
from<TAB>to<TAB>grade<TAB>carried<TAB>dropped
```

then one line per ordered pair of loaded formats, a format paired with itself
included: `from` in byte order of format name, and for each `from` every `to`
in that order. A line is the `from` format, a tab, the `to` format, a tab,
the grade (`full`, `partial` or `none`), a tab, the `carried` entries, a tab,
the `dropped` entries. The entries of a list are joined by a single space, in
the order of ruling 6d; an empty list is the empty text, so a line may end in
a tab. With n formats loaded the output has n² + 1 lines.

Every line that `list-formats`, `capability` and `matrix` write, the last
included, ends in a line feed, the byte 0x0A, with no carriage return.

## What the contract leaves to an engine

An engine's tool may have more subcommands than this section names, and an
engine's own options (for example a peak-memory report), whose names begin
with `--x-`; any other name this section does not give is a usage error. The
default of `--packs`, the text of `help` and of a usage error, the text after
the kind on standard error, and the message of an unreadable `--packs` are
the engine's.

## Vectors

`packs/conformance/tool-vectors/*.json` (`spec/vector-format.md`, Tool
vectors), run by `tools/tool-vectors.py` against the command that starts an
engine's tool.

---

# Version 0.24: builds with fewer wires

Status: Written. Version 0.24 adds no directive to the pack language. It lets
an engine be built with the codecs of only some wires, so that a program that
converts only `xml` formats does not carry the `bits` or `protobuf` codec.

## Rulings for 0.24

### Ruling 1: the wires of a build

- **1a.** An engine is built with a set of wires, a subset of `xml`,
  `geojson`, `json`, `bits`, `protobuf`, `text` and `tlv`. A build that names
  no set has all seven. The way a build names its set belongs to the engine's language
  and is stated in the engine's README (a Cargo feature, a build tag, a
  compile definition, a build option).
- **1b.** A build with a set of wires behaves, for every pack on a wire in
  the set, exactly as a build with all seven: the same bytes, the same model
  values and the same named errors.
- **1c.** A pack whose `wire` value is a wire of this specification that the
  build does not have is `unknown-wire`, raised where 5b of 0.11 raises
  `unknown-wire` (line check 6). Its message names the wire and says that
  this build does not have it, so the message tells it apart from a `wire`
  value that is not a wire at all. A pack whose `wire` value is no wire of
  this specification is `unknown-wire` as before.
- **1d.** A build never has a wire without the codecs it needs to read and
  write it: `geojson` needs nothing of `json`; the sequential layout, six-bit
  armor (0.14) and `encoding uper` (0.19) are part of `bits`.
- **1e.** The capability report and `model_keys` of a format that loaded are
  unchanged. A format that did not load is `unknown-format` (ruling 5 of
  0.11).

### What pins it

A conversion vector runs on a build with all seven wires. Ruling 1 is pinned by
each engine's reduced-build check, which the `conformance` workflow runs: the
engine is built with the set `xml`, `json` and `geojson`; every vector whose
`from` and `to` packs, and the packs those vectors load, are on those three
wires passes; and loading a pack on `bits`, on `protobuf` and on `text` is
`unknown-wire` with a message that names the wire (a pack on `tlv` too). The check also records the
size of the reduced build beside the full one.

`tools/goat-pkg plan` names, for each language, the switch that builds the
wires a package uses.

---

# Version 0.25: parse once, and a benchmark

Status: Written. Version 0.25 adds no directive to the pack language and
changes no result. It allows an engine to keep what it has parsed, and it
states a benchmark that every engine runs the same way.

## Rulings for 0.25

### Ruling 1: what an engine may keep

- **1a.** An engine may keep, for the life of an engine instance, the parsed
  form of every model module and pack it loaded, and any layout it computes
  from them (the index of a protobuf message's field numbers, the plan of a
  `bits` kind, the order of a group's items).
- **1b.** Keeping changes nothing that can be observed. For every input, a
  conversion on an instance that has converted other messages before gives
  the same bytes, model values and named errors as on a new instance that
  loaded the same packs. A failed conversion leaves nothing behind that a
  later conversion could see.
- **1c.** An instance that is used from several threads at once (where the
  language has threads) gives each conversion the result of 1b.
- **1d.** Loading reads each pack and module file once. A second load of the
  same directory into the same instance is `duplicate-format` or
  `duplicate-module`, as before.

### Ruling 2: the benchmark

- **2a.** The benchmark set is `bench/set.json`: an `iterations` count and a
  list of conversion vectors, each with an `expect`. It covers every wire.
- **2b.** An engine runs it like this. It loads only the packs the set's
  vectors name, and the model modules those packs use, into one instance, and
  records the time that took. Then, for each vector in order, it converts the
  vector's input once and checks the output against `expect`. A vector whose
  output differs fails the run. Then it converts the input `iterations`
  times, and records the time.
- **2c.** The run prints one line per vector, then one line for the load, each
  a JSON object on its own line:
  `{"vector": "<path as in the set>", "iterations": <n>, "ns_per_op": <integer>}`
  and `{"load": <number of packs>, "ns": <integer>}`. `ns_per_op` is the total
  time divided by `iterations`, rounded down. Nothing else is printed on
  standard output.
- **2d.** The numbers are measurements of one machine at one time. No vector
  and no CI check fails on a number. The `conformance` workflow runs each
  engine's benchmark and keeps its output as an artifact, so a change can be
  compared with the one before it.
- **2e.** The command that runs the benchmark belongs to the engine's
  language and is stated in its README.

---

# Version 0.26: whole-second time

Status: Written. Version 0.26 adds one transform, `iso8601_s`, for formats
whose schema allows a time to the whole second only (C2SIM's `IsoDateTime`,
`YYYY-MM-DDTHH:MM:SSZ`). The vectors are written by
`tools/gen/conformance-seconds-vectors.py`, which derives every expected value
from this section and imports no engine.

```
field  <key>  <locator>  iso8601_s
```

| Name | Decode | Encode |
|---|---|---|
| `iso8601_s` | as `iso8601_ms`: ISO 8601 UTC to epoch ms | epoch ms to `YYYY-MM-DDTHH:MM:SSZ` |

## Rulings for 0.26

1. **Valid where `iso8601_ms` is valid**: the `xml`, `geojson`, `json` and
   `text` wires, with the same JSON value (a string) on `json`. On another
   wire it is `bad-directive`. It takes no parameter (`iso8601_s:3` is
   `bad-directive`). It yields `int`, like `iso8601_ms`, so on a key of
   another type it is `key-type-mismatch`.
2. **Decode** is the decode of `iso8601_ms` exactly, ruling 3 of 0.11
   included: the grammar, the ranges, the fraction (its first three digits
   are the milliseconds, the rest dropped) and every refusal as
   `transform-decode`. A fraction on the wire is therefore read, not refused,
   and the model value keeps its milliseconds.
3. **Encode** writes the 24 characters `iso8601_ms` writes for the value, less
   the four characters `.fff`: `YYYY-MM-DDTHH:MM:SSZ`, 20 characters, four year
   digits, upper-case `T` and `Z`. The second written is the one that holds the
   instant (the milliseconds are dropped, never rounded, as ruling 3c of 0.11
   drops fraction digits): 999 writes `1970-01-01T00:00:00Z` and -1 writes
   `1969-12-31T23:59:59Z`. The range is that of ruling 3f of 0.11: a value
   below -62135596800000 or above 253402300799999 is `transform-encode`.
4. **A same-format round trip** of a time with a fraction is therefore not
   byte-exact: `2024-02-29T12:34:56.789Z` is written `2024-02-29T12:34:56Z`.
   A pack chooses `iso8601_s` only where its format allows whole seconds and
   nothing finer. `iso8601_short` (0.18) writes the fraction when it is not
   zero; `iso8601_s` never writes one.

# Version 0.27: a CRC-32 checksum on the `tlv` wire

Status: Written. A `tlv` set may end with a four-byte CRC-32 item in place of
the two-byte sum of Version 0.13. MISB ST 0806 (the Remote Video Terminal
Local Set) uses it, with the CRC of ISO/IEC 13818-1.

```
checksum  crc32 <tag>                  # optional: the last item of the set is a CRC-32
```

`checksum crc32 <tag>` follows every rule 0.13 states for `checksum sum16
<tag>`: one `checksum` line at most, before the first `kind`, valid only on
`tlv`, its `<tag>` a tag as 0.13 states it and not named by any other line;
each of these is checked after the file is read and is `bad-directive`.
`checksum sum16 <t>` and `checksum crc32 <t>` in one pack are a second
`checksum` line.

## The CRC

The CRC of a sequence of bytes is the CRC-32 of ISO/IEC 13818-1 (Annex A):
polynomial 0x04C11DB7, a 32-bit register starting at 0xFFFFFFFF, each byte
taken most significant bit first, no reflection of input or output, and no
final XOR. For each byte `b`: the register is XORed with `b` shifted left 24
bits; then eight times, if its top bit is set it is shifted left one bit and
XORed with the polynomial, else shifted left one bit; the result is the
register after the last byte. The CRC of the nine ASCII bytes `123456789` is
0x0376E6E7, and of no bytes 0xFFFFFFFF.

## Reading and writing

Step 4 of "Reading a message" of 0.13 holds with `crc32` for `sum16`, four
bytes for two, and the CRC for the sum: the last item of the top set has tag
`t` and a value of four bytes, else `malformed-wire`; its value, big-endian,
is the CRC of every byte of the input from the first (the first byte of the
key when there is one) to the last byte of the checksum item's length; a
different value is `malformed-wire`; an item of tag `t` in the top set
before the last is `malformed-wire`, and a nested set may hold tag `t` as any
other tag. Step 3 of "Writing a message" holds the
same way: an item of tag `t` with a four-byte value is the last item of the
top set, counts in the set's length, and its value is computed last over the
same bytes.

## Rulings for 0.27

1. **The bytes the CRC covers** are those `sum16` covers in 0.13: from the
   first byte of the input through the checksum item's tag and length, not
   its value. MISB ST 0806.4 says the CRC is "performed on entire LS packet,
   including 16-byte US key" and that the item is the last of the set; the
   value cannot cover itself, and this reading matches the range ST 0601 and
   0.13 use.
2. **The argument count of `checksum`** (ruling 12 of 0.13): as a line is
   read, a `checksum` line with one argument, or with two whose first is
   `sum16` or `crc32`, passes; any other count is `bad-directive` there.
3. **`checksum crc32` on another wire** is `bad-directive` after the file is
   read, as `checksum sum16` is (ruling 13 of 0.13: it may stand before the
   `wire` line).

# Version 0.28: the `cbor` wire

Status: Draft. A `cbor` format is one CBOR data item (RFC 8949): a map or an
array, whose items may be maps, arrays and scalars at any depth. It is the
binary counterpart of `json`, with integer map keys, byte strings and tags,
as COSE (RFC 9052) and Bundle Protocol 7 (RFC 9171) use them. Input and
output are hex text, as for `bits`, `protobuf` and `tlv`. `cbor` is a wire
value of ruling 5 of 0.11.

```
wire   cbor
tag    <n>                                  # optional: the message is tag n enclosing the item
field  <model-key> <path> <transform> [via <table>]
group  <list> <path>                        # 0.7 groups: each element of the array at <path>
```

`tag <n>` takes exactly one argument, checked as the line is read (step 3 of
5b of 0.11); it may stand before the `wire` line. `<n>` is a decimal integer
from 0 to 2^64-1 with no leading zero. On `cbor` it has the meaning of this
section and on `tlv` that of 0.13; elsewhere, more than once, after the first
`kind`, or with another value it is `bad-directive`, checked after the file
is read. On `cbor` the field options are `via` and the `with` of 0.18; `absent`, `swap`, `trim`
and `optional` are `bad-directive`, checked after the file.

## Paths

A path is one or more steps separated by `.`. A step is:

- **an integer key**: a decimal integer with an optional `-`, no leading
  zero, no `+`, not `-0`, from -2^63 to 2^64-1 (`4`, `-1`): the member of a
  map whose key is that integer (major type 0 or 1);
- **an array position** `[i]`: `i` a decimal integer from 0 to 65535 with no
  leading zero: the element of an array at that position, counting from 0. A
  position is a step of its own: `a.[0]`, never `a[0]`;
- **a text key**: one or more ASCII letters, digits, `_` and `-`, not
  beginning with a digit or `-`: the member of a map whose key is that text
  string (major type 3).

Text that is not a path of these steps (an empty step, `a[0]`, `[01]`, `-0`,
`+1`, a number out of range, a character outside the set) is `bad-locator`,
a line check (step 8 of 5b of 0.11).

Inside a group body a path is relative to the element, and `.` is the
element itself when it is a scalar (as on `json`, Version 0.7). `group
<list> .` names the top item, which is then an array.

**Types.** The first step of a path that is not inside a group body decides
the type of the top item: an array position or `group <list> .`, an array;
otherwise a map. Two such paths in the pack that decide differently are
`bad-directive`. Within one scope (the common lines with one kind's, or one
group body) a step whose item is used both as a map and as an array is
`bad-directive`. A pack with no such path has a map as its top item. A
`field`, `when` or `const` at or under a `group`'s path in the same scope is
`bad-directive`. These checks run after the file is read.

A map key of another type than an integer or text (a byte string, a float, a
bool, an array, a map, a tag), and a text key that the step grammar cannot
write (`"4"`, `"a.b"`), are not addressable; such a member is residue.

## Transforms for `cbor`

| Name | CBOR item | Decode | Encode |
|---|---|---|---|
| `uint` | major type 0 | to int; above 2^63-1 is `transform-decode` | major type 0; a negative value is `transform-encode` |
| `int` | major type 0 or 1 | to int; outside -2^63 to 2^63-1 is `transform-decode` | major type 0 when the value is 0 or more, else 1 |
| `float` | a half, single or double float, or major type 0 or 1 | to float; an integer item to the nearest double, ties to even (2b of 0.11); a NaN or an infinity is `transform-decode` | the shortest of half, single and double that holds the value exactly, subnormal halves included (RFC 8949 4.2.2); -0.0 as `f98000` |
| `text` | major type 3 | to string | major type 3 |
| `bytes` | major type 2 | to string: the bytes as lowercase hex | major type 2; the string must be an even number of lowercase hex digits, else `transform-encode` |
| `bool` | simple value 20 or 21 | to int 0 or 1 | 21 for 1, 20 for 0; another value is `transform-encode` |
| `epoch_s` | major type 0 or 1 | seconds since 1970 to `time_ms` (times 1000, exactly); outside -2^63 to 2^63-1 is `transform-decode` | major type 0 or 1: `time_ms` divided by 1000 exactly and rounded half away from zero |

On `cbor` the transforms of this table are valid and every other is
`bad-directive`, checked after the file. `bool` yields `int`, as on `json`.
An item of another type than its transform takes is `transform-decode`. The
simple values 22 (`null`) and 23 (`undefined`) are absent.

**Tags.** Every tag on an item that a line reads or walks into, at any depth,
the top item included, is passed over on decode and not written on encode.
With `tag <n>`, the outermost tag of the input must be `n` (`malformed-wire`
otherwise), further tags inside it are passed over, and the output is the
head of tag `n` and then the item. A tag head, like any head, is read in any
length.

## Reading a message

1. The input is the hex of exactly one well-formed data item (RFC 8949
   Appendix C). Bytes after it, an item that is not well formed, and a
   declared length greater than the bytes left (found before any memory is
   taken for it) are `malformed-wire`.
2. Definite and indefinite lengths are both read; heads longer than they
   need are read.
3. Text strings are valid UTF-8, each chunk of an indefinite text string on
   its own; invalid UTF-8 anywhere in the input is `malformed-wire`.
4. A map with two equal keys is `malformed-wire`. Keys of different major
   types are never equal (`1`, `1.0` and `true` are three keys). Two integer
   keys are equal when their values are, two text keys when their bytes are,
   and other keys when their core deterministic encodings (Writing, step 1)
   are equal.
5. Arrays, maps and tags count one level each, the top item level 1;
   scalars and string chunks count none. A depth above 64 is
   `malformed-wire`.
6. The top item, its tags passed over, must be of the type the paths decide,
   else `malformed-wire`.
7. Kinds are selected next. A `when` whose path passes through an item of
   the wrong type for its next step does not hold.
8. For each line of the selected scope: an item on the path that exists but
   is not a map or array of the type its next step needs is
   `malformed-wire`. A group path at `null` or `undefined` is an absent list;
   at another item that is not an array, `malformed-wire`. An element of the
   wrong type for the body is an item with no keys (ruling 12 of 0.7).
9. Group items count against the item limit of ruling 7 of 0.11.

## Writing a message

1. The output is one data item with the core deterministic encoding of
   RFC 8949 4.2.1: every head in its shortest form, every float at the
   shortest width that holds it exactly, every length definite, and every
   map's members sorted by the bytewise order of their encoded keys. The
   order of the lines sets no member order; which value is written at a path
   several lines name is as ruling 16 of 0.5 states, a `when` or `const`
   value over a `field`.
2. A map or an array is written when a line writes into it or residue lies
   in it; one with nothing in it is not written, except the top item, which
   is written empty, and except as step 4 and ruling 23 state.
3. An array addressed by positions is written up to its highest present
   position; a position below it with nothing to write is `null` (`f6`).
4. A present list writes its array, `80` when the list is empty, one element
   per item in list order. An item with nothing written is an empty map
   (`a0`), or an empty array (`80`) when the body's paths begin with
   positions; a scalar item (`.`) with no value is `f6`.
5. With `tag <n>`, the output is the head of tag `n` and then the item.

## Residue

Every member or element of the input that no line of the selected scope maps
and that no such line walks into is residue, keyed by its path, its value
the hex of its encoded item as it stood in the input, tags included. An item
a line walks into is not residue; its unmapped members and elements are. A
`when … present` walks into its path and does not map its last item (ruling
27 of 0.5). A member whose key is not addressable is keyed by its map's path,
`#` and the hex of the key's encoded item (`#6134` for the key `"4"` in the
top map, `1.#6134` in the map at `1`). Group items carry no residue: unmapped
content inside an item is dropped (0.7). On write, residue goes back into
its map or array, re-encoded with the core deterministic encoding, and takes
its place in the key order. Residue is written only into its own format.

## Kinds

A `when` or `const` value on `cbor` is an integer when 2a of 0.11 accepts it
(a sign and leading zeros allowed) and it lies in -2^63 to 2^64-1; `true` or
`false` is a bool; any other value is a text string, one leading `=`
stripped. `when <path> <value>` holds when the item at the path, its tags
passed over, is of that type and equal to it; it never holds on a float, a
byte string, `null` or `undefined`. `when <path> present` holds when the item
exists and is not `null` or `undefined`. On encode a `when` value and a
`const` are written with their type; `when … present` writes nothing, and a
pack that selects a kind by it lists in `requires` a key mapped at or under
that path.

## Vectors

`input` and `expect` of a `cbor` format are lowercase hex text.

## Rulings for 0.28

1. **Deterministic output and residue.** Residue re-encoded under 4.2.1 is
   not byte-exact when the input used longer heads, wider floats or
   indefinite lengths; the item it carries is the same.
2. **Tags on inner items** are not written. A pack that needs a tag on an
   inner item cannot state it in 0.28.
3. **Floats and integers.** `float` reads an integer item as its value and
   always writes a float. `int` and `uint` refuse a float item, even one with
   no fraction (`transform-decode`).
4. **Map keys equal in value but written differently** (`00` and `1800`,
   both the integer 0) are equal keys, so a map holding both is
   `malformed-wire` by step 4 of "Reading a message".
5. **The `tag` directive** names two forms: 0.13's on `tlv` and this
   section's on `cbor`; this replaces 0.13's "`bad-directive` on another
   wire" for `cbor`.
6. **`null` and `undefined` members.** A mapped item holding `null` or
   `undefined` is absent and is not written back. An unmapped one is residue
   like any other item and is written back as it stood (`f6` or `f7`).
7. **The range of `epoch_s`** applies to the product: a number of seconds
   whose `time_ms` falls outside -2^63 to 2^63-1 is `transform-decode`.
8. **Integer `when` and `const` values** on `cbor` lie in -2^63 to 2^64-1;
   for them this replaces the signed 64-bit limit of 2a of 0.11, so `when 0
   18446744073709551615` is an integer.
9. **`requires` with `when … present`** is guidance for pack authors and is
   not checked at load.
10. **`absent` on `cbor`** is `bad-directive` after the file is read (0.11
    5b: an option that does not fit its wire); step 10 of 5b does not check
    its values on `cbor`, so a later line's error comes first.
11. **Hex text** of `input` and `expect` follows the rules of `bits` and
    `protobuf` in spec/vector-format.md.
12. **`null` or `undefined` partway down a path** makes the line's item
    absent, as a group path at `null` is an absent list: `field … 7.1` on
    `a107f6` is absent, not `malformed-wire`. The `null` the line passes
    through is walked into, so it is not residue and is not written back.
13. **One path a value and a container.** Within one scope, a line whose path
    is a proper prefix of another line's path is `bad-directive`, checked
    after the file (as ruling 5 of 0.13 states for `tlv`); a `when …
    present` is exempt, since it tests and writes nothing, and may name a
    prefix of another line's path. So are a `group`
    at or under another `group`'s path in the same scope, and a group body
    that mixes `.` with other paths.
14. **A map or array element in a body of only `.`** is read by the
    transform, which refuses it: `transform-decode` (ruling 6 of 0.7).
15. **`when … present`** does not walk into its last item: an item it names
    and no other line walks into is residue whole.
16. **The hex of a key that is not addressable** is the key's bytes as they
    stood in the input (`780134` for `"4"` written with a one-byte length
    head gives `#780134`); on write the key is re-encoded with step 1 of
    Writing.
17. **Integer keys below -2^63** (major type 1 with an argument of 2^63 or
    more) are not addressable.
18. **Array residue past position 65535** has no key a path can write and is
    dropped.
19. **A `when` or `const` integer beyond -2^63 to 2^64-1** is a text string.
20. **Encoding a `float` that is infinite or NaN** is `transform-encode`.
21. **Residue at a place a line writes** is not written; the line wins.
22. **Ruling 13 in detail.** The `when … present` exemption holds only when
    it is the shorter path: `field x 7 int` beside `when 7.1 present` is
    `bad-directive`. A `group` line takes part in the prefix rule as any line
    does: `field x 9 int` beside `group probe.items 9.1` is `bad-directive`.
    `.` is a path only on a `field` in a group body and on a `group` outside
    one; elsewhere (`const .`, `when .`, a `group … .` in a body) it is
    `bad-locator`. `const <path> present` is `bad-directive`, as on every
    wire.
23. **A container gap in a positional array.** In Writing step 3, a position
    below the highest present one with nothing to write is written as an
    empty map (`a0`) when the pack's lines walk into it as a map, as an empty
    array (`80`) when they walk into it as an array, and as `null` (`f6`)
    otherwise. A `group`'s own path is not walked into: an absent list at a
    gap position is `f6` (a present list, even empty, is written by step 4).
    So COSE_Sign1 with an empty unprotected header map round-trips as `a0`
    at `[1]`.
24. **A `group` line maps its own path.** The item at a group's path is not
    residue: `null` or `undefined` there is an absent list and is not written
    back, so `81f6` through `conformance-cbor-group` is `80`. (A gap at that
    position below a present one is still `f6`, by ruling 23.)
25. **A transform name no wire has** on a `cbor` field is `bad-directive`
    after the file, as ruling 8 of 0.13 states for `tlv`, not
    `unknown-transform` as the line is read.
26. **`with` (0.18)** is a field option on `cbor` as on every wire; a
    suppressed line writes nothing, as a line whose key is absent.
27. **A deeper step of a group-body path** that meets an item of the wrong
    type for its next step is `malformed-wire` (Reading step 8); only the
    element itself being of the wrong type for the body makes an item with
    no keys.
28. **A NaN carried as residue** keeps its sign and payload, written at the
    shortest width that holds them exactly.
29. **A `field` at a path a `when` value or a `const` names** is not
    encoded (ruling 16 of 0.5, ruling 9 of 0.13): its value is never
    converted, so a value it could not encode raises no error.
30. **The lines of ruling 23** are those of the selected scope: the common
    lines and the chosen kind's. A position only another kind walks into is
    `f6`.
31. **Residue under ruling 21.** A line writes at a place only when it writes
    a value there; a container the selected lines walk into but leave empty
    takes its residue back whole.
32. **Step 8 covers `const` lines** as every line of the selected scope: a
    `const` whose path passes through an item of the wrong type for its next
    step is `malformed-wire` on decode.
33. **Residue through a written value.** Residue whose path passes through a
    place a line wrote a value at, or through a container of the other type,
    has nowhere to go and is dropped.
34. **The whole transform check on `cbor` is after the file**, as ruling 8
    of 0.13 states for `tlv`: no transform of the table takes parameters, so
    a transform with parameters (`uscale:x`, `uscale:1/4`) is one the table
    does not hold, and its name and parameters are checked together after
    the file is read (`bad-directive`); a later line's error comes first.
35. **Step 8 before any decode.** The type checks of Reading step 8, for
    every line of the selected scope and every group element, come before
    any value is decoded, so `malformed-wire` from step 8 wins over a
    `transform-decode` of an earlier line.
36. **No `when` lists on `cbor`.** The lists and ranges of 0.20 apply on
    the wires its ruling 38 names; `cbor` is not one of them, so a comma in
    a `when` value is part of a text string: `when 4 1,2` holds on the text
    "1,2", and `when 4 a,,b` and `when 4 present,1` load. Rulings 16 and 25
    of 0.20 govern lists and do not reach these values.
37. **0.22's `until:` on `cbor`** is not a path of 0.28 (`:` is not a
    path character), so it is `bad-locator` as the line is read (Paths),
    before 0.22's after-file check could apply.
38. **`cbor` and Versions 0.24 and 0.25.** `cbor` is a wire of ruling 1a of
    0.24: a build may leave it out, a build that names no set has all eight
    wires (the seven 0.24 lists and `cbor`), and a pack on `cbor` in a build
    without it is `unknown-wire` with the message 1c states. An engine names
    the switch for `cbor` the way it names the others, in its README. The
    reduced-build check of 0.24 also loads a pack on `cbor` and expects that
    error. The benchmark set of 0.25 (ruling 2a, every wire) holds a `cbor`
    vector, `packs/dtn-bpv7/vectors/01-ipn-round-trip.json`.

# Version 0.29: licence profiles in the loaders

<!-- REUSE-IgnoreStart: this section quotes licence tags; they label no file -->

Status: Written. Each pack carries one licence (`packs/<name>/REUSE.toml`),
and each model module may carry one (`model/<file>.def.license`). The flags
of every licence are in one table, `licences.toml`, beside the packs
directory (`LICENSING.md`). From these, every pack and module belongs to one
of three named profiles, or to none, and an engine can be asked to load only
the packs and modules of one profile. With no profile asked for, an engine
reads no licence file and loads as before, so every earlier result holds; the
one exception is the `licences` subcommand (ruling 4), which always reads
them. `tools/licences.py` computes the same profiles from the same files, and
`tools/licences.py --check` (CI) holds every file of the repository to the
forms ruling 1 reads, so the two agree on every tree that passes CI.

## The profiles

| Profile | Holds |
|---|---|
| `open` | licences with `commercial = "yes"`, `share_alike = false` and an empty `field_of_use` |
| `open+copyleft` | `open`, and those with `share_alike = true` (commercial `yes`, no field of use) |
| `everything` | every public licence: also `commercial = "no"` or `"unknown"`, or a field of use |

The profiles are ordered `open` < `open+copyleft` < `everything` < none.
"Wider" and "widest" in this section follow that order, so none is wider
than `everything`. Each of the three profiles holds itself and the profiles
before it; none is held by none of the three.

## Rulings for 0.29

### Ruling 1: the files an engine reads

**Lines.** Each file of this ruling is read as UTF-8 text cut into lines at
each line feed (0x0A); one carriage return (0x0D) directly before a line
feed, or at the end of the file, is removed with it. A line is then trimmed
of spaces and tabs at both ends. "Matches" means the whole trimmed line
matches. A file that is not valid UTF-8 is `bad-licence`. A byte-order mark
is not removed (so a licence line that follows one is not a licence line).

**A licence id** is one or more of the characters `A`-`Z`, `a`-`z`, `0`-`9`,
`.`, `-` and `+`, compared as exact text (`apache-2.0` is not `Apache-2.0`).

**Where.** `licences.toml` is the file named by the `--packs` text as given
followed by `/../licences.toml`, resolved by the operating system as the
default of `--models` is (Version 0.23). The module licence files are in the
directory the modules are loaded from. A file "does not exist" only when the
operating system reports that no entry has that name, or that a part of the
path before the last is not a directory or does not exist; any other failure to read it (a directory, no
permission) is `bad-licence`. An engine never reads the `REUSE.toml` at the
root of the tree.

- **1a. The licence of a pack** in directory `d` is read from
  `<packs>/d/REUSE.toml`. Its licence line matches `SPDX-License-Identifier`,
  any spaces or tabs, `=`, any spaces or tabs, `"`, a licence id, `"`. Every
  other line is skipped. The file must hold exactly one licence line; none
  or more than one, or a line that begins with `SPDX-License-Identifier`
  followed by a space, a tab or `=` and is not a licence line, is
  `bad-licence`. When the file does not exist the licence is `Apache-2.0`.
- **1b. The licence of a module** in file `m.def` is read from
  `<models>/m.def.license`. Its licence line matches
  `SPDX-License-Identifier:`, one or more spaces or tabs, a licence id. The
  rest is as 1a: exactly one, a line that begins with
  `SPDX-License-Identifier:` and is not a licence line is `bad-licence`, and
  no file is `Apache-2.0`.
- **1c. The table.** In `licences.toml` an empty line, or one that begins
  with `#`, is skipped. A line `[licences."<id>"]`, with a licence id and no
  space, starts the row of that licence; a second row of the same id is
  `bad-licence`. Inside a row exactly these four lines must stand, once each,
  in any order, with any spaces or tabs around `=`:

  | Line | Value, exactly |
  |---|---|
  | `commercial = "<v>"` | `yes`, `no` or `unknown` |
  | `share_alike = <v>` | `true` or `false` |
  | `field_of_use = <v>` | `[]` (empty), or `["`, then any characters or none, then `"]`, on that line (not empty: `[""]` is a field of use) |
  | `distribution = "<v>"` | `public` or `controlled` |

  Three more lines are allowed in a row, at most once each, and skipped:
  one that begins `name`, one that begins `url` and one that begins
  `attribution`, each followed by a space, a tab or `=`. Any
  other line (a line before the first row, a value not in the table, any
  other key, `field_of_use = [ ]`, a value followed by a comment, a
  `[`-line that is not a row header) is `bad-licence`. A row that lacks one
  of the four lines is `bad-licence`. When `licences.toml` does not exist,
  the table has one row, `Apache-2.0`, with `commercial = "yes"`,
  `share_alike = false`, `field_of_use = []` and `distribution = "public"`.

### Ruling 2: the profile of a licence, a module and a pack

- **2a.** A licence in the table with `distribution = "controlled"` is in no
  profile. Otherwise it is in `open` when commercial is `yes`, its field of
  use is empty and share-alike is `false`; in `open+copyleft` when commercial
  is `yes`, the field of use is empty and share-alike is `true`; in
  `everything` otherwise. A licence not in the table is in `everything`.
- **2b. The modules.** Profiles are computed over every module file of the
  model directory (the files Version 0.23, Loading, 1 loads), whether or not
  it will be loaded. Two lines of a module file or `pack.def` are read for
  this, each trimmed as ruling 1 trims: a line that matches `module`, one or
  more spaces or tabs, and a name; and a line that matches `uses`, one or
  more spaces or tabs, and a name. A name is one or more of `A`-`Z`, `a`-`z`,
  `0`-`9`, `_` and `-`. Every other line is passed over here, a `uses` line
  with a comment or a quoted name included; the file's own load reports
  whatever is wrong with it if it is loaded. A module's name is that of its
  first `module` line; a module file with no such line has no name. A
  module or `pack.def` file that cannot be read, or is not UTF-8, adds no
  line here and is never `bad-licence`. A module's profile is the widest of
  its licence's profile and the profiles of the modules it uses, directly or
  through others. A `uses` name that no module file has adds nothing. When
  two module files have the same name, a `uses` of that name takes the wider
  of them.
- **2c. The packs.** A pack's profile is the widest of its licence's profile,
  the profile of the module named `core` (every pack uses `core`, ruling 1
  of 0.4: the module file or files whose `module` line names `core`; none
  adds nothing), and the profiles of the modules its `uses` lines name, read
  as in 2b.

### Ruling 3: loading with a profile

- **3a.** An engine's loader takes an optional profile, one of the three
  names. A name not one of them is refused before anything is read: on the
  command line a usage error (ruling 4); in a library, `bad-licence`.
- **3b. Order.** With a profile, before any module is loaded, the engine
  reads `licences.toml` (1c), then, for each module file in file order
  (`core.def` first, then byte order of file name, not the order in which
  modules are loaded after the modules they use), its licence (1b) and its
  `module` and `uses` lines. The first file that cannot be read as ruling 1 says is the error,
  `bad-licence`, and nothing is loaded. Then it computes every module's
  profile (2b).
- **3c. Modules.** A module whose profile the profile does not hold is not
  loaded; every other module is loaded as before, in the same order.
- **3d. Packs.** Each pack is reached as Version 0.23, Loading, 2 says, and
  the checks of a `--packs-only` name there (one path component, a
  subdirectory holding `pack.def`, else `unknown-format`) come first. Then
  the engine reads the pack's licence (1a) and the `uses` lines of its
  `pack.def` (as 2b), computes its profile (2c), and, when the profile does
  not hold it, skips the pack: it is not otherwise read or checked, so a
  pack that would fail to load is skipped without its failure. A pack held
  by the profile is loaded as before.
- **3e. Skipped.** A module or pack that is not loaded is as if it were not
  there: it takes part in no `duplicate-format` or `duplicate-module` check,
  a `--packs-only` name given twice whose pack is skipped is skipped twice,
  a later `--from` or `--to` naming its format is `unknown-format`, and
  `list-formats`, `capability`, `matrix` and `licences` do not show it. (With
  no profile given nothing is skipped, and a pack in none is loaded.)
- **3f.** `bad-licence` is a load failure (ruling 4 of 0.11), with its kind
  and message like every other.

### Ruling 4: the command line

- **4a.** `--profile <open | open+copyleft | everything>` is one more of the
  `<options>` of Version 0.23, taken by `convert`, `list-formats`,
  `capability`, `matrix` and `licences`. Its default is no profile.
- **4b.** `<tool> licences <options>` is a fifth subcommand. Its options are
  `<options>` and `--json`. `--json` is the one option of the contract that
  takes no value: where an option name stands, `--json` is the whole option,
  and the next argument is again at a place where an option name stands. It
  is given at most once.
- **4c.** `licences` reads every file of ruling 1 in the order of 3b, with
  or without a profile, then loads as 3c and 3d say (with no profile, every
  module and pack is held, but each pack's licence and `uses` are still read
  as 3d says, before it is loaded). It writes one line per loaded pack, in
  byte order of the pack's directory name: the directory name, a tab, the
  format (written as `list-formats` writes it, without quotes), a tab, the
  licence, a tab, the pack's own profile (2c, whatever profile was asked
  for), a line feed. With `--json`
  it writes instead `{"packs":[`, then one object per pack in the same
  order, separated by `,`, then `]}` and a line feed. An object is
  `{"pack":"<dir>","format":"<format>","licence":"<licence>","profile":"<profile>"}`
  with no space anywhere; in each value `"` is written `\"`, `\` is written
  `\\`, each character below U+0020 is written `\u` and four lower-case hex
  digits, and every other character is itself, in UTF-8. With no profile, a
  pack in no profile is listed, and its profile is written `none`.
- **4d.** The usage errors of Version 0.23 change: in 2, `licences` is a
  valid first argument; in 3, `--profile` is a name every subcommand but
  `help` takes, and `--json` a name only `licences` takes; and there is a
  new one, 11: a `--profile` value that is not `open`, `open+copyleft` or
  `everything`.

### Ruling 5: what is not ruled

- The licence texts in `LICENSES/`, the `attribution` flag and the `name` and
  `url` of a row are for people and for `tools/licences.py`; an engine does
  not read them.
- Whether a `REUSE.toml` is valid REUSE beyond its licence line is checked by
  `reuse lint` and `tools/licences.py --check` in CI.
- A pack directory name that is not valid UTF-8, in the output of
  `licences`.
- `tools/licences.py` reads `model/` beside `packs/`; it gives an engine's
  result only when `--models` is that directory.
- A format value that holds a tab, in the output of `licences`.

## Vectors

Tool vectors `packs/conformance/tool-vectors/` numbered from 101, written by
`tools/gen/conformance-tool-vectors.py`, run against the fixture trees under
`packs/conformance/tool-fixtures/licences-*/`, each with its own
`licences.toml`, `model/` and `packs/`.

<!-- REUSE-IgnoreEnd -->

# Version 0.30: a sequential discriminator that is also a key

Status: Written. In a `layout sequential` pack (Version 0.8) the `when` bits
of a kind are read to select the kind and then skipped: no key holds them. A
format whose kinds are told apart by a label field therefore cannot hand the
label on to another format, and an encode from another format cannot choose
the kind by it. This version lets a `when` line bind its bits to a key.

```
when  <len> <value>[,<value>…]  as <model-key>
```

`as <model-key>` follows the values of a `when` line of a `layout sequential`
pack: a common `when` (before the first `kind`), a `when` of a message kind,
or a `when` of an item kind in a group body. The key follows the rules of a
`field` key in the same scope: a message key at message level, a key of the
list's items in a group body (a group body's common `when` included,
ruling 11). Its declared type must be `int`.

On a fixed `bits` layout the same thing is already stated with lines that
exist: a `field` line over the `when`'s bits gives the key on decode, and
`requires <key>=<value>…` (Version 0.20) chooses the kind on encode
(ruling 1). `as` there, and on any other wire, is `bad-directive`.

## Decode

The `when` line reads `len` bits at the cursor and tests them as before
(Versions 0.8 and 0.20). When the kind is selected, the key holds the bits
read as an unsigned integer. The `when` lines of a kind that is tested and
not selected set nothing. A common `when … as` sets its key whenever the
message decodes.

## Encode

**Choosing the kind.** A kind with a `when … as <k>` line qualifies, when the
kind is chosen by `requires` (Version 0.5, ruling 4 of 0.20), only when the
entity holds `<k>` and its value matches the `when`: it equals a listed value
or lies in a listed range. This is an implicit `requires` term, checked with
the kind's other `requires` terms; the kind may also carry them. When the
kind is chosen by the kind recorded on the entity (same format), the term is
not checked for choosing.

**The bits written.** A `when … as <k>` line writes the value of `<k>` when
the entity holds `<k>` and its value matches the `when`. When the entity does
not hold `<k>`, it writes the first listed value (for a range listed first,
its `lo`), as a `when` does without `as`. When the entity holds `<k>` with a
value the `when` does not match, encode is `transform-encode`: the output
would decode a different value. This case arises only for a common `when`
or a kind recorded on the entity, since a kind chosen by `requires` would not
have qualified.

## Load errors

`bad-directive`: `as` on a `when` of a pack that is not `layout sequential`;
`as` with no key or with a token after the key; `as` twice on one line; two
`when … as` lines of one kind (or of the common lines) naming one key; a key
named by `as` and also mapped by a `field` or `also` line in the same reading
path (common lines plus one kind, one case of each switch). A key of a module
the pack does not `uses` is `module-not-used`; an undeclared key is
`undeclared-key`; a list key, or a key whose type is not `int`, is
`key-type-mismatch`.

## Rulings for 0.30

1. **Fixed layouts.** A `field <k> <pos>:<len> uint` line over the bits of a
   kind's `when`, with `requires <k>=<values>` on the kind, states the same
   thing for single values and needs no new directive. The two forms differ:
   `requires =` takes no ranges, and on a fixed layout ruling 3 of 0.20 writes
   the first value over a field that does not match, where `as` is
   `transform-encode` (ruling 8).
2. **A switch on an `as` key.** A kind's `as` key counts as mapped from the
   start of its kind for a `switch` (Version 0.20): `switch <k>` in the kind
   selects a case by the label. A common `as` key counts as mapped from its
   own line on, in reading order, so a `switch` on it before that line is
   `bad-directive`.
3. **Several kinds, one key.** Different kinds of one body may each bind the
   same key with `as`; only the selected kind's line sets it. This is the
   intended use: one label key across every kind.
4. **Item kinds.** Ruling 26 of 0.8 still holds: an item that records a kind
   the group has uses it, and the implicit term is not checked for choosing;
   otherwise the item's kind is chosen by `requires`, with the implicit term.
5. **Capability.** A key bound by `as` is listed by `model_keys` at its
   `when` line in first-appearance order (6a of 0.11); in a group body the
   entry is `<list>[].<k>`.
6. **A `default` on an `as` key** has no effect on what is written or on
   choosing the kind: "holds" means the entity holds the key, as in rulings 15
   and 29 of 0.20. The default loads.
7. **Values and matching.** Decode reads the bits as `uint` does (ruling 2 of
   0.5): with `len` 64, a value of 2^63 or more is the negative integer with
   the same bits. "Matches" reads the entity's value as an unsigned 64-bit
   pattern and compares it with the listed unsigned values and ranges; a
   negative value never matches a `when` shorter than 64 bits.
8. **Ruling 3 of 0.20 does not apply** to an `as` line; this version's Encode
   rules replace it there.
9. **Two `as` lines naming one key in one reading path** (common lines plus
   one kind; a group body's common lines plus one item kind) are
   `bad-directive`, a common `as` and a kind `as` included. This and the ban
   on an `as` key mapped by a `field` or `also` line override 0.6, which lets
   several `field` lines map one key.
10. **The kind is chosen before any line is written.** `no-kind` wins over
    every error raised while writing, `transform-encode` of a common `as`
    included.
11. **The common `when` of a group body** (before the first item kind) may
    carry `as`. It acts as a common `when` for each item: the key is set on
    every item that decodes, and the encode rules for a common `when` apply
    per item.
12. **A kind's `when` lines set nothing until the kind is selected.** When an
    `as` line holds and a later `when` line of the same kind does not, the key
    is not set, and the next kind is tried.
13. **`requires` on an `as` key.** A plain `requires <k>` and
    `requires <k>=<values>` on a kind with `when … as <k>` load; every term
    must hold, so a `requires <k>=` value outside the `when` makes the kind
    unreachable by `requires`.
14. **`also` after a `when … as` line** is `bad-directive` (ruling 13 of
    0.8: `also` follows only a `field` or `also` line).
15. **Ruling 23 of 0.20 is amended** for `layout sequential` only: `as <key>`
    may follow the values of a `when`. Every other extra token stays
    `bad-directive`. `as` is a keyword only in the third token of a `when` of
    a sequential pack; on a text wire `when @t as` matches the text `as`.
16. **When the checks run** (0.11 ruling 5b). Every syntax error of `as` (no
    key, a token after the key, `as` twice, `as` on a pack that is not
    sequential) is a check after the file. The ban on two `as` lines naming one
    key and on an `as` key mapped by a `field` or `also` line needs only key
    names. It runs with the checks that need the whole file, before
    `missing-distribution` and `missing-source`.
17. **Error order** (ruling 19 of 0.20). `as` keys join the first pass:
    `module-not-used`, then `undeclared-key`, over every line. Their list and
    non-`int` checks (`key-type-mismatch`) run in the third pass, in line
    order with the `field` type checks.
18. **`as` lines are `when` lines** for ruling 10 of 0.8 (first lines of their
    kind) and for every rule that counts wire lines.

19. **A switch on an `as` key, on encode.** The `when … as` line is "the
    key's line" of 0.20's switch encode: when a common `as` key is absent,
    the first listed value it writes selects the case.
20. **A common `when … as` may follow other common lines.** Ruling 10 of 0.8
    places a kind's `when` lines first in their kind; common `when` lines
    keep 0.5's placement.
21. **Scopes for the bans of ruling 9.** An item key bound by `as` and a
    message-level `field` are in different scopes and load, as two `field`
    lines in those scopes do.
22. **The keyword is exact.** `as` is matched as written; `AS` is another
    token and is `bad-directive` in a sequential `when`.
23. **Two passes** in ruling 17: `module-not-used` over every line, then
    `undeclared-key` over every line, as Version 0.4 orders them.
24. **Ruling 6c of 0.11 is amended:** a place named by `when` is not a mapped
    key, except a `when … as` line, whose key is mapped (ruling 5).

### Stated, not yet pinned by a vector

25. A kind or item kind recorded on the entity: "the term is not checked for
    choosing", and `transform-encode` for a held value that does not match.
    Neither can be reached through `convert`, since a same-format decode sets
    the key to a matching value.
26. Ruling 1's comparison with ruling 3 of 0.20 on a fixed layout; only the
    `bad-directive` of `as` there is pinned.
27. Ruling 5: the capability vector is computed by the generator
    (`conformance-whenas-cap`) but not written.
28. Ruling 8, pinned only through the `transform-encode` of a common
    `when … as`.
29. Ruling 16: the `as` syntax checks run after `missing-format`,
    `missing-version` and `missing-wire`. The two bans of ruling 9 run after
    the syntax checks and before the other checks that need the whole file.
30. Ruling 18 for rules other than ruling 10 of 0.8 and ruling 32 of 0.21.
31. "`as` twice" (load errors) is any second `as` token after the first:
    `when 8 1 as as` is `bad-directive`, not a key named `as`.
32. Ruling 10 applies per body: a group item's kind is chosen when that item
    is written, so a common `as` of the message that does not match, written
    before the group, is reported before an item's `no-kind`.
33. The reading path of ruling 9 covers every block of the same scope: a
    `field` or `also` line in any `case`, `if`, `opt`, `chain`, `length`,
    `ext` or `choice` body of that scope conflicts with an `as` key; a group
    body is a separate scope (ruling 21).
34. **`@kind` in a vector with `@complete`** (spec/vector-format.md, step 3)
    names the kind `decode(from, input)` selected, with or without
    `@complete` and whether or not `from == to`. The entity `convert` hands to
    the encoder has no kind for another format (Version 0.6), but a vector's
    `@kind` checks decode, not that entity. Vector
    `conformance-whenas-kinds` `cross-format-complete-keeps-the-decoded-kind`
    pins it.

## Not in this version

- A transform or table on an `as` key: the key holds the unsigned value.
- `as` on a `when` of the fixed layout and of other wires (ruling 1).

# Version 0.31: one list counted from two places

Status: Written. A message carried inside a transport often states the length
of one list twice: the transport header counts the words that follow, and the
carried message has its own count field. Version 0.21 lets one count name
one list. This version lets one list name two counts, which must agree.

```
count <a> <len> [plus <n>]
…
count <b> <len> [plus <n>]
…
group <list> count @<a> @<b>
  …
end
```

Valid where `group <list> count @<name>` is valid (Version 0.21): a
`layout sequential` pack on `bits`. Each of `<a>` and `<b>` is a `count` line
of Version 0.21, with its own `len` and its own `plus`, and each must be
visible at the group line as 0.21 states. The group references both.

## Decode

When the group is reached, the number of items each count gives is its value
minus its own `plus`. When the two numbers are equal, that many items are
read. When they differ, the message is `malformed-wire`, raised at the group
line. A count value below its `plus` stays `malformed-wire` at its own count
line, as in 0.21.

When the group is not reached (0.21 ruling 6: it lies in a block or case
not read, or at or past the end of a `length` extent), the list is absent;
each count that was read passes its own below-`plus` check, and the two
values are not compared.

## Encode

Each count field holds the number of items plus its own `plus`, written at
its own place after the group is laid out, as in 0.21. A value outside
`0 … 2^len − 1` for either count is `transform-encode`. An absent list writes
each count's `plus`.

## Load errors

`bad-directive`: a token after `count` on a group line that is not
`@<name>` (`count @a 8`, `count 8 @a`, a bare `@`); more than two tokens; the
same name twice on one group (`count @a @a`); either name not visible at the
group line, or not a `count` name. On a layout or wire where 0.21 refuses
`count @<name>`, the two-name form gets the same error kind at the same step
(`bad-locator` on `protobuf`, ruling 44 of 0.21; `bad-directive` on `json`).

## Rulings for 0.31

1. **Order of the two names** has no meaning: `count @a @b` and
   `count @b @a` read and write the same bits.
2. **Where the counts sit.** Visibility is exactly as in 0.21 (rulings 9 and
   12): a count inside a `length`, `if`, `opt` or `case` block is not visible
   after the block's `end`. One count may be in the common lines and the
   other inside a kind, or a `length`, `if`, `opt` or `case` block that also
   holds the group.
3. **One reference per name per path.** In each reading path each of the two
   names is referenced by exactly one group (0.21 ruling 2): a path in which
   either name has no reference, or two, is `bad-directive`. One name may be
   referenced by a two-name group in one path and by a one-name group in
   another, provided every path meets the rule.
4. **Order of the decode checks.** The below-`plus` check runs at each count
   line. At the group line, equality is checked first, then the bits left
   (ruling 14 of 0.8, ruling 20 of 0.21) for the agreed number. All three are
   `malformed-wire`. No item is read before them.
5. **Exact integers.** The two numbers are compared as exact integers
   (0.21 ruling 7): equal only when value_a − plus_a = value_b − plus_b, with
   no wrapping.
6. **A failed field before the group.** When a field between the counts and
   the group failed its transform and the counts then disagree, the decode is
   `malformed-wire`: a structural error wins, as in ruling 5 of 0.22.
7. **When the checks run.** Every 0.31 load error is a check after the file,
   as a group's options are (0.11 ruling 5b), except the error kind that 0.21
   gives on `protobuf`, which stays at its own step.
8. **Encode.** The two fills are written at their own places after the group
   is laid out; their order cannot be seen. Each is range-checked as in 0.21
   (ruling 30 of 0.21); an absent list with a negative `plus` on one count is
   `transform-encode`.

9. **A count line not read** (at or past the end of a `length` extent, or
   in a block not read) gets no below-`plus` check
   (`conformance-twocount-length`).
10. **The bits-left check** compares the agreed number of items with the
    number of bits left, as ruling 25 of 0.8 states ("not with count times
    item size"); `conformance-twocount-bits` reaches that boundary with
    1-bit items.
11. **An empty list** is an item count of 0 like any other: a count whose
    `plus` makes 0 + `plus` fall outside its range is `transform-encode`.

### Stated, not yet pinned by a vector

12. The order of the three decode checks (ruling 4), "raised at the group
    line" and "no item is read before them": each gives `malformed-wire`, so
    no vector can tell the order.
13. The order of the two fills (ruling 8): it cannot be seen in the output.
14. On a fixed layout, whether the refusal of `count @` is a line check or a
    check after the file: 0.21 does not say, and only the kind
    (`bad-directive`) is pinned.

## Not in this version

- More than two counts on one list.
- A count that follows its items (claimed separately).
- Two counts in different packs (a transport pack and the pack it carries).
  Version 0.34 lets one pack carry the other and does not compare them.

# Version 0.33: a kind decided by a field after other fields

Status: Written. In a `layout sequential` pack the `when` lines of a kind are
its first lines, read where the common lines ended (Version 0.8). Some formats
decide the layout of a body by a field that comes after other fields of the
body, and those earlier fields mean different things in each kind. Declaring
them as common lines would give them one name for every kind. This version
lets a `when` look ahead.

```
when  <len> <value>[,<value>…]  at <offset>  [as <model-key>]
```

`at <offset>` is valid on a `when` of a message kind or of an item kind in a
`layout sequential` pack. `<offset>` is an unsigned decimal number of bits,
counted from the **kind start**: the cursor position where the common lines
(of the message, or of the item) ended, the same position from which every
kind's `when` lines are read. `as` is Version 0.30's and may follow.

## Decode

A `when … at <offset>` reads its `len` bits at kind start plus `<offset>` and
tests them as a `when` does. It does not move the cursor. A `when` without
`at` reads at the cursor and moves it, as before. A kind holds when all its
`when` lines hold; the first kind in pack order that holds is selected
(Version 0.5). Then the kind's other lines are read from the cursor, so the
kind's own `field` lines read the bits the look-ahead tested, under the
kind's own key names.

When the bits at kind start plus `<offset>` plus `len` lie beyond the input
(or beyond the enclosing `length` extent), that `when` does not hold and the
next kind is tried. If no kind holds, the message or item is `no-kind`.

## Encode

The kind is chosen as before (the kind recorded on the entity or item, or
`requires`, with Version 0.30's implicit term for an `as` key). The kind's
lines are written. Then each `when … at` of the selected kind settles its
window, in line order (ruling 1):

- when the window's bits as written match the `when`, and agree with the
  value of a held `as` key, they stand;
- otherwise the window's value is the value of the `as` key (Version 0.30)
  when the entity holds it, or else the first listed value. When a bit of that
  value differs from a bit that a key the entity holds wrote in the window,
  encode is `transform-encode`: the output would decode a different value.
  Otherwise the window is written with that value.

A `default` does not count as a held key (ruling 29 of 0.20). The windows are
settled before any `switch` reads its key back and before the prediction of
ruling 33 of 0.20, so a switch reads its key from the bits as they stand
after the windows are written. Presence and `fx` bits do not interact with
a window, which ends before any `presence`, `opt` or `chain` line (the fixed
rule below), and presence is computed from content, not from bits.

## Load errors

`bad-directive`: `at` on a `when` of a pack that is not `layout sequential`;
`at` on a common `when` (before the first `kind`, a group body's common lines
included); `at` without a value, twice, or with a value that is not plain
digits or does not fit in 64 bits (leading zeros allowed); a `when` whose
tokens are not exactly `when <len> <values> [at <n>] [as <k>]`, in that order.
Also `bad-directive`: the look-ahead window is not **fixed in the kind**.

The window of a `when … at` is the bits from kind start plus `<offset>` to
kind start plus `<offset>` plus `len`. To test it, walk the kind's lines in
reading order from its first line, skipping lines that occupy no bits (`when
… at`, `requires`, `default`, `also`) and summing the lengths of the others, until
the sum reaches or passes the window's end. Every line walked, the last one
included, must be one of: a `when` without `at`; `const`; `pad`; `also`; a
`field` whose locator is a bit length. That list is exhaustive. Field options
that keep the width keep a field fixed: `via`, `swap`, `trim`, `absent`,
`stop`, `with` (a suppressed field writes its `len` zero bits) and `hex`. Any
other line walked makes the window not fixed: for example `align`,
`presence`, `if`, `opt`, `chain`, `fx`, `length`, `group` (`group … count`
included), the 0.21 `count <name>` line, `switch`, `ext`, `choice`, `alt`, or
a `field` with an `until:` or UPER locator. A window that ends past the
kind's last line is not fixed either.

## Rulings for 0.33

1. **Settling a window** (Encode) follows ruling 3 of 0.20 for bits a held
   key wrote that match, and 0.30's rule against a silent change for bits that
   do not. The window may cover a whole `field`, part of one, or several;
   a partial cover is settled as ruling 13 states.
2. **Plain and look-ahead `when` lines in one kind** may be interleaved among
   the kind's first lines (ruling 10 of 0.8). Offsets count from kind start,
   not from the cursor; plain `when` lines consume bits in their line order.
3. **A window over a `const`.** A `const` is not checked on decode (0.6), so
   the kind holds whatever the `const` bits are; encode writes the `when`'s
   value over the `const`.
4. **Item kinds.** In a group body, kind start is where the item's common
   lines ended, for each item.
5. **Two windows** of one kind may overlap, and a window may cover a plain
   `when` of the same kind with another value. These load; windows are
   settled in line order with no check between them, so the later one's bits
   stand.
6. **Past the end.** A `when` (with `at` or without, in a sequential pack)
   any of whose bits lie beyond the input, beyond `length … whole`, or beyond
   the enclosing extent, does not hold, and the next kind is tried. A kind's
   `when` lines are tested in line order. Once a kind is selected it is
   final: a later line of it past the end is `malformed-wire`, and no other
   kind is tried.
7. **The enclosing extent** is the innermost `length` block around kind
   start (a group item is not an extent, ruling 12 of 0.22). A window that
   starts at or past its end does not hold; an item with no kind that holds
   is `no-kind`, which fails the whole decode (ruling 11 of 0.20).
8. **Raw bits.** A window reads and writes raw stream bits in the pack's
   bit order, independent of any field's transform or `swap`.
9. **Wire lines.** A `when … at` is a wire line for rulings 11 and 32 of
   0.21.
10. **When the checks run** (0.11 ruling 5b). Every `at` error is a check
    after the file. Order: `module-not-used` and `undeclared-key` first
    (ruling 19 of 0.20), then the 0.30 `as` checks, then the `at` form, then
    the fixed-window check.
11. **The token order** amends ruling 23 of 0.20 with 0.30's amendment:
    `when <len> <values> [at <n>] [as <k>]` is the only form with more than
    two arguments, on `layout sequential`.

12. **Bits a held key wrote** are the bits of a `field` (or `also`) line
    whose key the entity holds and whose line wrote its value. Bits of a
    `pad`, a `const`, a plain `when`, an earlier window, an absent key's zero
    bits or sentinel (`absent`), and a line that `with` suppressed are not;
    the window is written over them without a check.
13. **A partial cover** (ruling 1) is settled by the Encode rule above: the
    window's value is chosen first, and only the bits a held key wrote are
    compared with it.
14. **Error order against the header checks.** The `at` checks run after the
    key passes of ruling 10, which Version 0.4 orders after
    `missing-distribution` and `missing-source`; so those come before any
    `at` error. `missing-format`, `missing-version` and `missing-wire` come
    before them too (0.11 ruling 5b).
15. **The keyword.** `at` is a keyword only in a `when` of a sequential pack,
    in the position the token order of ruling 11 gives it; on a text wire
    `when @t at` matches the text `at`.
16. **The fixed-window check is a check after the file,** like every other
    `at` error: a line `bogus` after a pack whose window is not fixed gives
    `unknown-directive`.
17. **Ruling 6 amends Version 0.8** ("Reading past the end of the input … is
    `malformed-wire`") for `when` lines only: a `when` past the end does not
    hold.
18. **The extent of a message kind** is the message, or `length … whole`; the
    innermost `length` block of ruling 7 concerns item kinds.

### Stated, not yet pinned by a vector

19. Ruling 9 for conversion (load vectors only).
20. Presence and `fx` bits not interacting with a window, and windows settled
    before the prediction of ruling 33 of 0.20: packs with `opt` or
    `presence` after a window load but are never encoded.
21. Ruling 5 with held keys in both overlapping windows.
22. `as` with `at` in item kinds (ruling 4 of 0.30, the implicit term per
    item), and a switch on an `as` key that a window binds.
23. A window of an item kind inside a group-body block, and an item kind's
    window ending past its last line (the load side is pinned at message
    level only).
24. The order of the `at` form check and the fixed-window check, both
    `bad-directive`.
25. **The `at` checks run last among the module checks:** after the
    `default` value checks and the `requires =` and `case` value checks, so a
    bad `default` value is reported before an `at` error.
26. **Overlapping windows and held bits** (ruling 5 with ruling 12): a window
    that writes its value makes its bits "bits of an earlier window", so a
    later window writes over them without a check. A window whose bits stand
    leaves them a held key's bits, so a later window that would change them
    is `transform-encode`.
27. **A line holding `at` with its tokens out of order** (`when 8 1 as k at 0`,
    `at 0 as k y`, `at 0 as`) is an `at` form error, with the timing of
    rulings 10 and 14, even where the misplaced token is `as`. A line with
    `as` and no `at` keeps 0.30's checks.
28. **The key on a line whose token order is broken** (ruling 27) is not
    read as a key: `when 8 1 as probe.nosuch at 0` is the late `at` form
    error, not `undeclared-key`. On a line in the right order whose offset
    alone is bad (`at +8 as k`), the key is read and checked first
    (ruling 10, load vector 3341).
29. **A third token that is neither `at` nor `as`** (`when 8 1 x at 0`) stays
    the argument-count line check of ruling 23 of 0.20.
30. **`at` on a pack that is not `layout sequential`** (a fixed `bits`
    layout, `json`, any other wire) is an `at` error like the others, with
    the late timing of rulings 10 and 14: a pack with no `distribution` line
    and `when 0:0:8 1 at 0` on a fixed layout is `missing-distribution`.

## Not in this version

- A look-ahead past lines of variable width.
- `at` on a fixed layout, where every `when` is already positional.

# Version 0.93: a controlled pack is in no licence profile

Status: Written. Version 0.29 takes the profile of a pack and of a module from
its licence and the licence table alone. A pack whose own `distribution` line
says `controlled` (0.4), under a licence that the table calls public, is then
in a profile and loads under it. A profile is a promise about what may be
passed on, so this version puts a file in a profile only when the file itself
says that it is public.

It adds no directive, no option and no error kind. It amends, in 0.29: 2a to
2c, "Two lines are read" in 2b, 3a, and "every earlier result holds" for files
that do not hold the exact line of ruling 1; in 0.23: the default of
`--max-distribution` beside a profile; in 0.4: the distribution limit.

## Rulings

1. **Shown public.** A module file or `pack.def` is **shown public** when it
   was read as UTF-8, at least one of its lines, cut and trimmed as ruling 1
   of 0.29 says, is exactly `distribution`, one or more spaces or tabs, and
   `public`, and no line is a **doubtful** one. A line is doubtful when, with
   every double quote in it removed and then spaces, tabs and carriage returns
   removed at its ends, it begins with `distribution`, and it is not that exact
   line (with its quotes). So `"distribution" controlled`, `distri"bution" x`,
   `distribution"controlled"` and `distribution # x` are doubtful. A file that
   holds a NUL byte, a U+FEFF, or a carriage return that is not directly before
   a line feed or at the end of the file, anywhere, that has no such line, or
   that is not UTF-8 or cannot be read, is not shown public.
2. **The profile.** A file that is not shown public has the profile none,
   whatever its licence and the table say. Through 2b and 2c of 0.29, so has
   every module and pack that uses it, and with a `core` that is not shown
   public, and whose `module` line 2b reads, every pack. With a profile, a module
   file that 2b gives no name is **not loaded, also when it is shown public**
   (`module mx # note`, `module "mx"`), and a pack or module that uses it is
   `unknown-module`, as any pack that uses a module that is not loaded: by 2b
   its `uses` finds no module, so nothing of the module's licence would reach
   it. `core` is no exception: with such a line it is not loaded, and a pack
   that uses it is `unknown-module` (as for a `core` that cannot be read). With no profile nothing changes
   (ruling 7). For a tool (ruling 8) such a module file has the profile none,
   and so has a pack or module with a `uses` line whose name no module file
   has.
3. **The order of reading** stays that of 0.29: the licence of a module or
   pack is read first, so `bad-licence` comes before the skip, and the checks
   of a `--packs-only` name come before both.
4. **What is skipped is skipped** as 3c to 3e of 0.29 state: the module is not
   loaded, the pack is not otherwise read, so its own load errors
   (`missing-distribution` among them) are not reported. `--packs-only` with
   such a name skips it, without an error. A pack whose `uses` line 2b does
   not read and that names a skipped module is `unknown-module`.
5. **A profile sets the limit.** With a profile, the distribution limit of 0.4
   is `public`, without a message also when the caller asked for `controlled`.
   A file that reads as controlled when it is loaded is `distribution-refused`
   and the load fails, as any load failure. By ruling 2 that is only a file
   that changed after it was read for its profile; an engine that reads each
   file once and loads the bytes it checked cannot meet it, and tests the
   refusal with a hook of its own.
6. **An engine in a program.** The limit of ruling 5 is the engine instance's
   from the load with a profile on: its limit is the lower of `public` and what
   a caller sets before or after, so a controlled text loaded directly later
   is `distribution-refused`. A load with a profile on an instance that
   already holds a controlled module or pack is `distribution-refused` before
   anything is read. The order: a profile name that is none of the three is
   `bad-licence` first; then that instance check; both refuse with the limit
   unchanged and leave no trace. Then the limit is `public`, and stays so when
   the load fails later, so what it loaded before it failed stays within it. Setting
   `controlled` afterwards is no error and has no effect. A later load with no
   profile is bounded by the limit, not by the profile.
7. **No profile asked for:** nothing here is read and nothing changes, except
   by `licences`, which reads every file as 4c of 0.29 says and lists a pack
   that is not shown public with the profile `none`.
8. **The tools.** `tools/licences.py`, and every tool that chooses packs or
   modules by a profile, give the same profiles: a tool does not load what it
   chooses, so ruling 1 is all that stands there. For a tool a pack or module
   with a **doubtful** `uses` line also has the profile none: a line that,
   with every double quote removed and then spaces, tabs and carriage returns
   removed at its ends, begins with `uses`, and that 2b does not read. In an
   engine such a line is not looked at: a pack whose line names a skipped
   module is `unknown-module` (ruling 4). `tools/licences.py --check` refuses a
   `model/*.def` or a `packs/*/pack.def` that is not shown public or has a
   doubtful `uses` line.

## Until an engine has this version

`--max-distribution public` beside `--profile` refuses every controlled file
in an engine. It does nothing for a tool that packages by profile.

## Vector additions

Tool vectors from 139. A file that is not shown public never stands in the
repository as a file: a vector carries it in its `files` member
(`spec/vector-format.md`). A
controlled pack under each of three public licences and each profile; a
controlled module under a public licence and a public pack that uses it,
directly and through another; a `core` that is not shown public; each form of
ruling 1, the carriage return between the words and before them, the quoted
word, the byte-order mark, a file that is not UTF-8, no line, `public` beside
a doubtful line; such a pack with a bad licence file; a quoted `uses` of a
skipped module; a skipped name in `--packs-only`; `licences` with and without
a profile and with `--json`; `--max-distribution controlled` beside a profile;
no profile. Ruling 6 needs a test in each engine's library, and ruling 8 a
test of the tools.

# Version 0.46: five-character track numbers

Status: Written. Many track and unit identifiers are written as a short
string of characters, often five, from a restricted alphabet. Each position
may have its own alphabet: letters and digits in the leading positions,
digits only, or a smaller digit range, in the rest. Binary messages pack each
character as a code of a few bits. Text messages write the characters.
Version 0.15's `chars` takes one character set for every position. It cannot
state a different alphabet per position, nor the identifier as a number.
Version 0.46 adds pack-defined character sets and three transforms over a
sequence of them.

The rules are general: any number of positions from 1 to 16. A five-position
identifier is the common case and the examples use it. No alphabet is fixed
by this specification. A pack states the alphabets its format defines.

## Grammar

```
charset  <name> <characters> [<width>]    # pack-wide: the characters in code order
field    <key> <locator> code:<set>,<set>,…        # bits: yields string
field    <key> <locator> codestr:<set>,<set>,…     # text wires: yields string
field    <key> <locator> codenum:<set>,<set>,…     # bits and text wires: yields int
```

- **`charset`** is a pack-level line, before the first `kind`, repeatable,
  one name each. It may stand before the `wire` line, as `kind` and
  `default` may (ruling 14).
  - `<name>` is one or more of `A`–`Z`, `a`–`z`, `0`–`9`, `_` and `-`
    (ruling 7).
  - `<characters>` is one or more characters from 0x21 to 0x7E, all
    distinct, in code order: the first has code 0. `"` is not for use
    in a set: 0.11 does not rule a quote inside a token, and no vector has
    one. A `#` needs double quotes only at the start of the token, where it
    would begin a comment (ruling 1 of 0.1.1; ruling 9).
  - `<width>`, on `bits`, is the bits per character. It defaults to
    `max(1, ⌈log2(size)⌉)`, where `size` is the number of characters; a
    given width is at least that and at most 8 (ruling 8). On other wires it
    is ignored entirely, its range check included (ruling 14).
- **Positions.** The list after the transform name names one set per
  position, first position first, 1 to 16 positions. One set may be named at
  several positions (`code:L,L,D,D,D`).

## On `bits`: `code` and `codenum`

The field's `len` is the sum of the positions' widths. The field is read as
one unsigned integer of `len` bits, as `uint` reads it at that place in the
pack's bit order (after `swap`). Position 0 is its most significant `w_0`
bits, position 1 the next `w_1` bits, and so on; the last position holds the
least significant bits. The order does not depend on the bit order: the first
character written is at the top of the number (ruling 6). `len` is at most 64.
A position's value is the character's code.

- **`code` decode.** Each code is looked up in its position's set. A code at
  or beyond the set's size is `transform-decode`. The value is the
  characters, first position first, always one per position.
- **`code` encode.** The text has exactly one character per position, each
  in its position's set; otherwise `transform-encode`. Each code is written
  in its position's bits.
- **`codenum` decode.** The value is the mixed-radix number of the codes,
  first position most significant: `v = c_0`, then `v = v × size_i + c_i`
  for each later position. A code at or beyond its set's size is
  `transform-decode`.
- **`codenum` encode.** The integer `x` is split into codes by the reverse
  of that rule, last position first. An `x` below 0 or at or above the
  product of the sizes is `transform-encode`.

## On text wires: `codestr` and `codenum`

`codestr` and `codenum` are valid on `xml`, `json`, `geojson` and `text`. The
text is read as the wire reads a field. On `json` and `geojson` the member
must be a string, otherwise `transform-decode`, and encode writes a string,
`codenum` included (ruling 11). On a `text` column, `codenum` is not one of
0.10's numeric transforms: a column's leading spaces are kept (and refused),
and padding is with spaces on the right (ruling 14). On `text`, a set used by
`codestr` or `codenum` must not hold the record's delimiter, or `*` under
`checksum nmea` (ruling 12).

- **Decode.** The text has exactly one character per position, each in its
  position's set; otherwise `transform-decode`. No character is trimmed,
  case is compared exactly, and a shorter text is refused (ruling 3).
  `codestr` yields the text; `codenum` yields the mixed-radix number of its
  codes, as on `bits`.
- **Encode.** `codestr` checks the text as decode does
  (`transform-encode`). `codenum` writes the characters of `x`'s codes, all
  positions included.

## Where the rules apply

| Construct | Rule |
|---|---|
| wires | `code` on `bits` only; `codestr` on `xml`, `json`, `geojson`, `text`; `codenum` on `bits` and those four. `protobuf`, `tlv` and UPER locators: `bad-directive` |
| layouts | `bits` fixed and sequential; a field with a bit length in a UPER pack, as for the 0.15 transforms (ruling 27 of 0.19) |
| bit orders, `swap` | the field is read as `uint` reads it, under all three orders and with `swap` |
| `absent` (0.9) | on `bits` the raw value of the whole field as `uint` reads it (`len` ≤ 64), before any lookup; on `xml`, `json` and `geojson` the text. On `text` `absent` stays `bad-directive` (ruling 16 of 0.10), `codestr` and `codenum` included (ruling 10) |
| `via` | sees the string or the integer the transform yields |
| `default`, kinds, groups, gates | no special rule |
| `armor sixbit` (0.14) | valid |
| model keys | `code` and `codestr` yield `string`, `codenum` yields `int`. Two formats convert an identifier when they map it to the same key, as for any value |

## Load errors

| Error | Cause | When it is checked (ruling 5b of 0.11) |
|---|---|---|
| `bad-directive` | `charset` with other than two or three arguments | step 3 |
| `bad-directive` | a `charset` name outside its grammar; a set with a repeated character, a character outside 0x21 to 0x7E, more characters than `2^width`; on `bits`, a width outside its range (ruling 8); a second `charset` of one name; `charset` after the first `kind`; on `text`, a set used by `codestr` or `codenum` that holds the delimiter, or `*` under `checksum nmea` | after the file is read |
| `bad-directive` | a transform naming a set no `charset` declares, no position or more than 16; a `bits` field whose `len` is not the sum of the widths, or is above 64; `codenum` whose product of sizes is above `2^63` | after the file is read (the set names need the whole file) |
| `bad-directive` | a transform on a wire that does not take it (above) | after the file is read, with the checks that need the wire (ruling 10 of 0.10) |

`charset` is added to a pack's directives in ruling 5b of 0.11. In a module
it is `unknown-directive`.

## Rulings for 0.46

1. **Code order is the pack's.** The first character of a `charset` has code
   0. Two packs that write the same characters with different codes declare
   different sets, and both read the same text.
2. **Unused codes.** On `bits`, a code at or beyond the set's size is
   `transform-decode`. With `<width>` larger than needed, the codes above
   the set are unused.
3. **Leading zeros are characters.** The text form always has one character
   per position. A position's code-0 character is written, never dropped,
   and a text that is shorter is `transform-decode`. In the `codenum` form a
   leading code-0 character adds 0, so the number does not show it.
4. **Case is exact.** `a` and `A` are different characters. A pack whose
   format accepts either case uses a `via` table, or declares both in a set
   with distinct codes.
5. **The string and the number are two keys.** A pack chooses the form its
   model key has. `codenum` on one format and `codestr` on another meet only
   if both map one key of one type. The number is of the pack's own codes
   (ruling 1), so it carries codes, not characters: two packs that declare
   the same characters in another order and map one integer key with
   `codenum` convert with no error and change the identifier. `01234` under
   `charset D 0123456789` is 1234; a pack with `charset D 9876543210` writes
   1234 as the codes 0, 1, 2, 3, 4 and reads them as `98765`. Formats that
   share an identifier as a number declare the same sets in the same code
   order, or map the text form, which keeps the characters.
6. **The most significant end first.** Sources print an identifier with its
   first character in the highest bits of the number. With `lsb` this differs
   from `chars` (0.15), which reads characters in bit order. `codenum` is the
   mixed-radix number of the codes; when every set is full (its size is 2 to
   the power of its width) it equals the field read as `uint`.

Rulings 7 to 14 settle the findings of the review of this version (finding
number in brackets).

7. **Set names** [41-1] are one or more of `A`–`Z`, `a`–`z`, `0`–`9`, `_`
   and `-`; anything else is `bad-directive` after the file.
8. **Width** [41-2]. The default is `max(1, ⌈log2(size)⌉)`. A given width
   is at least that and at most 8. A one-character set takes 1 bit, and
   code 1 is then unused (`transform-decode`).
9. **`#` and `"`** [41-3]. `#` needs quotes only at the start of the token
   (`charset S AB#C` loads, with 4 characters). What a `"` inside the
   token does is left unruled, as in 0.11.
10. **`absent` on `text`** [41-4] stays `bad-directive` (ruling 16 of 0.10),
    `codestr` included.
11. **`json` members** [41-5] must be strings, otherwise `transform-decode`.
    Encode writes a string, `codenum` included.
12. **Characters `text` cannot carry** [41-6]. On `text`, a set used by
    `codestr` or `codenum` that holds the record's delimiter, or `*` under
    `checksum nmea`, is `bad-directive` after the file.
13. **An empty set name** [41-8]: `code:L,,D` names a set no `charset`
    declares, `bad-directive` after the file.
14. **Placement, width and columns** [41-8]. `charset` may stand before the
    `wire` line. A width on a pack that is not `bits` is ignored entirely,
    its range check included. On `text` columns `codenum` keeps the column's
    leading spaces (and refuses them) and pads with spaces on the right.

15. **Parameters and sets are after-file checks.** 0.11 ruling 5b makes a
    transform's parameters a line check; for `code`, `codestr` and `codenum`
    the table above replaces it: every error of their list, an empty list
    (`code:`) and a second colon (`code:D:x`) included, is `bad-directive`
    after the file is read. The values of an `absent` option stay a line check
    (step 10 of 5b): they need no set. A `charset` error is raised with the
    checks that need the whole file, before `missing-distribution`.
16. **Place of `charset`.** It stands at the top level of the pack, before the
    first message `kind`. Inside a block, a group body included, it is
    `bad-directive` after the file.
17. **Width** on `bits` is plain digits; `+4` is `bad-directive`. On another
    wire any third token is ignored (ruling 14).
18. **`cbor` (Version 0.28)** takes none of the three: `bad-directive`.
19. **`absent` and `codenum`.** The sentinel is the raw number, not the
    `codenum` value. A held value whose bits equal the sentinel is written
    (0.9) and decodes as absent.
20. **The largest product** is 2^63: the greatest `codenum` value is then
    2^63 − 1.

21. **A bare `code`, `codestr` or `codenum`** without a colon is an empty list
    (ruling 15): `bad-directive` after the file.
22. **`absent` on `json` and `geojson`** keeps 0.9 unchanged. The sentinel is
    compared as text before ruling 11's check, so `absent 5` matches the
    member `"5"` and the number 5, and `absent =5` both too. An absent key
    writes the number 5 for `absent 5` and `"5"` for `absent =5`.
23. **`geojson` coordinates.** `codestr` and `codenum` on a `geometry.*`
    locator are `bad-directive` after the file. Inside a group body such a
    locator is a member path (0.9 ruling 25) and loads.
24. **Widths and places.** A width may have leading zeros (0.11 ruling 2c). The
    `2^width` limit on the number of characters applies on `bits` only (ruling
    14). A `charset` after a group with item kinds, before the first message
    `kind`, loads. The limit of 2^63 applies on every wire.

### Stated, not yet pinned by a vector

25. `null` as a `geojson` member under `codestr` or `codenum`: 0.1 has no rule
    for it, and this version adds none.
26. `code` under `msb-lsb` with a `len` that is not a multiple of 8, for
    conversion; `stop` and `until:` with `code` (`bad-directive`, 0.22).

## Vector additions

- `conformance-charset-bits`: a five-position field with two sets of different
  widths; decode, encode and round trip; an unused code (`transform-decode`);
  a text with a character outside its position's set (`transform-encode`);
  `codenum` of the same field, at 0 and at the largest value; one past the
  largest (`transform-encode`).
- `conformance-charset-text`: `codestr` on `json` and on `text`; a four-
  character text (`transform-decode`); a lowercase letter where only
  uppercase is in the set; `codenum` on `xml`.
- By finding:
  - [41-2] `charset Z 0`, `code:Z,Z` on a 2-bit field: bits `00` give
    `"00"`; any pattern holding a 1 is `transform-decode`;
  - [41-5] `json` `{"id":12345}` under `codestr:D,D,D,D,D`:
    `transform-decode`; `codenum` encode writes `"12345"`;
  - ruling 6: one identifier of sets of 5, 5, 3, 3 and 3 bits under `msb`
    and under `lsb`, with the same characters from the same number;
  - ruling 5: `conformance-charset-order-num-a` and `-b`, the sets `ABCD`
    and `DCBA` under `codenum`: one number, two texts, no error.
- Load vectors:
  - [41-1] `charset A,B 0123`: `bad-directive`;
  - [41-3] `charset S AB#C` loads with 4 characters;
  - [41-4] a `text` pack with `field k 1 codestr:L,L absent AA`:
    `bad-directive`;
  - [41-6] delimiter `,` and `charset P A,B` used by `codestr:P`:
    `bad-directive`;
  - every other row of Load errors.

## Not in this version

- A text form that omits leading code-0 characters, or pads with spaces.
- An identifier whose positions change alphabet depending on another
  position's value.
- Check characters computed from the others.
- Sets shared between packs. A `charset` is declared per pack, so related
  packs repeat their tables; packs share nothing by design.

## Why this rule

Short identifiers with a different alphabet per position are common in
tracking and reporting formats, both packed into bits and written as text.
They need to convert between the two forms exactly, leading zeros included.
`chars` covers one alphabet. A per-position list of pack-declared sets
covers these identifiers with no alphabet fixed in the specification. A
format's own table stays in its pack, and a restricted format's table stays
in its overlay. The number form serves formats that carry the same
identifier as an integer.

# Version 0.64: one text token split into coded fields

Status: Written. A text place often holds one token made of parts: a type code
whose second part is an affiliation letter and whose third is an environment
letter. Today the whole token is one field. This version binds single parts of
it to keys, in both directions, each through its own table.

```
field  <key> <locator> part:<sep>:<n>  [via <table>]  [unlisted]
const  <locator> part:<sep>:<n> <text>
```

Valid on `xml`, `json`, `geojson` and `text`. The **token** is the text of the
place, read and written as `string` reads and writes it there. Its **parts**
are the pieces between `<sep>` characters, numbered from 0; empty parts count,
and an empty token has one part, the empty text. The lines with one locator
(as text) in one reading scope (common lines plus one kind; one group body
likewise) form a **part group**, with one `<sep>`. The group may also have one
**whole line**: `field <key> <locator> string`, without options but, on
`text`, `optional`.

`<sep>` is as for `tokens` (Version 0.18); `<n>` is 0 to 255, without leading
zeros. `part` yields `string`, and `via` then `typemap` see its text.

## Decode

An absent place leaves every key of the group absent. Otherwise the whole
line's key holds the token, and for each part line:

- a `const` part that is missing or differs is `transform-decode`;
- a field whose part is missing is `transform-decode`;
- a part with no entry in its `via` table is `transform-decode`, or with
  `unlisted` the line counts as one whose place is absent;
- parts that no line names are ignored.

## Encode

1. When the entity holds the whole line's key, its text (after `typemap`) is
   checked and written. Every `const` part must be there and equal. For every
   part field whose key no other line of the scope maps: the part must decode
   by the rules above, and when the entity holds the key, to that value; a
   line that `unlisted` leaves absent needs the entity not to hold the key.
   Anything else is `transform-encode`.
2. Otherwise, when the entity holds a key of a part line, or every part field
   has a held value or a `default`, parts 0 to the highest `<n>` are written,
   joined by `<sep>`: each the text of its `const` or of its field (its held
   value, or its `default`). A field with no value, a value with no table
   entry, and a text that holds `<sep>`, are `transform-encode`.
3. Otherwise a `default` of the whole line's key is checked and written as in
   step 1; without one nothing is written, the `const` parts included.

## Load errors

`bad-directive`: a separator or `<n>` outside the rules; two part lines of one
group for one part; a number from 0 to the highest `<n>` that no part line of
the group names; a group with no part `field`; two separators in one group; a
second whole line; a whole line and a part line of one key; or any other
`field`, `const`, `when` (`present` included) or `group` on the group's
locator; `unlisted` without `via`, on another
transform, or twice; any field option but `via`, `unlisted` and, on `text`,
`optional`; `also` after a part line; `part` on another wire, a column, a pair
or `geometry.*`; on `text`, a `<sep>` that is the delimiter, or `*` under
`checksum nmea`; a const text that is empty or holds `<sep>`. A key that is
not `string` without a `via` is `key-type-mismatch`.

## Rulings for 0.64

1. **The whole line is how parts survive.** Without it the parts that no line
   names are lost, and a token of which `unlisted` left a key absent cannot be
   written again (`transform-encode`; with every key absent, nothing). A pack
   that must carry such tokens maps the whole token too.
2. **No silent change.** A whole text that disagrees with a held part key is
   an error, never a choice between them. A whole key is not a private copy:
   when another format sets it (`type`), its text must fit this pack's parts,
   and a consumer that edits a part key must drop or edit the whole key. A
   key that only this pack maps avoids the first. A key with another line in
   the scope is left to the order of lines (0.6) and not checked.
3. **Tables** (amends 0.6 for part lines): a value with no entry never passes
   through a `via` table, in either direction, whatever the types. `typemap` on
   the key `type` keeps its own rule, a code without an entry passing, on a
   part line and on a whole line. `unlisted` is for decode.
4. **`const … part`** (amends 0.6): it is checked on decode, after kind
   selection, and its failure is never forgiven by another line of a key. A
   place that `string` cannot read is a failure of each of its lines, the
   const lines included. It
   has three arguments; `const <locator> part:-:1` with two is a const of 0.6.
   Its text follows 0.6, always written as text: a leading `=` is taken off
   and a bare `present` is `bad-directive`. On `text` the const value rules of
   0.10 hold as well.
5. **Failed lines.** A missing part is a failed transform (0.6 ruling 5), a
   missing table entry a failed table (0.7 ruling 10).
6. **Gaps** are checked for the common lines with each kind, or alone when
   there are no kinds.
7. **Empty parts** decode and encode as the empty text. An empty token is
   written as `string` writes the empty text at that place; where the wire
   reads that back as absent, it decodes absent.
8. **Position.** The token is written where the group's first line stands (0.9
   ruling 23). On `text` "every const writes" (0.10) yields to step 3.
9. **`token` (Version 0.57)** is a one-way derive function, numbered from 0
   too. It leaves a missing part absent, where a part line refuses it. Its
   `*` table entries, if a table has them, are entries here; a pass-through
   text that does not read as the key's type is `transform-decode`, with
   `unlisted` too.
10. **Amends 0.18 ruling 9:** the separator names apply to `part`.
11. **When the checks run** (0.11 5b): the parameters of `part`, on `field` and
    `const`, are a step 7 check, a repeated `unlisted` step 9; everything else
    is a check after the file, and the key's type in the order of 0.4.
12. **Kinds.** A kind cannot be chosen by a part on decode. On encode,
    `requires` on a bound key or on the whole key remains.
13. **Items.** In a group body "the entity" is the item; an item of which
    nothing is written is an item without a value (0.7 ruling 11).
14. **`model_keys`** lists the whole and the part keys in line order. A place
    that a part group maps is never residue.
15. **`optional`** on `text`: a field that a const part addresses is never
    removed (0.10 step 5 needs every line to carry it).
16. **`geojson`** members that are numbers are not pinned by a vector: 0.1's
    rule for `string` there applies.

17. **`const .`** in a scalar item stays `bad-directive` (0.7 ruling 18), with
    `part` too.
18. **Another line** in Encode step 1 is any other line of the scope that maps
    the key, a second part line of the same group included.
19. **Per scope.** "A group with no part `field`" is checked like ruling 6: a
    common const part with a kind that adds no part field is `bad-directive`.
20. **`geometry.*`** inside a geojson group body is a member path (0.9 ruling
    25), so `part` loads there.
21. **Held** in step 1 excludes a `default`.

22. **Compared as values.** "To that value" in Encode step 1 compares numbers
    as numbers: -0 equals 0.
23. **`tlv` and `cbor`.** A `part` with malformed parameters on a `field` is
    an after-file check there (0.13 ruling 8, 0.28 ruling 25). On a `const`
    with three arguments the check is a line check on every wire. A `const`
    has three arguments only when the text of its second up to the first `:`
    is `part`.
24. **The whole line with other options.** A `string` line on the group's
    locator with any option other than `optional` on `text` is "any other
    `field`".
25. **Only `field` lines** of the scope are "another line" (ruling 18).

26. **A missing table entry beside another line of the key** (settles 0.7
    ruling 10 with 0.6 ruling 4, on every wire). A line whose transform
    succeeds and whose `via` table has no entry for the value, the two types
    differing, fails the decode whichever line of the key succeeds, and
    whether that line stands before or after it. Where the types are the same
    the value passes through (0.6), so the line succeeds and the earliest
    line's value is kept. Pinned by `conformance-twolines-*`.

### Stated, not yet pinned by a vector

27. Ruling 9 (Version 0.57 is not built), ruling 14 for `model_keys`, ruling
    16, ruling 17, ruling 18 for a second part line, and ruling 13 for a
    scalar item on `xml`.

## Not in this version

- A table keyed on several parts, or on the longest matching prefix.

# Version 0.32: time hygiene in core

A change to `core`: it took the merge slot, carries ADR 0005 ("Time hygiene in
core, on two axes, never invented"), and every consumer was re-measured on its
branch before merge (AGENTS.md rule 9).

Status: Written. `core` 0.3.0 gains five keys for the second axis of goat's time
hygiene and for attestation, beside `time_error_ms` and `time_state` (core
0.2.0). No engine changes: the keys are ordinary model keys, and the one rule
below is checked in CI by `tools/time-quality-guard.py`, not by the engines.

## The two axes

goatcore ADR 1037 (`docs/adr/1037-fabric-internal-time-synchronization-first.md`):

- line 34: "**Internal coherence** — is this node locked to the fabric ensemble
  within a bounded synchronization error?" Core 0.2.0 carries it:
  `time_error_ms` (the coherence error bound) and `time_state` (`coherent`,
  `drifting`, `free-running`).
- line 35: "**UTC confidence** — how well is the ensemble anchored to true UTC,
  and how fresh is the last anchor?" This version adds it.
- line 37: "A node can be **internally-coherent but UTC-unknown** — the correct
  and common state for denied-edge operation — and that must read as *fully
  healthy for fabric ordering*, degraded only for UTC-bound operations."

In the model that state is `time_state = coherent` with `time_utc_state =
unknown`, and it is a normal state: no key of one axis constrains a key of the
other.

## The keys

`core` 0.3.0 adds, after `time_state`:

| Key | Type | Unit | Values / meaning |
|---|---|---|---|
| `time_utc_state` | string | - | `confident` or `unknown` |
| `time_utc_error_ms` | float | ms | one-sigma uncertainty of the offset from UTC, 0 or more |
| `time_anchor` | string | - | `gnss`, `peer_nts`, `wan_nts`, `orphan` or `none` |
| `time_anchor_age_ms` | int | ms | time from the last external anchor to the report's `time_ms`, 0 or more |
| `time_attested` | int | - | 1: a signed attestation backs the time quality; 0: the source states it is not attested |
| `time_attestation` | string | - | `ntp-attest-v1:<valid_until_ms>:<host_id>` |

Where the names come from (goatcore, verbatim):

| Key | Source |
|---|---|
| `time_utc_state` | `docs/design/time-hygiene-trusted-time.md` line 242 `UT -->|fresh anchor| G2["🟢 UTC-confident"]` and line 243 `UT -->|anchor stale| A2["🟡 UTC-unknown<br/>(still 🟢 for ordering)"]`: the two labels, lowercased, the axis name dropped. goatcore states no enum. A UTC confidence that is decaying ("UTC-confidence decays honestly", line 158) is `confident` with a growing `time_utc_error_ms` and `time_anchor_age_ms`, until the source calls it unknown. |
| `time_utc_error_ms` | `docs/design/time-quality-attestation.md` line 55: "`sigma_us` \| uint64 \| Best-case 1σ uncertainty in microseconds at this emission's timestamp" (the design document of goatcore ADR 0514), here in milliseconds |
| `time_anchor` | `ops/time-hygiene/internal/state/state.go` lines 36-40: `SourceGNSS    SelectedSource = "gnss"`, `SourcePeerNTS SelectedSource = "peer_nts"`, `SourceWanNTS  SelectedSource = "wan_nts"`, `SourceOrphan  SelectedSource = "orphan"`, `SourceNone    SelectedSource = "none"`; JSON tag `selected_source`, line 62 |
| `time_anchor_age_ms` | `docs/design/time-quality-attestation.md` line 57: "`seconds_since_external_lock` \| uint64 \| Convenience: monotonic seconds since `last_external_lock_at`", here in milliseconds |
| `time_attested` | `crates/goat-cli/src/health_wire.rs` line 202: `pub attested: bool,`; lines 177-178: "color is the 5-state honesty signal, attested=false reads idle (never a false green)." |
| `time_attestation` | `ops/time-hygiene/internal/attest/attest.go` line 29: `const Alg = "ntp-attest-v1"`; signed fields `host_id` (line 37) and `valid_until` (line 44) |

### Meanings settled

1. **`time_anchor` and the per-emission envelope.** A source that states the
   envelope's `source` (time-quality-attestation.md line 54: `gnss_locked` /
   `nts_verified` / `chrony_steered` / `peer_attested` / `self_clocking`) maps it:
   `gnss_locked` → `gnss`, `nts_verified` → `wan_nts`, `peer_attested` →
   `peer_nts`, `self_clocking` → `orphan`; `chrony_steered` names no anchor and
   leaves `time_anchor` absent.
2. **External anchors** are `gnss`, `wan_nts` and `peer_nts`. `time_anchor_age_ms`
   is the age of the last of those, measured to the report's `time_ms`; with
   `time_anchor` `orphan` or `none` it is absent unless the source states it.
3. **`time_attested` = 0** only when the source states "not attested"; a source
   that says nothing leaves it absent (shared-model.md, flags). 1 without a
   `time_attestation`, and an attestation whose `valid_until_ms` is before the
   report's `time_ms`, are both carried as stated; judging them is the consumer's.
4. **`time_attestation`** is the text `ntp-attest-v1:`, then `valid_until` as
   decimal epoch milliseconds, then `:`, then the `host_id` as it is (the rest of
   the text, which may hold `:`). An engine never parses it.
5. **Units.** A pack converts with the exact-factor transforms of Version 0.15
   (`uiscale:1/1000` for microseconds to milliseconds on an `int`, `scale` on a
   text wire) and their rounding; a value outside the key's range is
   `transform-decode`, as 0.15 states.
6. **Context** is stated time quality: a caller that passes these keys as
   context (Version 0.6) states them.

## The rule: a pack never invents time quality

`tools/time-quality-guard.py` (run in CI on every pack and module) refuses, for the eight
time-quality keys `time_error_ms`, `time_state`, `time_utc_state`,
`time_utc_error_ms`, `time_anchor`, `time_anchor_age_ms`, `time_attested`,
`time_attestation`, written bare or with `core.`:

- a `default` line on one of them, in any pack;
- a `derive` line whose target is one of them, in any model module, `core`
  included;
- a `const` line, or an `absent` option, on a field of one of them;
- on a `bits` wire, a field of one of them that is neither `optional` nor inside
  a presence-gated block (`if`, `opt`, `chain` part, or an FSPEC/presence bit),
  so an absent key is never written as zero bits.

Engines are unchanged: they load such a pack as before; the check keeps it out of
the repository. A pack in another repository that does these things is outside
the guarantee; its `pack.md` says so.

## Loss

A conversion into a format that cannot carry a key the entity holds loses it. The
capability report (ruling 6 of 0.11) lists the key as one the target does not
map; once Version 0.30's loss report merges, it names the key per conversion.

## Vectors

`packs/conformance-time-hygiene` (`json`, the eight keys, no default and no
sentinel):

- `01`: every key round-trips, and the attestation's `host_id` `fd00::1`, which
  holds `:`, comes back byte-exact;
- `02`: coherent but UTC-unknown, nothing else stated;
- `03`: only the coherence axis;
- `04`: nothing stated, nothing written;
- `05`: stated not attested (`time_attested` 0) with `time_anchor` `none`.

`tools/tests/test_time_quality_guard.py` covers each refused form, bare and
`core.`-prefixed, an `optional` and a gated `bits` field that pass, and the whole
repository.

---

# Version 0.34: a message of another pack inside a field

Status: Written. Some binary formats are transports: their own fields are a
header, and the rest of the message is a whole message of another format,
which the transport frames but does not describe. Before 0.34 a pack for the
transport could only copy the other format's field lines into its own kinds,
or leave the payload unread. Version 0.34 lets a `layout sequential` pack
hand a run of its bytes to another loaded pack, which decodes them into the
same entity and encodes them back from it.

It reads **one** inner message. A run of inner messages, one after another in
the same extent, is not read: bytes after the first message are
`malformed-wire` (Decode, step 3), and encode writes one message. With
`partial` decode ignores those bytes, and they do not come back on encode. A
format whose payload may hold several messages cannot be carried whole by this
version.

```
wire    bits
layout  sequential
…
length 8 bytes
  inner  <format> [partial]   # the bytes to the end of the extent are one <format> message
end
```

## The `inner` line

`inner <format> [partial]` is a line of a `layout sequential` `bits` pack (Version
0.8). It names the **inner pack**; the pack holding the line is the **outer
pack**. The **inner input** is every byte from the cursor to the end of the
line's enclosing extent (Version 0.21: the innermost `length` block around
the line, or else the message, which a `length … whole` ends at its stated
length, ruling 14 of 0.21).

Where it may stand:

- in the common lines, in a kind, and inside `length` blocks, at any depth
  of `length` blocks;
- nowhere else: under a `group`, `if`, `opt`, `chain`, `switch`, `case`,
  `ext`, `alt` or `choice` block, at any depth, it is `bad-directive`;
- it is the last wire line of its extent, as a `rest` group is: rulings 11,
  26 and 32 of 0.21 apply to `inner` as written for `rest`;
- at most one `inner` line lies on any reading path (ruling 33 of 0.21): an
  `inner` in the common lines and another in a kind, or two in one body, is
  `bad-directive`; one in each of two kinds loads;
- in a pack with `armor sixbit` (0.14) or `encoding uper` (0.19) it is
  `bad-directive`; `armor hex`, the default, is not armor in this sense.

Load order (5b and 5e of 0.11): `inner` takes one or two arguments, a
format name and the word `partial` (compared after quotes are removed); none,
or three and more, is the line check of 5e, and a second argument other than
`partial` is `bad-directive` after the file, with the block checks. It is a line that the `wire` line and `layout sequential` must
stand before (5b), with the same errors as the other lines of that list.
The block, path, last-line, armor and `encoding` checks, and `inner` in a
pack whose wire is not `bits` or whose layout is fixed (no `layout
sequential` line), run after the file is read, with the checks of ruling 25
of 0.5. Nothing about the inner pack
is checked at load: packs load in any order, and each loads alone.

## Reaching the `inner` line

The inner pack is looked up when decode or encode reaches the `inner` line,
not when the outer pack loads. A line that is not reached (in a kind not
selected, or after a failure of the wire that stops the decode) checks
nothing. A `transform-decode` does not stop a decode (ruling 9 of 0.1.1), so
an `inner` line after it is reached, and a failed check there is reported
ahead of that `transform-decode`. When it is reached,
these are checked in this order:

1. the inner format is loaded: otherwise `unknown-format` (a pack refused at
   load, by a build without its wire (0.24), a distribution limit or a
   licence profile (0.29), is not loaded);
2. the inner pack's wire is `bits` and it has neither `armor sixbit` nor
   `encoding uper`: otherwise `bad-directive`;
3. the inner pack has no `inner` line of its own and is not the outer pack
   (one layer only): otherwise `bad-directive`;
4. when the outer pack's `distribution` is `public`, so is the inner pack's:
   otherwise `distribution-violation`.

An engine that keeps parsed packs (0.25) may keep a lookup that succeeded;
one that failed is made again at the next use, so a pack loaded later is
found (ruling 1b of 0.25).

## Decode

When the cursor reaches `inner`, after the checks above:

1. The cursor must stand on a whole byte from the start of the message;
   otherwise `malformed-wire`.
2. An enclosing extent that ends beyond the input, or a `length … bits`
   extent that does not end on a whole byte, is `malformed-wire`.
3. The inner input is decoded as `decode(<format>, bytes)` by the inner
   pack's own rules: its `bit_order`, its layout, its kinds and its length
   rules. The inner pack is called also when the inner input is empty
   (ruling 7 of 0.8, a line at the end of its extent reading as absent, does
   not apply to `inner`). When the inner decode has selected its kind and
   read its lines, bytes of the inner input at or after the **inner message's
   end** (rulings 13 and 14) are `malformed-wire`, unless the line is `inner
   <format> partial`, which ignores them. Ruling 9 of 0.8 (input beyond the
   last line is ignored) and the fixed layout's acceptance of a longer input
   stay as they are for a message decoded on its own.
4. The keys of the inner entity join the outer entity under the rule of 0.6
   for one key at several locators: in one decode, the first value read in
   reading order, outer or inner, is kept, and no later line, outer or inner,
   replaces it. A list is one key: an outer list read first is kept whole,
   and the inner list of the same name is discarded.
5. `Entity.inner_kind` records the pair `(<format>, kind name)` of the kind
   the inner pack selected, next to the outer pack's `Entity.kind` (0.5). An
   inner pack with no `kind` line records nothing: `Entity.inner_kind` is
   absent.

An error raised in the inner decode keeps its kind and names the inner
format. An error that stops the decode (`malformed-wire`, `no-kind`, and a
failed check at the `inner` line), in either pack, is reported ahead of any
`transform-decode` read before it, as a later `no-kind` already is within
one pack; among `transform-decode` errors the earliest in reading order is
reported.

`max_items` (7a-7g of 0.11): the inner decode starts with the budget the
outer lines read so far have left, and its counts are checked against it
(7d). Items of an inner list discarded by step 4 are not counted (7g).

## Encode

When the encoder reaches `inner`, after the checks above, the cursor must
stand on a whole byte, otherwise `transform-encode`; this is checked before
the inner pack encodes. It then computes `encode(<format>, entity)` on the
same entity and writes the bytes at the cursor. An inner encode error keeps
its kind and stands at the `inner` line for the order of errors (ruling 12
of 0.20). The extent's length, where one is written, counts the inner
bytes; a length that does not fit its field is `transform-encode`.

The inner kind is selected by the first of these that holds:

1. `Entity.inner_kind` names the inner format;
2. `Entity.kind` names the inner format;
3. the inner pack's `requires` lines (0.5, 0.20).

`encode(<format>, entity)` at the top level (not as a layer) selects by
`Entity.kind` when it names the format, then by `Entity.inner_kind` when it
names the format, then by `requires`. The two orders differ on purpose: each
looks first at the record made for the place being written. A named kind the
pack does not have is `no-kind` (ruling 24 of 0.5), in both places.

A key mapped by both packs is written by both from the one value the entity
holds. Encode writes the inner message whenever the line is reached, also
when the entity holds none of the inner pack's keys: the inner pack then
selects a kind and writes its absent keys as it does at the top level.

## Conversion

`convert(from, to, …)` keeps `Entity.kind` when `from == to` (0.5), and also
when `to` has an `inner` line (any of its `inner` lines) naming the format
of `Entity.kind`. It keeps `Entity.inner_kind` when `from == to`, when it
names `to`, or when it names the format of any `inner` line of `to`.
Otherwise each is cleared before encode. So a message converted from an
inner format to an outer one and back, or from the outer to the inner and
back, keeps the inner message's kind. The inner bytes then come back as they
were when the extent holds one inner message and nothing after it, the inner
pack maps every bit it reads, and no key mapped by both packs held different
values in the two places (decode step 4 keeps one).

## Capability

`model_keys(<outer>)` (6a of 0.11) is computed when it is asked for, not at
load. Each `inner` line is taken on its own: a line whose pack passes
checks 1 to 4 above adds, at its place in reading order, the
entries of `model_keys(<format>)` not yet listed by the lines before it, in
their order; later outer lines add only entries not yet listed. List
entries of the two packs with one name are joined as 6b joins them. An
`inner` line whose pack does not pass the checks adds nothing, and
`model_keys` and the capability report do not fail because of it: the
failure is reported by decode and encode. An inner format and its outer
pack therefore carry every key of the inner format between them and drop
only the outer pack's own keys.

## Vectors

- A conversion vector's `model` may hold `"@inner_kind"`, the kind name
  `Entity.inner_kind` must hold after decode, and `"@absent"` may list
  `"@inner_kind"`.
- `expect_error` of a conversion vector may be `bad-directive` or
  `distribution-violation` for the checks made when the `inner` line is
  reached.
- Wherever packs are loaded for vectors (conversion, capability, the 0.25
  benchmark), a pack named by an `inner` line of a loaded pack is loaded too,
  from `packs/`, and so on for the packs loaded that way; a name with no
  directory under `packs/` is skipped (its use is then `unknown-format`).

## Rulings for 0.34

1. **Reduced builds (0.24).** An outer pack is on `bits`, so a build without
   `bits` refuses it. Ruling 1b of 0.24 (the same result in every build that
   loads the pack) does not extend to the checks made at the `inner` line:
   whether the inner pack is loaded may differ between builds. The
   reduced-build check runs no vector of an outer pack.
2. **Empty inner input.** The inner pack's result for no bytes: an error
   when it needs bits, or an entity (a `rest` list of no items, present and
   empty) when it reads none.
3. **A whole length.** A `length … whole` before the `inner` line ends the
   message extent; bytes of the input beyond it are not part of the inner
   input.
4. **No residue.** A `bits` inner message has no residue (the `bits` wire
   keeps none), so a layered decode adds none.
5. **One record.** `Entity.inner_kind` holds one pair. It is set by decode
   only, and a decode that reads no `inner` line leaves it absent.
6. **An empty input and kinds.** For an inner pack whose kinds have `when`
   lines, an empty inner input selects no kind: `no-kind`, by ruling 21 of
   0.5 (a `when` whose bits lie beyond the input does not hold), before any
   line is read.
7. **Counts of a discarded list.** An inner `count` is checked against the
   remaining budget when it is read (7d), whether or not step 4 later
   discards the list; "not counted" (7g) is about the items the decoded
   entity holds. A `count <n>` the pack states is not read from the wire,
   so 7d does not check it, and the items of a discarded list with such a
   count are not counted.
8. **`as` keys (Version 0.30) and an inner pack.** Packs are checked alone,
   so an outer `when … as <k>` whose key the inner pack also maps loads (the
   0.30 ban on a key named by `as` and mapped by a `field` in one reading path
   does not reach into the inner pack). Decode keeps the first value read
   (step 4); encode writes both from the one value.
9. **A `when … as` of the inner pack on encode.** When the entity's value of
   the key does not match the inner pack's `when`, the inner encode fails as
   0.30 states, and the error stands at the `inner` line (Encode). A layered
   encode can therefore fail where the inner pack's own round trip does not,
   when an outer line read first gave the key another value.
10. **A recorded inner kind and `as`.** A kind chosen by `Entity.inner_kind`
    or `Entity.kind` (Encode, steps 1 and 2) is chosen by the kind recorded on
    the entity in the sense of 0.30, so the implicit `as` term is not checked
    for choosing it.
11. **A look-ahead window (Version 0.33) and an `inner` line.** The lines a
    window may walk are an exhaustive list and `inner` is not in it, so an
    outer window that reaches an `inner` line is not fixed: `bad-directive`.
    A window that ends before the line is as 0.33 states.
12. **A look-ahead window of the inner pack.** The message of ruling 18 of
    0.33 is the inner input: kind start is counted from its first byte, and a
    window past its end does not hold, whatever outer bytes follow it.
13. The inner message's end, sequential layout. When the decode read a `length
    … whole` line, the length the message states (the field's value minus its
    `plus`), whatever the lines after it read, a `rest` group included; of
    several, the smallest. Otherwise the cursor after the last line read,
    rounded up to a whole byte. The bits left in the last byte are padding and
    are not checked (0.8). Content of a `length` extent that no line reads lies
    before the end (0.8). A message-level `rest` group in a message with no
    `whole` line reads to the end of the input, the padding of 0.21 included.
    In these three cases nothing is left over.
14. The inner message's end, fixed layout. The furthest bit, rounded up to
    a whole word, over: the common lines and the selected kind's lines
    outside any block, `when` and `const` lines and count locators included;
    the lines of the 0.17 blocks that hold on this input, and their gate
    locators; and the items of its groups. An `optional` line counts whether
    or not the input reaches it; a block that does not hold does not, and
    neither do its gate bits; a counted group counts up to its start also when
    it has no items (0.7 does not say whether a message on its own does, and
    this version does not change it). Every group counts in full, a list that
    step 4 discards included. A message none of whose counted lines has a bit
    ends at 0. An encoding this version writes for an inner message with at
    least one counted bit never has bytes left over; how long a message with
    none is on its own is not settled here.
15. An input that ends before the end leaves nothing over; whether it is an
    error is the inner pack's own rule (an `optional` line beyond the input).
16. An empty inner input leaves nothing over, with or without `partial`; its
    result is that of rulings 2 and 6. An inner pack that reads no bytes has
    its end at 0, so any byte is left over.
17. Error order. The check is made when the inner lines have been read, before
    the keys join (step 4). An inner error that stops the decode is reported
    instead of it; a `transform-decode`, in either pack, does not stop the
    decode (a `switch` on a key whose line failed does, ruling 35 of 0.20), so
    the check is made and its `malformed-wire` is reported ahead.
18. `partial` changes decode only. Encode writes the same bytes with or
    without it, so bytes it ignored do not come back. It does not change
    `model_keys`, the kinds kept by conversion, or where `inner` may stand.
    It has no meaning on another line: there it has the error, at the step,
    that an unknown word has today.
19. **After an inner `transform-decode`** the inner decode goes on (ruling 9 of
    0.1.1), and the keys whose lines succeeded join as step 4 states, before
    the outer lines after the block are read.
20. **Two outer groups of one list** (ruling 33 of 0.8) around an `inner` line
    are as 0.8 states between themselves: the later replaces the earlier. Step
    4 is about an outer list against the inner one: an inner list is discarded
    when an outer group gave the list before it, and one that is kept is not
    replaced by an outer group after it.
21. **A failed item of a discarded list.** A list is one key, whose value comes
    from the earliest line that succeeds (0.6), so a `transform-decode` in the
    items of a list that step 4 discards, outer or inner, is not an error. A
    failure of the wire in it is, and so is a `switch` there on a key whose
    line failed (ruling 35 of 0.20). A line whose transform succeeds and
    whose table has no entry, the types differing, is an error there too
    (ruling 4 of 0.6, ruling 10 of 0.7), in a discarded list as in a kept one.
22. **Counts of any discarded list.** Ruling 7 applies to a discarded outer list
    as to a discarded inner one. Counts nested in its items are each checked
    against the budget as it stood before the list: they do not accumulate.
23. **A key mapped by both packs whose line fails.** Rulings 4 and 5 of 0.6 and
    ruling 10 of 0.7 apply across the two packs as within one: a line whose
    transform fails is forgiven when another line of its key succeeds, outer or
    inner, whichever came first; a line whose transform succeeds and whose
    table has no entry, the types differing, fails the decode, also when the
    other pack gave the key.

## Not in this version

- A run of inner messages: more than one inner message in an extent, a count
  of them, or a list of them (an `inner` line in a group is `bad-directive`).
- A count in the outer pack that states how many units the inner message
  holds, compared with the inner message or with a count of its own. A
  `length` block states the extent in bytes or bits only, and a 0.21 `count`
  line still needs a group of its own pack.

# Version 0.52: a discriminator key the entity need not hold

Status: Written. With Version 0.30 a kind whose `when` line binds a key
qualifies on encode only when the entity holds that key. An entity from a
format that has no such key then qualifies for no kind, so a pack cannot bind
its discriminator in every kind and still be a target for other formats. This
version adds a word that relaxes the choosing rule for one line.

```
when  <len> <value>[,<value>…]  [at <offset>]  as <model-key>  [optional]
```

`optional` follows the key of an `as` (Version 0.30) on a `when` of a message
kind or an item kind, with or without `at` (Version 0.33). It changes the
choosing of a kind and nothing else.

## Encode

**Choosing the kind.** The implicit `requires` term of a kind's `when … as
<k> optional` line fails only when the entity holds `<k>` with a value that
the `when` does not match. It holds when the entity does not hold `<k>`.
Kinds are tried in pack order, as in Version 0.5.

**The bits written** are unchanged. Without `at`, Version 0.30 applies: the
held value, or the first listed value when the entity does not hold `<k>`.
With `at`, Version 0.33 alone applies: bits that match already stand.

Decode, a kind recorded on the entity or on the item, and `model_keys` are
unchanged.

## Load errors

`bad-directive`: `optional` that does not directly follow the key of an `as`;
`optional` twice; a token after it; `optional` on an `as` of a common `when`
(of the message or of a group body). Ruling 3 states when each is checked.

## Rulings for 0.52

1. **Amended rules.** Of 0.30: "only when the entity holds `<k>`" (Choosing
   the kind), "with a token after the key" (Load errors) and ruling 15. Of
   0.33: ruling 11 and the form in Load errors. The form is now `when <len>
   <values> [at <n>] [as <k> [optional]]`. Vector 07 of
   `conformance-whenas-json` stands: its line has no `optional`.
2. **Choosing looks at keys only** (Version 0.5). A window that settles to
   `transform-encode` (0.33) does not make the next kind be tried.
3. **When the errors are raised.** A third token that is neither `at` nor
   `as` is the line check of ruling 23 of 0.20, `optional` included (`when 8
   1 optional`). On a line without `at`, the errors of this version are raised
   with the `as` syntax checks (rulings 16 and 29 of 0.30), the one for a
   common `when` included. On a line that holds `at`, a wrong, repeated or
   misplaced token is the broken order of rulings 27 and 28 of 0.33 (late, key
   not read). `optional` on a common `when` in the right order is a late `at`
   form error whose key is read.
4. **The token after `as` is the key,** except `as` itself (ruling 31 of
   0.30): `as optional` and `as at` name keys. Such an `at` does not make the
   line one that holds `at`.
5. **Several `as` lines in one kind** each have their own term; one may be
   `optional` and another not. Every term must hold.
6. **Plain `requires` terms still apply.** `requires <k>` beside `as <k>
   optional` needs the key.
7. **What an entity holds** includes keys from the context and from
   derivations, as for `requires` (0.6). A `default` does not count (ruling 6
   of 0.30). For an item kind, the entity is the item.
8. **The order of kinds decides for an entity without the key.** The first
   kind all of whose terms hold takes it. A pack whose kinds have no other
   terms sends every such entity to its first kind; `requires` lines on the
   kinds' own keys tell them apart, the more specific kind first.
9. **A `switch` on the key** (ruling 19 of 0.30) selects by the bits written,
   for a kind's line as for a common one: an absent key selects by the first
   listed value, or with `at` by the settled bits.
10. **Layers (Version 0.34).** Encode sets no key. An outer and an inner pack
    cannot bind one key at an `inner` line: ruling 20 refuses it.
11. **Which check sees the line.** The third token decides first: `when 8 1
    optional at 0` is the line check. `when 8 1 as at 0` has the key `at` and
    a token after it (the `as` syntax check); `as at at 0` holds `at`.
12. **The word is exact:** `OPTIONAL` is another token, as `AS` is (ruling 22
    of 0.30).
13. **On a common line without `at`** the error comes before the key passes,
    so an undeclared key there is not reported.

14. **The first `as` only** (ruling 4). The token after a later `as` is not
    exempt: `when 8 1 as k as at` holds `at`, and its error is the late one.
15. **`at optional as k`** has `optional` out of place: the broken order, with
    the key not read. So have `at as as k` and `at at as k`: one of the words
    `at`, `as` and `optional` in the offset's place is never an offset alone
    bad (ruling 28 of 0.33), of which `+8` is an example.

16. **A held key under two windows** (amends rulings 5, 12 and 26 of 0.33;
    a window takes no bit away from a held key, so in ruling 26 a window that
    writes its value does not make bits that a held key wrote "bits of an
    earlier window"). The
    bits of a `when … as <k>` line of the kind, with or without `at`, whose
    key the entity holds count as bits that key wrote. A later window that
    would change one is `transform-encode`, as for a `field`. The bits of a
    line whose key the entity does not hold are not such bits by themselves:
    they are written over without a check, except a bit that a held key
    wrote. "Later" is the order of settling: windows
    settle after all lines are written, so a window is later than every plain
    `when … as` of its kind, wherever that line stands. Reason: otherwise the
    output decodes another value of a held key.
17. **`as k at 0` on a pack that is not sequential** is the late `at` error
    (rulings 27 and 30 of 0.33). Ruling 15 of 0.33 is about the
    text wires (`when @t at` matches the text `at`), not about this line.

18. **An empty counted group on a fixed layout** (settles 0.7, "The message
    length is extended by the items"). A `bits` group of a fixed layout that
    decode or encode reaches extends the message at least to the group's
    start, also when it has no items: a count locator that reads 0, an empty
    or an absent list (ruling 14 of 0.7), or `count 0`. Decode of a shorter
    input is `malformed-wire`; encode writes up to the start, with zero bits
    where no line writes. It holds in the common lines and the selected kind,
    for a group nested in an item, and for the `L` of 0.14.
    - It settles what ruling 14 of 0.34 leaves open for a message on its own;
      the inner message's end there is unchanged and agrees with it.
    - The length decode requires is the greater of the start and what the
      other lines require. An `optional` field, or a line of a gate block that
      does not hold, before the start does not lower it. Where the other
      lines already require as much, nothing changes.
    - An item whose empty nested group starts beyond `item <bits>` ends at
      that start; the next item begins there (ruling 4 of 0.7).
    - Such a pack loads when the nested count is a locator. A nested group
      with a fixed count, `count 0` included, that starts beyond the item is
      `bad-directive` (ruling 4 of 0.7).
    - A group in the body of a list with no items is not reached.
    - An absent list under `count 0` stays `transform-encode` (ruling 5 of
      0.7).

19. **No counted bit** (settles 0.5, "as many whole words as the furthest
    mapped or `when` bit reaches", with 0.17). A fixed layout none of whose
    counted lines has a bit on this input or for this entity has zero words:
    every line is in a 0.17 block that does not hold, or there is no line with
    a bit. Decode needs no byte, an empty input included; encode writes none.
    There is no smallest length of one word (ruling 14 of 0.34 leaves this to
    a message on its own; an inner message then ends at 0, as there). An `optional` field counts as it
    does in 0.6: not for what decode needs, and on encode it does, so a layout
    with only such a field writes it.

20. **A key both packs map is refused** (amends 0.34). When an `inner` line is
    reached, on decode and on encode, a fifth check follows the four of 0.34:
    no key that the outer pack's **lines in reach** map is a mapped key of the
    inner pack; otherwise `bad-directive`, at the `inner` line, naming the
    inner format. The lines in reach of an `inner` line in a kind are the
    common lines and that kind's lines. Of an `inner` line in the common lines
    they are the common lines and the lines of every kind, since the kind may
    be chosen after the line; one clashing kind then refuses every message
    that reaches the line. A pack without kinds has common lines only. Lines
    after the `inner` line count, and a line counts whether or not it is
    reached or its block is read: every block, every `case` and `else`
    included. For an `inner` line in a kind, lines of other kinds do not
    count. A key is mapped as 6a to 6c of 0.11, ruling 13 of 0.8 (`also`) and
    ruling 24 of 0.30 (`when … as`, with or without `at` or `optional`) state,
    in both packs; the mapped keys of the inner pack are its `model_keys`, all
    its kinds together, whichever kind is selected. Keys are compared as the
    entries of `model_keys` are, as exact text: a list both map (`rows[]`) is
    refused, an item key and an entity key of one name are two entries, and so
    are `rows[].sub[]` and `sub[]`. A key named only by `requires`, `with`,
    `default`, `switch`, a derivation or the caller's context is not mapped;
    count and presence names are not keys.
20b. **When the check is made.** Before the whole-byte test of the cursor and
    before any inner line is read or written, also when the line is `partial`
    and when the inner input is empty. A format that is not loaded and the
    other three checks of 0.34 come first. On decode it stops the decode. An
    error that stopped the decode before the line wins: a `malformed-wire`, an
    item limit, a `no-kind` (of a common `when`, an item or a `switch`), and
    the `transform-decode` of ruling 35 of 0.20. It is ahead of every other
    `transform-decode`. A `length` block whose extent ends beyond the input or
    beyond its enclosing extent is `malformed-wire` at its `length` line,
    before anything in the block is read, and so before any check of an
    `inner` line in it; a `length … whole` longer than the input is met at its
    own line likewise. On encode it is an error of the `inner` line for ruling
    12 of 0.20, as the other four are: an error of an earlier line wins, and
    so does the `no-kind` of choosing the outer message's kind. A `no-kind` of
    a later `switch` or of the inner pack does not win. An engine that keeps a
    lookup (0.34) keeps checks 1 to 4; the fifth belongs to each `inner` line.
    The check is not one of the pack: `model_keys` and the capability report
    of 0.34 keep checks 1 to 4, so a clashing line still adds the inner pack's
    keys there. A pack that always refuses is therefore still reported as
    carrying its inner pack's keys; `tools/model-checks.py --inner-keys`
    refuses such a pack before it ships, in a tree that runs it. An `inner`
    line in a block that reads as absent (ruling 21 of 0.8) is not reached on
    decode, though encode may reach it; a line at the end of its own extent is
    reached.
20c. **What 0.34 says that has nothing left to apply to.** Decode step 4's
    keeping of the first value read where both packs map the key, and its
    sentence "A list is one key" on a list of both; "Items of an inner list
    discarded by step 4 are not counted (7g)"; "A key mapped by both packs is
    written by both" (Encode); "no key mapped by both packs held different
    values" (Conversion); the last sentence of ruling 8 of 0.34 (its first
    stands: such a pack loads); the last sentence of ruling 9 of 0.34; "a list
    that step 4 discards included" (ruling 14 of 0.34); and rulings 21, 22 and
    23 of 0.34. Of ruling 20 of 0.34 the first sentence stands and "Step 4 is
    about" to its end goes; two outer groups of one list are 7g's alone. Of
    ruling 7 of 0.34 "An inner `count` is checked against the remaining budget
    when it is read (7d)" and "A `count <n>` the pack states is not read from
    the wire, so 7d does not check it" stand. Ruling 19 of 0.34, the order of
    errors, and the join of keys that one pack maps stand.
20d. **The outer pack's `typemap`** applies only to values that lines of the
    outer pack read or write, and the inner pack's only to its own ("pack-wide",
    ruling 18 of 0.5). A `type` that the inner message gave is not changed by
    the outer pack's `typemap`, on decode or on encode, also when no line in
    reach of the outer pack maps `type`. Whether a pack with a `typemap` line
    and no field on `type` loads is not ruled here.

### Stated, not yet pinned by a vector

21. Ruling 10, and `model_keys` unchanged (no capability vector, as for ruling
    27 of 0.30).
22. A recorded kind, pinned only by round trips, whose key always matches
    (ruling 25 of 0.30).
23. A `switch` on an `optional` key in an item kind.

## Not in this version

- `optional` on a `requires` line.

# Version 0.83: a length given by an earlier count

Status: Written. A transport header often states how many words of a fixed
size its payload has, with other header fields between that number and the
payload. Version 0.8's `length` is followed at once by the block it counts, in
bytes or bits. Version 0.21's `count` may stand earlier, but it counts items
of a list, not an extent. This version lets an earlier count size a block.

```
count <name> <len> [plus <n>]
…
length @<name> units <u>
  …
end
```

A line of a `layout sequential` `bits` pack. `<name>` is a `count` line of
Version 0.21, visible at the `length` line as rulings 9 and 12 of 0.21 state.
`<u>` is the size of one unit in bits, 1 to 65535. The block is a `length`
extent (Version 0.8) of (value − `plus`) × `<u>` bits. It is counted in bytes
when `<u>` is a multiple of 8, and otherwise in bits.

## Decode

When the line is reached, the block is read within that extent under the
rules of a `length` block of that size: lines beyond it read as absent, and
content of the extent that no line reads is skipped. `inner` (Version 0.34)
and a `rest` list may end it. A value below the `plus` is `malformed-wire` at
the count line, as in 0.21.

## Encode

The block is written. Its length must be a whole number of units (ruling 10),
otherwise `transform-encode`.
The count field holds that number plus its `plus`, filled in as 0.21 fills a
count. A value outside `0 … 2^len − 1` is `transform-encode`.

## Load errors

`bad-directive`: a line that is not exactly `length @<name> units <u>` while
its first argument starts with `@`, or that holds `units` without it (`length
8 units 8`, `length units 8 @a`); a `<u>` that is not plain digits from 1 to
65535 (leading zeros allowed); a name not visible or not a `count`; `length @`
on a fixed layout or another wire.

## Rulings for 0.83

1. **Amended rules.** The `length` line of 0.8 (grammar and ruling 8) gains
   this form. Rulings 2 of 0.21 and 3 of 0.31: a `length @<name>` is a
   reference as a group is, counted statically, and "group" there reads
   "group or `length @`". A name sizes a block or counts a list in one path,
   never both.
2. **A path with nothing to size.** A kind with no payload has an empty block:
   `length @w units 72`, then `end`. It loads. Decode skips the extent; encode
   writes 0 units.
3. **The unit count is not an item count.** It is not compared with
   `max_items` (7d of 0.11) or with the bits left (ruling 14 of 0.8). Every
   product is exact.
4. **Enclosing extents.** A block whose extent ends beyond the innermost
   `length` block around it is `malformed-wire` at the line. A block whose
   line stands at or past the end of that enclosing block is absent, and
   nothing in it is reached (ruling 21 of 0.8). This comes first: such a
   block is absent whatever its count states. Ruling 4 is about `length @`
   only.
5. **Beyond the input.** An extent that ends beyond the input, or beyond a
   whole length read before the line, is `malformed-wire` at the line, before
   anything in the block is read, as for a plain `length` (ruling 17), also
   when all its lines would fit. An absent block (ruling 4) is not tested.
6. **Zero units.** The block's lines are read as at the end of any `length`
   extent (rulings 7, 21 and 34 of 0.8, ruling 14 of 0.20, rulings 3 and 31
   of 0.21): a `rest` list is present and empty. `inner` is reached with an
   empty input (0.34).
7. **More than is there.** A count larger than the payload needs leaves the
   rest of the extent to the rules of its lines: an ordinary block skips it,
   and what follows an inner message is for `inner` (0.34) to rule. Encode
   writes the length of what it writes.
8. **Less than is there** is the inner message's own error.
9. **Not written.** When the line is in a block not written, the count holds
   its `plus` (ruling 6 of 0.21). On decode a count that states units (its
   value minus its `plus` is not 0) of which no `length @` block is read,
   because it stands in an `if`, `opt` or `chain` part that is not read, is
   absent by ruling 4, or is inside a block that is absent, is
   `malformed-wire` when the scope that holds the count line (the message, or
   the item, with its kind) has been read; a block of 0 units there is no
   error (a block of 0 units whose line stands past a whole length is
   malformed by ruling 5). A `switch` or a `choice` inside such a part counts
   when any of its cases or alternatives holds the block; one that was read
   counts by its selected case or its chosen alternative. An `alt` of a
   `choice` that was not chosen, and a kind or case that was not selected, are
   no error. A count line that was itself absent states nothing.
10. **Padding.** A block counted in bytes is padded to a whole byte from its
    first bit (ruling 34 of 0.21), and then tested for whole units; nothing
    pads to a unit. A block counted in bits is not padded, and a `rest` in it
    needs 1 bit for an item. "A `length … bits` extent" in 0.34 includes it.
11. **Encode errors.** An error in the contents first, then the unit test at
    the block's `end`, in reading order ahead of later lines. The range of the
    count is checked as in ruling 30 of 0.21.
12. **A wire line.** `length @` is one, for rulings 11 and 32 of 0.21.
13. **When the checks run.** Every error of this form, its number of arguments
    included, is a check after the file. `length` before `wire` or before
    `layout` stays as 0.11 ruling 5b has it.
14. **Presence, `opt` and `fx` bits, and predictions** (0.20 ruling 33) see the
    block as any `length` block.

15. **Kinds past the input.** A `when` whose bits lie past the input, or past
    a whole length, does not hold (ruling 6 of 0.33): an item of kinds there
    is `no-kind`, any other line `malformed-wire`.
16. **A whole length inside a block**, a plain `length` or a `length @`, at
    any depth, ends the input and not the block (ruling 8 of 0.8; ruling 14 of
    0.21): from then on, in that block, in the blocks around it and after
    them, a line that needs bits past the stated whole is `malformed-wire`,
    and is not read as absent because a block goes on (ruling 15 stands for
    `when` lines: one past the whole does not hold). A block opened after it
    is tested against it (ruling 5). A `rest` list runs to its block's end and
    so fails at the whole; an `inner` whose enclosing extent ends beyond the
    whole is `malformed-wire` by step 2 of 0.34, and at message level its
    input ends at the whole (0.34 ruling 3), empty when the cursor is past it,
    after the whole-byte test on the exact cursor. A line that starts at or
    after the end of its block is absent (ruling 7 of 0.8), also when the
    whole length ends at the same place or before. After the block the cursor
    stands at its stated end, also beyond the whole: there, at message level,
    a line that needs bits is `malformed-wire`, a `rest` list and a list whose
    `count @` is 0 are present and empty, and an `inner` line has an empty
    input.
17. **A plain `length`** inside a `length @` block, or anywhere, is tested as
    ruling 5 says: an extent that ends beyond the input, a whole length read
    before the line, or any extent around it, is `malformed-wire` at its line,
    before anything in it is read (0.52 ruling 20b), also when all its lines
    would fit. Ruling 4 is about `length @` only; a plain `length` whose line
    stands at or past the end of its enclosing block keeps 0.8 ruling 21.
18. **`align`** in a block that a whole length read in it cuts stops at the
    end of the input (ruling 20 of 0.8).

## Stated limits

A block behaves as a plain `length` block in what comes back: units that no line reads are skipped on decode and not
written back, so the count is written anew; and a block of fewer units than its
lines write grows on encode, the missing fields as zero bits that then decode
as values. A pack that must keep them maps every unit, by a closing `rest` of
raw units or by a kind for each size.

## Not in this version

- A unit that is not stated in the pack.
- `units` on a `length` whose field stands at the block.
- Header bytes inside the stated length that stand before the block.
- A message that states 0 units and has no inner message, in a pack whose
  block holds `inner`: a kind with an empty block is needed.

# Version 0.92: a run of inner messages

Status: Written.

A transport may carry several messages of one format, one after another, with
nothing between them: each ends where its own decode ends. Version 0.34's
`inner` hands over one message.

```
inner <format> run
```

A line as `inner` of 0.34, with its places, checks and errors. The inner pack
must be `layout sequential` and have a `framing self` line
(ruling 16), otherwise `bad-directive`, with check 2 of 0.34.
A pack with a `run` line is a **carrier pack**. A **carrier** is a message
whose selected lines reach an `inner … run`. A message that does not reach one
(a kind without it, an absent block) is an ordinary message, for every
operation.

## Where one message ends

Decoded by the inner pack from its first byte, with the input ending at the
extent's end, a message ends at the **inner message's end** of 0.34 (its
ruling 13): the stated end of a `length ... whole`, otherwise the cursor after
its last line, rounded up to a whole byte. A message-level `rest` list without
a `whole` cannot stand in such a pack (ruling 16). Its "three cases" are the
padding bits, the unread content of a `length` extent and a `rest` group under
a whole. "The inner input" of 0.34's ruling 12 is, in a run, from the
message's start to the extent's end. An end beyond the extent, or at the start
of the message, is `malformed-wire`. The next message starts there, until the
extent ends. `align` and windows count from the message's own start. No byte
stands between messages or after the last one: bytes that do not make a
message are a message that fails.

A pack says that its messages end by themselves with one line:

```
framing self
```

It is the author's word that each message of the pack ends where its last line
ends: for example by a `length … whole`, a block that a count sizes (`length
@<name> units <u>`, Version 0.83), a counted group of items of one size, or a
kind of fixed size. An engine does not prove it. A message shorter than its
lines then takes bytes of the next one, which no check here can see.

Messages of one run may select different kinds: each selects its own.

## Operations

```
decode_run(format, bytes)             -> (outer entity, [entity or error])
convert_run(from, to, bytes, context) -> [result]
```

- **`decode_run`** returns the entity of the outer lines alone and one entity
  per message, joined with the outer keys by step 4 of 0.34's Decode as if the
  carrier held that message alone. Each has the outer `Entity.kind` and its
  own `Entity.inner_kind`. An ordinary message gives one entity.
- **`convert_run` to a format that is not a carrier pack** gives one result per
  message, 0.6 steps 1 to 4 on each joined entity.
- **From a carrier to a carrier pack** (its own format included) it gives one
  result: as ruling 6 states. Every length or count that sizes the extent in
  the target covers the whole run. Any error is the error of the call: nothing
  is written in part.
- **From any other format to a carrier pack** it gives one: a carrier
  of one message, as `encode` writes it.
- **`decode` and `convert`** read a carrier of exactly one message as 0.34
  does. Otherwise they raise `message-count`, a new error kind (ruling 1).

## Rulings

1. **`message-count`.** On a `run` line the checks of 0.34, the fifth of 0.52
   (ruling 20) and Decode steps 1 and 2 of 0.34 come first, in every
   operation. Then, in `decode` and `convert`: an empty extent is
   `message-count`; message 1 is decoded, and an error that stops its decode
   is reported; if bytes remain after its end, `message-count`, without
   reading further. It stops the decode, so it is ahead of any
   `transform-decode` and of errors of later outer lines. The end rules above
   hold in these operations too: an end beyond the extent, or at the start of
   the message, is `malformed-wire` (amends 0.34 rulings 2, 6, 15 and 16 on a
   `run` line).
2. **Zero messages.** No inner decode is called. `decode_run` gives no
   entities, `convert_run` no results, or an empty run for a carrier pack.
3. **Message errors**, to a target that is not a carrier pack and in
   `decode_run`: a `transform-decode` or an encode error is that message's
   result and the run goes on. `malformed-wire` and `no-kind` that stop its
   decode (a `no-kind` of encode is an encode error), and a `switch` that is
   reached and reads a key whose line failed, forgiven or not within its own
   pack (0.20 ruling 35), of a message at a `run` line, in every operation,
   `decode` and `convert` of a carrier included (outer lines and a plain
   `inner` keep 0.20 as it is), end the run, as its last result. A failed key
   whose `switch` is not reached does not end it. Outer lines after the block
   are still read.
4. **Call errors:** `unknown-format` of `from` or `to`, always; and a bad
   context key, unless the one ordinary message did not decode (then its error
   is the result, as 0.6 and spec/vector-format.md state). Then, when `from`
   is a carrier pack and the decode reached a `run` line or stopped before
   that was known: 0.34's checks and the fifth of 0.52 (ruling 20), steps 1
   and 2, and any error of the outer lines, a `transform-decode` that no outer
   line forgives included, whatever the messages do. To a carrier pack every
   error fails the call. A decode that came to its end without reaching a
   `run` line, or that stopped after the kind was selected with no `run` line
   in its reach, or after its `run` line was passed in a block that reads as
   absent, is of an ordinary message, as every decode is when `from` is no
   carrier pack: each of its decode and encode errors is its one result, or
   the call's to a carrier pack. Errors come in phases, each in reading order:
   those that stop a decode (the `switch` of ruling 3 included), then other
   decode errors, then context, then encode. To a target that is not a carrier
   pack, message errors take no part in the call's; a bad context key beside
   an outer `transform-decode` is reported after it.
5. **`max_items`** bounds the number of messages in run operations only, by
   itself: one more than it allows is `malformed-wire` of the call, raised
   when that message would start, and it stops the decode. Each message's items
   start from the budget the outer lines before it left; in run operations the
   outer lines after the run do not count message items. It also bounds the
   items of all the joined entities together, in `decode_run` and in
   `convert_run` to every target. Over the messages whose decode came to its
   end (a message whose result is a `transform-decode` included), the items of
   the outer entity, once for each such message, and each message's own items
   are summed. The sum may reach `max_items`; one item more is `malformed-wire`
   of the call. It is checked when the carrier's decode has ended, after every
   other decode error of the call and before context and encode; a message
   that ends the run with its own error, to a target that is not a carrier
   pack, is no error of the call, so the sum is still checked. The outer
   entity that `decode_run` gives alone is not counted again.
   `decode` keeps 0.34.
6. **Carrier pack to carrier pack.** The outer lines are encoded from the
   outer entity alone, `requires` and `with` included, so a key that only a
   message holds is not written by an outer line. Each message is encoded from
   the joined entity (ruling 9) into the inner format of the `run` line of the
   target's selected kind: with the inner format of the source without context
   and derivations unless the caller gives context, with another by 0.6 steps
   1 to 4. When the outer formats differ, or the caller gives context, the
   outer entity runs 0.6 steps 2 and 3, with or without equal inner formats;
   the sentence on context of ruling 10 is about the messages. The target's
   kind is chosen on the outer entity alone. A kind without a `run` line takes
   exactly one message: the joined entity is then encoded into that kind by
   0.6 steps 1 to 4, through a plain `inner` line as 0.34 states or without
   one; none or several is `message-count`, in the encode phase, where the
   kind is chosen (no kind chosen is `no-kind`). An ordinary message is
   `convert`. For an empty run the checks of 0.34 and the fifth of 0.52 on the
   target's `inner` line are made where it is reached, the format not loaded
   and the whole-byte cursor included.
7. **What comes back.** A message comes back as it was when its pack maps
   every bit it reads and its sized last block holds exactly what the block's
   lines write. A block with fewer units grows on encode (0.8): the fields it
   did not hold are written as zero bits and then decode as values. One with
   more units is cut to what the lines write. A pack keeps more units by a
   closing `rest` of raw units inside the block and fewer by one kind for each
   size. The same holds for a plain `length` block.
8. **A message that cannot be found again.** On every encode that reaches a
   `run` line (of `convert` and `encode` too, where one message is written),
   never at a plain `inner` line, a message that writes no bytes is
   `transform-encode`.
9. **Keys are joined** in every case. The fifth check of 0.52 (ruling 20) is
   made on a `run` line too, so a carrier's outer lines in reach and its inner
   pack share no key: no list is discarded by the join and no failure is
   forgiven across the two packs. A failed line of an outer key or of a
   message key is an error unless another line of that same pack forgives it
   (0.6). A `with <key>` names a key without mapping it, so an outer line in
   reach (the lines in reach of ruling 20 of 0.52) whose `with` names a mapped
   key of the inner pack of a `run` line would be written as absent in a run:
   it is `bad-directive` at the `run` line, with the fifth check. An inner
   line's `with` may name an outer key, and holds when the joined entity holds
   it.
10. **Context.** Keys of the caller's context fill the outer entity and each
    joined entity (after the join) where they are absent. They are checked
    once, after the decode errors (ruling 4), for an empty run too. With
    context a derivation may set a message key from an outer one; without
    context, from a carrier to a carrier with the same inner format, neither
    context nor derivations run.
11. **Kinds.** Each message's kinds are cleared as 0.34's Conversion states,
    and the outer entity's `Entity.kind` unless `from` and `to` are equal.
12. **Load.** `inner` takes one or two arguments; none, or three and more, is
    the line check of 0.34. A
    second word other than `run` or `partial`, compared after quotes are
    removed, is an after-file `bad-directive`. `inner run` names a format.
13. **Vectors.** `expect_results` is an array of objects holding `expect` or
    `expect_error`; a vector with it calls `convert_run` and may hold
    `context` and `max_items`. A call that fails holds `expect_error` and
    `"run": true`.
14. **Capability** is 0.34's. The pipe counts and the loss report go by
    result. The C library offers `convert` only, so it gives `message-count`.
15. **Not pinned:** `decode_run` itself, the recorded kinds, the pipe, the
    report.
16. **`framing self`.** A header directive of a `layout sequential` `bits`
    pack, with the one argument `self` (compared after quotes are removed).
    Load: it joins the lines of 0.11 5b that `layout sequential` and the
    `wire` line must stand before, with that list's errors (`missing-wire`,
    and `bad-directive` for the order); no argument, or two and more, is the
    line check (5e); another word, a second `framing` line, a fixed layout,
    another wire, `armor sixbit` and `encoding uper` are `bad-directive` after
    the file, with the checks of ruling 25 of 0.5. It stands outside every
    block (ruling 24 of 0.8) and before the first `kind` of the message (the
    `kind` lines of a group's items do not count), otherwise `bad-directive`
    after the file. A `rest` group whose enclosing extent (0.21) is the
    message, in whatever other block it stands, needs a `length … whole` line
    before it that is read whenever that `rest` is: in the common lines or the
    same kind, outside every block, or in a block that also holds the `rest`;
    otherwise the load is `bad-directive` after the file, judged for the
    common lines with each kind and for each `case`. A `rest` in a `length` or
    `length @` block is allowed; one in an item is judged by the `rest` its
    group stands in. A pack with `framing self` and an `inner` line of its own
    loads, but is never an inner pack (check 3 of 0.34). Use: an `inner … run`
    whose inner pack is not `layout sequential` or has no `framing self` line
    is `bad-directive`, made at each `run` line between checks 2 and 3 of
    0.34, also by an engine that keeps lookups; it is ahead of the fifth check
    of 0.52, and is made on decode and on encode, in every operation and for
    an empty run. It changes nothing else: `decode`, `encode` and a plain
    `inner` of the pack are as without it, and `model_keys` and the capability
    report use checks 1 to 4 of 0.34, so a `run` line over a pack without it
    still adds the inner pack's keys.

## Amends

0.8 (the last byte), 0.21 ruling 14, 0.20 ruling 35, 0.11 rulings 5e and 7 and
the error kinds, 0.6 (order), 0.11 5b, 5e and its directive list, 0.8 ruling
24, 0.34 (the second word of `inner` may be `run`, its introduction and the
first bullet of its "Not in this version", check 2, Decode step 3, Encode (the
outer entity alone), rulings 2, 6, 12, 15, 16 and 17, and its vectors:
`message-count` in `expect_error`), 0.52 ruling 20 (the fifth check on a `run`
line).

## Not in this version

- Padding, or any byte between or after the messages.
- Messages of more than one inner format in one run.

# Version 0.94: a conversion into a kind holds one of its keys

Status: Written. Converting an entity to a format that holds none of what the
entity holds gives a message of constants and zeros, and such a message can be
a valid command (an acknowledgement, an abort, a query). With this version a
conversion into a pack that has message kinds refuses it. The rule is small on
purpose: one held key of the kind is enough, a key of the common lines
included, so an entity that holds only a time passes into a kind whose common
lines map it. A pack that needs more says so with `requires`.

## Rule

In `convert(from, to, …)` with `from` different from `to`, after the context and
the derivations (0.6 steps 2 and 3), after the message kind is chosen (0.5) and
before any line is written: if the pack of `to` has a **message kind** and the
entity holds **no key of the chosen kind**, the error is `no-kind`.

- **Keys of a kind** are the keys that 6a to 6c of 0.11 and ruling 24 of 0.30
  list, over the common lines and the chosen kind's lines, whether or not a
  block, case or line is written (a line that `with` suppresses included); the
  `model_keys` of the inner pack of an `inner` line among those lines (0.34,
  whichever inner kind encode will choose; a pack that does not pass 0.34's
  checks 1 to 4 adds nothing, so the result is then `no-kind` where nothing
  else is held; those four checks only, not the `framing self` check of 0.92
  ruling 16); and the keys, with `=` or without, of the kind's own
  `requires` lines, not of a group's. A list counts by the entry of the list
  (`rows[]`), not by item keys. Keys are compared as literal text. A key does
  not count by being named by `with`, `switch` or a gate (a line that maps it
  counts); presence and count names are not keys; the keys of a group's items
  do not count.
- **Holds** means a value that decode, the caller's context or a derivation
  gave: 0, the empty text and a value equal to a sentinel count; a key left
  absent by a sentinel does not (0.9, 0.12). A `default`, a `const` and a `when`
  value are not held. A list counts when it has at least one item, whether or
  not its items hold a key. Residue does not count.

## Rulings

1. **The next kind is not tried.** The kind is the one that 0.5 chooses; this
   check only refuses it. No output changes other than to this error. A kind
   with a scalar `requires` or a non-optional `as` always passes; one with an
   optional `as` passes when its label is held, even alone. A `requires` of a
   list is met only by a list with at least one item (0.7, unchanged), which is
   held, so such a kind passes too.
2. **Same format and direct encode.** `convert(f, f, …)`, with or without
   context, and `encode(f, entity)` are unchanged. The `requires` choice of 0.5
   is made by both as before. A program that decodes and encodes by itself is
   not covered.
3. **A kind that maps no key** is refused unless the entity holds one of its
   `requires` keys, a list with an item (a `requires` key need not be mapped).
4. **Not checked:** the kind of a group item, the kind of an inner message, and
   a kept kind: when `Entity.kind` or `Entity.inner_kind` names the format of an
   `inner` line of the chosen kind or of the common lines (0.34), or names `to`.
   An `inner` line cannot stand in a group body (0.34), so no other line keeps
   a kind. In a run, ruling 7 says which kinds are kept.
   A pack without message kinds is not checked (ruling 6), a pack whose only
   `kind` lines are in a group body included: a message with no position still
   gives an empty GeoJSON Feature.
5. **Order of errors.** The check is made inside step 4 of 0.6's order in
   `convert`, between choosing and the first line, and reported like the
   `no-kind` of choosing (the same error, that one first), ahead of every
   encode error; context and derivation errors come before it.
6. **A pack without kinds opts in** with kinds that hold only `requires`; its
   lines stay common lines, before the first `kind`:

   ```
   kind     clear
   requires ocpp16clearcache.go
   ```

   By 0.5 and 0.20: several terms of one kind must all hold; of several kinds
   the first that holds is chosen, so any of their keys is enough; a kind
   without `when` always holds on decode, so a message still decodes (unless a
   common `when` fails), as the first such kind, whatever it held, and a
   same-format round trip keeps the recorded kind and the bytes. A named key
   is any declared key, mapped or not. Beside this check, `encode` of 0.5
   makes the `requires` choice. What changes for such a pack: `Entity.kind` is
   recorded with the first kind's name (so a message that holds only `b` in
   the table below decodes as `by-a`); on `xml` a wrong root is `no-kind`
   instead of `missing-root` (0.6); as an inner pack it records `inner_kind`,
   and encoding it as a layer can be `no-kind` unless a kind is kept.

   A pack of no field lines, the same pack with `kind clear` / `requires go`,
   and a pack with common lines `a`, `b`, `uid` (at `a`, `b`, `id`) and `kind
   by-a` / `requires a`, `kind by-b` / `requires b`:

   | Entity, from another format | No kinds | `clear` | `by-a`, `by-b` |
   |---|---|---|---|
   | only `uid` | `{}` | `no-kind` | `no-kind` |
   | only `go`, or `go` as context | `{}` | `{}` | `no-kind` |
   | only `a` | `{}` | `no-kind` | `{"a":…}` |
   | only `b` and `uid` | `{}` | `no-kind` | `{"b":…,"id":…}` |
   | the same format's `{}` | `{}` | `{}` | `{}` |

7. **Runs (0.92).** `convert_run` makes this check wherever it converts with
   `from` different from `to`; `decode_run` checks nothing.
   - To a target that is not a carrier pack: on each message's joined entity,
     as `convert`, each result on its own.
   - From any other format to a carrier pack: on the entity, as `convert`; the
     carrier of one message is a `convert`.
   - From a carrier to a carrier pack: once, on the kind that ruling 6 of 0.92
     chooses, and on the outer entity joined with the first message, or on the
     outer entity alone when the run is empty. So a kind whose only line is
     its `run` line holds a key when the first message holds one of the inner
     pack's keys. The inner kind that the first message records is not a
     kept kind here, though it names the format of the `run` line: the check
     is made. A kind without a `run` line takes the one message: the count of
     0.92 ruling 6 is made first, where the kind is chosen (none or several
     messages is `message-count`, as the `no-kind` of choosing comes before
     this check, ruling 5); then the joined entity is checked as `convert`,
     ruling 4 included. The messages' own kinds are those of inner messages
     (ruling 4) and are not checked.
8. **Vectors this version changes.** Five vectors written before 0.94 expected
   output from an entity that holds no key of the chosen kind:
   - `geojson` `bpv7-01-to-dtn-bpv7-nothing-to-write` is now `no-kind`: a
     Feature holds no key of `dtn-bpv7`'s chosen kind, and the bundle of
     constants it gave before is the case the rule is for.
   - `conformance-held-src` 40 is rederived under 0.7: an empty list does not
     meet `requires`, so kind `other` is chosen and holds `w`.
   - `conformance-asopt-json` 10 and `conformance-inner-refused-json` 13 keep
     their point (the order of kinds, 0.52 ruling 8; the refusal of 0.52
     ruling 20 on encode) with an input that holds a key of the kind.
   - `cot-xml` `cam-01-to-etsi-cam-non-numeric-uid` is now `no-kind`: of kind
     `cam` the entity holds nothing, as `etsicam.station_id` is absent. The
     same case.

## Amends

0.5 Encode ("A kind with no `requires` always qualifies": it is then also held
to this check), 0.6 "Order inside `convert`" (step 4), the `no-kind` row of the
error table of 0.11.

## Not in this version

- This check in `encode`.
- A check for packs without message kinds that do not opt in.
