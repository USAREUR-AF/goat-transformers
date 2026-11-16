// goat_transformers.mjs: the goat-transformers engine as a WebAssembly module.
// Hand-written, no dependencies. Works in Node and in a browser.
//
//   const gt = await GoatTransformers.load(wasmBytes);
//   gt.loadModel(coreDefText);          // core first, then the other modules
//   gt.loadPack(packDefText);
//   const out = gt.convert("cot-xml", "geojson", xml);
//
// An engine error is thrown as an Error whose message is the engine's error
// text; a named error begins with its kind ("malformed-wire: ...",
// "undeclared-key: ..."). An argument this file refuses before the engine
// runs is thrown as a TypeError ("bad-argument: ...").

const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

// The distribution limits, as the module's gt_engine_set_max_distribution takes them.
const DISTRIBUTION_LIMITS = new Map([
  ["public", 0],
  ["controlled", 1],
]);

export class GoatTransformers {
  #x; // the module's exports
  #engine; // engine handle; 0 once disposed
  #dead = null; // the trap that ended this instance

  // Not for a host to call: use GoatTransformers.load.
  constructor(exports) {
    this.#x = exports;
    this.#engine = exports.gt_engine_new();
  }

  /**
   * Instantiate the module and create an empty engine.
   * `wasm` is the bytes of goat_transformers_wasm.wasm (ArrayBuffer or a
   * typed array) or a compiled WebAssembly.Module. Each call gives a separate
   * engine with its own memory.
   *
   * `options.maxDistribution` is "public" or "controlled" (the default).
   * With "public" the engine refuses every model module and pack marked
   * `distribution controlled` with a `distribution-refused` error. The limit
   * is set here and cannot be changed afterwards.
   */
  static async load(wasm, options = {}) {
    const limit = distributionLimit(options);
    const module = wasm instanceof WebAssembly.Module ? wasm : await WebAssembly.compile(wasm);
    const instance = await WebAssembly.instantiate(module, {});
    const gt = new GoatTransformers(instance.exports);
    if (limit !== undefined) gt.#call((x, engine) => x.gt_engine_set_max_distribution(engine, limit), []);
    return gt;
  }

  /** Load one model module: the text of a model/<module>.def. Load core first. */
  loadModel(text) {
    this.#live();
    this.#call((x, engine, [[ptr, len]]) => x.gt_load_model(engine, ptr, len), [toBytes(text, "model text")]);
  }

  /** Load one pack: the text of a packs/<format>/pack.def. */
  loadPack(text) {
    this.#live();
    this.#call((x, engine, [[ptr, len]]) => x.gt_load_pack(engine, ptr, len), [toBytes(text, "pack text")]);
  }

