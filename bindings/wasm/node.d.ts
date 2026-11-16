/** Types of node.mjs: the Node entry of the package. */

import { GoatTransformers } from "./goat_transformers.mjs";

export { GoatTransformers };
export type { Context } from "./goat_transformers.mjs";

/** The path of the WebAssembly module in this package. */
export declare const wasmPath: string;

/** An empty engine on the WebAssembly module in this package. */
export declare function load(): Promise<GoatTransformers>;

/**
 * Load the named packs from `<root>/packs/<name>/pack.def`, and before them
 * the model modules they need from `<root>/model/*.def`: `core`, every module
 * a named pack `uses`, and every module one of those `uses`. Nothing else in
 * the tree is loaded.
 * @param root a directory holding `model/` and `packs/`
 * @param packs pack directory names
 * @param engine an engine to load into; omitted: a new one
 * @returns the engine
 */
export declare function loadTree(
  root: string,
  packs: readonly string[],
  engine?: GoatTransformers,
): Promise<GoatTransformers>;
