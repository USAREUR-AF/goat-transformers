/*
 * goat_transformers.h: C ABI of the goat-transformers reference engine.
 *
 * Link libgoat_transformers_c (shared or static). The header compiles as C99
 * and as C++17. The library keeps no global state; everything hangs off a
 * gt_engine.
 *
 * THE CONTRACT
 *
 * Text. Every text argument is a pointer and a byte length, UTF-8. It needs
 * no terminating NUL, and a NUL inside it is one more character, not an end.
 * A length of 0 is the empty text, whatever the pointer; a NULL pointer with
 * any other length is refused (GT_ERR_ARGUMENT), as is text that is not
 * UTF-8. A message of a binary wire (bits, protobuf) is hex text, as in the
 * conversion vectors. The library reads an argument during the call only and
 * keeps no pointer to it.
 *
 * Results. Every call that can fail returns a status and writes `out`. On
 * GT_OK `out` holds the result; on any other status it holds the error text.
 * `out` may be NULL when only the status is wanted. A call overwrites `out`
 * without reading it: free a filled buffer before passing it again.
 *
 * Error text. An engine error (GT_ERR_ENGINE) is the engine's own text; a
 * named error begins with its kind and a colon ("malformed-wire: ...",
 * "distribution-refused: ..."). The library adds two kinds: "bad-argument: "
 * (GT_ERR_ARGUMENT) and "panic: " (GT_ERR_PANIC). The text is for a person
 * or a log; a program decides on the status and on the kind before the colon.
 *
 * Ownership. The caller owns every gt_engine it got from gt_engine_new and
 * releases it once with gt_engine_free. The caller owns every gt_buf a call
 * wrote, the error text included, and releases it once with gt_buf_free; it
 * stays valid until then, also after the engine is freed. Do not release
 * either with free(), and do not write to `data`. gt_buf_free zeroes the
 * gt_buf, so freeing the same gt_buf twice is safe; freeing two copies of one
 * gt_buf, or freeing an engine twice, is undefined behavior, as it is for
 * free().
 *
 * Threads. An engine may be used from any thread. gt_convert and gt_formats
 * only read the engine and may run on several threads at once on one engine.
 * gt_engine_set_max_distribution, gt_load_model, gt_load_pack and
 * gt_engine_free change it and need the engine to themselves: set the limit,
 * load everything, then convert. Each thread passes its own `out`.
 *
 * Panics. No panic of the engine crosses this boundary: it is caught and the
 * call returns GT_ERR_PANIC with "panic: <message>" (the Rust runtime also
 * prints the message on stderr). After a panic in a call that changes the
 * engine, the engine may be half-changed, so it refuses every later call with
 * GT_ERR_PANIC; free it. A failed allocation and a stack overflow are not
 * panics: they end the process.
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
#define GT_ERR_ENGINE 1   /* the engine refused; out holds its error text */
#define GT_ERR_ARGUMENT 2 /* unusable argument; out holds "bad-argument: ..." */
#define GT_ERR_PANIC 3    /* the engine panicked; out holds "panic: ..." */

/* A distribution limit, for gt_engine_set_max_distribution. */
#define GT_DISTRIBUTION_PUBLIC 0     /* load only what is marked public */
#define GT_DISTRIBUTION_CONTROLLED 1 /* load everything; the default */

/* An engine: the loaded model modules and packs. Opaque. */
typedef struct gt_engine gt_engine;

/*
 * A buffer the caller owns: `len` bytes at `data`, followed by one NUL that
 * `len` does not count, so a text result is also a C string. A result that
 * holds a NUL of its own is longer than strlen(data); `len` is its length.
 * An empty result has len 0 and a non-NULL `data`. Initialize with {0}.
 */
typedef struct gt_buf {
    uint8_t *data;
    size_t len;
} gt_buf;

/*
 * A new, empty engine, with the distribution limit GT_DISTRIBUTION_CONTROLLED.
 * NULL only if it could not be created.
 */
gt_engine *gt_engine_new(void);

/* Release an engine. NULL is accepted. The pointer is not usable afterwards. */
void gt_engine_free(gt_engine *engine);

/*
 * Set what the engine loads. With GT_DISTRIBUTION_PUBLIC every later load of
 * a model module or a pack marked `distribution controlled` fails with
 * GT_ERR_ENGINE, "distribution-refused: ...".
 *
 * Call it on a new engine, before the first load. On an engine that has
 * loaded a module or a pack, and for any other value of `limit`, it changes
 * nothing and returns GT_ERR_ARGUMENT.
 */
int32_t gt_engine_set_max_distribution(gt_engine *engine, int32_t limit,
                                       gt_buf *out);

/*
 * Load one model module: the text of a model/<module>.def. Load `core` first,
 * and every module before the modules and packs that use it. A module name is
 * loaded once: a second load fails with "duplicate-module: ...". A load that
 * fails changes nothing.
 */
int32_t gt_load_model(gt_engine *engine, const uint8_t *text, size_t text_len,
                      gt_buf *out);

/*
 * Load one pack: the text of a packs/<format>/pack.def. Loading a pack whose
 * format name is already loaded replaces that format. A load that fails
 * changes nothing.
 */
int32_t gt_load_pack(gt_engine *engine, const uint8_t *text, size_t text_len,
                     gt_buf *out);

/*
 * Convert `input` from format `from` to format `to`.
 *
 * `context` supplies model keys the input does not carry. NULL: no context.
 * Otherwise text, one "key=value" per line, each line ended by '\n'; the key
 * ends at the first '=', so a value may hold '=' and may be empty. A non-NULL
 * context of length 0 is an empty context, which the engine still treats as a
 * context given. A value cannot hold '\n'. A line with no '=' is refused with
 * GT_ERR_ARGUMENT.
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
 * Release a buffer a call wrote, and zero it. NULL and a zeroed buffer are
 * accepted.
 */
void gt_buf_free(gt_buf *buf);

#ifdef __cplusplus
}
#endif

#endif /* GOAT_TRANSFORMERS_H */
