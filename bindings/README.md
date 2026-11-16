# Bindings: the Rust engine inside another language

Two builds of the Rust reference engine (`engines/rust`) for a host that does
not carry an engine of its own:

| Directory | What it builds | For |
|---|---|---|
| `c/` | `libgoat_transformers_c`, shared and static, with `goat_transformers.h` | C, C++, and any language that can call C |
| `wasm/` | `goat_transformers_wasm.wasm` with `goat_transformers.mjs` and its types | Node, browsers, TypeScript hosts |

Both are thin: hand-written glue over the engine's public API, no dependency
beyond the Rust standard library. `c/install.sh <prefix>` installs the C
library with its header and a pkg-config file; `wasm/` is also the npm package
`@usareur-af/goat-transformers`, built by `wasm/build.sh` and `npm pack`
([docs/using.md](../docs/using.md)). The engine source is not
changed. Both are a way to ship the engine; neither is a voice in the vector
cross-check, which always runs the independent native engines
(`spec/interop-and-sharing.md`).

Status: built and tested on macOS (arm64). The CI job in `ci-job.yml.txt` is a
proposal and has not run.

## What both offer

- create and free an engine;
- load a model module from the text of a `model/<module>.def` (`core` first);
- load a pack from the text of a `packs/<format>/pack.def`;
- convert a message from one loaded format to another, with an optional
  context (model keys the input does not carry, `spec/engine-spec.md`
  Version 0.6);
- list the loaded formats.

The host reads the files; the bindings take text. A message of a binary wire
(`bits`, `protobuf`) is hex text on both sides, as in the vectors. An error is
the engine's named error, the kind then a colon then the text
(`malformed-wire: ...`). The bindings add two kinds of their own:
`bad-argument` and `panic`.

Not offered: `decode`, `encode`, `model_keys`, `capability`, the distribution
limit, and the directory loaders. The npm package's Node entry (`wasm/node.mjs`)
adds `loadTree(root, packs)`, which reads the named packs and the modules they
use from a directory.

## C library

Build and test:

```
cd bindings/c
./test.sh
```

`test.sh` runs `cargo build --release`, compiles `test/test.c` with `cc` once
against the shared library and once against the static library, and runs both.
The test loads `model/core.def`, `model/track.def` and the `cot-xml`,
`geojson` and `canonical-track-v2` packs from this repository, converts
vectors of those packs and compares with their `expect`, and checks the error
paths.

The build leaves, under `bindings/c/target/release/`:

| File | Size (macOS arm64) |
|---|---|
| `libgoat_transformers_c.dylib` (`.so` on Linux) | 1,004,128 bytes |
| `libgoat_transformers_c.a` | 18,999,032 bytes |

Use:

```c
#include "goat_transformers.h"

gt_engine *e = gt_engine_new();
gt_buf out = {0};
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

Rules, stated in full in the header:

- Every text argument is a pointer and a byte length, UTF-8.
- Every call returns a status (`GT_OK`, `GT_ERR_ENGINE`, `GT_ERR_ARGUMENT`,
  `GT_ERR_PANIC`) and fills a `gt_buf` with the result or the error text. The
  caller frees it with `gt_buf_free`.
- A context is text, one `key=value` per line. `NULL` is no context. A value
  cannot hold a line break.
- No global state. Converting and listing may run on several threads at once
  on one engine; loading needs the engine to itself.
- No panic leaves the library. A panic inside a load makes the engine refuse
  every later call.

## WebAssembly module

Build (needs `rustup target add wasm32-unknown-unknown`):

```
cd bindings/wasm
cargo build --release --target wasm32-unknown-unknown
cargo build --profile small --target wasm32-unknown-unknown
```

| Build | File under `bindings/wasm/target/wasm32-unknown-unknown/` | Size | gzip -9 |
|---|---|---|---|
| `--release` | `release/goat_transformers_wasm.wasm` | 589,760 bytes | 200,531 bytes |
| `--profile small` (`opt-level = "z"`, `lto`, `strip`, one codegen unit, `panic = "abort"`) | `small/goat_transformers_wasm.wasm` | 346,027 bytes | 139,601 bytes |

The module has no imports. The `.wasm` is a build product and is not kept in
the repository.

Test, from the repository root:

```
node --test bindings/wasm/test/vectors.test.mjs
GT_WASM=bindings/wasm/target/wasm32-unknown-unknown/small/goat_transformers_wasm.wasm node --test bindings/wasm/test/vectors.test.mjs
GT_PACKS=cot-xml,geojson,canonical-track-v2 node --test bindings/wasm/test/vectors.test.mjs
```

The test loads every `model/*.def` and every pack, runs every conversion
vector of the loaded packs through the module and compares with `expect` or
`expect_error`. With all 96 packs loaded: 3291 vectors, 3291 passed, on both
builds (`python3 -I tools/repo-stats` prints the current counts of packs and
vectors, and the size of a built module). The test prints the load time and
the run time. `GT_PACKS` chooses packs; a vector whose target format is not
among them is counted as skipped. The `model` checks of a vector are not run,
because the module has no decode call. Load vectors are not run.

Use (`goat_transformers.d.ts` gives the types to a TypeScript host):

```js
import { readFileSync } from "node:fs";
import { GoatTransformers } from "./goat_transformers.mjs";

const gt = await GoatTransformers.load(readFileSync("goat_transformers_wasm.wasm"));
gt.loadModel(readFileSync("model/core.def", "utf8"));
gt.loadModel(readFileSync("model/track.def", "utf8"));
gt.loadPack(readFileSync("packs/canonical-track-v2/pack.def", "utf8"));
gt.loadPack(readFileSync("packs/cot-xml/pack.def", "utf8"));

gt.formats();                                   // ["canonical-track-v2", "cot-xml"]
const xml = gt.convert("canonical-track-v2", "cot-xml", trackJson, { stale_ms: 1614456180250 });
gt.dispose();
```

- `convert` returns a string and throws an `Error` whose `message` is the
  engine's named error.
- `context` is an object or a `Map`; omitted means no context.
- Each `load` gives a separate engine with its own memory.
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
| `gt_load_model(engine, ptr, len) -> result` | load a model module text |
| `gt_load_pack(engine, ptr, len) -> result` | load a pack text |
| `gt_convert(engine, from, from_len, to, to_len, input, input_len, has_context, context, context_len) -> result` | convert; context is `key=value\n` text |
| `gt_formats(engine) -> result` | format names, one per line |
| `gt_result_ok(result)`, `gt_result_ptr(result)`, `gt_result_len(result)`, `gt_result_free(result)` | read a result (1: the result text, 0: the error text), then release it |

Read `memory.buffer` again after every call: growing the memory replaces it.
