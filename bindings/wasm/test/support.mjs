// What the tests of the WebAssembly module share: where the repository and
// the built module are, and an engine loaded from the repository's files.
//
// GT_WASM   path of the .wasm (default: the release build under target/)

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { GoatTransformers } from "../goat_transformers.mjs";

const here = dirname(fileURLToPath(import.meta.url));

/** The repository root. */
export const root = resolve(here, "../../..");

/** The bytes of the module under test. */
export const wasm = readFileSync(
  resolve(process.env.GT_WASM ?? join(here, "../target/wasm32-unknown-unknown/release/goat_transformers_wasm.wasm")),
);

/** Byte order of names, as the engine's directory loaders use. */
export const byBytes = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b));

/** The text of a file of the repository. */
export const repositoryText = (...path) => readFileSync(join(root, ...path), "utf8");

/** A vector file of the repository, parsed. */
export const vector = (pack, file) => JSON.parse(repositoryText("packs", pack, "vectors", file));

// The model files in load order: core.def first, then byte order, each
// module after the modules its `uses` lines name (spec/engine-spec.md, Model
// additions in 0.8).
function modelFiles() {
  const names = readdirSync(join(root, "model")).filter((n) => n.endsWith(".def")).sort(byBytes);
  const order = ["core.def", ...names.filter((n) => n !== "core.def")];
  const uses = new Map();
  for (const file of order) {
    uses.set(file, [...repositoryText("model", file).matchAll(/^\s*uses\s+(\S+)/gm)].map((m) => `${m[1]}.def`));
  }
  const done = [];
  const visit = (file, path) => {
    if (done.includes(file) || !uses.has(file)) return;
    if (path.includes(file)) throw new Error(`model modules use each other in a cycle: ${file}`);
    for (const used of uses.get(file)) visit(used, [...path, file]);
    done.push(file);
  };
  for (const file of order) visit(file, []);
  return done;
}

/** A new engine holding every model module and the named packs. */
export async function loadEngine(packs, options) {
  const gt = await GoatTransformers.load(wasm, options);
  for (const file of modelFiles()) gt.loadModel(repositoryText("model", file));
  for (const pack of packs) gt.loadPack(readFileSync(join(root, "packs", pack, "pack.def")));
  return gt;
}
