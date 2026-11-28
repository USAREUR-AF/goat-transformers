/*
 * The contract of goat_transformers.h, one statement of the header per
 * function below: text arguments, ownership of buffers, error kinds, the
 * engine's life, loading twice, and the distribution limit.
 *
 * The program runs under AddressSanitizer and UndefinedBehaviorSanitizer in
 * test.sh, with leak detection where the platform has it, so "freed exactly
 * once" is checked by the tool and not only stated here.
 *
 * usage: api <repository root>
 */
#include "support.h"

/* A cot-xml event that converts, and what it converts to in its own format. */
static const char EVENT[] = "<event uid=\"a\" type=\"a-f-G\"/>";
static const char EVENT_CANONICAL[] =
    "<event version=\"2.0\" uid=\"a\" type=\"a-f-G\">"
    "<point hae=\"9999999\" ce=\"9999999\" le=\"9999999\"/><detail/></event>";

/* Synthetic texts for the load tests: a model and two packs of one format. */
static const char PROBE_CORE[] =
    "module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\n"
    "key uid string -\nkey lat float deg\nkey time_ms int ms\n";
static const char PROBE_MODULE_CONTROLLED[] =
    "module ctl\nversion 0.1.0\ndistribution controlled\nsource \"probe\"\nkey code int -\n";
static const char PROBE_PACK_PUBLIC[] =
    "format probe\nversion 0.4.0\ndistribution public\nsource \"probe\"\n"
    "wire xml\nroot item\nfield uid @id string\n";
static const char PROBE_PACK_CONTROLLED[] =
    "format probe\nversion 0.4.0\ndistribution controlled\nsource \"probe\"\n"
    "wire xml\nroot item\nfield uid @id string\n";
/* The same format with another root element: tells the two packs apart. */
static const char PROBE_PACK_OTHER_ROOT[] =
    "format probe\nversion 0.4.1\ndistribution public\nsource \"probe\"\n"
    "wire xml\nroot thing\nfield uid @id string\n";

/* An engine holding the files of the repository these tests convert with. */
static gt_engine *repository_engine(const char *root) {
    gt_engine *e = gt_engine_new();
    check(e != NULL, "gt_engine_new");
    load_file(e, root, "model/core.def", 1);
    load_file(e, root, "model/track.def", 1);
    load_file(e, root, "model/cot.def", 1);
    load_file(e, root, "packs/cot-xml/pack.def", 0);
    load_file(e, root, "packs/geojson/pack.def", 0);
    load_file(e, root, "packs/canonical-track-v2/pack.def", 0);
    return e;
}

/* Is the engine still answering correctly? Run after every refusal. */
static void check_still_converts(const gt_engine *e, const char *after) {
    gt_buf out = {0};
    int32_t rc = convert(e, "cot-xml", "cot-xml", EVENT, NULL, &out);
    check(rc == GT_OK && buf_is(&out, EVENT_CANONICAL), "the engine converts after %s: %s", after, buf_text(&out));
    gt_buf_free(&out);
}

/* Expect a status and the beginning of the text; free the buffer. */
static void expect(int32_t rc, gt_buf *out, int32_t want_rc, const char *want_prefix, const char *what) {
    check(rc == want_rc && buf_starts_with(out, want_prefix), "%s: want status %d and `%s...`, got %d `%s`",
          what, (int)want_rc, want_prefix, (int)rc, buf_text(out));
    gt_buf_free(out);
}

static void test_engine_life(void) {
    gt_engine *e = gt_engine_new();
    check(e != NULL, "gt_engine_new gives an engine");

    gt_buf out = {0};
    int32_t rc = gt_formats(e, &out);
    check(rc == GT_OK && out.len == 0, "a new engine has no formats");
    check(out.data != NULL && out.data[0] == 0, "an empty result is a non-NULL, NUL-terminated buffer");
    gt_buf_free(&out);

    gt_engine_free(e);
    gt_engine_free(NULL); /* accepted */

    /* engines are separate: what one loads the other does not have */
    gt_engine *a = gt_engine_new();
    gt_engine *b = gt_engine_new();
    check(a != NULL && b != NULL && a != b, "two engines are two objects");
    expect(load_model(a, PROBE_CORE, &out), &out, GT_OK, "", "load core into the first engine");
    expect(load_pack(a, PROBE_PACK_PUBLIC, &out), &out, GT_OK, "", "load a pack into the first engine");
    rc = gt_formats(a, &out);
    check(rc == GT_OK && buf_is(&out, "probe\n"), "the first engine has the format");
    gt_buf_free(&out);
    rc = gt_formats(b, &out);
    check(rc == GT_OK && buf_is(&out, ""), "the second engine does not");
    gt_buf_free(&out);
    gt_engine_free(a);
    gt_engine_free(b);
}

