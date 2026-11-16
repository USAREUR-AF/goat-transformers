// Conformance through the WebAssembly module: load model/*.def and the packs,
// run every conversion vector of the loaded packs, compare with `expect` or
// `expect_error` (spec/vector-format.md). `model` checks are not run: the
// module's interface has no decode.
//
//   node --test bindings/wasm/test/
//
// GT_WASM   path of the .wasm (default: the release build under target/)
// GT_PACKS  comma-separated pack directory names (default: every pack)

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { GoatTransformers } from "../goat_transformers.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");
const wasmPath = resolve(
  process.env.GT_WASM ?? join(here, "../target/wasm32-unknown-unknown/release/goat_transformers_wasm.wasm"),
);
const wasm = readFileSync(wasmPath);

// byte order of name, as the engine's directory loaders use
const byBytes = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b));

// core.def first, then byte order, each module after the modules its `uses`
// lines name (spec/engine-spec.md, Model additions in 0.8).
function modelFiles() {
  const names = readdirSync(join(root, "model")).filter((n) => n.endsWith(".def")).sort(byBytes);
  const order = ["core.def", ...names.filter((n) => n !== "core.def")];
  const uses = new Map();
  for (const f of order) {
    const text = readFileSync(join(root, "model", f), "utf8");
    uses.set(f, [...text.matchAll(/^\s*uses\s+(\S+)/gm)].map((m) => `${m[1]}.def`));
  }
  const done = [];
  const visit = (f, path) => {
    if (done.includes(f) || !uses.has(f)) return;
    if (path.includes(f)) throw new Error(`model modules use each other in a cycle: ${f}`);
    for (const dep of uses.get(f)) visit(dep, [...path, f]);
    done.push(f);
  };
  for (const f of order) visit(f, []);
  return done;
}

function packNames() {
  const all = readdirSync(join(root, "packs"))
    .filter((n) => existsSync(join(root, "packs", n, "pack.def")))
    .sort(byBytes);
  if (!process.env.GT_PACKS) return all;
  const chosen = process.env.GT_PACKS.split(",").map((s) => s.trim()).filter(Boolean);
  for (const n of chosen) assert.ok(all.includes(n), `GT_PACKS names no pack directory: ${n}`);
  return chosen;
}

async function loadEngine(packs) {
  const gt = await GoatTransformers.load(wasm);
  for (const f of modelFiles()) gt.loadModel(readFileSync(join(root, "model", f), "utf8"));
  for (const p of packs) gt.loadPack(readFileSync(join(root, "packs", p, "pack.def")));
  return gt;
}

// One conversion vector. Returns null when it passes, else what went wrong.
function checkVector(gt, v) {
  let got;
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
  const failures = [];
  const runStarted = performance.now();
  for (const pack of packs) {
    const dir = join(root, "packs", pack, "vectors");
    if (!existsSync(dir)) continue;
    for (const file of readdirSync(dir).filter((n) => n.endsWith(".json")).sort(byBytes)) {
      const v = JSON.parse(readFileSync(join(dir, file), "utf8"));
      // a vector to a format that was not chosen cannot run
      if (!formats.has(v.from) || !formats.has(v.to)) {
        skipped++;
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
      `(target format not loaded); ${packs.length} packs, ${wasm.length} byte module, ` +
      `load ${loadMs.toFixed(0)} ms, run ${runMs.toFixed(0)} ms`,
  );
  assert.deepEqual(failures, []);
  assert.ok(passed > 0, "no vector ran");
  if (!process.env.GT_PACKS) assert.equal(skipped, 0, "with every pack loaded no vector is skipped");
});

test("the class API", async () => {
  const gt = await loadEngine(["cot-xml", "geojson", "canonical-track-v2"]);
  assert.deepEqual(gt.formats(), ["canonical-track-v2", "cot-xml", "geojson"]);

  const cot = JSON.parse(readFileSync(join(root, "packs/cot-xml/vectors/01-track-to-geojson.json"), "utf8"));
  assert.equal(gt.convert("cot-xml", "geojson", cot.input), cot.expect);
  // input as bytes, context as a Map
  const trk = JSON.parse(
    readFileSync(join(root, "packs/canonical-track-v2/vectors/09-to-cot-xml-context-stale-and-how.json"), "utf8"),
  );
  const bytes = new TextEncoder().encode(trk.input);
  assert.equal(gt.convert(trk.from, trk.to, bytes, new Map(Object.entries(trk.context))), trk.expect);
  // a number is written with String()
  assert.equal(gt.convert(trk.from, trk.to, trk.input, { stale_ms: 1614456180250, how: "m-p" }), trk.expect);

  // errors carry the engine's kind, and the engine stays usable
  assert.throws(() => gt.convert("cot-xml", "cot-xml", cot.input, { "no.such_key": "1" }), /^Error: undeclared-key:/);
  assert.throws(() => gt.convert("cot-xml", "geojson", cot.input, { stale_ms: "soon" }), /^Error: key-type-mismatch:/);
  assert.throws(() => gt.convert("no-such-format", "geojson", "x"), Error);
  assert.throws(() => gt.loadPack("format x\n"), Error);
  assert.throws(() => gt.convert("cot-xml", "geojson", cot.input, { "a=b": "1" }), TypeError);
  assert.throws(() => gt.convert("cot-xml", "geojson", 7), TypeError);
  assert.throws(() => gt.convert("cot-xml", "geojson", new Uint8Array([0xff, 0xfe])), /^Error: bad-argument:/);
  assert.equal(gt.convert("cot-xml", "geojson", cot.input), cot.expect);

  // two engines do not share state
  const other = await GoatTransformers.load(wasm);
  assert.deepEqual(other.formats(), []);
  other.dispose();

  gt.dispose();
  assert.throws(() => gt.formats(), /disposed/);
});
