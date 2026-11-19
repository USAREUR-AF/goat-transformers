# Engine specification

Status: Written. Version 0.11. This is what every language's engine implements,
from this document and the vectors, never from another engine's source. The
document grows by one section per version; a later section that replaces an
earlier sentence says so, and the later section holds.

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
