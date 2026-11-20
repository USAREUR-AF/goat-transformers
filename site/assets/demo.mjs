// demo.mjs: the page's copy buttons, and the demo, which runs the library's own
// WebAssembly module (assets/engine/, written by site/build.sh). No dependency,
// no request to another origin.

const $ = (id) => document.getElementById(id);
document.documentElement.classList.replace("no-js", "js");

// ---- copy buttons ----------------------------------------------------------
for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const source = $(button.dataset.copy);
    const text = source.textContent;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch {
      // no clipboard access: select the text so the reader can copy it
      const range = document.createRange();
      range.selectNodeContents(source);
      const selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = "Selected";
    }
    setTimeout(() => (button.textContent = "Copy"), 1600);
  });
}

// ---- the demo --------------------------------------------------------------
const ENGINE = new URL("./engine/", import.meta.url);
const REPO = "https://github.com/USAREUR-AF/goat-transformers/blob/";
const WHY = {
  "no-kind": "The target has no message kind whose required keys this message carries.",
  "malformed-wire": "The input is not a well-formed message of the source format.",
  "transform-decode": "A value in the input cannot be read as the type its field line states.",
  "transform-encode": "A value cannot be written in the form the target's field line states.",
  "undeclared-key": "A supplied key is not declared by any loaded model module.",
  "key-type-mismatch": "A supplied value cannot be read as its key's declared type.",
};

const el = {
  from: $("demo-from"), to: $("demo-to"), input: $("demo-input"), output: $("demo-output"),
  outLabel: $("demo-out-label"), sample: $("demo-sample"), verdict: $("demo-verdict"),
  carried: $("demo-carried"), dropped: $("demo-dropped"), droppedNote: $("demo-dropped-note"),
  cli: $("demo-cli"), status: $("demo-status"), reset: $("demo-reset"),
  context: $("demo-context"), contextWrap: $("demo-context-wrap"),
};

let bundle, gt;
const loadedModules = new Set();
const loadedPacks = new Set();
let loadedBytes = 0;

const text = async (path) => {
  const response = await fetch(new URL(path, ENGINE));
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  const body = await response.text();
  loadedBytes += new TextEncoder().encode(body).length;
  return body;
};
const format = (name) => bundle.formats.find((f) => f.name === name);
const number = (n) => n.toLocaleString("en-US");
const isHex = (s) => /^[0-9a-fA-F]+$/.test(s) && s.length % 2 === 0;
const shellQuote = (s) => (/^[A-Za-z0-9_.,:=\/-]+$/.test(s) ? s : "'" + s.replaceAll("'", "'\\''") + "'");

// Load a format's model modules and pack into the engine, once.
async function ensure(name) {
  if (loadedPacks.has(name)) return;
  for (const module of format(name).uses) {
    if (loadedModules.has(module)) continue;
    gt.loadModel(await text(`model/${module}.def`));
    loadedModules.add(module);
  }
  gt.loadPack(await text(`packs/${name}.def`));
  loadedPacks.add(name);
}

function targetsOf(source) {
  return bundle.formats.filter((f) => bundle.pairs[`${source}>${f.name}`]).map((f) => f.name);
}

