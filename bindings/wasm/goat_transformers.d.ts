/** Types of goat_transformers.mjs. */

/** A text argument: a string, or its UTF-8 bytes. */
export type Text = string | Uint8Array | ArrayBuffer;

/**
 * Model keys the input does not carry, by key. A value is written with
 * String() and read by the engine as the key's declared type. A key cannot
 * hold `=` or a line break; a value cannot hold a line break. `{}` is an
 * empty context, which the engine still treats as a context given.
 */
export type Context =
  | Readonly<Record<string, string | number | bigint | boolean>>
  | ReadonlyMap<string, string | number | bigint | boolean>;

/** How far a model module or a pack may be distributed. */
export type Distribution = "public" | "controlled";

/** Options of `GoatTransformers.load`. */
export interface LoadOptions {
  /**
   * The most restricted marking the engine loads. With `"public"` every model
   * module and pack marked `distribution controlled` is refused with a
   * `distribution-refused` error. Default: `"controlled"`, which loads both.
   * It is set when the engine is made and cannot be changed afterwards.
   */
  readonly maxDistribution?: Distribution;
}

/**
 * One engine in its own WebAssembly instance.
 *
 * `loadModel`, `loadPack` and `convert` throw an `Error` whose `message` is
 * the engine's error text; a named error begins with its kind and a colon
 * (`"malformed-wire: ..."`, `"undeclared-key: ..."`). Two kinds come from the
 * binding itself: `bad-argument` (thrown as `TypeError` when the argument is
 * refused before the engine runs) and `panic` (the engine trapped; the object
 * refuses every later call, and `cause` holds the trap).
 */
export declare class GoatTransformers {
  private constructor();

  /**
   * Instantiate the module and create an empty engine.
   * @param wasm the bytes of `goat_transformers_wasm.wasm`, or a compiled module
   */
  static load(wasm: BufferSource | WebAssembly.Module, options?: LoadOptions): Promise<GoatTransformers>;

  /** Load one model module: the text of a `model/<module>.def`. Load `core` first. */
  loadModel(text: Text): void;

  /** Load one pack: the text of a `packs/<format>/pack.def`. */
  loadPack(text: Text): void;

  /**
   * Convert `input` from format `from` to format `to`.
   * A message of a binary wire (`bits`, `protobuf`) is hex text on both sides.
   * @param context omitted, `undefined` or `null`: no context
   * @returns the target message
   */
  convert(from: string, to: string, input: Text, context?: Context | null): string;

  /** The loaded format names, sorted. */
  formats(): string[];

  /**
   * The size of the module's linear memory, in bytes. It grows when a call
   * needs more and never shrinks.
   */
  readonly memoryBytes: number;

  /** Release the engine. The object cannot be used afterwards. Safe to call again. */
  dispose(): void;
}

export default GoatTransformers;
