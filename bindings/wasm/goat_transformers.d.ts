/** Types of goat_transformers.mjs. */

/**
 * Model keys the input does not carry, by key. A value is written with
 * String() and read by the engine as the key's declared type. `{}` is an
 * empty context, which the engine still treats as a context given.
 */
export type Context =
  | Readonly<Record<string, string | number | bigint | boolean>>
  | ReadonlyMap<string, string | number | bigint | boolean>;

/**
 * One engine in its own WebAssembly instance.
 *
 * `loadModel`, `loadPack` and `convert` throw an `Error` whose `message` is
 * the engine's named error: the kind, a colon, then the text
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
  static load(wasm: BufferSource | WebAssembly.Module): Promise<GoatTransformers>;

  /** Load one model module: the text of a `model/<module>.def`. Load `core` first. */
  loadModel(text: string | Uint8Array): void;

  /** Load one pack: the text of a `packs/<format>/pack.def`. */
  loadPack(text: string | Uint8Array): void;

  /**
   * Convert `input` from format `from` to format `to`.
   * A message of a binary wire (`bits`, `protobuf`) is hex text on both sides.
   * @param context omitted: no context
   * @returns the target message
   */
  convert(from: string, to: string, input: string | Uint8Array, context?: Context): string;

  /** The loaded format names, sorted. */
  formats(): string[];

  /** Release the engine. The object cannot be used afterwards. */
  dispose(): void;
}

export default GoatTransformers;
