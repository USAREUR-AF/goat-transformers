// The wrapper goat_transformers.mjs and the module's raw interface: what a
// host passes and gets back, what is refused and how, and what happens to
// the module's memory over many calls.
//
//   node --test bindings/wasm/test/wrapper.test.mjs
//
// GT_WASM   path of the .wasm (default: the release build under target/)

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { GoatTransformers } from "../goat_transformers.mjs";
import { loadTree } from "../node.mjs";
import { loadEngine, root, vector, wasm } from "./support.mjs";

const PACKS = ["cot-xml", "geojson", "canonical-track-v2"];
const EVENT = '<event uid="a" type="a-f-G"/>';
const EVENT_CANONICAL =
  '<event version="2.0" uid="a" type="a-f-G"><point hae="9999999" ce="9999999" le="9999999"/><detail/></event>';

// Synthetic texts for the load tests. The controlled ones exist only here
// and in a temporary directory: the repository holds nothing controlled.
const PROBE_CORE = 'module core\nversion 0.1.0\ndistribution public\nsource "probe"\nkey uid string -\n';
const probeModule = (distribution) =>
  `module ctl\nversion 0.1.0\ndistribution ${distribution}\nsource "probe"\nkey code int -\n`;
const probePack = (distribution) =>
  `format probe\nversion 0.4.0\ndistribution ${distribution}\nsource "probe"\nwire xml\nroot item\nfield uid @id string\n`;

// A cot-xml event that carries `callsign`.
const eventNamed = (callsign) =>
  `<event uid="a" type="a-f-G"><detail><contact callsign="${callsign}"/></detail></event>`;

test("formats, and a conversion from a string, from bytes and from an ArrayBuffer", async () => {
  const gt = await loadEngine(PACKS);
  assert.deepEqual(gt.formats(), ["canonical-track-v2", "cot-xml", "geojson"]);
  assert.deepEqual((await GoatTransformers.load(wasm)).formats(), [], "a new engine has no formats");

  const cot = vector("cot-xml", "01-track-to-geojson.json");
  const bytes = new TextEncoder().encode(cot.input);
  assert.equal(gt.convert("cot-xml", "geojson", cot.input), cot.expect);
  assert.equal(gt.convert("cot-xml", "geojson", bytes), cot.expect);
  assert.equal(gt.convert("cot-xml", "geojson", bytes.buffer), cot.expect);
  assert.equal(gt.convert("cot-xml", "geojson", Buffer.from(cot.input)), cot.expect);
  // a view of part of a larger buffer is read as that part only
  const padded = new TextEncoder().encode(`junk${cot.input}junk`);
  assert.equal(gt.convert("cot-xml", "geojson", padded.subarray(4, 4 + bytes.length)), cot.expect);
  // a module or pack text may be bytes too
  gt.loadPack(Buffer.from(probePack("public")));
  assert.ok(gt.formats().includes("probe"));
  gt.dispose();
});

test("a context is an object or a Map, and no context is undefined or null", async () => {
  const gt = await loadEngine(PACKS);
  const track = vector("canonical-track-v2", "09-to-cot-xml-context-stale-and-how.json");
  assert.equal(gt.convert(track.from, track.to, track.input, track.context), track.expect);
  assert.equal(gt.convert(track.from, track.to, track.input, new Map(Object.entries(track.context))), track.expect);
  // a number and a bigint are written with String()
  assert.equal(gt.convert(track.from, track.to, track.input, { stale_ms: 1614456180250, how: "m-p" }), track.expect);
  assert.equal(gt.convert(track.from, track.to, track.input, { stale_ms: 1614456180250n, how: "m-p" }), track.expect);

  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT), EVENT_CANONICAL);
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT, undefined), EVENT_CANONICAL);
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT, null), EVENT_CANONICAL);
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT, {}), EVENT_CANONICAL);
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT, new Map()), EVENT_CANONICAL);
  gt.dispose();
});

