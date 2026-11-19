/* gt_example.h: the C side of embedded/example-bare.
 *
 * Link libexample_bare.a, built for the target, in embedded/, with
 *   cargo rustc -p example-bare --release --target thumbv7em-none-eabihf --crate-type staticlib
 */
#ifndef GT_EXAMPLE_H
#define GT_EXAMPLE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* What the caller supplies for each record. */
typedef struct {
    double   time_of_day_s; /* I062/070: seconds since the last UTC midnight */
    uint16_t track_number;  /* I062/040: 0 to 65535 */
    uint8_t  sac;           /* I062/010: system area code */
    uint8_t  sic;           /* I062/010: system identification code */
    uint8_t  confirmed;     /* 1: confirmed track, 0: tentative */
} gt_cat062_context;

/* Error codes: the negative return values of the conversion. */
#define GT_ERR_NO_KIND            (-1)  /* not a Location message */
#define GT_ERR_MALFORMED_WIRE     (-2)  /* the input is shorter than 25 bytes */
#define GT_ERR_TRANSFORM_DECODE   (-3)
#define GT_ERR_TRANSFORM_ENCODE   (-4)  /* a value does not fit its CAT062 field */
#define GT_ERR_UNDECLARED_KEY     (-5)
#define GT_ERR_KEY_TYPE_MISMATCH  (-6)
#define GT_ERR_OUTPUT_FULL        (-7)  /* out_cap is less than the record needs */
#define GT_ERR_SCRATCH_FULL       (-8)
#define GT_ERR_BAD_PLAN           (-9)
#define GT_ERR_NULL               (-10)

/* The longest block this plan writes, in bytes. */
#define GT_CAT062_MAX_BYTES 32

/* Convert one ASTM F3411 Remote ID Location message (25 bytes) to one
 * ASTERIX CAT062 data block. Latitude, longitude and geodetic altitude are
 * carried from the message; the rest of the record comes from ctx.
 * Returns the number of bytes written to out, or a negative error code.
 * No heap, no global state: safe to call from any context. */
int32_t gt_rid_location_to_cat062(const uint8_t *input, size_t input_len,
                                  uint8_t *out, size_t out_cap,
                                  const gt_cat062_context *ctx);

#ifdef __cplusplus
}
#endif

#endif /* GT_EXAMPLE_H */
