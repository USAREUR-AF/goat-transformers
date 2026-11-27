# Bindings: the Rust engine inside another language

Two builds of the Rust reference engine (`engines/rust`) for a host that does
not carry an engine of its own:

| Directory | What it builds | For |
|---|---|---|
| `c/` | `libgoat_transformers_c`, shared and static, with `goat_transformers.h` | C, C++, and any language that can call C |
| `wasm/` | `goat_transformers_wasm.wasm` with `goat_transformers.mjs` and its types | Node, browsers, TypeScript hosts |

Both are thin: hand-written glue over the engine's public API, no dependency
beyond the Rust standard library. What the two do the same way (reading an
argument, reading a context, setting the distribution limit) is one file,
`shared/glue.rs`, that both include. `c/install.sh <prefix>` installs the C
library with its header and a pkg-config file; `wasm/` is also the npm package
`@usareur-af/goat-transformers`, built by `wasm/build.sh` and `npm pack`
([docs/using.md](../docs/using.md)). The engine source is not
changed. Both are a way to ship the engine; neither is a voice in the vector
cross-check, which always runs the independent native engines
(`spec/interop-and-sharing.md`).

Status: built. Measured on macOS (arm64) with the commands on this page; the
`bindings` job of `.github/workflows/conformance.yml` runs them on Linux.

## What both offer

- create and free an engine;
- set the engine's distribution limit before the first load: limited to
  `public`, the engine refuses every model module and pack marked
  `distribution controlled` with `distribution-refused`
  (`spec/engine-spec.md`, Distribution limit);
- load a model module from the text of a `model/<module>.def` (`core` first);
- load a pack from the text of a `packs/<format>/pack.def`;
- convert a message from one loaded format to another, with an optional
  context (model keys the input does not carry, `spec/engine-spec.md`
  Version 0.6);
- list the loaded formats.

The host reads the files; the bindings take text. A message of a binary wire
(`bits`, `protobuf`) is hex text on both sides, as in the vectors. An error is
the engine's error text; a named error is the kind, then a colon, then the text
(`malformed-wire: ...`). The bindings add two kinds of their own:
`bad-argument` and `panic`.

Not offered: `decode`, `encode`, `model_keys`, `capability`, and the directory
loaders. The npm package's Node entry (`wasm/node.mjs`) adds
`loadTree(root, packs)`, which reads the named packs and the modules they use
from a directory.

## C library

Build and test:

```
cd bindings/c
./test.sh
```

The build leaves, under `bindings/c/target/release/`:

| File | Size (macOS arm64) |
|---|---|
| `libgoat_transformers_c.dylib` (`.so` on Linux) | 1,023,184 bytes |
| `libgoat_transformers_c.a` | 19,062,080 bytes |

Use:

```c
#include "goat_transformers.h"

gt_engine *e = gt_engine_new();
gt_buf out = {0};
gt_engine_set_max_distribution(e, GT_DISTRIBUTION_PUBLIC, NULL);  /* optional */
gt_load_model(e, core_def, core_def_len, &out);   gt_buf_free(&out);
gt_load_pack(e, cot_def, cot_def_len, &out);      gt_buf_free(&out);
gt_load_pack(e, geo_def, geo_def_len, &out);      gt_buf_free(&out);

int32_t rc = gt_convert(e, (const uint8_t *)"cot-xml", 7,
                        (const uint8_t *)"geojson", 7,
                        xml, xml_len,
                        NULL, 0,          /* no context */
                        &out);
if (rc == GT_OK) fwrite(out.data, 1, out.len, stdout);
else fprintf(stderr, "%s\n", (const char *)out.data);
gt_buf_free(&out);
gt_engine_free(e);
```

Link the shared library with `-L<dir> -lgoat_transformers_c`. Link the static
library by naming the `.a` and adding the system libraries the Rust standard
library needs: `-lSystem -lc -lm -liconv` on macOS,
`-lgcc_s -lutil -lrt -lpthread -lm -ldl -lc` on Linux.

Rules, stated in full at the top of the header:

- Every text argument is a pointer and a byte length, UTF-8. A NUL inside it
  is one more character. A length of 0 is the empty text; a NULL pointer with
  another length is refused.
- Every call returns a status (`GT_OK`, `GT_ERR_ENGINE`, `GT_ERR_ARGUMENT`,
  `GT_ERR_PANIC`) and fills a `gt_buf` with the result or the error text. The
  caller owns it and frees it once with `gt_buf_free`, which zeroes it.