static void test_buffer_ownership(const char *root) {
    gt_engine *e = repository_engine(root);
    gt_buf out = {0};

    gt_buf_free(NULL);  /* accepted */
    gt_buf_free(&out);  /* a zeroed buffer is accepted */
    check(out.data == NULL && out.len == 0, "freeing a zeroed buffer leaves it zeroed");

    int32_t rc = gt_formats(e, &out);
    check(rc == GT_OK && buf_is(&out, "canonical-track-v2\ncot-xml\ngeojson\n"), "gt_formats: %s", buf_text(&out));
    check(out.data[out.len] == 0, "one NUL follows the bytes");
    gt_buf_free(&out);
    check(out.data == NULL && out.len == 0, "gt_buf_free zeroes the buffer");
    gt_buf_free(&out); /* so freeing the same gt_buf twice is safe */

    /* an error text is a buffer the caller owns too */
    rc = convert(e, "cot-xml", "geojson", "<event", NULL, &out);
    check(rc == GT_ERR_ENGINE && out.len > 0 && out.len == strlen((const char *)out.data), "an error fills the buffer with text");
    gt_buf_free(&out);

    /* a call overwrites `out` without reading it: garbage in it is harmless */
    gt_buf garbage;
    memset(&garbage, 0xa5, sizeof garbage);
    rc = gt_formats(e, &garbage);
    check(rc == GT_OK && garbage.len == 35, "a call does not read what `out` held");
    gt_buf_free(&garbage);

    /* `out` may be NULL on success and on failure: nothing is allocated for the caller */
    check(gt_formats(e, NULL) == GT_OK, "out may be NULL on success");
    check(convert(e, "cot-xml", "cot-xml", EVENT, NULL, NULL) == GT_OK, "out may be NULL on a conversion");
    check(convert(e, "cot-xml", "geojson", "<event", NULL, NULL) == GT_ERR_ENGINE, "out may be NULL on an error");

    /* a buffer outlives the engine that filled it */
    gt_buf kept = {0};
    rc = convert(e, "cot-xml", "cot-xml", EVENT, NULL, &kept);
    gt_engine_free(e);
    check(rc == GT_OK && buf_is(&kept, EVENT_CANONICAL), "a result is valid after gt_engine_free");
    gt_buf_free(&kept);
}

