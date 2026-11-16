/*
 * Test of the C ABI. Loads the core and track model modules and the cot-xml,
 * geojson and canonical-track-v2 packs from the repository's files, runs
 * conversion vectors through gt_convert and compares with their `expect`.
 *
 * usage: test <repository root>
 */
#include "goat_transformers.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;
static int checks = 0;

static void check(int ok, const char *what) {
    checks++;
    if (!ok) {
        failures++;
        fprintf(stderr, "FAIL: %s\n", what);
    }
}

static char *read_file(const char *root, const char *rel, size_t *len) {
    char path[4096];
    snprintf(path, sizeof path, "%s/%s", root, rel);
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        exit(2);
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc((size_t)n + 1);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        fprintf(stderr, "cannot read %s\n", path);
        exit(2);
    }
    fclose(f);
    buf[n] = 0;
    *len = (size_t)n;
    return buf;
}

static int hex4(const char *p) {
    int v = 0;
    for (int i = 0; i < 4; i++) {
        char c = p[i];
        int d = c >= '0' && c <= '9' ? c - '0'
              : c >= 'a' && c <= 'f' ? c - 'a' + 10
              : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (d < 0) return -1;
        v = v * 16 + d;
    }
    return v;
}

/*
 * The string value of a top-level member of a vector file, unescaped. Enough
 * JSON for the vector files: it skips strings properly, so a key name inside
 * another member's value is not taken for the member. Returns NULL when the
 * member is absent. \u escapes above U+007F are not needed by the vectors
 * this test reads and are refused.
 */
static char *json_member(const char *json, const char *key) {
    size_t klen = strlen(key);
    int depth = 0;
    const char *p = json;
    while (*p) {
        if (*p == '{' || *p == '[') { depth++; p++; continue; }
        if (*p == '}' || *p == ']') { depth--; p++; continue; }
        if (*p != '"') { p++; continue; }
        /* a string starts: find its end */
        const char *start = p + 1;
        const char *q = start;
        while (*q && *q != '"') q += (*q == '\\' && q[1]) ? 2 : 1;
        if (!*q) return NULL;
        const char *after = q + 1;
        while (*after == ' ' || *after == '\n' || *after == '\t' || *after == '\r') after++;
        int is_key = depth == 1 && *after == ':';
        if (!(is_key && (size_t)(q - start) == klen && memcmp(start, key, klen) == 0)) {
            p = q + 1;
            continue;
        }
        /* the member: its value must be a string */
        after++;
        while (*after == ' ' || *after == '\n' || *after == '\t' || *after == '\r') after++;
        if (*after != '"') return NULL;
        after++;
        char *out = malloc(strlen(after) + 1);
        char *o = out;
        while (*after && *after != '"') {
            if (*after != '\\') { *o++ = *after++; continue; }
            after++;
            switch (*after) {
            case 'n': *o++ = '\n'; break;
            case 't': *o++ = '\t'; break;
            case 'r': *o++ = '\r'; break;
            case 'b': *o++ = '\b'; break;
            case 'f': *o++ = '\f'; break;
            case 'u': {
                int v = hex4(after + 1);
                if (v < 0 || v > 0x7f) {
                    fprintf(stderr, "unsupported \\u escape in vector\n");
                    exit(2);
                }
                *o++ = (char)v;
                after += 4;
                break;
            }
            default: *o++ = *after; break; /* \" \\ \/ */
            }
            after++;
        }
        *o = 0;
        return out;
    }
    return NULL;
}

static void load(gt_engine *e, const char *root, const char *rel, int is_model) {
    size_t len;
    char *text = read_file(root, rel, &len);
    gt_buf out = {0};
    int32_t rc = is_model ? gt_load_model(e, (const uint8_t *)text, len, &out)
                          : gt_load_pack(e, (const uint8_t *)text, len, &out);
    if (rc != GT_OK) fprintf(stderr, "load %s: %s\n", rel, (const char *)out.data);
    check(rc == GT_OK, rel);
    gt_buf_free(&out);
    free(text);
}

static int32_t convert(const gt_engine *e, const char *from, const char *to,
                       const char *input, const char *context, gt_buf *out) {
    return gt_convert(e, (const uint8_t *)from, strlen(from),
                      (const uint8_t *)to, strlen(to),
                      (const uint8_t *)input, strlen(input),
                      (const uint8_t *)context, context ? strlen(context) : 0, out);
}

