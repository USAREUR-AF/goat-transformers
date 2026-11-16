// goat_transformers.mjs: the goat-transformers engine as a WebAssembly module.
// Hand-written, no dependencies. Works in Node and in a browser.
//
//   const gt = await GoatTransformers.load(wasmBytes);
//   gt.loadModel(coreDefText);          // core first, then the other modules
//   gt.loadPack(packDefText);
//   const out = gt.convert("cot-xml", "geojson", xml);
//
// An engine error is thrown as an Error whose message is the engine's named
// error ("malformed-wire: ...", "undeclared-key: ...").

const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

export class GoatTransformers {
  #x; // the module's exports
  #engine; // engine handle; 0 once disposed or dead
  #dead = null; // the trap that ended this instance

  constructor(exports) {
    this.#x = exports;
    this.#engine = exports.gt_engine_new();
  }

  /**
   * Instantiate the module and create an empty engine.
   * `wasm` is the bytes of goat_transformers_wasm.wasm (ArrayBuffer or a
   * typed array) or a compiled WebAssembly.Module. Each call gives a separate
   * engine with its own memory.
   */
  static async load(wasm) {
    const module = wasm instanceof WebAssembly.Module ? wasm : await WebAssembly.compile(wasm);
    const instance = await WebAssembly.instantiate(module, {});
    return new GoatTransformers(instance.exports);
  }

  /** Load one model module: the text of a model/<module>.def. Load core first. */
  loadModel(text) {
    this.#call((x, e, arg) => {
      const [p, n] = arg(text, "model text");
      return x.gt_load_model(e, p, n);
    });
  }

  /** Load one pack: the text of a packs/<format>/pack.def. */
  loadPack(text) {
    this.#call((x, e, arg) => {
      const [p, n] = arg(text, "pack text");
      return x.gt_load_pack(e, p, n);
    });
  }

  /**
   * Convert `input` from format `from` to format `to` and return the target
   * message as a string. A message of a binary wire (bits, protobuf) is hex
   * text on both sides. `input` is a string or UTF-8 bytes.
   *
   * `context` supplies model keys the input does not carry: an object or a
   * Map of key to value. Values are written with String(). Omitted or
   * undefined: no context. `{}` is an empty context, which the engine still
   * treats as a context given.
   */
  convert(from, to, input, context) {
    const contextText = context === undefined || context === null ? null : contextToText(context);
    return this.#call((x, e, arg) => {
      const [fp, fn] = arg(from, "from");
      const [tp, tn] = arg(to, "to");
      const [ip, inl] = arg(input, "input");
      const [cp, cn] = contextText === null ? [0, 0] : arg(contextText, "context");
      return x.gt_convert(e, fp, fn, tp, tn, ip, inl, contextText === null ? 0 : 1, cp, cn);
    });
  }

  /** The loaded format names, sorted. */
  formats() {
    const text = this.#call((x, e) => x.gt_formats(e));
    return text === "" ? [] : text.slice(0, -1).split("\n");
  }

  /** Release the engine. The object cannot be used afterwards. */
  dispose() {
    if (this.#engine !== 0 && this.#dead === null) this.#x.gt_engine_free(this.#engine);
    this.#engine = 0;
  }

  // Run one export that returns a result handle. `arg` copies a text argument
  // into linear memory; everything it allocated is released afterwards.
  #call(fn) {
    if (this.#dead !== null) {
      throw new Error("panic: this engine stopped after an earlier trap; load a new one", { cause: this.#dead });
    }
    if (this.#engine === 0) throw new Error("bad-argument: this engine was disposed");
    const x = this.#x;
    const held = [];
    const arg = (value, what) => {
      let bytes;
      if (typeof value === "string") bytes = encoder.encode(value);
      else if (value instanceof Uint8Array) bytes = value;
      else if (value instanceof ArrayBuffer) bytes = new Uint8Array(value);
      else throw new TypeError(`bad-argument: ${what} must be a string or UTF-8 bytes`);
      const ptr = x.gt_alloc(bytes.length);
      held.push([ptr, bytes.length]);
      // the view is taken after the allocation: growing memory replaces the buffer
      new Uint8Array(x.memory.buffer, ptr, bytes.length).set(bytes);
      return [ptr, bytes.length];
    };
    let ok, text;
    try {
      const r = fn(x, this.#engine, arg);
      ok = x.gt_result_ok(r) === 1;
      text = decoder.decode(new Uint8Array(x.memory.buffer, x.gt_result_ptr(r), x.gt_result_len(r)));
      x.gt_result_free(r);
      for (const [ptr, len] of held) x.gt_free(ptr, len);
    } catch (e) {
      if (e instanceof TypeError) throw e; // a refused argument, raised before the engine ran
      // a trap (an engine panic, memory or stack exhausted): the instance is not reusable
      this.#dead = e;
      throw new Error(`panic: the engine trapped: ${e.message}`, { cause: e });
    }
    if (!ok) throw new Error(text);
    return text;
  }
}

// The interface's context text: one "key=value" per line.
function contextToText(context) {
  const entries = context instanceof Map ? [...context] : Object.entries(context);
  let text = "";
  for (const [key, raw] of entries) {
    const value = String(raw);
    if (typeof key !== "string" || key === "" || key.includes("=") || key.includes("\n")) {
      throw new TypeError(`bad-argument: context key ${JSON.stringify(key)} must be a non-empty string without = or a line break`);
    }
    if (value.includes("\n")) {
      throw new TypeError(`bad-argument: the value of context key ${key} holds a line break`);
    }
    text += `${key}=${value}\n`;
  }
  return text;
}

export default GoatTransformers;
