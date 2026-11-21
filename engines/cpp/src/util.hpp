// Internal helpers: number formatting/parsing, ISO 8601 civil-date arithmetic, UTF-8.
#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace goat_transformers::detail {

// Shortest round-trip decimal, never exponent form; integer-valued doubles carry
// no decimal point (30.0 -> "30"). Throws std::domain_error for NaN/infinity.
std::string format_double(double d);

// Version 0.11 ruling 2a: an optional `-` and one or more ASCII digits, nothing
// else, within a signed 64-bit integer. Leading zeros are allowed.
bool parse_int_text(std::string_view s, std::int64_t& out);
// Version 0.11 ruling 2b: `-`? digits (`.` digits)? ([eE] [+-]? digits)?, nothing
// else. The nearest double; infinite is refused; below the smallest subnormal
// reads as zero, negative zero after a `-`.
bool parse_number_text(std::string_view s, double& out);
// Version 0.11 ruling 2c: an unsigned decimal integer, one or more ASCII digits
// and nothing else (leading zeros allowed), within 64 bits.
bool parse_unsigned_text(std::string_view s, std::uint64_t& out);
// Version 0.11 ruling 2d: the exact value of JSON number text, when it is an
// integer within a signed 64-bit integer (`1.0`, `1e3` are integers).
bool json_exact_int(std::string_view s, std::int64_t& out);

// Whole-string decimal parse (surrounding ASCII whitespace and a leading '+' allowed).
bool parse_double(std::string_view s, double& out);
// Whole-string integer parse; an integral decimal such as "12.0" is accepted.
bool parse_int(std::string_view s, std::int64_t& out);

// Days since 1970-01-01 for a proleptic Gregorian date, and the inverse.
std::int64_t days_from_civil(std::int64_t y, unsigned m, unsigned d);
void civil_from_days(std::int64_t z, std::int64_t& y, unsigned& m, unsigned& d);

// YYYY-MM-DDTHH:MM:SS[.f+] followed by Z, z, +hh:mm or -hh:mm -> epoch ms UTC
// (fraction truncated to ms). The T may be lowercase (0.6). Version 0.11
// ruling 3: nothing before or after, years 0001 to 9999, and the instant
// within 0001-01-01T00:00:00.000Z to 9999-12-31T23:59:59.999Z.
bool parse_iso8601_ms(std::string_view s, std::int64_t& out);
// The instants ruling 3 of 0.11 allows, in epoch ms.
constexpr std::int64_t kMinIsoMs = -62135596800000;
// 0000-01-01T00:00:00Z, the first instant iso8601_short writes (0.18 ruling 11).
constexpr std::int64_t kMinIsoShortMs = -62167219200000;
constexpr std::int64_t kMaxIsoMs = 253402300799999;
// epoch ms -> YYYY-MM-DDTHH:MM:SS.fffZ. Throws std::domain_error outside
// kMinIsoMs to kMaxIsoMs (0.11 ruling 3f).
std::string format_iso8601_ms(std::int64_t ms);
// v0.18 `iso8601_short`: no fraction when the milliseconds are 0, otherwise the
// three digits with trailing zeros removed. Throws std::domain_error outside
// the years 0000-9999.
std::string format_iso8601_short(std::int64_t ms);
// v0.55 `iso8601_si`: no fraction when the milliseconds are 0, otherwise all
// three digits; years 0001 to 9999 (throws std::domain_error outside them).
std::string format_iso8601_si(std::int64_t ms);

void append_utf8(std::string& out, std::uint32_t cp);

std::string_view trim(std::string_view s);

}  // namespace goat_transformers::detail