test("context keys and values: =, an empty value, text that is not ASCII", async () => {
  const gt = await loadEngine(PACKS);
  const withContext = (context) => gt.convert("cot-xml", "cot-xml", EVENT, context);

  // the key ends at the first "=", so a value may hold one
  assert.match(withContext({ how: "m=p" }), / how="m=p"/);
  assert.match(withContext({ how: "=" }), / how="="/);
  assert.match(withContext({ how: "" }), / how=""/, "an empty value is a value");
  assert.match(withContext({ callsign: "Zoë 東京 🐐" }), /callsign="Zoë 東京 🐐"/);
  assert.match(withContext(new Map([["how", "a=b=c"]])), / how="a=b=c"/);

  // a key with "=" cannot be written in the context text: refused, not cut in two
  assert.throws(() => withContext({ "how=m": "p" }), TypeError);
  assert.throws(() => withContext({ "how=m": "p" }), /bad-argument: context key "how=m"/);
  // a key that is not ASCII reaches the engine whole, and the engine refuses it by name
  assert.throws(() => withContext({ "clé.東京": "1" }), /^Error: undeclared-key: context key `clé.東京`/);
  assert.throws(() => withContext({ "no.such_key": "1" }), /^Error: undeclared-key:/);
  assert.throws(() => withContext({ time_ms: "soon" }), /^Error: key-type-mismatch:/);

  // a key the message carries is not replaced
  assert.match(gt.convert("cot-xml", "cot-xml", '<event uid="a" type="a-f-G" how="h-e"/>', { how: "m-p" }), / how="h-e"/);
  assert.equal(withContext(undefined), EVENT_CANONICAL, "the engine converts after the refusals");
  gt.dispose();
});

test("an argument that is neither a string nor bytes is a TypeError", async () => {
  const gt = await loadEngine(PACKS);
  const notText = [7, null, undefined, {}, [], true, 10n, Symbol("s"), new Uint16Array(2), new DataView(new ArrayBuffer(2))];
  for (const bad of notText) {
    const what = `for ${typeof bad} ${String(bad?.constructor?.name ?? bad)}`;
    assert.throws(() => gt.convert(bad, "geojson", EVENT), { name: "TypeError", message: /bad-argument: from must be/ }, what);
    assert.throws(() => gt.convert("cot-xml", bad, EVENT), { name: "TypeError", message: /bad-argument: to must be/ }, what);
    assert.throws(() => gt.convert("cot-xml", "geojson", bad), { name: "TypeError", message: /bad-argument: input must be/ }, what);
    assert.throws(() => gt.loadModel(bad), { name: "TypeError", message: /bad-argument: model text must be/ }, what);
    assert.throws(() => gt.loadPack(bad), { name: "TypeError", message: /bad-argument: pack text must be/ }, what);
  }

  const convertWith = (context) => () => gt.convert("cot-xml", "cot-xml", EVENT, context);
  // a context that is not an object or a Map
  for (const bad of ["how=m-p", 7, true, ["how", "m-p"], () => ({})]) {
    assert.throws(convertWith(bad), { name: "TypeError", message: /bad-argument: context must be/ });
  }
  // keys the context text cannot carry
  for (const key of ["", "a=b", "a\nb"]) {
    assert.throws(convertWith({ [key]: "1" }), { name: "TypeError", message: /bad-argument: context key/ });
  }
  assert.throws(convertWith(new Map([[7, "1"]])), { name: "TypeError", message: /bad-argument: context key 7/ });
  // values String() would turn into something the caller did not write
  for (const value of [null, undefined, {}, [], Symbol("s"), () => 1]) {
    assert.throws(convertWith({ how: value }), { name: "TypeError", message: /the value of context key how must be/ });
  }
  assert.throws(convertWith({ how: "a\nb" }), { name: "TypeError", message: /holds a line break/ });

  // bytes that are not UTF-8 are for the module to refuse: an Error, not a TypeError
  assert.throws(
    () => gt.convert("cot-xml", "geojson", new Uint8Array([0xff, 0xfe])),
    (e) => e.constructor === Error && e.message === "bad-argument: input is not UTF-8",
  );
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT), EVENT_CANONICAL, "the engine converts after the refusals");
  gt.dispose();
});

