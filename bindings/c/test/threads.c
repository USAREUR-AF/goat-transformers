/*
 * The header's statement on threads: gt_convert and gt_formats may run on
 * several threads at once on one engine.
 *
 * Eight threads each run 1,000 conversions on one engine, every thread
 * walking the same set of conversions from a different starting point, while
 * a ninth thread only reads the format list. Every result must equal the one
 * a single thread got before the others started. All threads are held at a
 * gate and released together, so the calls overlap.
 *
 * What makes this safe is in the library, not here: the engine type is
 * checked at compile time to be shareable between threads (`Send + Sync`),
 * and the two calls take the engine read-only. This program shows the
 * statement holding under load, and test.sh also runs it under
 * ThreadSanitizer, which watches the C side of the boundary.
 *
 * usage: threads <repository root>
 */
#include "support.h"

#include <pthread.h>

enum { CONVERTERS = 8, CONVERSIONS_EACH = 1000, FORMAT_READS = 2000 };

typedef struct {
    const char *from;
    const char *to;
    const char *input;
    const char *context; /* NULL: none */
    int32_t status;      /* what one thread got, before the others ran */
    gt_buf result;
} conversion;

/* Successes of several shapes and an error: every path is shared. */
static conversion conversions[] = {
    {"cot-xml", "geojson",
     "<event uid=\"J-01334\" type=\"a-f-G-U-C\" time=\"2021-02-27T20:00:00.000Z\" how=\"m-g\">"
     "<point lat=\"30.0090027\" lon=\"-85.9578182\" hae=\"-42.6\" ce=\"45.3\" le=\"99.5\"/>"
     "<detail><contact callsign=\"GATOR\"/></detail></event>",
     NULL, 0, {0}},
    {"cot-xml", "cot-xml", "<event uid=\"a\" type=\"a-f-G\"/>", NULL, 0, {0}},
    {"cot-xml", "cot-xml", "<event uid=\"b\" type=\"a-h-A\"/>", "how=m-p\ncallsign=VIPER\n", 0, {0}},
    {"geojson", "cot-xml",
     "{\"type\":\"Feature\",\"id\":\"g1\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[8.5,47.25,410]},"
     "\"properties\":{\"type\":\"a-f-G\",\"time_ms\":1614456000000}}",
     NULL, 0, {0}},
    {"cot-xml", "geojson", "<event uid=\"cut", NULL, 0, {0}},
    {"cot-xml", "cot-xml", "<event uid=\"a\" type=\"a-f-G\"/>", "no.such_key=1\n", 0, {0}},
};
enum { CONVERSION_COUNT = sizeof conversions / sizeof conversions[0] };

static const gt_engine *engine;
static gt_buf formats_expected;

/* The gate every thread waits at, so that all of them start together. */
static pthread_mutex_t gate_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t gate_opened = PTHREAD_COND_INITIALIZER;
static int gate_is_open = 0;

static void wait_at_gate(void) {
    pthread_mutex_lock(&gate_lock);
    while (!gate_is_open) pthread_cond_wait(&gate_opened, &gate_lock);
    pthread_mutex_unlock(&gate_lock);
}

static void open_gate(void) {
    pthread_mutex_lock(&gate_lock);
    gate_is_open = 1;
    pthread_cond_broadcast(&gate_opened);
    pthread_mutex_unlock(&gate_lock);
}

static int same(int32_t status, const gt_buf *got, int32_t want_status, const gt_buf *want) {
    return status == want_status && got->data && got->len == want->len && memcmp(got->data, want->data, want->len) == 0;
}

/* What a thread found. A thread counts for itself: `check` is not shared. */
typedef struct {
    int start; /* where in `conversions` this thread begins */
    long calls;
    long mismatches;
} tally;

static void *run_conversions(void *arg) {
    tally *t = arg;
    wait_at_gate();
    for (int i = 0; i < CONVERSIONS_EACH; i++) {
        const conversion *c = &conversions[(t->start + i) % CONVERSION_COUNT];
        gt_buf out = {0};
        int32_t status = convert(engine, c->from, c->to, c->input, c->context, &out);
        t->calls++;
        if (!same(status, &out, c->status, &c->result)) t->mismatches++;
        gt_buf_free(&out);
    }
    return NULL;
}

static void *read_formats(void *arg) {
    tally *t = arg;
    wait_at_gate();
    for (int i = 0; i < FORMAT_READS; i++) {
        gt_buf out = {0};
        int32_t status = gt_formats(engine, &out);
        t->calls++;
        if (!same(status, &out, GT_OK, &formats_expected)) t->mismatches++;
        gt_buf_free(&out);
    }
    return NULL;
}

/* One thread, before any other exists: the results all threads must repeat. */
static void record_expected_results(void) {
    int successes = 0;
    for (int i = 0; i < CONVERSION_COUNT; i++) {
        conversion *c = &conversions[i];
        c->status = convert(engine, c->from, c->to, c->input, c->context, &c->result);
        if (c->status == GT_OK) successes++;
        check(c->result.data != NULL, "conversion %d gives a result or an error text", i);
    }
    check(successes == 4, "four of the conversions succeed and two fail (%d succeed)", successes);
    check(gt_formats(engine, &formats_expected) == GT_OK, "gt_formats");
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <repository root>\n", argv[0]);
        return 2;
    }
    const char *root = argv[1];
    gt_engine *loading = gt_engine_new();
    load_file(loading, root, "model/core.def", 1);
    load_file(loading, root, "model/track.def", 1);
    load_file(loading, root, "packs/cot-xml/pack.def", 0);
    load_file(loading, root, "packs/geojson/pack.def", 0);
    engine = loading; /* loading is over: from here the engine is only read */
    record_expected_results();

    pthread_t threads[CONVERTERS + 1];
    tally tallies[CONVERTERS + 1];
    for (int i = 0; i <= CONVERTERS; i++) {
        tallies[i].start = i;
        tallies[i].calls = 0;
        tallies[i].mismatches = 0;
        void *(*work)(void *) = i < CONVERTERS ? run_conversions : read_formats;
        if (pthread_create(&threads[i], NULL, work, &tallies[i]) != 0) stop("cannot start", "a thread");
    }
    open_gate();
    long calls = 0;
    for (int i = 0; i <= CONVERTERS; i++) {
        pthread_join(threads[i], NULL);
        calls += tallies[i].calls;
        check(tallies[i].mismatches == 0, "thread %d: %ld of %ld results differ from the single-threaded result",
              i, tallies[i].mismatches, tallies[i].calls);
    }
    check(calls == (long)CONVERTERS * CONVERSIONS_EACH + FORMAT_READS, "every call ran (%ld)", calls);
    printf("threads: %d threads x %d conversions and %d format reads on one engine\n", CONVERTERS, CONVERSIONS_EACH, FORMAT_READS);

    for (int i = 0; i < CONVERSION_COUNT; i++) gt_buf_free(&conversions[i].result);
    gt_buf_free(&formats_expected);
    gt_engine_free(loading);
    return finish("threads");
}
