# Embedded profile

Status: Built and Measured on a development host and for one microcontroller
target (`thumbv7em-none-eabihf`). Not yet run on hardware. Pre-1.0: the
compiled format and the engine interface can still change.

The embedded profile runs a conversion between two binary formats on a device
with no operating system and no heap. A host tool compiles the packs ahead of
time into a small binary plan; a Rust engine with no standard library runs the
plan against buffers the caller provides.

## What it is for

The seven engines read pack text when they start, allocate as they go and need
an operating system. A microcontroller that turns one binary message into
another, for example a Remote ID receiver that feeds an ASTERIX consumer, has
none of that to spare. The profile moves the work that needs text and memory
to build time:

| | Engines (`engines/`) | Embedded profile (`embedded/`) |
|---|---|---|
| Reads packs | as text, at start | never; `tools/gen/packc.py` compiles them on the host |
| Formats and kinds held | every pack loaded | the formats and kinds named when the plan is compiled |
| Model keys | names | small integers; names only in an optional debug section |
| Memory | allocates | caller's buffers, fixed size |
| Wires | `xml`, `geojson`, `json`, `protobuf`, `bits` | `bits` only, as bytes or as six-bit armored text |
| Needs | a standard library | `core` only: `#![no_std]`, no allocator, no dependency, `forbid(unsafe_code)` |

## What it is not

`embedded/gt-core` is a second execution form of the Rust reference engine
(`engines/rust`). It was written with that engine's source open, and it
follows that engine's code paths for the `bits` wire. It is not an eighth
engine written independently from the specification, and it does not count as
one of the voices that check each other on the vectors
(`spec/interop-and-sharing.md`). Agreement between it and the Rust engine
shows that the compiler and the port are faithful, not that the specification
was read twice.

## Workflow

1. **Choose formats and kinds.** Name the source format and the target format
   and, for each, the message kinds the device will see. Only those kinds are
   compiled.
