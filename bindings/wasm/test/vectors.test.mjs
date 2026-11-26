// Conformance through the WebAssembly module: load model/*.def and the packs,
// run every conversion vector of the loaded packs, compare with `expect` or
// `expect_error` (spec/vector-format.md), with the vector's `max_items` as
// the limit on list items. `model` checks are not run: the module's
// interface has no decode.
//
//   node --test bindings/wasm/test/vectors.test.mjs
//
// GT_WASM   path of the .wasm (default: the release build under target/)
// GT_PACKS  comma-separated pack directory names (default: every pack)

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { byBytes, loadEngine, root, wasm } from "./support.mjs";

function packNames() {
  const all = readdirSync(join(root, "packs"))
    .filter((n) => existsSync(join(root, "packs", n, "pack.def")))
    .sort(byBytes);
  if (!process.env.GT_PACKS) return all;
  const chosen = process.env.GT_PACKS.split(",").map((s) => s.trim()).filter(Boolean);
  for (const n of chosen) assert.ok(all.includes(n), `GT_PACKS names no pack directory: ${n}`);
  return chosen;
}

// The limit on list items when a vector does not set one (ruling 7 of 0.11).
const DEFAULT_MAX_ITEMS = 100000;

// One conversion vector. Returns null when it passes, else what went wrong.
function checkVector(gt, v) {
  let got;
  // `max_items`: the limit on list items for this vector
  gt.setMaxItems(v.max_items === undefined ? DEFAULT_MAX_ITEMS : v.max_items);
  try {
    // a `context` member, even an empty one, is a context given
    got = gt.convert(v.from, v.to, v.input, v.context);
  } catch (e) {
    if (v.expect_error === undefined) return `convert failed: ${e.message}`;
    return e.message.startsWith(`${v.expect_error}:`) ? null : `want error kind ${v.expect_error}, got: ${e.message}`;
  }
  if (v.expect_error !== undefined) return `should fail with ${v.expect_error}, produced ${got}`;
  if (typeof v.expect !== "string") return "no `expect`";
  return got === v.expect ? null : `(${v.from} -> ${v.to}) output mismatch\n  got  ${got}\n  want ${v.expect}`;
}

test("every conversion vector of the loaded packs", async () => {
  const packs = packNames();
  const started = performance.now();
  const gt = await loadEngine(packs);
  const loadMs = performance.now() - started;
  const formats = new Set(gt.formats());
  assert.equal(formats.size, packs.length, "one format per pack loaded");

  let passed = 0;
  let skipped = 0;
  let runs = 0; // vectors of `convert_run`: the wrapper offers `convert` only (ruling 14 of 0.92)
  const failures = [];
  const runStarted = performance.now();
  for (const pack of packs) {
    const dir = join(root, "packs", pack, "vectors");
    if (!existsSync(dir)) continue;
    for (const file of readdirSync(dir).filter((n) => n.endsWith(".json")).sort(byBytes)) {
      const v = JSON.parse(readFileSync(join(dir, file), "utf8"));
      // a vector to a pack that was not chosen cannot run; a vector naming a
      // format that is no pack directory pins `unknown-format` and runs
      const unchosen = (name) => !formats.has(name) && existsSync(join(root, "packs", name, "pack.def"));
      if (unchosen(v.from) || unchosen(v.to)) {
        skipped++;
        continue;
      }
      if (v.expect_results !== undefined || v.run === true) {
        runs++;
        continue;
      }
      const why = checkVector(gt, v);
      if (why === null) passed++;
      else failures.push(`${pack}/vectors/${file}: ${why}`);
    }
  }
  const runMs = performance.now() - runStarted;
  gt.dispose();
  console.log(
    `goat-transformers wasm: ${passed} vectors passed, ${failures.length} failed, ${skipped} skipped ` +
      `(target format not loaded), ${runs} of convert_run set aside; ${packs.length} packs, ${wasm.length} byte module, ` +
      `load ${loadMs.toFixed(0)} ms, run ${runMs.toFixed(0)} ms`,
  );
  assert.deepEqual(failures, []);
  assert.ok(passed > 0, "no vector ran");
  if (!process.env.GT_PACKS) assert.equal(skipped, 0, "with every pack loaded no vector is skipped");
});
