/*
 * Every conversion vector of the repository through the C ABI.
 *
 * Loads every model/<module>.def and every packs/<format>/pack.def, then runs
 * every packs/<format>/vectors/<name>.json with gt_convert and compares with
 * its `expect` (the same bytes) or its `expect_error` (GT_ERR_ENGINE and a
 * text that begins with that kind and a colon), as spec/vector-format.md
 * states. The `model` checks of a vector are not run: the library has no
 * decode call. Load vectors are not run.
 *
 * The library is a way to ship the Rust engine, so this run is not a voice
 * in the cross-check of the engines. It shows that the boundary loses
 * nothing: texts, lengths, contexts and error kinds arrive as they were sent.
 *
 * usage: vectors <repository root>
 */
#define _POSIX_C_SOURCE 200809L /* opendir, readdir */

#include "support.h"

#include <dirent.h>

/* ---- a list of names, sorted in byte order --------------------------------- */

typedef struct {
    char **items;
    size_t count;
} names;

static void names_add(names *list, const char *name) {
    list->items = realloc(list->items, (list->count + 1) * sizeof *list->items);
    if (!list->items) stop("out of memory", "");
    char *copy = must_alloc(strlen(name) + 1);
    strcpy(copy, name);
    list->items[list->count++] = copy;
}

static void names_free(names *list) {
    for (size_t i = 0; i < list->count; i++) free(list->items[i]);
    free(list->items);
    list->items = NULL;
    list->count = 0;
}