  /**
   * Convert `input` from format `from` to format `to` and return the target
   * message as a string. A message of a binary wire (bits, protobuf) is hex
   * text on both sides. `input` is a string or UTF-8 bytes.
   *
   * `context` supplies model keys the input does not carry: an object or a
   * Map of key to value. A value is a string, a number, a bigint or a
   * boolean, written with String(). Omitted, undefined or null: no context.
   * `{}` is an empty context, which the engine still treats as a context
   * given.
   */
  convert(from, to, input, context) {
    this.#live();
    const hasContext = context !== undefined && context !== null;
    const texts = [toBytes(from, "from"), toBytes(to, "to"), toBytes(input, "input")];
    if (hasContext) texts.push(toBytes(contextToText(context), "context"));
    return this.#call((x, engine, [f, t, i, c = [0, 0]]) => {
      return x.gt_convert(engine, f[0], f[1], t[0], t[1], i[0], i[1], hasContext ? 1 : 0, c[0], c[1]);
    }, texts);
  }

  /** The loaded format names, sorted. */
  formats() {
    this.#live();
    const text = this.#call((x, engine) => x.gt_formats(engine), []);
    return text === "" ? [] : text.slice(0, -1).split("\n");
  }

  /**
   * The size of the module's linear memory, in bytes. It grows when a call
   * needs more and never shrinks; a host that converts many messages can
   * watch it.
   */
  get memoryBytes() {
    return this.#x.memory.buffer.byteLength;
  }

  /** Release the engine. The object cannot be used afterwards. Safe to call again. */
  dispose() {
    if (this.#engine !== 0 && this.#dead === null) this.#x.gt_engine_free(this.#engine);
    this.#engine = 0;
  }

  // Refuse a call on an engine that trapped or was disposed.
  #live() {
    if (this.#dead !== null) {
      throw new Error("panic: this engine stopped after an earlier trap; load a new one", { cause: this.#dead });
    }
    if (this.#engine === 0) throw new Error("bad-argument: this engine was disposed");
  }

  // Run one export that returns a result handle, and return the result text
  // or throw the error text. `texts` are the text arguments as bytes; `run`
  // gets each as [pointer, length] in linear memory.
  //
  // Nothing in the `try` can throw except the module itself: the caller has
  // checked and encoded every argument before this function allocates, and
  // the result is decoded after everything is released. So a call that
  // returns has released all it allocated, and whatever is caught is a trap
  // (an engine panic, memory or stack exhausted). After a trap the instance
  // cannot run again and its memory cannot be released; the object refuses
  // every later call and the host drops it.
  #call(run, texts) {
    const x = this.#x;
    let ok, bytes;
    try {
      const held = texts.map((text) => copyIn(x, text));
      const result = run(x, this.#engine, held);
      ok = x.gt_result_ok(result) === 1;
      bytes = copyOut(x, x.gt_result_ptr(result), x.gt_result_len(result));
      x.gt_result_free(result);
      for (const [ptr, len] of held) x.gt_free(ptr, len);
    } catch (trap) {
      this.#dead = trap;
      throw new Error(`panic: the engine trapped: ${trap.message}`, { cause: trap });
    }
    const text = decoder.decode(bytes);
    if (!ok) throw new Error(text);
    return text;
  }
}

// Copy bytes into linear memory the module allocates; returns [pointer, length].
function copyIn(x, bytes) {
  const ptr = x.gt_alloc(bytes.length);
  // The view is made after the allocation and used once: growing the memory
  // replaces memory.buffer and detaches every view made on the old one.
  new Uint8Array(x.memory.buffer, ptr, bytes.length).set(bytes);
  return [ptr, bytes.length];
}

// Copy bytes out of linear memory. The view is made after the calls that
// gave `ptr` and `len`, for the reason above, and the copy outlives the
// release of the result.
function copyOut(x, ptr, len) {
  return new Uint8Array(x.memory.buffer, ptr, len).slice();
}

// A text argument as bytes: a string, or UTF-8 bytes in a Uint8Array or an
// ArrayBuffer. Anything else is refused here, before anything is allocated.
function toBytes(value, what) {
  if (typeof value === "string") return encoder.encode(value);
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  throw new TypeError(`bad-argument: ${what} must be a string or UTF-8 bytes`);
}

// The `maxDistribution` of the load options as the module's number, or
// undefined when the option is not given.
function distributionLimit(options) {
  if (options === null || typeof options !== "object") {
    throw new TypeError("bad-argument: the load options must be an object");
  }
  const name = options.maxDistribution;
  if (name === undefined) return undefined;
  const limit = DISTRIBUTION_LIMITS.get(name);
  if (limit === undefined) {
    throw new TypeError(`bad-argument: maxDistribution must be "public" or "controlled", got ${JSON.stringify(name) ?? String(name)}`);
  }
  return limit;
}

// The interface's context text: one "key=value" per line. The key ends at
// the first "=", so a key cannot hold one; a value can. Neither can hold a
// line break.
function contextToText(context) {
  if (typeof context !== "object" || Array.isArray(context)) {
    throw new TypeError("bad-argument: context must be an object or a Map of key to value");
  }
  const entries = context instanceof Map ? [...context] : Object.entries(context);
  let text = "";
  for (const [key, raw] of entries) {
    if (typeof key !== "string" || key === "" || key.includes("=") || key.includes("\n")) {
      throw new TypeError(`bad-argument: context key ${JSON.stringify(key)} must be a non-empty string without = or a line break`);
    }
    if (!["string", "number", "bigint", "boolean"].includes(typeof raw)) {
      throw new TypeError(`bad-argument: the value of context key ${key} must be a string, a number, a bigint or a boolean`);
    }
    const value = String(raw);
    if (value.includes("\n")) {
      throw new TypeError(`bad-argument: the value of context key ${key} holds a line break`);
    }
    text += `${key}=${value}\n`;
  }
  return text;
}

export default GoatTransformers;
