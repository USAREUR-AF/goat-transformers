#!/usr/bin/env node
// Canonical Track v2 JSON on stdin, CoT event XML on stdout, through the
// WebAssembly module. The track does not say when it goes stale, so the
// caller supplies it as the context key `stale_ms`.
//
//   node translate.mjs [--stale-after-ms <n>] [--wasm <file>] < track.json
//
// --stale-after-ms  how long after `observedAt` the event goes stale
//                   (default 180000)

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { GoatTransformers } from "../goat_transformers.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");

function option(name, fallback) {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : fallback;
}

const wasmPath = option("--wasm", join(here, "../target/wasm32-unknown-unknown/release/goat_transformers_wasm.wasm"));
const staleAfterMs = Number(option("--stale-after-ms", "180000"));
if (!Number.isInteger(staleAfterMs)) {
  console.error("--stale-after-ms needs a whole number of milliseconds");
  process.exit(2);
}

// Load only what this conversion needs: two model modules, two packs.
const gt = await GoatTransformers.load(readFileSync(wasmPath));
for (const module of ["core", "track"]) gt.loadModel(readFileSync(join(root, "model", `${module}.def`)));
for (const pack of ["canonical-track-v2", "cot-xml"]) gt.loadPack(readFileSync(join(root, "packs", pack, "pack.def")));

const input = readFileSync(0, "utf8").trim();
const observedAt = Date.parse(JSON.parse(input).observedAt);
if (Number.isNaN(observedAt)) {
  console.error("the track has no readable observedAt");
  process.exit(1);
}

try {
  console.log(gt.convert("canonical-track-v2", "cot-xml", input, { stale_ms: observedAt + staleAfterMs }));
} catch (e) {
  console.error(`convert error: ${e.message}`);
  process.exit(1);
}
