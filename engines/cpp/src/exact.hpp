// Exact arithmetic for the integer scales of engine-spec.md 0.15 (Exact
// factors): factors and offsets read as exact numbers, round-half-away-from-
// zero of the exact value, and the exact decimal text of `iscale`. A small
// signed big integer does the arithmetic, so no value goes through a double.
#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace goat_transformers::detail {

// A signed integer of any size: magnitude in 32-bit limbs, least significant
// first, with no leading zero limb. Zero has no limbs and is not negative.
struct Big {
    bool neg = false;
    std::vector<std::uint32_t> mag;

    static Big of_u64(std::uint64_t v);
    static Big of_i64(std::int64_t v);
    bool zero() const { return mag.empty(); }
};

Big big_add(const Big& a, const Big& b);
Big big_sub(const Big& a, const Big& b);
Big big_mul(const Big& a, const Big& b);
// round(a / b), half away from zero; b is not zero.
Big big_round_div(const Big& a, const Big& b);
// True with `out` set when `v` is in the signed 64-bit range.
bool big_to_i64(const Big& v, std::int64_t& out);
// True with `out` set when `v` is in [0, 2^64).
bool big_to_u64(const Big& v, std::uint64_t& out);

// `<factor>` of an integer scale: `[-]digits[.digits]` or `[-]digits/digits`,
// in lowest terms with numerator and denominator each at most 2^32 and not 0.
// `den` is positive. Returns false with `err` set.
bool parse_exact_factor(std::string_view text, std::int64_t& num, std::int64_t& den, std::string& err);
// `<offset>` of an integer scale: `[-]digits`, absolute value below 2^63.
bool parse_exact_offset(std::string_view text, std::int64_t& off, std::string& err);

// round(v × num / den) + off. False when the result is outside the signed
// 64-bit range.
bool exact_scale(const Big& v, std::int64_t num, std::int64_t den, std::int64_t off, std::int64_t& out);
// round((x − off) × den / num), the integer an integer scale encodes.
Big exact_unscale(std::int64_t x, std::int64_t num, std::int64_t den, std::int64_t off);

// `iscale` decode: `text` must be `-?digits(.digits)?([eE][+-]?digits)?` with
// an exponent of at most 400 in absolute value; then round(r × num / den) +
// off. Returns false with `why` set.
bool iscale_decode(const std::string& text, std::int64_t num, std::int64_t den, std::int64_t off,
                   std::int64_t& out, std::string& why);
// `iscale` encode: (x − off) × den / num exactly, in plain decimal notation
// with at most 18 fraction digits. Returns false with `why` set.
bool iscale_encode(std::int64_t x, std::int64_t num, std::int64_t den, std::int64_t off, std::string& out,
                   std::string& why);

}  // namespace goat_transformers::detail
