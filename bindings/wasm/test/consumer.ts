// A TypeScript host of the package, compiled and never run:
//
//   tsc --noEmit --strict --target es2022 --module nodenext --skipLibCheck false bindings/wasm/test/consumer.ts
//
// It fails to compile when goat_transformers.d.ts or node.d.ts stop
// describing what goat_transformers.mjs and node.mjs do: every use below is
// one the wrapper accepts (test/wrapper.test.mjs runs the same calls), and
// every line under @ts-expect-error is one the wrapper refuses with a
// TypeError. An expectation that is not met is itself a compile error, so a
// declaration that fell back to `any` cannot pass.
//
// The package is imported by its name, as an installed copy is: the name
// resolves through the `exports` of package.json to the two declaration files.

import GoatTransformersDefault, { GoatTransformers } from "@usareur-af/goat-transformers";
import type { Context, Distribution, LoadOptions, Text } from "@usareur-af/goat-transformers";
import { GoatTransformers as FromNode, load, loadTree, wasmPath } from "@usareur-af/goat-transformers/node";
import type { LoadOptions as NodeLoadOptions } from "@usareur-af/goat-transformers/node";

declare const wasmBytes: Uint8Array;
declare const compiled: WebAssembly.Module;

// load: bytes, an ArrayBuffer or a compiled module; the options are optional
const gt: GoatTransformers = await GoatTransformers.load(wasmBytes);
await GoatTransformers.load(wasmBytes.buffer as ArrayBuffer);
await GoatTransformers.load(compiled, {});
const limit: Distribution = "public";
const options: LoadOptions = { maxDistribution: limit };
const limited: GoatTransformers = await GoatTransformers.load(wasmBytes, options);
await GoatTransformers.load(wasmBytes, { maxDistribution: "controlled" });

// texts are strings or bytes
const texts: Text[] = ["text", wasmBytes, new ArrayBuffer(1)];
for (const text of texts) {
  gt.loadModel(text);
  gt.loadPack(text);
  const converted: string = gt.convert("a", "b", text);
  void converted;
}

// a context is an object or a Map of string, number, bigint or boolean; or absent
const asObject: Context = { stale_ms: 1614456180250, how: "m-p", big: 10n, flag: true };
const asMap: Context = new Map<string, string | number>([["how", "m-p"]]);
gt.convert("a", "b", "input", asObject);
gt.convert("a", "b", "input", asMap);
gt.convert("a", "b", "input", {});
gt.convert("a", "b", "input", undefined);
gt.convert("a", "b", "input", null);

const names: string[] = gt.formats();
const bytes: number = gt.memoryBytes;
const nothing: void = gt.dispose();
void names, bytes, nothing, limited;

// the default export and the Node entry's export are the same class
const sameDefault: typeof GoatTransformers = GoatTransformersDefault;
const sameFromNode: typeof GoatTransformers = FromNode;
void sameDefault, sameFromNode;

// the Node entry
const path: string = wasmPath;
const fromPackage: GoatTransformers = await load();
const nodeOptions: NodeLoadOptions = { maxDistribution: "public" };
const fromTree: GoatTransformers = await loadTree("vendor/goat", ["cot-xml", "geojson"]);
const packs: readonly string[] = ["cot-xml"];
await loadTree("vendor/goat", packs, await load(nodeOptions));
void path, fromPackage, fromTree;

// ---- what the wrapper refuses, the declarations refuse too --------------------

// @ts-expect-error the constructor is not for a host: use GoatTransformers.load
new GoatTransformers();
// @ts-expect-error a limit is "public" or "controlled"
await GoatTransformers.load(wasmBytes, { maxDistribution: "secret" });
// @ts-expect-error the options are an object
await GoatTransformers.load(wasmBytes, "public");
// @ts-expect-error a text is a string or bytes
gt.loadModel(7);
// @ts-expect-error a text is a string or bytes
gt.loadPack(null);
// @ts-expect-error a format name is a string
gt.convert(7, "b", "input");
// @ts-expect-error an input is a string or bytes
gt.convert("a", "b", { input: true });
// @ts-expect-error a context is not a string
gt.convert("a", "b", "input", "how=m-p");
// @ts-expect-error a context value is not null
gt.convert("a", "b", "input", { how: null });
// @ts-expect-error a context value is not an object
gt.convert("a", "b", "input", new Map([["how", {}]]));
// @ts-expect-error formats() gives strings
const notNumbers: number[] = gt.formats();
// @ts-expect-error the memory size is read, not set
gt.memoryBytes = 0;
// @ts-expect-error loadTree takes pack names
await loadTree("vendor/goat", "cot-xml");
// @ts-expect-error loadTree's third argument is an engine, not options
await loadTree("vendor/goat", ["cot-xml"], { maxDistribution: "public" });
// @ts-expect-error formats() of an engine from loadTree gives strings
const alsoNotNumbers: number[] = fromTree.formats();
void notNumbers, alsoNotNumbers;