function readContext() {
  const context = {};
  for (const line of el.context.value.split("\n")) {
    const at = line.indexOf("=");
    if (at > 0) context[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return context;
}

function fillSelect(select, names, chosen) {
  select.replaceChildren(...names.map((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = `${format(name).label} (${name})`;
    option.selected = name === chosen;
    return option;
  }));
}

function chips(list, keys) {
  list.replaceChildren(...keys.map((key) => {
    const item = document.createElement("li");
    item.textContent = key;
    return item;
  }));
}

function setSample() {
  const source = format(el.from.value);
  el.input.value = source.sample;
  const link = document.createElement("a");
  link.href = REPO + bundle.commit + "/" + source.sample_from;
  link.textContent = source.sample_from;
  const binary = source.wire === "bits" || source.wire === "protobuf";
  el.sample.replaceChildren(
    `${source.label}: ${source.what}${binary ? ", as hex text" : ""}. From `, link, ".");
}

function setPair() {
  const pair = bundle.pairs[`${el.from.value}>${el.to.value}`];
  const entries = Object.entries(pair.context);
  el.context.value = entries.map(([k, v]) => `${k}=${v}`).join("\n");
  el.contextWrap.hidden = entries.length === 0;

  const cap = bundle.capability[`${el.from.value}>${el.to.value}`];
  chips(el.carried, cap.carried);
  if (cap.dropped_count === 0) {
    el.dropped.hidden = true;
    el.droppedNote.hidden = false;
    el.droppedNote.textContent = "None: every key the source maps has a field in the target.";
  } else if (cap.dropped) {
    chips(el.dropped, cap.dropped);
    el.dropped.hidden = false;
    el.droppedNote.hidden = true;
  } else {
    el.dropped.hidden = true;
    el.droppedNote.hidden = false;
    const code = document.createElement("code");
    code.textContent = "goat-xf matrix --detail";
    el.droppedNote.replaceChildren(
      `${number(cap.dropped_count)} keys of ${format(el.from.value).label}. `, code, " prints all of them.");
  }
}

async function run() {
  const from = el.from.value, to = el.to.value, input = el.input.value.trim();
  const context = readContext();
  const sets = Object.entries(context).map(([k, v]) => ` --set ${shellQuote(`${k}=${v}`)}`).join("");
  el.cli.textContent =
    `echo ${shellQuote(input)} | goat-xf convert --from ${from} --to ${to} --packs-only ${from},${to}${sets}`;
  el.outLabel.textContent = `Message out: ${format(to).label}`;

  let output, failed = false;
  const started = performance.now();
  try {
    await ensure(from);
    await ensure(to);
    output = gt.convert(from, to, input, Object.keys(context).length ? context : undefined);
  } catch (error) {
    failed = true;
    output = error.message;
    if (output.startsWith("panic:")) gt = await newEngine();
  }
  const ms = performance.now() - started;

  el.output.classList.toggle("err", failed);
  el.output.textContent = output;
  if (failed) {
    const kind = output.split(":")[0];
    el.verdict.textContent = `The engine refused the message with the named error ${kind}. ${WHY[kind] ?? ""}`;
  } else {
    const pair = bundle.pairs[`${from}>${to}`];
    const sameInput = input === format(from).sample &&
      JSON.stringify(context) === JSON.stringify(pair.context);
    const size = isHex(output) ? `${number(output.length / 2)} bytes as hex text. ` : "";
    if (sameInput && output === pair.expect) {
      el.verdict.textContent = `${size}Equal to what goat-xf printed for this input when the page was built.`;
    } else if (sameInput) {
      el.verdict.textContent = `${size}DIFFERS from what goat-xf printed when the page was built: ${pair.expect}`;
    } else {
      el.verdict.textContent = `${size}Converted here from your edited input in ${ms.toFixed(1)} ms.`;
    }
  }
  status();
}

function status() {
  const wasm = bundle.stats.wasm_bytes;
  const b = (s) => { const e = document.createElement("b"); e.textContent = s; return e; };
  el.status.replaceChildren(
    "Engine: ", b("goat_transformers_wasm.wasm"), `, ${number(wasm)} bytes, built from commit `,
    b(bundle.commit.slice(0, 7)), `. Loaded so far: ${loadedPacks.size} of ${bundle.formats.length} packs and ` +
    `${loadedModules.size} model modules, ${number(loadedBytes)} bytes of text.`);
}

let wasmModule;
async function newEngine() {
  loadedModules.clear();
  loadedPacks.clear();
  const { GoatTransformers } = await import(new URL("goat_transformers.mjs", ENGINE).href);
  return GoatTransformers.load(wasmModule);
}

async function start() {
  if (!el.from) return;
  try {
    const [bundleText, wasmBytes] = await Promise.all([
      fetch(new URL("bundle.json", ENGINE)).then((r) => { if (!r.ok) throw new Error(`bundle.json: HTTP ${r.status}`); return r.json(); }),
      fetch(new URL("goat_transformers_wasm.wasm", ENGINE)).then((r) => { if (!r.ok) throw new Error(`module: HTTP ${r.status}`); return r.arrayBuffer(); }),
    ]);
    bundle = bundleText;
    wasmModule = await WebAssembly.compile(wasmBytes);
    gt = await newEngine();
  } catch (error) {
    el.status.textContent =
      `The engine did not load (${error.message}); the conversion above is the one goat-xf prints. ` +
      "site/build.sh writes the engine files.";
    for (const node of document.querySelectorAll("#demo-box .js-only")) node.hidden = true;
    return;
  }
  for (const node of document.querySelectorAll('[data-stat="wasm_bytes"]')) {
    node.textContent = number(bundle.stats.wasm_bytes);
  }

  const first = bundle.formats[0].name;
  fillSelect(el.from, bundle.formats.map((f) => f.name), first);
  fillSelect(el.to, targetsOf(first), "cot-xml");
  setSample();
  setPair();

  el.from.addEventListener("change", () => {
    const targets = targetsOf(el.from.value);
    fillSelect(el.to, targets, targets.includes(el.to.value) ? el.to.value : targets[0]);
    setSample();
    setPair();
    run();
  });
  el.to.addEventListener("change", () => { setPair(); run(); });
  el.reset.addEventListener("click", () => { setSample(); setPair(); run(); });
  let timer;
  const later = () => { clearTimeout(timer); timer = setTimeout(run, 120); };
  el.input.addEventListener("input", later);
  el.context.addEventListener("input", later);
  $("demo-form").addEventListener("submit", (event) => event.preventDefault());
  await run();
}

start();
