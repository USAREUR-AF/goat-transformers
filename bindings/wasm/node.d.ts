/** Types of node.mjs: the Node entry of the package. */

// The main entry is named as a consumer names it. A relative import of
// "./goat_transformers.mjs" would make TypeScript look for a file
// goat_transformers.d.mts, find none, and type everything below as `any`.
import { GoatTransformers } from "@usareur-af/goat-transformers";
import type { LoadOptions } from "@usareur-af/goat-transformers";

export { GoatTransformers };
export type { Context, Distribution, LoadOptions, Text } from "@usareur-af/goat-transformers";

/** The path of the WebAssembly module in this package. */
export declare const wasmPath: string;

/** An empty engine on the WebAssembly module in this package. */
export declare function load(options?: LoadOptions): Promise<GoatTransformers>;

/**
 * Load the named packs from `<root>/packs/<name>/pack.def`, and before them
 * the model modules they need from `<root>/model/*.def`: `core`, every module
 * a named pack `uses`, and every module one of those `uses`. Nothing else in
 * the tree is loaded.
 * @param root a directory holding `model/` and `packs/`
 * @param packs pack directory names
 * @param engine an engine to load into, for example one made with a
 *   distribution limit by `load({ maxDistribution: "public" })`; omitted: a
 *   new one
 * @returns the engine
 */
export declare function loadTree(
  root: string,
  packs: readonly string[],
  engine?: GoatTransformers,
): Promise<GoatTransformers>;
