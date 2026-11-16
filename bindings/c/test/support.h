/*
 * What the C tests share: a check counter, file reading, and short forms of
 * the calls that take a C string. Each test is one program that includes
 * this file once.
 */
#ifndef GT_TEST_SUPPORT_H
#define GT_TEST_SUPPORT_H

#include "goat_transformers.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int checks = 0;
static int failures = 0;

/* Count one check; print `what` (a printf format) when it does not hold. */
static inline void check(int ok, const char *what, ...) {
    checks++;
    if (ok) return;
    failures++;
    va_list args;
    va_start(args, what);
    fputs("FAIL: ", stderr);
    vfprintf(stderr, what, args);
    fputc('\n', stderr);
    va_end(args);
}

/* Print the count and give the exit status of the program. */
static inline int finish(const char *program) {
    printf("%s: %d checks, %d failed\n", program, checks, failures);
    return failures ? 1 : 0;
}

/* A test that cannot run (a file is missing, memory ran out) stops here. */
static inline void stop(const char *what, const char *detail) {
    fprintf(stderr, "cannot run: %s %s\n", what, detail);
    exit(2);
}

static inline void *must_alloc(size_t size) {
    void *p = malloc(size ? size : 1);
    if (!p) stop("out of memory", "");
    return p;
}

/* `dir` + "/" + `rel`, allocated. */
static inline char *join_path(const char *dir, const char *rel) {
    size_t n = strlen(dir) + 1 + strlen(rel) + 1;
    char *path = must_alloc(n);
    snprintf(path, n, "%s/%s", dir, rel);
    return path;
}

/* The bytes of a file, allocated, with a NUL after them. */
static inline char *read_file(const char *dir, const char *rel, size_t *len) {
    char *path = join_path(dir, rel);
    FILE *f = fopen(path, "rb");
    if (!f) stop("cannot open", path);
    if (fseek(f, 0, SEEK_END) != 0) stop("cannot seek", path);
    long size = ftell(f);
    if (size < 0 || fseek(f, 0, SEEK_SET) != 0) stop("cannot measure", path);
    char *bytes = must_alloc((size_t)size + 1);
    if (fread(bytes, 1, (size_t)size, f) != (size_t)size) stop("cannot read", path);
    fclose(f);
    free(path);
    bytes[size] = 0;
    *len = (size_t)size;
    return bytes;
}

/* gt_load_model with a C string. */
static inline int32_t load_model(gt_engine *e, const char *text, gt_buf *out) {
    return gt_load_model(e, (const uint8_t *)text, strlen(text), out);
}

/* gt_load_pack with a C string. */
static inline int32_t load_pack(gt_engine *e, const char *text, gt_buf *out) {
    return gt_load_pack(e, (const uint8_t *)text, strlen(text), out);
}

/* gt_convert with C strings; a NULL `context` is no context. */
static inline int32_t convert(const gt_engine *e, const char *from, const char *to,
                              const char *input, const char *context, gt_buf *out) {
    return gt_convert(e, (const uint8_t *)from, strlen(from),
                      (const uint8_t *)to, strlen(to),
                      (const uint8_t *)input, strlen(input),
                      (const uint8_t *)context, context ? strlen(context) : 0, out);
}

/* Load a file of the repository into the engine; a failure is a failed check. */
static inline void load_file(gt_engine *e, const char *root, const char *rel, int is_model) {
    size_t len;
    char *text = read_file(root, rel, &len);
    gt_buf out = {0};
    int32_t rc = is_model ? gt_load_model(e, (const uint8_t *)text, len, &out)
                          : gt_load_pack(e, (const uint8_t *)text, len, &out);
    check(rc == GT_OK, "load %s: %s", rel, (const char *)out.data);
    gt_buf_free(&out);
    free(text);
}

/* Does the buffer hold exactly these `len` bytes, and its NUL after them? */
static inline int buf_is_bytes(const gt_buf *b, const char *bytes, size_t len) {
    return b->data && b->len == len && memcmp(b->data, bytes, len) == 0 && b->data[len] == 0;
}

/* Does the buffer hold exactly this C string? */
static inline int buf_is(const gt_buf *b, const char *text) {
    return buf_is_bytes(b, text, strlen(text));
}

static inline int buf_starts_with(const gt_buf *b, const char *prefix) {
    size_t n = strlen(prefix);
    return b->data && b->len >= n && memcmp(b->data, prefix, n) == 0;
}

static inline int buf_contains(const gt_buf *b, const char *text) {
    return b->data && strstr((const char *)b->data, text) != NULL;
}

/* The buffer's text for a message, also when the buffer is empty. */
static inline const char *buf_text(const gt_buf *b) {
    return b->data ? (const char *)b->data : "(no buffer)";
}

#endif /* GT_TEST_SUPPORT_H */
