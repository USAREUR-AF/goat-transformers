/*
 * goat_transformers.h read by a strict compiler, as C99 and as C++17
 * (test.sh compiles this one file both ways with -Wall -Wextra -Wpedantic
 * -Werror). Nothing here runs. It fails to compile when the header stops
 * standing on its own, when a declaration changes its types or its
 * const-ness, or when gt_buf changes its layout.
 */
#include "goat_transformers.h"
#include "goat_transformers.h" /* a second time: the include guard holds */

#ifdef __cplusplus
#define LAYOUT_CHECK(name, condition) static_assert(condition, #name)
#else
/* C99 has no static assertion: an array of negative size does not compile */
#define LAYOUT_CHECK(name, condition) typedef char layout_check_##name[(condition) ? 1 : -1]
#endif

/* gt_buf is a pointer and then a length, with nothing between or after */
LAYOUT_CHECK(buf_data_is_first, offsetof(gt_buf, data) == 0);
LAYOUT_CHECK(buf_len_follows, offsetof(gt_buf, len) == sizeof(uint8_t *));
LAYOUT_CHECK(buf_has_no_other_member, sizeof(gt_buf) == sizeof(uint8_t *) + sizeof(size_t));

/* the values a caller may have compiled in */
LAYOUT_CHECK(status_values, GT_OK == 0 && GT_ERR_ENGINE == 1 && GT_ERR_ARGUMENT == 2 && GT_ERR_PANIC == 3);
LAYOUT_CHECK(limit_values, GT_DISTRIBUTION_PUBLIC == 0 && GT_DISTRIBUTION_CONTROLLED == 1);

/*
 * Every function, as a pointer of the exact type a caller relies on. The
 * calls that only read an engine take it as const; the others do not.
 */
struct signatures {
    gt_engine *(*engine_new)(void);
    void (*engine_free)(gt_engine *);
    int32_t (*engine_set_max_distribution)(gt_engine *, int32_t, gt_buf *);
    int32_t (*engine_set_max_items)(gt_engine *, uint64_t, gt_buf *);
    int32_t (*load_model)(gt_engine *, const uint8_t *, size_t, gt_buf *);
    int32_t (*load_pack)(gt_engine *, const uint8_t *, size_t, gt_buf *);
    int32_t (*convert)(const gt_engine *, const uint8_t *, size_t, const uint8_t *, size_t,
                       const uint8_t *, size_t, const uint8_t *, size_t, gt_buf *);
    int32_t (*formats)(const gt_engine *, gt_buf *);
    void (*buf_free)(gt_buf *);
};

/* declared first: a const object is otherwise file-local in C++ */
extern const struct signatures gt_signatures;
const struct signatures gt_signatures = {
    gt_engine_new,
    gt_engine_free,
    gt_engine_set_max_distribution,
    gt_engine_set_max_items,
    gt_load_model,
    gt_load_pack,
    gt_convert,
    gt_formats,
    gt_buf_free,
};