/* Run one vector file that has `expect`; `context` is NULL or key=value text. */
static void run_vector(const gt_engine *e, const char *root, const char *rel, const char *context) {
    size_t len;
    char *json = read_file(root, rel, &len);
    char *from = json_member(json, "from");
    char *to = json_member(json, "to");
    char *input = json_member(json, "input");
    char *expect = json_member(json, "expect");
    if (!from || !to || !input || !expect) {
        fprintf(stderr, "%s: from, to, input and expect are needed\n", rel);
        exit(2);
    }
    gt_buf out = {0};
    int32_t rc = convert(e, from, to, input, context, &out);
    int ok = rc == GT_OK && out.len == strlen(expect) && memcmp(out.data, expect, out.len) == 0;
    if (!ok) fprintf(stderr, "%s\n  got  (%d) %s\n  want %s\n", rel, (int)rc, (const char *)out.data, expect);
    else printf("ok   %s (%s -> %s, %zu bytes)\n", rel, from, to, out.len);
    check(ok, rel);
    gt_buf_free(&out);
    free(from); free(to); free(input); free(expect); free(json);
}

static int starts_with(const gt_buf *b, const char *prefix) {
    return b->data && strncmp((const char *)b->data, prefix, strlen(prefix)) == 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <repository root>\n", argv[0]);
        return 2;
    }
    const char *root = argv[1];
    gt_engine *e = gt_engine_new();
    check(e != NULL, "gt_engine_new");

    load(e, root, "model/core.def", 1);
    load(e, root, "model/track.def", 1);
    load(e, root, "packs/cot-xml/pack.def", 0);
    load(e, root, "packs/geojson/pack.def", 0);
    load(e, root, "packs/canonical-track-v2/pack.def", 0);

    gt_buf out = {0};
    int32_t rc = gt_formats(e, &out);
    check(rc == GT_OK && strcmp((const char *)out.data, "canonical-track-v2\ncot-xml\ngeojson\n") == 0, "gt_formats");
    gt_buf_free(&out);
    check(out.data == NULL && out.len == 0, "gt_buf_free zeroes the buffer");
    gt_buf_free(&out); /* a zeroed buffer is accepted */

    /* the vectors: CoT XML to GeoJSON, and one with a context */
    run_vector(e, root, "packs/cot-xml/vectors/01-track-to-geojson.json", NULL);
    run_vector(e, root, "packs/cot-xml/vectors/02-cot-roundtrip.json", NULL);
    run_vector(e, root, "packs/canonical-track-v2/vectors/02-to-cot-xml.json", NULL);
    run_vector(e, root, "packs/canonical-track-v2/vectors/09-to-cot-xml-context-stale-and-how.json",
               "stale_ms=1614456180250\nhow=m-p\n");

    /* errors keep the engine's kind, and the engine stays usable */
    rc = convert(e, "cot-xml", "geojson", "<event", NULL, &out);
    check(rc == GT_ERR_ENGINE && out.len > 0, "truncated input is an engine error");
    gt_buf_free(&out);
    rc = convert(e, "cot-xml", "cot-xml", "<event uid=\"a\"/>", "no.such_key=1\n", &out);
    check(rc == GT_ERR_ENGINE && starts_with(&out, "undeclared-key:"), "undeclared context key");
    gt_buf_free(&out);
    rc = convert(e, "cot-xml", "geojson", "<event uid=\"a\"/>", "not a pair\n", &out);
    check(rc == GT_ERR_ARGUMENT && starts_with(&out, "bad-argument:"), "context line without =");
    gt_buf_free(&out);
    rc = convert(e, "no-such-format", "geojson", "x", NULL, &out);
    check(rc == GT_ERR_ENGINE && out.len > 0, "unknown format is an engine error");
    gt_buf_free(&out);
    rc = gt_convert(e, (const uint8_t *)"cot-xml", 7, (const uint8_t *)"geojson", 7,
                    (const uint8_t *)"\xff\xfe", 2, NULL, 0, &out);
    check(rc == GT_ERR_ARGUMENT, "input that is not UTF-8");
    gt_buf_free(&out);
    rc = gt_load_pack(e, (const uint8_t *)"format x\n", 9, &out);
    check(rc == GT_ERR_ENGINE && out.len > 0, "a bad pack is refused");
    gt_buf_free(&out);
    rc = gt_formats(NULL, &out);
    check(rc == GT_ERR_ARGUMENT, "null engine");
    gt_buf_free(&out);
    check(convert(e, "cot-xml", "geojson", "<event", NULL, NULL) == GT_ERR_ENGINE, "out may be NULL");
    run_vector(e, root, "packs/cot-xml/vectors/01-track-to-geojson.json", NULL);

    gt_engine_free(e);
    gt_engine_free(NULL);
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}
