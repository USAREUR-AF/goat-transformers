// node.mjs: what a Node host adds to goat_transformers.mjs. It reads the
// WebAssembly module that ships beside this file, and loads packs from a tree
// on disk. A browser host uses goat_transformers.mjs and fetches the texts.
//
//   import { loadTree } from "@usareur-af/goat-transformers/node";
//   const gt = await loadTree("vendor/goat", ["cot-xml", "geojson"]);
//   const out = gt.convert("cot-xml", "geojson", xml);

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { GoatTransformers } from "./goat_transformers.mjs";

export { GoatTransformers };

/** The path of the WebAssembly module in this package. */
export const wasmPath = fileURLToPath(new URL("./dist/goat_transformers.wasm", import.meta.url));

/**
 * An empty engine on the WebAssembly module in this package. `options` are
 * those of GoatTransformers.load: `{ maxDistribution: "public" }` makes an
 * engine that refuses everything marked `distribution controlled`.
 */
export async function load(options) {
  return GoatTransformers.load(readFileSync(wasmPath), options);
}

// The `module` name and the `uses` names of a module or pack text.
function head(text) {
  let name = null;
  const uses = [];
  for (const m of text.matchAll(/^[ \t]*(module|uses)[ \t]+([^\s#]+)[ \t]*(?:#.*)?$/gm)) {
    if (m[1] === "uses") uses.push(m[2]);
    else if (name === null) name = m[2];
  }
  return { name, uses };
}

/**
 * Load the named packs from `<root>/packs/<name>/pack.def`, and before them
 * the model modules they need from `<root>/model/*.def`: `core`, every module
 * a named pack `uses`, and every module one of those `uses`, each after the
 * modules it uses. Nothing else in the tree is loaded.
 *
 * A tree is a directory holding `model/` and `packs/`: a checkout of the
 * library, or a bundle written by `tools/goat-pkg bundle`.
 *
 * `engine` is an engine to load into; it must not already hold one of the
 * modules. Without it a new engine is made. Returns the engine. To load a
 * tree under a distribution limit, pass an engine made with that limit:
 * `loadTree(root, packs, await load({ maxDistribution: "public" }))`.
 */
export async function loadTree(root, packs, engine) {
  const texts = [];
  for (const name of new Set(packs)) {
    const def = join(root, "packs", name, "pack.def");
    if (!existsSync(def)) throw new Error(`unknown-format: no pack ${name} under ${join(root, "packs")}`);
    texts.push(readFileSync(def, "utf8"));
  }
  const heads = new Map(); // module name -> { text, uses }
  const modelDir = join(root, "model");
  if (existsSync(modelDir)) {
    const byBytes = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b));
    for (const file of readdirSync(modelDir).filter((n) => n.endsWith(".def")).sort(byBytes)) {
      const text = readFileSync(join(modelDir, file), "utf8");
      const { name, uses } = head(text);
      if (name !== null && !heads.has(name)) heads.set(name, { text, uses });
    }
  }
  const order = [];
  const placing = new Set();
  const place = (name) => {
    // a module no file declares is left to the pack's load: unknown-module
    if (order.includes(name) || !heads.has(name)) return;
    if (placing.has(name)) throw new Error(`bad-directive: the uses lines of the model modules form a cycle through ${name}`);
    placing.add(name);
    for (const used of heads.get(name).uses) if (used !== name) place(used);
    placing.delete(name);
    order.push(name);
  };
  place("core");
  for (const text of texts) for (const used of head(text).uses) place(used);

  const gt = engine ?? (await load());
  for (const name of order) gt.loadModel(heads.get(name).text);
  for (const text of texts) gt.loadPack(text);
  return gt;
}