- A context is text, one `key=value` per line; the key ends at the first `=`.
  `NULL` is no context. A value cannot hold a line break.
- No global state. Converting and listing may run on several threads at once
  on one engine; setting the limit, loading and freeing need the engine to
  themselves.
- No panic leaves the library: it becomes `GT_ERR_PANIC`. A panic inside a
  call that changes the engine makes the engine refuse every later call.
- The distribution limit is set on a new engine only. On an engine that has
  loaded anything `gt_engine_set_max_distribution` changes nothing and
  returns `GT_ERR_ARGUMENT`, so a limit cannot be lifted or lowered under
  what is loaded.
- `gt_engine_set_max_items(engine, n, out)` sets the limit on list items one
  decode holds (engine-spec ruling 7 of 0.11): 100000 by default, 0 refuses
  any item, and a conversion whose decode would hold one item more fails with
  `malformed-wire`. It may be set at any time; it changes the engine, so it
  needs the engine to itself.
- A format name is loaded once: a second pack of a loaded format name fails
  with `duplicate-format` and the first stays loaded.

### What `test.sh` runs

| Step | What it checks |
|---|---|
| `cargo test --release` | the shared glue (argument and context reading, the limit) and what C cannot reach: a panic becomes `GT_ERR_PANIC` with its message, and a panic while the engine is being changed stops the engine |
| `test/header.c` compiled as C99 and as C++17 with `-Wall -Wextra -Wpedantic -Werror` | the header stands alone in both languages; the type and const-ness of every function; the layout of `gt_buf`; the values of the status and limit constants |
| `nm` on the shared library against the header | the library exports exactly the 9 functions the header declares |
| `test/api.c` | the contract of the header, by statement: a NULL engine in every call; a NULL pointer with a length and with length 0, for every text argument; text that is not UTF-8 or is cut inside a character; a NUL inside a format name, a message and a model text; buffer ownership (a zeroed buffer, the same buffer freed twice, `out == NULL`, a buffer used after its engine is freed, an error text as an owned buffer); error kinds; malformed input (a message cut off inside a tag or an attribute, and cot-xml and geojson nested 65 and 30,000 levels deep, give `GT_ERR_ENGINE` with `malformed-wire`, never `GT_ERR_PANIC`; 64 levels convert); context text (`=` in a value, an empty value, UTF-8, an empty key); the same module loaded twice (`duplicate-module`) and the same pack loaded twice (`duplicate-format`, the first stays loaded, listed once); the distribution limit (a controlled pack and a controlled module refused with `distribution-refused` under `public`, loaded under the default and under `controlled`, a value that is no limit, a limit set after a load). After each group of refusals the engine must still convert. The controlled texts are synthetic and exist only in the test |
| `test/threads.c` | 8 threads, each 1,000 `gt_convert` calls over 6 conversions (4 that succeed, 2 that fail) on one engine, while a ninth thread calls `gt_formats` 2,000 times; all released together; every result equal to the one a single thread got first |
| `test/vectors.c` | every model module and every pack loaded, then every conversion vector under `packs/*/vectors/` through `gt_convert`, with the vector's `max_items` as the limit on list items, compared with `expect` or with the kind in `expect_error`. The `model` checks and the load vectors are not run: the library has no decode call |

Each of the three programs runs four times: against the shared library,
against the static library, under AddressSanitizer with
UndefinedBehaviorSanitizer, and under a leak check. `test/threads.c` also runs
under ThreadSanitizer. `GT_SANITIZE=0` runs only the first two.

Measured on macOS arm64 (Apple clang 21): `api` 158 checks, `threads` 22
checks, `vectors` 3291 of 3291 vectors with 96 packs and 43 model modules; all
pass in every configuration; 0 leaks.

What the sanitizer runs do and do not cover:

- The sanitizers instrument the C programs, and see every allocation and
  release, also those made inside the library. They catch a buffer read past
  its end or after its release from C, a release made twice or of a pointer
  the library did not give, and memory never released. The library is built
  as it ships: the Rust code is not instrumented, so ThreadSanitizer watches
  the C side of the threaded test only.
- Thread safety inside the library rests on the compiler: `c/src/lib.rs`
  fails to build unless the engine type is `Send + Sync`, and `gt_convert`
  and `gt_formats` take the engine read-only.
