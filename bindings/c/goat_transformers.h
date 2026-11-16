/*
 * goat_transformers.h: C ABI of the goat-transformers reference engine.
 *
 * Link libgoat_transformers_c (shared or static). The library keeps no global
 * state; everything hangs off a gt_engine.
 *
 * Text: every text argument is a pointer and a byte length, UTF-8. It needs no
 * terminating NUL. A message of a binary wire (bits, protobuf) is hex text, as
 * in the conversion vectors.
 *
 * Results: every call returns a status and fills `out`. On GT_OK `out` holds
 * the result; on any other status it holds the error text, which begins with
 * the error kind and a colon ("malformed-wire: ..."). `out` may be NULL when
 * only the status is wanted. Release a filled buffer with gt_buf_free.
 *
 * Threads: an engine may be used from any thread. gt_convert and gt_formats
 * may run on several threads at once on one engine. gt_load_model,
 * gt_load_pack and gt_engine_free need the engine to themselves: load
 * everything first, then convert.
 */
#ifndef GOAT_TRANSFORMERS_H
#define GOAT_TRANSFORMERS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Status of a call. */
#define GT_OK 0           /* out holds the result (empty for a load) */
#define GT_ERR_ENGINE 1   /* the engine refused; out holds its named error */
#define GT_ERR_ARGUMENT 2 /* unusable argument; out holds "bad-argument: ..." */
#define GT_ERR_PANIC 3    /* the engine panicked; out holds "panic: ..." */

/* An engine: the loaded model modules and packs. Opaque. */
typedef struct gt_engine gt_engine;

/*
 * An owned buffer: `len` bytes at `data`, followed by one NUL that `len` does
 * not count, so a text result is also a C string.
 */
typedef struct gt_buf {
    uint8_t *data;
    size_t len;
} gt_buf;

/* A new, empty engine. NULL only if it could not be created. */
gt_engine *gt_engine_new(void);

/* Release an engine. NULL is accepted. */
void gt_engine_free(gt_engine *engine);

/*
 * Load one model module: the text of a model/<module>.def. Load `core` first,
 * and every module before the packs that use it.
 */
int32_t gt_load_model(gt_engine *engine, const uint8_t *text, size_t text_len,
                      gt_buf *out);

/* Load one pack: the text of a packs/<format>/pack.def. */
int32_t gt_load_pack(gt_engine *engine, const uint8_t *text, size_t text_len,
                     gt_buf *out);

/*
 * Convert `input` from format `from` to format `to`.
 *
 * `context` supplies model keys the input does not carry. NULL: no context.
 * Otherwise text, one "key=value" per line, each line ended by '\n'; the key
 * ends at the first '='. A non-NULL context of length 0 is an empty context,
 * which the engine still treats as a context given. A value cannot hold '\n'.
 */
int32_t gt_convert(const gt_engine *engine,
                   const uint8_t *from, size_t from_len,
                   const uint8_t *to, size_t to_len,
                   const uint8_t *input, size_t input_len,
                   const uint8_t *context, size_t context_len,
                   gt_buf *out);

/* The loaded format names, sorted, one per line, each ended by '\n'. */
int32_t gt_formats(const gt_engine *engine, gt_buf *out);

/*
 * Release a buffer a call filled, and zero it. NULL and an already zeroed
 * buffer are accepted.
 */
void gt_buf_free(gt_buf *buf);

#ifdef __cplusplus
}
#endif

#endif /* GOAT_TRANSFORMERS_H */