test("engine errors keep the engine's text and leave the engine usable", async () => {
  const gt = await loadEngine(PACKS);
  assert.throws(() => gt.convert("no-such-format", "geojson", "x"), /^Error: unknown-format: no pack loaded for format `no-such-format`$/);
  assert.throws(() => gt.convert("cot-xml", "geojson", "<event"), Error);
  assert.throws(() => gt.loadPack("format x\n"), Error);
  assert.throws(() => gt.loadModel("module x\nversion 1\n"), /^Error: missing-distribution:/);
  // a module name and a format name are each loaded once (ruling 5 of 0.11)
  assert.throws(() => gt.loadModel(PROBE_CORE), /^Error: duplicate-module:/);
  gt.loadPack(probePack("public"));
  assert.throws(() => gt.loadPack(probePack("public")), /^Error: duplicate-format:/);
  assert.deepEqual(gt.formats(), ["canonical-track-v2", "cot-xml", "geojson", "probe"]);
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT), EVENT_CANONICAL);
  gt.dispose();
});

// A cot-xml event nested `levels` deep: the root element is level 1, its
// <detail> level 2, and each <n> inside one level more.
const nestedXml = (levels) =>
  `<event uid="a" type="a-f-G"><detail>${"<n>".repeat(levels - 2)}${"</n>".repeat(levels - 2)}</detail></event>`;
// A GeoJSON feature nested `levels` deep: the outermost object is level 1,
// its `properties` level 2, and each array inside one level more.
const nestedJson = (levels) =>
  `{"type":"Feature","id":"a","geometry":null,"properties":{"x":${"[".repeat(levels - 2)}${"]".repeat(levels - 2)}}}`;

// The engine owns the rule (spec/engine-spec.md, Malformed input, ruling 35:
// 64 levels of nesting convert, 65 do not) and the conformance-malformed
// packs pin it. This test shows what a host of the module sees: an Error
// with the engine's kind, no trap, and an engine that goes on converting.
test("a message that is not well formed is malformed-wire, not a trap", async () => {
  const gt = await loadEngine(PACKS);
  const malformed = /^Error: malformed-wire:/;

  // an attribute cut off after its "=", and other ways to stop early
  for (const cut of ["<event uid=", '<event uid="', "<event uid", "<event ", "<", '<event uid="a"><point']) {
    assert.throws(() => gt.convert("cot-xml", "geojson", cut), malformed, cut);
  }
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT), EVENT_CANONICAL);

  for (const [format, nested] of [["cot-xml", nestedXml], ["geojson", nestedJson]]) {
    assert.equal(typeof gt.convert(format, format, nested(64)), "string", `${format} nested 64 levels converts`);
    for (const levels of [65, 30000]) {
      assert.throws(() => gt.convert(format, format, nested(levels)), malformed, `${format} nested ${levels} levels`);
    }
    assert.equal(gt.convert("cot-xml", "cot-xml", EVENT), EVENT_CANONICAL, "the engine converts afterwards");
  }
  gt.dispose();
});

test("a 1 MiB message: the memory grows under the call and the views are taken again", async () => {
  const gt = await loadEngine(["cot-xml", "geojson"]);
  // characters of 1, 2, 3 and 4 UTF-8 bytes, so that a length in characters is never a length in bytes
  const callsign = "aé東🐐".repeat(Math.ceil((1 << 20) / 10));
  const input = eventNamed(callsign);
  assert.ok(Buffer.byteLength(input) > 1 << 20);

  const before = gt.memoryBytes;
  const geojson = gt.convert("cot-xml", "geojson", input);
  assert.ok(gt.memoryBytes > before, `the memory grew (${before} -> ${gt.memoryBytes} bytes)`);
  assert.equal(JSON.parse(geojson).properties.callsign, callsign, "every byte arrived and came back");

  // the same as bytes, and back again through the other format
  assert.equal(gt.convert("cot-xml", "geojson", Buffer.from(input)), geojson);
  assert.ok(gt.convert("geojson", "cot-xml", geojson).includes(`callsign="${callsign}"`));

  // the memory that grew is used again: the same call needs no more
  const grown = gt.memoryBytes;
  gt.convert("cot-xml", "geojson", input);
  assert.equal(gt.memoryBytes, grown);
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT), EVENT_CANONICAL);
  gt.dispose();
});