- Leak detection is LeakSanitizer where the compiler has it (Linux). Apple
  clang has none, so on macOS `test.sh` runs each program under
  `leaks --atExit` instead.

## WebAssembly module

Build (needs `rustup target add wasm32-unknown-unknown`):

```
cd bindings/wasm
cargo build --release --target wasm32-unknown-unknown
cargo build --profile small --target wasm32-unknown-unknown
```

| Build | File under `bindings/wasm/target/wasm32-unknown-unknown/` | Size | gzip -9 |
|---|---|---|---|
| `--release` | `release/goat_transformers_wasm.wasm` | 614,821 bytes | 207,783 bytes |
| `--profile small` (`opt-level = "z"`, `lto`, `strip`, one codegen unit, `panic = "abort"`) | `small/goat_transformers_wasm.wasm` | 361,911 bytes | 145,141 bytes |

Measured with rustc 1.97.1. The module has no imports. The `.wasm` is a build
product and is not kept in the repository.

Test, from the repository root:

```
node --test bindings/wasm/test/*.test.mjs
GT_WASM=bindings/wasm/target/wasm32-unknown-unknown/small/goat_transformers_wasm.wasm node --test bindings/wasm/test/*.test.mjs
GT_PACKS=cot-xml,geojson,canonical-track-v2 node --test bindings/wasm/test/vectors.test.mjs
cd bindings/wasm && cargo test --release
```

`test/vectors.test.mjs` loads every `model/*.def` and every pack, runs every
conversion vector of the loaded packs through the module and compares with
`expect` or `expect_error`. With all 96 packs loaded: 3291 vectors, 3291
passed, on both builds (`python3 -I tools/repo-stats` prints the current counts
of packs and vectors, and the size of a built module). The test prints the load
time and the run time. `GT_PACKS` chooses packs; a vector whose target format
is not among them is counted as skipped. The `model` checks of a vector are not
run, because the module has no decode call. Load vectors are not run.

`test/wrapper.test.mjs` tests `goat_transformers.mjs`, `node.mjs` and the raw
interface, 20 tests, all passing on both builds:

| Subject | What is checked |
|---|---|
| arguments | a message as a string, a `Uint8Array`, a view of part of a buffer, an `ArrayBuffer`, a `Buffer`; a context as an object and as a `Map`; `undefined` and `null` as no context |
| context | `=` in a value, an empty value, text of 1 to 4 UTF-8 bytes per character; a key with `=` refused; a key that is not ASCII reaching the engine whole |
| refused arguments | 10 values that are neither a string nor bytes, in each of the 5 text positions; contexts, keys and values the context text cannot carry: each a `TypeError` that begins `bad-argument:` |
| memory | a message over 1 MiB (the memory grows under the call; the output equals the input character for character); 10,000 conversions (successes, a context, engine errors) with `memoryBytes` unchanged after the first 400; 10,000 refused arguments and 10,000 refusals by the module with `memoryBytes` unchanged; a view made before the memory grows is detached |
| life of an engine | every call after `dispose` fails with `bad-argument: this engine was disposed`; a second `dispose` does nothing; two engines side by side share no modules, packs or memory |
| malformed input | a cot-xml message cut off inside a tag or an attribute, and cot-xml and geojson messages nested 65 and 30,000 levels deep, fail with `malformed-wire`; 64 levels convert; the engine converts afterwards |
| trap | an export that throws as a trap does: the call fails with `panic: the engine trapped: ...`, every later call with `panic: this engine stopped ...`, and the instance is not called again |
| distribution limit | under `maxDistribution: "public"` a controlled pack and a controlled module are refused with `distribution-refused` and public ones load and convert; the default and `"controlled"` load both; a value that is no limit is a `TypeError`; `loadTree` into a limited engine refuses a controlled pack of a tree written to a temporary directory |
| raw interface | a handle of 0 gives an error result in every call; the module imports nothing and exports exactly the documented names |

`test/consumer.ts` is a TypeScript host that is compiled and never run. It
uses every declaration of `goat_transformers.d.ts` and `node.d.ts`, and states
under `@ts-expect-error` the uses the wrapper refuses, so a declaration that
is wrong or resolves to `any` does not compile:

```
npx -p typescript@5.9.3 tsc --noEmit --strict --target es2022 --module nodenext --skipLibCheck false bindings/wasm/test/consumer.ts
```