static int by_bytes(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static int ends_with(const char *name, const char *suffix) {
    size_t n = strlen(name), s = strlen(suffix);
    return n >= s && strcmp(name + n - s, suffix) == 0;
}

/*
 * The entries of `dir` whose name ends with `suffix`, sorted. A directory
 * that does not exist has no entries; `must_exist` makes that an error.
 */
static names list_dir(const char *dir, const char *suffix, int must_exist) {
    names found = {0};
    DIR *d = opendir(dir);
    if (!d) {
        if (must_exist) stop("cannot list", dir);
        return found;
    }
    for (struct dirent *entry; (entry = readdir(d)) != NULL;) {
        if (entry->d_name[0] != '.' && ends_with(entry->d_name, suffix)) names_add(&found, entry->d_name);
    }
    closedir(d);
    if (found.count) qsort(found.items, found.count, sizeof *found.items, by_bytes);
    return found;
}

static int file_exists(const char *dir, const char *rel) {
    char *path = join_path(dir, rel);
    FILE *f = fopen(path, "rb");
    free(path);
    if (f) fclose(f);
    return f != NULL;
}

/* ---- JSON: what a vector file needs ---------------------------------------- */

/* A text with its length: a vector's input may hold a NUL (\u0000). */
typedef struct {
    char *bytes; /* NULL: the member is absent */
    size_t len;
} text;

typedef struct {
    const char *at;
    const char *file; /* for messages */
} json;

static void json_stop(const json *j, const char *what) {
    fprintf(stderr, "cannot run: %s: %s near `%.20s`\n", j->file, what, j->at);
    exit(2);
}

static void json_space(json *j) {
    while (*j->at == ' ' || *j->at == '\n' || *j->at == '\t' || *j->at == '\r') j->at++;
}

/* Skip white space, then take `c` if it is next. */
static int json_take(json *j, char c) {
    json_space(j);
    if (*j->at != c) return 0;
    j->at++;
    return 1;
}

static void json_need(json *j, char c, const char *what) {
    if (!json_take(j, c)) json_stop(j, what);
}

static unsigned json_hex4(json *j) {
    unsigned value = 0;
    for (int i = 0; i < 4; i++) {
        char c = *j->at++;
        unsigned digit = c >= '0' && c <= '9'   ? (unsigned)(c - '0')
                         : c >= 'a' && c <= 'f' ? (unsigned)(c - 'a' + 10)
                         : c >= 'A' && c <= 'F' ? (unsigned)(c - 'A' + 10)
                                                : 16;
        if (digit == 16) json_stop(j, "a \\u escape needs four hex digits");
        value = value * 16 + digit;
    }
    return value;
}

/* The code point of a \u escape whose "\u" was read; joins a surrogate pair. */
static unsigned json_escaped_code_point(json *j) {
    unsigned high = json_hex4(j);
    if (high < 0xd800 || high > 0xdfff) return high;
    if (high > 0xdbff || j->at[0] != '\\' || j->at[1] != 'u') json_stop(j, "a surrogate with no partner");
    j->at += 2;
    unsigned low = json_hex4(j);
    if (low < 0xdc00 || low > 0xdfff) json_stop(j, "a surrogate with no partner");
    return 0x10000 + ((high - 0xd800) << 10) + (low - 0xdc00);
}

/* Write a code point as UTF-8; returns the place after it. */
static char *utf8_put(char *to, unsigned cp) {
    if (cp < 0x80) {
        *to++ = (char)cp;
    } else if (cp < 0x800) {
        *to++ = (char)(0xc0 | (cp >> 6));
        *to++ = (char)(0x80 | (cp & 0x3f));
    } else if (cp < 0x10000) {
        *to++ = (char)(0xe0 | (cp >> 12));
        *to++ = (char)(0x80 | ((cp >> 6) & 0x3f));
        *to++ = (char)(0x80 | (cp & 0x3f));
    } else {
        *to++ = (char)(0xf0 | (cp >> 18));
        *to++ = (char)(0x80 | ((cp >> 12) & 0x3f));
        *to++ = (char)(0x80 | ((cp >> 6) & 0x3f));
        *to++ = (char)(0x80 | (cp & 0x3f));
    }
    return to;
}

/* A JSON string, unescaped. The value is never longer than its source. */
static text json_string(json *j) {
    json_need(j, '"', "a string is expected");
    text value;
    value.bytes = must_alloc(strlen(j->at) + 1);
    char *to = value.bytes;
    while (*j->at != '"') {
        if (*j->at == 0) json_stop(j, "a string does not end");
        if (*j->at != '\\') {
            *to++ = *j->at++;
            continue;
        }
        char escape = j->at[1];
        j->at += 2;
        switch (escape) {
        case '"': case '\\': case '/': *to++ = escape; break;
        case 'n': *to++ = '\n'; break;
        case 't': *to++ = '\t'; break;
        case 'r': *to++ = '\r'; break;
        case 'b': *to++ = '\b'; break;
        case 'f': *to++ = '\f'; break;
        case 'u': to = utf8_put(to, json_escaped_code_point(j)); break;
        default: json_stop(j, "an unknown escape");
        }
    }
    j->at++;
    *to = 0;
    value.len = (size_t)(to - value.bytes);
    return value;
}

/* Skip one value of any type. */
static void json_skip(json *j) {
    json_space(j);
    char open = *j->at;
    if (open == '"') {
        free(json_string(j).bytes);
    } else if (open == '{' || open == '[') {
        char close = open == '{' ? '}' : ']';
        j->at++;
        if (json_take(j, close)) return;
        do {
            if (open == '{') {
                free(json_string(j).bytes);
                json_need(j, ':', "`:` is expected after a member name");
            }
            json_skip(j);
        } while (json_take(j, ','));
        json_need(j, close, "a list or an object does not end");
    } else {
        /* a number, true, false or null */
        const char *start = j->at;
        while (*j->at && !strchr(",}] \n\t\r", *j->at)) j->at++;
        if (j->at == start) json_stop(j, "a value is expected");
    }
}

/* ---- a vector --------------------------------------------------------------- */

typedef struct {
    text from, to, input, expect, expect_error;
    text context; /* "key=value\n" lines; bytes NULL: the vector has no context */
} vector;

static void vector_free(vector *v) {
    free(v->from.bytes);
    free(v->to.bytes);
    free(v->input.bytes);
    free(v->expect.bytes);
    free(v->expect_error.bytes);
    free(v->context.bytes);
}

/*
 * A vector's `context` object as the text gt_convert takes. An empty object
 * is an empty text that is not NULL: a context given (ruling 10 of 0.6).
 */
static text context_text(json *j) {
    text lines;
    lines.bytes = must_alloc(strlen(j->at) + 1);
    lines.len = 0;
    json_need(j, '{', "`context` is an object");
    if (json_take(j, '}')) return lines;
    do {
        text key = json_string(j);
        json_need(j, ':', "`:` is expected after a context key");
        json_space(j);
        if (*j->at != '"') json_stop(j, "a context value is a string");
        text value = json_string(j);
        if (memchr(key.bytes, '=', key.len) || memchr(key.bytes, '\n', key.len) || memchr(value.bytes, '\n', value.len)) {
            json_stop(j, "a context the key=value text cannot carry");
        }
        /* key, '=', value and '\n' are never longer than their JSON source */
        memcpy(lines.bytes + lines.len, key.bytes, key.len);
        lines.len += key.len;
        lines.bytes[lines.len++] = '=';
        memcpy(lines.bytes + lines.len, value.bytes, value.len);
        lines.len += value.len;
        lines.bytes[lines.len++] = '\n';
        free(key.bytes);
        free(value.bytes);
    } while (json_take(j, ','));
    json_need(j, '}', "`context` does not end");
    return lines;
}

static vector read_vector(const char *source, const char *file) {
    vector v;
    memset(&v, 0, sizeof v);
    json j = {source, file};
    json_need(&j, '{', "a vector is an object");
    if (json_take(&j, '}')) return v;
    do {
        text name = json_string(&j);
        json_need(&j, ':', "`:` is expected after a member name");
        json_space(&j);
        text *member = strcmp(name.bytes, "from") == 0           ? &v.from
                       : strcmp(name.bytes, "to") == 0           ? &v.to
                       : strcmp(name.bytes, "input") == 0        ? &v.input
                       : strcmp(name.bytes, "expect") == 0       ? &v.expect
                       : strcmp(name.bytes, "expect_error") == 0 ? &v.expect_error
                                                                 : NULL;
        if (member && member->bytes) json_stop(&j, "a member appears twice");
        if (member) *member = json_string(&j);
        else if (strcmp(name.bytes, "context") == 0) v.context = context_text(&j);
        else json_skip(&j);
        free(name.bytes);
    } while (json_take(&j, ','));
    json_need(&j, '}', "a vector does not end");
    return v;
}

/* Run one vector. Returns 1 when it passes; prints why when it does not. */
static int run_vector(const gt_engine *e, const char *rel, const vector *v) {
    if (!v->from.bytes || !v->to.bytes || !v->input.bytes || (!v->expect.bytes == !v->expect_error.bytes)) {
        fprintf(stderr, "%s: needs from, to, input, and one of expect and expect_error\n", rel);
        return 0;
    }
    gt_buf out = {0};
    int32_t status = gt_convert(e, (const uint8_t *)v->from.bytes, v->from.len,
                                (const uint8_t *)v->to.bytes, v->to.len,
                                (const uint8_t *)v->input.bytes, v->input.len,
                                (const uint8_t *)v->context.bytes, v->context.len, &out);
    int passed;
    if (v->expect.bytes) {
        passed = status == GT_OK && buf_is_bytes(&out, v->expect.bytes, v->expect.len);
        if (!passed) fprintf(stderr, "%s (%s -> %s)\n  got  (%d) %s\n  want %s\n", rel, v->from.bytes, v->to.bytes, (int)status, buf_text(&out), v->expect.bytes);
    } else {
        const text *kind = &v->expect_error;
        passed = status == GT_ERR_ENGINE && out.len > kind->len && memcmp(out.data, kind->bytes, kind->len) == 0 && out.data[kind->len] == ':';
        if (!passed) fprintf(stderr, "%s (%s -> %s)\n  got  (%d) %s\n  want the error kind %s\n", rel, v->from.bytes, v->to.bytes, (int)status, buf_text(&out), kind->bytes);
    }
    gt_buf_free(&out);
    return passed;
}

/* ---- loading the repository ------------------------------------------------- */

/* The module names of the `uses` lines of a model text. */
static names uses_of(const char *model_text) {
    names used = {0};
    for (const char *line = model_text; line && *line; line = strchr(line, '\n')) {
        line += strspn(line, " \t\r\n");
        if (strncmp(line, "uses", 4) != 0 || (line[4] != ' ' && line[4] != '\t')) continue;
        const char *name = line + 4 + strspn(line + 4, " \t");
        size_t len = strcspn(name, " \t\r\n#");
        char *copy = must_alloc(len + 1);
        memcpy(copy, name, len);
        copy[len] = 0;
        names_add(&used, copy);
        free(copy);
    }
    return used;
}

typedef struct {
    const char *root;
    names files;  /* model file names, sorted */
    char *loaded; /* one flag per file */
    gt_engine *engine;
} model_loader;

/*
 * Load one model file after the modules its `uses` lines name: module `m` is
 * the file m.def. A module that no file holds is left to the engine to
 * refuse. A file is marked before the files it uses are visited, so a cycle
 * of `uses` lines ends, and the engine refuses the load.
 */
static void load_model_file(model_loader *m, const char *file) {
    size_t index = 0;
    while (index < m->files.count && strcmp(m->files.items[index], file) != 0) index++;
    if (index == m->files.count || m->loaded[index]) return;
    m->loaded[index] = 1;

    char *rel = join_path("model", file);
    size_t len;
    char *model_text = read_file(m->root, rel, &len);
    names used = uses_of(model_text);
    for (size_t i = 0; i < used.count; i++) {
        char *used_file = must_alloc(strlen(used.items[i]) + 5);
        sprintf(used_file, "%s.def", used.items[i]);
        load_model_file(m, used_file);
        free(used_file);
    }
    load_file(m->engine, m->root, rel, 1);
    names_free(&used);
    free(model_text);
    free(rel);
}

/* `core` first, then the others in byte order, each after what it uses. */
static size_t load_models(gt_engine *e, const char *root) {
    char *dir = join_path(root, "model");
    model_loader m = {root, list_dir(dir, ".def", 1), NULL, e};
    m.loaded = must_alloc(m.files.count);
    memset(m.loaded, 0, m.files.count);
    load_model_file(&m, "core.def");
    for (size_t i = 0; i < m.files.count; i++) load_model_file(&m, m.files.items[i]);
    size_t count = m.files.count;
    names_free(&m.files);
    free(m.loaded);
    free(dir);
    return count;
}

/* The directories under packs/ that hold a pack.def, sorted. */
static names pack_names(const char *root) {
    char *dir = join_path(root, "packs");
    names all = list_dir(dir, "", 1);
    names packs = {0};
    for (size_t i = 0; i < all.count; i++) {
        char *rel = join_path(all.items[i], "pack.def");
        if (file_exists(dir, rel)) names_add(&packs, all.items[i]);
        free(rel);
    }
    names_free(&all);
    free(dir);
    return packs;
}

static size_t count_lines(const gt_buf *b) {
    size_t lines = 0;
    for (size_t i = 0; i < b->len; i++) lines += b->data[i] == '\n';
    return lines;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <repository root>\n", argv[0]);
        return 2;
    }
    const char *root = argv[1];
    gt_engine *e = gt_engine_new();
    size_t modules = load_models(e, root);
    names packs = pack_names(root);
    for (size_t i = 0; i < packs.count; i++) {
        char rel[1024];
        snprintf(rel, sizeof rel, "packs/%s/pack.def", packs.items[i]);
        load_file(e, root, rel, 0);
    }
    gt_buf formats = {0};
    check(gt_formats(e, &formats) == GT_OK && count_lines(&formats) == packs.count,
          "one format per pack: %zu packs, %zu formats", packs.count, count_lines(&formats));
    gt_buf_free(&formats);

    long passed = 0, failed = 0;
    for (size_t i = 0; i < packs.count; i++) {
        char dir[1024];
        snprintf(dir, sizeof dir, "%s/packs/%s/vectors", root, packs.items[i]);
        names files = list_dir(dir, ".json", 0);
        for (size_t f = 0; f < files.count; f++) {
            char rel[2048];
            snprintf(rel, sizeof rel, "packs/%s/vectors/%s", packs.items[i], files.items[f]);
            size_t len;
            char *source = read_file(root, rel, &len);
            vector v = read_vector(source, rel);
            if (run_vector(e, rel, &v)) passed++;
            else failed++;
            vector_free(&v);
            free(source);
        }
        names_free(&files);
    }
    check(failed == 0, "%ld vectors failed", failed);
    check(passed > 0, "no vector ran");
    printf("vectors: %ld passed, %ld failed; %zu packs, %zu model modules\n", passed, failed, packs.count, modules);

    names_free(&packs);
    gt_engine_free(e);
    return finish("vectors");
}