test("10,000 conversions leave the memory the size it was after a warm-up of 400", async () => {
  const gt = await loadEngine(PACKS);
  const cot = vector("cot-xml", "01-track-to-geojson.json");
  const track = vector("canonical-track-v2", "09-to-cot-xml-context-stale-and-how.json");
  // a success, a success with a context, and an engine error: each path releases what it took
  const round = () => {
    assert.equal(gt.convert(cot.from, cot.to, cot.input), cot.expect);
    assert.equal(gt.convert(track.from, track.to, track.input, track.context), track.expect);
    assert.throws(() => gt.convert("cot-xml", "geojson", "<event"), /^Error: malformed-wire:/);
    assert.throws(() => gt.convert("cot-xml", "cot-xml", EVENT, { "no.such_key": "1" }), /undeclared-key/);
  };
  for (let i = 0; i < 100; i++) round();
  const warm = gt.memoryBytes;
  for (let i = 0; i < 2500; i++) round();
  assert.equal(gt.memoryBytes, warm, "the memory did not grow over 10,000 calls");
  gt.dispose();
});

test("10,000 refused arguments leave the memory the size it was", async () => {
  const gt = await loadEngine(PACKS);
  // Large arguments before the refused one: were they copied into the module
  // and not released, 10,000 calls would need 640 MiB.
  const large = "x".repeat(32 * 1024);
  gt.convert("cot-xml", "cot-xml", EVENT);
  const before = gt.memoryBytes;
  for (let i = 0; i < 5000; i++) {
    assert.throws(() => gt.convert(large, large, 7), TypeError);
    assert.throws(() => gt.convert(large, large, EVENT, { "a=b": "1" }), TypeError);
  }
  assert.equal(gt.memoryBytes, before, "a refused argument takes no memory");
  // nor does an argument the module refuses, or an engine error
  for (let i = 0; i < 5000; i++) {
    assert.throws(() => gt.convert(large, large, new Uint8Array([0xff])), /bad-argument: input is not UTF-8/);
    assert.throws(() => gt.loadPack(large), Error);
  }
  assert.equal(gt.memoryBytes, before, "a refusal by the module releases its arguments");
  assert.equal(gt.convert("cot-xml", "cot-xml", EVENT), EVENT_CANONICAL);
  gt.dispose();
});

test("after dispose every call says the engine was disposed", async () => {
  const gt = await loadEngine(PACKS);
  gt.dispose();
  const disposed = { name: "Error", message: "bad-argument: this engine was disposed" };
  assert.throws(() => gt.formats(), disposed);
  assert.throws(() => gt.convert("cot-xml", "cot-xml", EVENT), disposed);
  assert.throws(() => gt.loadModel(PROBE_CORE), disposed);
  assert.throws(() => gt.loadPack(probePack("public")), disposed);
  // the state of the engine is reported before a bad argument is
  assert.throws(() => gt.convert(7, 7, 7), disposed);
  gt.dispose(); // a second dispose does nothing
  assert.throws(() => gt.formats(), disposed);
});

test("two engines side by side share nothing", async () => {
  const a = await GoatTransformers.load(wasm);
  const b = await GoatTransformers.load(wasm);
  a.loadModel(PROBE_CORE);
  a.loadPack(probePack("public"));
  b.loadModel(PROBE_CORE); // the same module name in another engine is no duplicate
  b.loadPack(probePack("public").replace("root item", "root thing"));

  for (let i = 0; i < 100; i++) {
    assert.equal(a.convert("probe", "probe", `<item id="a${i}"/>`), `<item id="a${i}"/>`);
    assert.equal(b.convert("probe", "probe", `<thing id="b${i}"/>`), `<thing id="b${i}"/>`);
  }
  assert.throws(() => a.convert("probe", "probe", '<thing id="x"/>'), Error);
  assert.throws(() => b.convert("probe", "probe", '<item id="x"/>'), Error);

  // one engine's memory growing is not the other's
  const bBefore = b.memoryBytes;
  a.loadModel(`module big\nversion 0.1.0\ndistribution public\nsource "probe"\n${"# padding\n".repeat(300000)}key k int -\n`);
  assert.ok(a.memoryBytes > bBefore);
  assert.equal(b.memoryBytes, bBefore);

  a.dispose();
  assert.equal(b.convert("probe", "probe", '<thing id="still"/>'), '<thing id="still"/>');
  b.dispose();
});