Measured with TypeScript 5.9.3: no errors, with `--module nodenext` and with
`--module esnext --moduleResolution bundler`.

`cargo test --release` in `bindings/wasm` runs the shared glue tests and
drives the raw interface on the build machine (17 tests).

Use (`goat_transformers.d.ts` gives the types to a TypeScript host):

```js
import { readFileSync } from "node:fs";
import { GoatTransformers } from "./goat_transformers.mjs";

const gt = await GoatTransformers.load(readFileSync("goat_transformers_wasm.wasm"));
gt.loadModel(readFileSync("model/core.def", "utf8"));
gt.loadModel(readFileSync("model/track.def", "utf8"));
gt.loadModel(readFileSync("model/cot.def", "utf8"));
gt.loadPack(readFileSync("packs/canonical-track-v2/pack.def", "utf8"));
gt.loadPack(readFileSync("packs/cot-xml/pack.def", "utf8"));

gt.formats();                                   // ["canonical-track-v2", "cot-xml"]
const xml = gt.convert("canonical-track-v2", "cot-xml", trackJson, { stale_ms: 1614456180250 });
gt.dispose();
```

- `convert` returns a string and throws an `Error` whose `message` is the
  engine's error text.
- An argument the wrapper refuses before the engine runs is a `TypeError`
  whose message begins `bad-argument:`. Nothing is copied into the module for
  such a call.
- `context` is an object or a `Map` of key to string, number, bigint or
  boolean; omitted, `undefined` or `null` means no context.
- `GoatTransformers.load(wasm, { maxDistribution: "public" })` gives an engine
  that loads nothing marked `distribution controlled`. The limit is set when
  the engine is made and cannot be changed afterwards.
- Each `load` gives a separate engine with its own memory. `memoryBytes` is
  the size of that memory; it grows when a call needs more and never shrinks.
- A panic in the engine is a trap in WebAssembly. The object then refuses
  every later call with a `panic:` error; load a new one.

### Example host

`wasm/example/translate.mjs` reads a Canonical Track v2 JSON on stdin and
prints a CoT event, supplying `stale_ms` as context (`observedAt` plus
`--stale-after-ms`, default 180000). It loads two model modules and two packs.

```
node -e 'process.stdout.write(JSON.parse(require("fs").readFileSync("packs/canonical-track-v2/vectors/02-to-cot-xml.json","utf8")).input)' | node bindings/wasm/example/translate.mjs
```

prints

```
<event version="2.0" uid="trk-0042" type="a-u-A-M-F-Q" time="2021-02-27T20:00:00.250Z" start="2021-02-27T20:00:00.250Z" stale="2021-02-27T20:03:00.250Z"><point lat="30.0090027" lon="-85.9578182" hae="1250.5" ce="15" le="30"/><detail><track course="270" speed="40.25"/></detail></event>
```

## The module's raw interface

For a host that does not use `goat_transformers.mjs`. All values are `i32`.

| Export | Meaning |
|---|---|
| `memory` | the linear memory |
| `gt_alloc(len) -> ptr`, `gt_free(ptr, len)` | memory for the host to write an argument into |
| `gt_engine_new() -> engine`, `gt_engine_free(engine)` | an engine |
| `gt_engine_set_max_distribution(engine, limit) -> result` | the distribution limit: 0 `public`, 1 `controlled` (the default); refused after the first load |
| `gt_engine_set_max_items(engine, n) -> result` | the limit on list items one decode holds (`n` unsigned; default 100000); `setMaxItems(n)` in `goat_transformers.mjs` |
| `gt_load_model(engine, ptr, len) -> result` | load a model module text |
| `gt_load_pack(engine, ptr, len) -> result` | load a pack text |
| `gt_convert(engine, from, from_len, to, to_len, input, input_len, has_context, context, context_len) -> result` | convert; context is `key=value\n` text |
| `gt_formats(engine) -> result` | format names, one per line |
| `gt_result_ok(result)`, `gt_result_ptr(result)`, `gt_result_len(result)`, `gt_result_free(result)` | read a result (1: the result text, 0: the error text), then release it |

Read `memory.buffer` again after every call: growing the memory replaces it
and detaches every view made on the old one. An engine or result handle of 0
is refused with an error result (`bad-argument: engine is 0`) or ignored; it
is never read.