static void test_null_engine(void) {
    gt_buf out = {0};
    expect(gt_formats(NULL, &out), &out, GT_ERR_ARGUMENT, "bad-argument: engine is a null pointer", "gt_formats(NULL)");
    expect(load_model(NULL, PROBE_CORE, &out), &out, GT_ERR_ARGUMENT, "bad-argument: engine", "gt_load_model(NULL)");
    expect(load_pack(NULL, PROBE_PACK_PUBLIC, &out), &out, GT_ERR_ARGUMENT, "bad-argument: engine", "gt_load_pack(NULL)");
    expect(convert(NULL, "a", "b", "c", NULL, &out), &out, GT_ERR_ARGUMENT, "bad-argument: engine", "gt_convert(NULL)");
    expect(gt_engine_set_max_distribution(NULL, GT_DISTRIBUTION_PUBLIC, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: engine", "gt_engine_set_max_distribution(NULL)");
    expect(gt_engine_set_max_items(NULL, 1, &out), &out, GT_ERR_ARGUMENT, "bad-argument: engine", "gt_engine_set_max_items(NULL)");
    check(gt_formats(NULL, NULL) == GT_ERR_ARGUMENT, "a null engine and a null out");
}

/* gt_convert with `input` given as a pointer and a length. */
static int32_t convert_bytes(const gt_engine *e, const uint8_t *input, size_t input_len, gt_buf *out) {
    return gt_convert(e, (const uint8_t *)"cot-xml", 7, (const uint8_t *)"cot-xml", 7, input, input_len, NULL, 0, out);
}

static void test_null_and_empty_text(const char *root) {
    gt_engine *e = repository_engine(root);
    gt_buf out = {0};
    const uint8_t *cot = (const uint8_t *)"cot-xml";
    const uint8_t *event = (const uint8_t *)EVENT;
    size_t event_len = strlen(EVENT);

    /* a NULL pointer with a length is refused, for every text argument */
    expect(convert_bytes(e, NULL, 5, &out), &out, GT_ERR_ARGUMENT, "bad-argument: input is a null pointer", "NULL input with a length");
    expect(gt_convert(e, NULL, 7, cot, 7, event, event_len, NULL, 0, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: from is a null pointer", "NULL from with a length");
    expect(gt_convert(e, cot, 7, NULL, 7, event, event_len, NULL, 0, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: to is a null pointer", "NULL to with a length");
    expect(gt_load_model(e, NULL, 9, &out), &out, GT_ERR_ARGUMENT, "bad-argument: model text is a null pointer", "NULL model text with a length");
    expect(gt_load_pack(e, NULL, 9, &out), &out, GT_ERR_ARGUMENT, "bad-argument: pack text is a null pointer", "NULL pack text with a length");
    check_still_converts(e, "refused NULL arguments");

    /*
     * A length of 0 is the empty text, whatever the pointer: the argument is
     * accepted and it is the engine that refuses the empty message or file.
     */
    expect(convert_bytes(e, NULL, 0, &out), &out, GT_ERR_ENGINE, "", "NULL input of length 0 is the empty message");
    expect(convert_bytes(e, event, 0, &out), &out, GT_ERR_ENGINE, "", "an input of length 0 is the empty message");
    expect(gt_convert(e, NULL, 0, cot, 7, event, event_len, NULL, 0, &out), &out, GT_ERR_ENGINE, "", "NULL from of length 0 is the empty name");
    expect(gt_load_model(e, NULL, 0, &out), &out, GT_ERR_ENGINE, "", "NULL model text of length 0 is the empty file");
    expect(gt_load_pack(e, NULL, 0, &out), &out, GT_ERR_ENGINE, "", "NULL pack text of length 0 is the empty file");

    /* a NULL context is no context, whatever its length says */
    int32_t rc = gt_convert(e, cot, 7, cot, 7, event, event_len, NULL, 99, &out);
    check(rc == GT_OK && buf_is(&out, EVENT_CANONICAL), "a NULL context is no context: %s", buf_text(&out));
    gt_buf_free(&out);
    /* a context of length 0 that is not NULL is an empty context */
    rc = gt_convert(e, cot, 7, cot, 7, event, event_len, event, 0, &out);
    check(rc == GT_OK && buf_is(&out, EVENT_CANONICAL), "an empty context: %s", buf_text(&out));
    gt_buf_free(&out);

    check_still_converts(e, "empty arguments");
    gt_engine_free(e);
}

static void test_text_that_is_not_utf8(const char *root) {
    gt_engine *e = repository_engine(root);
    gt_buf out = {0};
    const uint8_t *cot = (const uint8_t *)"cot-xml";
    const uint8_t *event = (const uint8_t *)EVENT;
    size_t event_len = strlen(EVENT);
    const uint8_t bad[] = {0xff, 0xfe};
    /* "é" is two bytes; one of them alone is a sequence cut short */
    const uint8_t cut[] = {'a', 0xc3};

    expect(convert_bytes(e, bad, sizeof bad, &out), &out, GT_ERR_ARGUMENT, "bad-argument: input is not UTF-8", "input that is not UTF-8");
    expect(convert_bytes(e, cut, sizeof cut, &out), &out, GT_ERR_ARGUMENT, "bad-argument: input is not UTF-8", "input cut inside a character");
    expect(gt_convert(e, bad, sizeof bad, cot, 7, event, event_len, NULL, 0, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: from is not UTF-8", "from that is not UTF-8");
    expect(gt_convert(e, cot, 7, bad, sizeof bad, event, event_len, NULL, 0, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: to is not UTF-8", "to that is not UTF-8");
    expect(gt_convert(e, cot, 7, cot, 7, event, event_len, bad, sizeof bad, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: context is not UTF-8", "context that is not UTF-8");
    expect(gt_load_model(e, bad, sizeof bad, &out), &out, GT_ERR_ARGUMENT, "bad-argument: model text is not UTF-8", "model text that is not UTF-8");
    expect(gt_load_pack(e, bad, sizeof bad, &out), &out, GT_ERR_ARGUMENT, "bad-argument: pack text is not UTF-8", "pack text that is not UTF-8");

    check_still_converts(e, "text that is not UTF-8");
    gt_engine_free(e);
}

/*
 * The length says where a text ends, not a NUL: a NUL inside an argument is
 * one more character, and a result that holds one is longer than its strlen.
 * An XML encoder refuses to write U+0000 (engine-spec ruling 1d of 0.11), so
 * a NUL in an attribute value reaches the encoder and fails there.
 */
static void test_embedded_nul(const char *root) {
    gt_engine *e = repository_engine(root);
    gt_buf out = {0};

    /* a format name is not cut at its NUL: "cot-xml\0x" is not "cot-xml" */
    const uint8_t name[] = "cot-xml\0x";
    int32_t rc = gt_convert(e, name, 9, (const uint8_t *)"cot-xml", 7, (const uint8_t *)EVENT, strlen(EVENT), NULL, 0, &out);
    check(rc == GT_ERR_ENGINE, "a format name with a NUL in it names no loaded format (status %d)", (int)rc);
    check(out.len > strlen((const char *)out.data), "the error text holds the whole name, NUL included");
    gt_buf_free(&out);

    /* a value with a NUL in it is read whole: the document parses (cut at the
       NUL it would be `malformed-wire`) and the encoder refuses the character */
    const char input[] = "<event uid=\"a\0b\" type=\"a-f-G\"/>";
    rc = convert_bytes(e, (const uint8_t *)input, sizeof input - 1, &out);
    expect(rc, &out, GT_ERR_ENGINE, "transform-encode:", "a NUL inside a value reaches the encoder");

    /* a model text is read past a NUL too: the line after it is still seen */
    const char model[] = "module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\n\0key uid string -\nnot-a-directive\n";
    gt_engine *fresh = gt_engine_new();
    rc = gt_load_model(fresh, (const uint8_t *)model, sizeof model - 1, &out);
    check(rc == GT_ERR_ENGINE, "a model text is not cut at a NUL (status %d: %s)", (int)rc, buf_text(&out));
    gt_buf_free(&out);
    gt_engine_free(fresh);

    check_still_converts(e, "arguments with a NUL");
    gt_engine_free(e);
}

static void test_error_kinds(const char *root) {
    gt_engine *e = repository_engine(root);
    gt_buf out = {0};

    expect(convert(e, "cot-xml", "geojson", "<event", NULL, &out), &out, GT_ERR_ENGINE, "malformed-wire:", "a truncated message");
    expect(convert(e, "no-such-format", "geojson", "x", NULL, &out), &out, GT_ERR_ENGINE, "", "a source format that is not loaded");
    expect(convert(e, "cot-xml", "no-such-format", EVENT, NULL, &out), &out, GT_ERR_ENGINE, "", "a target format that is not loaded");
    expect(convert(e, "cot-xml", "cot-xml", EVENT, "no.such_key=1\n", &out), &out, GT_ERR_ENGINE, "undeclared-key:", "a context key no module declares");
    expect(convert(e, "cot-xml", "cot-xml", EVENT, "time_ms=soon\n", &out), &out, GT_ERR_ENGINE, "key-type-mismatch:", "a context value of the wrong type");
    expect(convert(e, "cot-xml", "geojson", EVENT, "not a pair\n", &out), &out, GT_ERR_ARGUMENT, "bad-argument: context line `not a pair`", "a context line without =");
    expect(load_pack(e, "format x\n", &out), &out, GT_ERR_ENGINE, "", "a pack that does not parse");
    expect(load_model(e, "module x\nversion 1\n", &out), &out, GT_ERR_ENGINE, "missing-distribution:", "a model module without a distribution");

    /* a refused load changes nothing */
    int32_t rc = gt_formats(e, &out);
    check(rc == GT_OK && buf_is(&out, "canonical-track-v2\ncot-xml\ngeojson\n"), "refused loads leave the formats as they were");
    gt_buf_free(&out);
    check_still_converts(e, "every kind of error");
    gt_engine_free(e);
}

/* Append `count` copies of `piece` at `to`; returns the place after them. */
static char *append(char *to, const char *piece, int count) {
    size_t len = strlen(piece);
    for (int i = 0; i < count; i++, to += len) memcpy(to, piece, len);
    *to = 0;
    return to;
}

/*
 * A message nested `levels` deep: `open` holds the two outer levels, then
 * come levels - 2 of `down` closed by as many `up`, then `close`. Allocated.
 */
static char *nested(const char *open, const char *down, const char *up, const char *close, int levels) {
    int inner = levels - 2;
    char *text = must_alloc(strlen(open) + (size_t)inner * (strlen(down) + strlen(up)) + strlen(close) + 1);
    append(append(append(append(text, open, 1), down, inner), up, inner), close, 1);
    return text;
}

/* A cot-xml event: the root element is level 1 and its <detail> level 2. */
static char *nested_xml(int levels) {
    return nested("<event uid=\"a\" type=\"a-f-G\"><detail>", "<n>", "</n>", "</detail></event>", levels);
}

/* A GeoJSON feature: the outermost object is level 1 and `properties` level 2. */
static char *nested_json(int levels) {
    return nested("{\"type\":\"Feature\",\"id\":\"a\",\"geometry\":null,\"properties\":{\"x\":", "[", "]", "}}", levels);
}

/*
 * A message that is not well formed is the engine's `malformed-wire`, never
 * a panic and never the end of the process (spec/engine-spec.md, Malformed
 * input, ruling 35: 64 levels of nesting convert, 65 do not). The engine
 * owns the rule and the conformance-malformed packs pin it; this test shows
 * what a host of the library sees: GT_ERR_ENGINE, not GT_ERR_PANIC, and an
 * engine that goes on converting.
 */
static void test_malformed_input(const char *root) {
    gt_engine *e = repository_engine(root);
    gt_buf out = {0};

    /* an attribute cut off after its `=`, and other ways to stop early */
    const char *cut[] = {"<event uid=", "<event uid=\"", "<event uid", "<event ", "<", "<event uid=\"a\"><point"};
    for (size_t i = 0; i < sizeof cut / sizeof cut[0]; i++) {
        expect(convert(e, "cot-xml", "geojson", cut[i], NULL, &out), &out, GT_ERR_ENGINE, "malformed-wire:", cut[i]);
    }
    check_still_converts(e, "truncated messages");

    struct {
        const char *format;
        char *(*message)(int levels);
    } wires[] = {{"cot-xml", nested_xml}, {"geojson", nested_json}};
    for (size_t w = 0; w < sizeof wires / sizeof wires[0]; w++) {
        const char *format = wires[w].format;

        char *at_limit = wires[w].message(64);
        int32_t rc = convert(e, format, format, at_limit, NULL, &out);
        check(rc == GT_OK, "%s nested 64 levels converts (status %d: %.80s)", format, (int)rc, buf_text(&out));
        gt_buf_free(&out);
        free(at_limit);

        int too_deep[] = {65, 30000};
        for (size_t d = 0; d < sizeof too_deep / sizeof too_deep[0]; d++) {
            char *message = wires[w].message(too_deep[d]);
            rc = convert(e, format, format, message, NULL, &out);
            check(rc == GT_ERR_ENGINE && buf_starts_with(&out, "malformed-wire:"),
                  "%s nested %d levels is malformed-wire (status %d: %.80s)", format, too_deep[d], (int)rc, buf_text(&out));
            gt_buf_free(&out);
            free(message);
        }
        check_still_converts(e, "messages nested too deep");
    }
    gt_engine_free(e);
}

/* The context text: the key ends at the first '=', and the value is the rest. */
static void test_context_text(const char *root) {
    gt_engine *e = repository_engine(root);
    gt_buf out = {0};

    int32_t rc = convert(e, "cot-xml", "cot-xml", EVENT, "how=m=p\n", &out);
    check(rc == GT_OK && buf_contains(&out, " how=\"m=p\""), "a value may hold '=': %s", buf_text(&out));
    gt_buf_free(&out);

    rc = convert(e, "cot-xml", "cot-xml", EVENT, "how=\n", &out);
    check(rc == GT_OK && buf_contains(&out, " how=\"\""), "a value may be empty: %s", buf_text(&out));
    gt_buf_free(&out);

    rc = convert(e, "cot-xml", "cot-xml", EVENT, "callsign=Zo\xc3\xab\n", &out);
    check(rc == GT_OK && buf_contains(&out, "callsign=\"Zo\xc3\xab\""), "a value may be any UTF-8: %s", buf_text(&out));
    gt_buf_free(&out);

    rc = convert(e, "cot-xml", "cot-xml", EVENT, "\n\nhow=m-p\n\ncallsign=GATOR", &out);
    check(rc == GT_OK && buf_contains(&out, " how=\"m-p\"") && buf_contains(&out, "callsign=\"GATOR\""),
          "empty lines are skipped and the last line needs no line break: %s", buf_text(&out));
    gt_buf_free(&out);

    expect(convert(e, "cot-xml", "cot-xml", EVENT, "=1\n", &out), &out, GT_ERR_ENGINE, "undeclared-key:", "an empty key is the engine's to refuse");

    /* a key the message already carries is not replaced by the context */
    rc = convert(e, "cot-xml", "cot-xml", "<event uid=\"a\" type=\"a-f-G\" how=\"h-e\"/>", "how=m-p\n", &out);
    check(rc == GT_OK && buf_contains(&out, " how=\"h-e\"") && !buf_contains(&out, "m-p"), "the message wins over the context: %s", buf_text(&out));
    gt_buf_free(&out);

    gt_engine_free(e);
}

static void test_loading_twice(void) {
    gt_engine *e = gt_engine_new();
    gt_buf out = {0};
    expect(load_model(e, PROBE_CORE, &out), &out, GT_OK, "", "load core");
    expect(load_pack(e, PROBE_PACK_PUBLIC, &out), &out, GT_OK, "", "load the pack");

    /* a module name is loaded once, and the refusal leaves the engine as it was */
    expect(load_model(e, PROBE_CORE, &out), &out, GT_ERR_ENGINE, "duplicate-module:", "the same module a second time");
    int32_t rc = convert(e, "probe", "probe", "<item id=\"u1\"/>", NULL, &out);
    check(rc == GT_OK && buf_is(&out, "<item id=\"u1\"/>"), "the engine converts after a duplicate module: %s", buf_text(&out));
    gt_buf_free(&out);

    /* a format name is loaded once (engine-spec ruling 5 of 0.11): the same
       pack a second time is refused and the format is listed once */
    expect(load_pack(e, PROBE_PACK_PUBLIC, &out), &out, GT_ERR_ENGINE, "duplicate-format:", "the same pack a second time");
    rc = gt_formats(e, &out);
    check(rc == GT_OK && buf_is(&out, "probe\n"), "a format loaded twice is listed once: %s", buf_text(&out));
    gt_buf_free(&out);

    /* another pack of a loaded format name is refused; the first stays loaded */
    expect(load_pack(e, PROBE_PACK_OTHER_ROOT, &out), &out, GT_ERR_ENGINE, "duplicate-format:", "another pack of the same format name");
    rc = convert(e, "probe", "probe", "<item id=\"u1\"/>", NULL, &out);
    check(rc == GT_OK && buf_is(&out, "<item id=\"u1\"/>"), "the first pack is the one in use: %s", buf_text(&out));
    gt_buf_free(&out);
    expect(convert(e, "probe", "probe", "<thing id=\"u1\"/>", NULL, &out), &out, GT_ERR_ENGINE, "missing-root:", "the refused pack is not in use");

    gt_engine_free(e);
}

/* A new engine with the limit set, and the core module loaded. */
static gt_engine *engine_limited_to(int32_t limit) {
    gt_engine *e = gt_engine_new();
    gt_buf out = {0};
    expect(gt_engine_set_max_distribution(e, limit, &out), &out, GT_OK, "", "set the distribution limit");
    expect(load_model(e, PROBE_CORE, &out), &out, GT_OK, "", "a public module loads under any limit");
    return e;
}

static void test_distribution_limit(void) {
    gt_buf out = {0};

    /* public only: everything controlled is refused at load, by the engine's named error */
    gt_engine *e = engine_limited_to(GT_DISTRIBUTION_PUBLIC);
    expect(load_pack(e, PROBE_PACK_CONTROLLED, &out), &out, GT_ERR_ENGINE, "distribution-refused: pack `probe` is controlled",
           "a controlled pack under the public limit");
    expect(load_model(e, PROBE_MODULE_CONTROLLED, &out), &out, GT_ERR_ENGINE, "distribution-refused: model module `ctl` is controlled",
           "a controlled module under the public limit");
    int32_t rc = gt_formats(e, &out);
    check(rc == GT_OK && buf_is(&out, ""), "nothing refused was loaded: %s", buf_text(&out));
    gt_buf_free(&out);
    expect(convert(e, "probe", "probe", "<item id=\"u1\"/>", NULL, &out), &out, GT_ERR_ENGINE, "", "a refused format does not convert");
    /* what is public still loads and converts */
    expect(load_pack(e, PROBE_PACK_PUBLIC, &out), &out, GT_OK, "", "a public pack under the public limit");
    rc = convert(e, "probe", "probe", "<item id=\"u1\"/>", NULL, &out);
    check(rc == GT_OK && buf_is(&out, "<item id=\"u1\"/>"), "the public pack converts: %s", buf_text(&out));
    gt_buf_free(&out);
    /* the limit cannot be lifted once something is loaded */
    expect(gt_engine_set_max_distribution(e, GT_DISTRIBUTION_CONTROLLED, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: the distribution limit is set before", "lifting the limit after a load");
    expect(load_pack(e, PROBE_PACK_CONTROLLED, &out), &out, GT_ERR_ENGINE, "distribution-refused:", "the limit still holds");
    gt_engine_free(e);

    /* the default, and the limit `controlled` said out loud, load both markings */
    e = gt_engine_new();
    expect(load_model(e, PROBE_CORE, &out), &out, GT_OK, "", "load core");
    expect(load_model(e, PROBE_MODULE_CONTROLLED, &out), &out, GT_OK, "", "a controlled module with no limit set");
    expect(load_pack(e, PROBE_PACK_CONTROLLED, &out), &out, GT_OK, "", "a controlled pack with no limit set");
    /* nor can the limit be lowered under what is already loaded */
    expect(gt_engine_set_max_distribution(e, GT_DISTRIBUTION_PUBLIC, &out), &out, GT_ERR_ARGUMENT,
           "bad-argument: the distribution limit is set before", "lowering the limit after a load");
    gt_engine_free(e);

    e = engine_limited_to(GT_DISTRIBUTION_CONTROLLED);
    expect(load_pack(e, PROBE_PACK_CONTROLLED, &out), &out, GT_OK, "", "a controlled pack under the controlled limit");
    gt_engine_free(e);

    /* a value that is no limit is refused and leaves the default */
    e = gt_engine_new();
    expect(gt_engine_set_max_distribution(e, 2, &out), &out, GT_ERR_ARGUMENT, "bad-argument: distribution limit 2", "a limit of 2");
    expect(gt_engine_set_max_distribution(e, -1, &out), &out, GT_ERR_ARGUMENT, "bad-argument: distribution limit -1", "a limit of -1");
    expect(load_model(e, PROBE_CORE, &out), &out, GT_OK, "", "load core");
    expect(load_pack(e, PROBE_PACK_CONTROLLED, &out), &out, GT_OK, "", "a controlled pack after refused limits");
    gt_engine_free(e);

    /* the status alone says whether the limit was set */
    e = gt_engine_new();
    check(gt_engine_set_max_distribution(e, GT_DISTRIBUTION_PUBLIC, NULL) == GT_OK, "out may be NULL when setting the limit");
    expect(load_model(e, PROBE_CORE, &out), &out, GT_OK, "", "load core");
    expect(load_pack(e, PROBE_PACK_CONTROLLED, &out), &out, GT_ERR_ENGINE, "distribution-refused:", "the limit set with a NULL out holds");
    gt_engine_free(e);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <repository root>\n", argv[0]);
        return 2;
    }
    const char *root = argv[1];
    test_engine_life();
    test_buffer_ownership(root);
    test_null_engine();
    test_null_and_empty_text(root);
    test_text_that_is_not_utf8(root);
    test_embedded_nul(root);
    test_error_kinds(root);
    test_malformed_input(root);
    test_context_text(root);
    test_loading_twice();
    test_distribution_limit();
    return finish("api");
}