test("maxDistribution public: everything controlled is refused at load", async () => {
  const gt = await GoatTransformers.load(wasm, { maxDistribution: "public" });
  gt.loadModel(PROBE_CORE);
  assert.throws(() => gt.loadPack(probePack("controlled")), /^Error: distribution-refused: pack `probe` is controlled/);
  assert.throws(() => gt.loadModel(probeModule("controlled")), /^Error: distribution-refused: model module `ctl` is controlled/);
  assert.deepEqual(gt.formats(), [], "nothing refused was loaded");
  assert.throws(() => gt.convert("probe", "probe", '<item id="u1"/>'), Error);

  // what is public still loads and converts
  gt.loadModel(probeModule("public"));
  gt.loadPack(probePack("public"));
  assert.equal(gt.convert("probe", "probe", '<item id="u1"/>'), '<item id="u1"/>');
  // and the limit holds afterwards
  assert.throws(() => gt.loadPack(probePack("controlled")), /^Error: distribution-refused:/);
  gt.dispose();
});

test("maxDistribution controlled is the default: both markings load", async () => {
  for (const options of [undefined, {}, { maxDistribution: "controlled" }, { maxDistribution: undefined }]) {
    const gt = await GoatTransformers.load(wasm, options);
    gt.loadModel(PROBE_CORE);
    gt.loadModel(probeModule("controlled"));
    gt.loadPack(probePack("controlled"));
    assert.deepEqual(gt.formats(), ["probe"]);
    gt.dispose();
  }
});

test("a maxDistribution that is no limit is refused before an engine is made", async () => {
  for (const bad of ["secret", "PUBLIC", "", 0, null, true, {}]) {
    await assert.rejects(GoatTransformers.load(wasm, { maxDistribution: bad }), {
      name: "TypeError",
      message: /bad-argument: maxDistribution must be "public" or "controlled"/,
    });
  }
  await assert.rejects(GoatTransformers.load(wasm, null), { name: "TypeError", message: /load options must be an object/ });
  await assert.rejects(GoatTransformers.load(wasm, "public"), { name: "TypeError", message: /load options must be an object/ });
});

test("loadTree into an engine limited to public refuses a controlled pack of a tree on disk", async (t) => {
  // a tree with one public and one controlled pack, in a temporary directory
  const tree = mkdtempSync(join(tmpdir(), "goat-transformers-test-"));
  t.after(() => rmSync(tree, { recursive: true, force: true }));
  mkdirSync(join(tree, "model"));
  writeFileSync(join(tree, "model", "core.def"), PROBE_CORE);
  for (const [name, distribution] of [["open", "public"], ["closed", "controlled"]]) {
    mkdirSync(join(tree, "packs", name), { recursive: true });
    writeFileSync(join(tree, "packs", name, "pack.def"), probePack(distribution).replace("format probe", `format ${name}`));
  }

  const limited = () => GoatTransformers.load(wasm, { maxDistribution: "public" });
  const open = await loadTree(tree, ["open"], await limited());
  assert.deepEqual(open.formats(), ["open"]);
  open.dispose();
  const refusing = await limited();
  await assert.rejects(loadTree(tree, ["open", "closed"], refusing), /^Error: distribution-refused: pack `closed` is controlled/);
  assert.deepEqual(refusing.formats(), ["open"], "the controlled pack is not loaded; the public one before it is");
  refusing.dispose();

  const unlimited = await loadTree(tree, ["open", "closed"], await GoatTransformers.load(wasm));
  assert.deepEqual(unlimited.formats(), ["closed", "open"]);
  unlimited.dispose();
});

test("loadTree loads the named packs of the repository and the modules they use", async () => {
  const gt = await loadTree(root, ["cot-xml", "geojson"], await GoatTransformers.load(wasm));
  assert.deepEqual(gt.formats(), ["cot-xml", "geojson"]);
  const cot = vector("cot-xml", "01-track-to-geojson.json");
  assert.equal(gt.convert(cot.from, cot.to, cot.input), cot.expect);
  await assert.rejects(loadTree(root, ["no-such-pack"], gt), /^Error: unknown-format: no pack no-such-pack/);
  gt.dispose();
});

// The module's exports with one of them replaced, for the tests below.
async function exportsWith(replaced) {
  const { exports } = await WebAssembly.instantiate(await WebAssembly.compile(wasm), {});
  return { ...exports, ...replaced(exports) };
}