2. **Compile a plan.** The compiler writes the blob, a Rust source file that
   holds it as a `static`, and a size report.

   ```
   python3 tools/gen/packc.py \
       --from remote-id:location --to asterix-cat062 \
       --context cat062.sac,cat062.sic,cat062.time_of_day_s,cat062.track_number,track.confirmed \
       --out-rs plan.rs
   ```

   The report states what the conversion carries. For the command above:
   `lat`, `lon` and `hae` are read from the Remote ID message and written to
   the CAT062 record; the five `--context` keys are supplied by the caller;
   the other 18 keys of a Remote ID Location message are not compiled, because
   CAT062 has no place for them. The compiler refuses a plan the device could
   not run, with a named reason (`embedded/FORMAT.md`, "What the compiler
   refuses"). Without the last three context keys the command above is
   refused as `target-unreachable`: a CAT062 record requires a time of day, a
   track number and a confirmed flag, and a Remote ID Location message holds
   none of them.
3. **Link gt-core.** The firmware includes the generated file and calls the
   engine:

   ```rust
   let plan = gt_core::Plan::parse(&PLAN)?;
   let mut scratch = gt_core::Scratch::<12>::new();
   let context = [(gt_core::KeyId(KEY_CAT062_SAC), gt_core::Value::Int(1)), /* ... */];
   let n = gt_core::convert(&plan, message, &mut out, &mut scratch, &context)?;
   ```

   `Scratch<N>` holds `N` values and `N` list items, 32 bytes for each `N`.
   `convert` returns the number of bytes written or one of nine errors. Six
   are the named error kinds of the specification (`no-kind`,
   `malformed-wire`, `transform-decode`, `transform-encode`, `undeclared-key`,
   `key-type-mismatch`); three belong to the device (`output-full`,
   `scratch-full`, `bad-plan`).

The compiler is a Python script on the standard library, like the other
generators in `tools/gen/`. It runs on any build host without a Rust build of
its own, and its output is checked against the reference engine by the proof
below, not by sharing that engine's code.

`embedded/example-bare` is this example as a static library for C firmware:
`build.rs` compiles the plan, `src/lib.rs` exports
`gt_rid_location_to_cat062`, and `include/gt_example.h` is the header.

A format with `armor sixbit` (spec 0.14) takes and gives its message as the
armored text itself, one byte a character: `convert` reads the characters of
`message` and writes characters to `out`, which needs one byte for each six
bits of the message.

A plan may also hold one format only. `--from` alone gives a decode-only plan
(wire to values, read with `Session::get`); `--to` alone gives an encode-only
plan (values set with `Session::put_int`, `put_float`, `put_text` and
`add_item`, then written). `Session` exposes the four steps of a conversion
one at a time: `decode`, `fill`, `complete`, `encode`.

## Supported features

The blob layout, the operation table and the full list are in
`embedded/FORMAT.md`.

| Pack-language feature | Status |
|---|---|
| `bits` wire, fixed layout: words, `bit_order`, fields past their word, `optional` | Built |
| Transforms `uint`, `twos`, `linscale`, `uscale`, `sscale`, `f32`, `f64`, `ascii`; `swap`, `trim` | Built |
| Six-bit armor (spec 0.14): `armor sixbit`, fixed and sequential layout, and the `sixbit` transform with either armor | Built |
| The value transforms of spec 0.15 (`uiscale`, `siscale`, `smag`, `smscale`, `f32scale`, `f64scale`, `chars`, `octal`) | Not built; refused as `unsupported-feature` |
| Kinds: `kind`, `when`, `requires`; a plan compiled for some kinds of a format | Built |
| `const`, `default`, `map` and `via`, `typemap`, `also` | Built |
| `absent` field option (absent-value sentinels, spec 0.9): fixed and sequential layout, `also`, groups, `optional`, presence | Built |
| Groups with a fixed count or a count field, nested | Built |
| `layout sequential`: `pad`, `align`, `presence`, `if`, `opt`, `chain`, `length`, `group ... count / while / more / fx`, items by kind | Built |
| Context keys, named when the plan is compiled | Built |
| Derivations `copy`, `neg`, `scale`, `offset`, `day_seconds`, `any`, `not`, `parse_int`, `present` | Built |
| Derivation `hypot` (gt-core feature `sqrt`) | Built |
| Derivations `bearing`, `east_of`, `north_of` (gt-core feature `trig`) | Built |
| Text wires `xml`, `geojson`, `json`, `protobuf` | Not built; out of scope |
| Derivations `join`, `text_of` | Not built; refused when a conversion needs them |
| Residue | Not built; a `bits` format has none |

Arithmetic follows the reference engine's rulings: a scale is applied as
`v * num / den + offset` in doubles, encode rounds half away from zero, and a
value outside its field is `transform-encode`. `core` has no `round`, `sqrt`,
`sin`, `cos` or `atan2`, so `gt-core` carries its own
(`embedded/gt-core/src/num.rs`). Its `round` and `sqrt` give the host
library's bits on 400,000 values each. Its `sin`, `cos` and `atan2` stay
within 2.3e-16 relative of the host library on 1.1 million values; the
specification compares a derived float within 1e-9.

No input makes the engine panic. Every read of the plan and of the message is
bounds-checked and returns an error; nesting is followed to 12 levels and no
further; a count larger than the bits left in the message is refused before
any item is read. The image linked for the microcontroller target holds no
symbol of Rust's panic machinery.

## How equivalence with the reference engine is checked

`embedded/gt-proof` is a host-side test crate that links both `gt-core` and
the Rust reference engine. It compiles every plan with `packc.py` and compares
the two engines. Run it with `cargo test -p gt-proof` in `embedded/`.

Every conversion vector of the repository with a `bits` format on either side
runs, in one of three ways:

| Group | What the device does | Compared with | Vectors | Pass |
|---|---|---|---|---|
| bits to bits | converts the input | the vector's `expect` byte for byte, or its `expect_error` kind; the decoded values with the reference engine's and with the vector's `model`, `"@absent"` included | 7,836 | 7,836 |
| bits to text | decodes the input | every value, list, item and kind the reference engine decodes; the vector's `model`, `"@absent"` included | 139 | 139 |
| text to bits | takes the values the reference engine decodes from the text side, fills the context, derives, encodes | the vector's `expect` byte for byte, or its `expect_error` kind | 185 | 185 |

Measured. 805 vectors with a `bits` side do not run, each for a reason the
test states and checks: 7 of `conformance-malformed-bits`, whose input is hex
text that is not well formed (ruling 36 of 0.8), because the device takes
bytes, not hex text; 2 of `conformance-limit-bits`, whose message holds more
list items than the proof's scratch (`scratch-full`, below); and 796 whose
plan the compiler refuses as `unsupported-feature`, because a pack of the
conversion uses a value transform of spec 0.15 (by the first transform the
compiler meets: `uiscale` 608, `chars` 176, `smag` 12). Any other refusal fails
the test. By pack that owns the vector:

| Pack | bits to bits | bits to text | text to bits |
|---|---|---|---|
| `ais` | 47 | 9 |  |
| `ais-binary` | 29 | 3 |  |
| the 342 `ardupilot-log-*` packs | 343 | 7 |  |
| `asterix-cat062` | 18 | 2 |  |
| the 20 other `asterix-cat*` packs | 124 | 1 |  |
| `canonical-track-v2` |  |  | 14 |
| the 5 `ccsds-*` packs | 33 |  |  |
| `conformance-absent-bits`, `-bits-lsb`, `-seq`, `-seq-also`, `conformance-numbers-absent` | 14 | 3 |  |
| `conformance-absent-json` |  |  | 4 |
| `conformance-armor`, `conformance-armor-absent`, `conformance-armor-seq`, `conformance-sixbit-lsb` | 39 | 4 |  |
| `conformance-groups-bits`, `-msb`, `-var`, `-rulings-bits` | 20 | 7 |  |
| `conformance-groups-json`, `-protobuf`, `-xml` |  |  | 12 |
| `conformance-json` |  |  | 5 |
| the 4 `conformance-limit-*` packs | 8 | 3 |  |
| `conformance-malformed-bits` | 6 |  |  |
| `conformance-numbers`, `-numbers-f64` |  | 26 | 4 |
| `conformance-rules-bits`, `-lsb`, `conformance-rulings-bits` | 13 | 5 |  |
| `conformance-scale`, `-scale-widths-lsb`, `-scale-widths-msb` | 128 | 12 |  |
| `conformance-scale-json` |  |  | 70 |
| `conformance-seq-*` (the 15 sequential bits packs) | 77 | 20 |  |
| `conformance-seq-json` |  |  | 43 |
| `cot-xml` |  |  | 1 |
| the 250 `cyphal-*` packs | 304 |  |  |
| the 91 `dbc-*` packs | 5,298 | 2 |  |
| `demo-bits`, `-bytes`, `-msb`, `demo-kinds-bits` | 33 | 7 |  |
| `demo-track-json` |  |  | 1 |
| `drip` | 9 | 1 |  |
| the 132 `dronecan-*` packs | 142 | 5 |  |
| `gdl90` | 17 | 2 |  |
| `geojson` |  |  | 31 |
| the 11 `mavlink2-*` dialect packs | 76 | 1 |  |
| the 15 network protocol header packs (`arp-*`, `bfd-*`, `dns-*`, `gre-*`, `icmp-*`, `igmpv2`, `ipv4-*`, `ipv6-*`, `mpls-*`, `rtcp-*`, `rtp-*`, `sctp-*`, `tcp-*`, `udp-*`, `vxlan-*`) | 94 |  |  |
| `nmea2000` | 475 | 6 |  |
| `nmea2000-seq` | 33 | 1 |  |
| the 298 `px4-ulog-*` packs | 300 | 7 |  |
| `remote-id` | 12 | 4 |  |
| the 22 `sbp-*` packs | 144 | 1 |  |

Every vector in a row passes. In the text-to-bits group the model values come
from the reference engine's decode of the text side, because a vector's
`model` lists only some keys.

Plans compiled for one kind of a format, over nine formats (`remote-id`,
`adsb`, `demo-kinds-bits`, `demo-bits-bytes`, `demo-bits-msb`,
`conformance-seq-kinds`, `conformance-seq-msb`, and up to twelve kinds each of
`mavlink2` and `nmea2000`): 33 one-kind plans; 43 vector messages of the
compiled kind converted to the vector's bytes; 5,821 messages of other kinds
were refused with `no-kind`. 44 kinds, of `adsb` and `mavlink2`, use a value
transform of spec 0.15 and are refused by the compiler as
`unsupported-feature`. Measured.

The example plan of `embedded/example-bare`, with its `Scratch<12>`, gives the
reference engine's bytes on the four Remote ID Location vectors. Measured.

Fuzz-style runs, with a seeded generator, through the same-format plan of each
of the 1,238 `bits` formats the profile compiles (23 of the 1,261 use a value
transform of spec 0.15) and four cross-format plans (1,242 plans). For a
source with six-bit armor, half the inputs are mapped onto armor characters,
so that they reach the lines:

| Run | Inputs | Result |
|---|---|---|
| Random bytes, and vector inputs with bits flipped, bytes replaced, tails cut or extended | 13,662,000 | no panic: 6,982,416 converted, 6,679,584 refused with a named error |
| The same kinds of input, device against reference engine | 1,863,000 | 953,500 equal outputs, 909,387 equal error kinds, 113 beyond the device's buffers, 0 differences |
| Every proper prefix of every same-format vector input | 154,113 | 152,657 refused with the reference engine's error kind; 1,456 accepted with the reference engine's bytes (the prefix is itself a message of the format); 0 differences |
| Plan blobs with one to four bytes changed | 2,484,000 | no panic; 1,540,703 still parsed and were run |

Measured in a build with overflow checks and debug assertions on.

## Measured sizes

One plan and the engine, linked for `thumbv7em-none-eabihf` (Cortex-M4F and
M7F, single-precision floating-point unit) with `opt-level = "z"`, link-time
optimisation and unused sections dropped. `embedded/measure.sh` builds the
image and prints these numbers; `embedded/measure.sh thumbv7em-none-eabihf
"gt-core/sqrt gt-core/trig"` gives the image with the derive features. The
sizes depend on the Rust compiler; these are from Rust 1.99.

The plan is Remote ID `location` to ASTERIX CAT062, as compiled in the
workflow above: 68 operations, 14 keys, nesting 3.

| | Bytes |
|---|---|
| Plan blob (in `.rodata`, 1,758 bytes in all) | 1,752 |
| Code (`.text`), no derive features | 30,580 |
| Code (`.text`), with `sqrt` and `trig` | 34,804 |
| Zero-initialised data of the measurement image (`.bss`) | 81 |

Of the 30,580 bytes of code, about 23,900 are the engine and the C wrapper,
and about 6,600 are support routines the compiler adds for this target:
double-precision arithmetic in software, 64-bit division and memory copy. The
engine computes in doubles because the reference engine does; on a core with a
double-precision unit the support routines are not linked.

The plan blob by table:

| Table | Bytes |
|---|---|
| header and section directory | 148 |
| formats | 32 |
| operations | 1,088 |
| pool (constants, scales, table entries) | 248 |
| `if` conditions | 40 |
| value tables | 8 |
| keys | 56 |
| derive lines and their arguments | 10 |
| plan | 12 |
| carry (the conversion plan) | 108 |

Working memory for this plan: it needs a `Scratch<9>`; the example takes a
`Scratch<12>` of 384 bytes, so a pack change that adds a value or two does not
refuse the example. Then the 25-byte input
and an output buffer of 32 bytes.

Stack. `embedded/elfsize.py` bounds the stack from the disassembly of the
linked image: the bytes each function pushes and reserves, added along the
deepest chain of calls, with the functions that walk nested blocks counted
once per level of nesting. For this plan (nesting 3, counted as 4) the bound
is 3,476 bytes from the entry of `gt_rid_location_to_cat062`; for the deepest
plan the compiler accepts (nesting 12) it is 6,420 bytes. This is a bound
computed from the image, not a measurement on a running device.
`elfsize.py` needs a disassembler that reads ARM images: LLVM's
`llvm-objdump`, or the one `rustup component add llvm-tools` installs.
`GT_DEPTH=4 embedded/measure.sh` gives the bound for nesting counted as 4.

For comparison, the whole `nmea2000` pack (473 kinds) compiled both ways with
names is 161,356 bytes, and the whole `ais` pack (22 kinds, six-bit armor)
10,352 bytes. `nmea2000` compiled for the one kind `pgn129025`, without names,
is 19,992 bytes: the kinds before it stay in the plan as selectors, so that a
message of another kind is refused and not read as this one.

## What is not supported and not done

- Text wires. A conversion with `xml`, `geojson`, `json` or `protobuf` on
  either side is refused by the compiler.
- Running on hardware. The image for `thumbv7em-none-eabihf` links and its
  sizes are measured; it was not executed on a microcontroller or an emulator.
  Equivalence is measured on the host, where the same source runs.
- Other targets. `thumbv6m-none-eabi` and `riscv32imc-unknown-none-elf` were
  not built.
- `east_of` and `north_of` for a course beyond ±94 million degrees leave the
  target absent, where the reference engine computes a value.
- A message with more values or list items than the caller's `Scratch` holds
  is `scratch-full`. The reference engine has no such limit. The limit on
  list items of engine-spec ruling 7 of 0.11 is the same on both
  (`Session::set_max_items`, `gt_core::convert_limited`; 100,000 by
  default), and a count is compared with it before any item is read, so a
  count above the limit is `malformed-wire` whatever the scratch. A vector
  whose items fit the limit and not the proof's scratch (`SLOTS`, 4,096) is
  left out of the equivalence run with the reason `scratch-full`.
- Text values are never copied: a text value is read from the input message,
  the plan or the caller's context when it is written. A derivation that
  builds new text (`join`, `text_of`) is therefore not compiled.
- `tools/goat-pkg` does not yet plan an embedded package. Designed: a
  `--runtime bare` constraint that prints the `packc.py` command and the
  `gt-core` features for the formats asked for.