test("a trap stops the engine: the call says so, and so does every later call", async () => {
  // The module traps when the engine panics or runs out of memory or stack.
  // Here the trap is made by the test: the export throws what a trap throws.
  const calls = { free: 0 };
  const trap = new WebAssembly.RuntimeError("unreachable");
  const gt = new GoatTransformers(
    await exportsWith((x) => ({
      gt_convert: () => {
        throw trap;
      },
      gt_engine_free: (engine) => {
        calls.free++;
        x.gt_engine_free(engine);
      },
    })),
  );
  gt.loadModel(PROBE_CORE);
  gt.loadPack(probePack("public"));

  assert.throws(
    () => gt.convert("probe", "probe", '<item id="u1"/>'),
    (e) => e.constructor === Error && e.message === "panic: the engine trapped: unreachable" && e.cause === trap,
  );
  const stopped = (e) => e.message === "panic: this engine stopped after an earlier trap; load a new one" && e.cause === trap;
  assert.throws(() => gt.formats(), stopped);
  assert.throws(() => gt.loadPack(probePack("public")), stopped);
  assert.throws(() => gt.convert("probe", "probe", '<item id="u1"/>'), stopped);
  gt.dispose();
  assert.equal(calls.free, 0, "a trapped instance is not called again, not even to release the engine");
});

test("the raw interface: a handle of 0 is an error result, not a read of address 0", async () => {
  const x = await exportsWith(() => ({}));
  const read = (result) => {
    const ok = x.gt_result_ok(result) === 1;
    const text = new TextDecoder().decode(new Uint8Array(x.memory.buffer, x.gt_result_ptr(result), x.gt_result_len(result)));
    x.gt_result_free(result);
    return { ok, text };
  };
  const refused = { ok: false, text: "bad-argument: engine is 0" };
  assert.deepEqual(read(x.gt_formats(0)), refused);
  assert.deepEqual(read(x.gt_load_model(0, 0, 0)), refused);
  assert.deepEqual(read(x.gt_load_pack(0, 0, 0)), refused);
  assert.deepEqual(read(x.gt_convert(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)), refused);
  assert.deepEqual(read(x.gt_engine_set_max_distribution(0, 0)), refused);
  x.gt_engine_free(0);
  x.gt_result_free(0);
  assert.equal(x.gt_result_ok(0), 0);
  assert.equal(x.gt_result_len(0), 0);

  // the limit through the raw interface: only 0 and 1, and only before a load
  const engine = x.gt_engine_new();
  assert.deepEqual(read(x.gt_engine_set_max_distribution(engine, 2)).ok, false);
  assert.deepEqual(read(x.gt_engine_set_max_distribution(engine, 0)), { ok: true, text: "" });
  x.gt_engine_free(engine);
});

test("the raw interface: growing the memory detaches a view made before", async () => {
  // Why the wrapper makes a view after every allocation and keeps none.
  const x = await exportsWith(() => ({}));
  const view = new Uint8Array(x.memory.buffer);
  const sizeBefore = view.byteLength;
  assert.ok(sizeBefore > 0);
  const len = 4 * sizeBefore;
  const ptr = x.gt_alloc(len);
  assert.equal(view.byteLength, 0, "the old view is detached");
  assert.ok(x.memory.buffer.byteLength >= sizeBefore + len, "memory.buffer is a new, larger buffer");
  x.gt_free(ptr, len);
});

test("the module imports nothing and exports the documented interface", async () => {
  const module = await WebAssembly.compile(wasm);
  assert.deepEqual(WebAssembly.Module.imports(module), []);
  const documented = [
    "memory", "gt_alloc", "gt_free", "gt_engine_new", "gt_engine_free", "gt_engine_set_max_distribution",
    "gt_engine_set_max_items", "gt_load_model", "gt_load_pack", "gt_convert", "gt_formats",
    "gt_result_ok", "gt_result_ptr", "gt_result_len", "gt_result_free",
  ];
  const exported = WebAssembly.Module.exports(module).map((e) => e.name).filter((n) => !n.startsWith("__"));
  assert.deepEqual(exported.sort(), documented.sort());
});

test("setMaxItems sets the limit on list items and refuses a value that is no limit", async () => {
  const gt = await GoatTransformers.load(wasm);
  gt.setMaxItems(0);
  gt.setMaxItems(4294967295);
  for (const bad of [-1, 1.5, 4294967296, "3", undefined]) {
    assert.throws(() => gt.setMaxItems(bad), { name: "TypeError", message: /^bad-argument: the limit on list items/ });
  }
  gt.dispose();
  assert.throws(() => gt.setMaxItems(1), /bad-argument: this engine was disposed/);
});
