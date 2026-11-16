// Internal helpers: number formatting/parsing, ISO 8601 civil-date arithmetic, UTF-8.
#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace goat_transformers::detail {

// Shortest round-trip decimal, never exponent form; integer-valued doubles carry
// no decimal point (30.0 -> "30"). Throws std::domain_error for NaN/infinity.
std::string format_double(double d);

// Whole-string decimal parse (surrounding ASCII whitespace and a leading '+' allowed).
bool parse_double(std::string_view s, double& out);
// Whole-string integer parse; an integral decimal such as "12.0" is accepted.
bool parse_int(std::string_view s, std::int64_t& out);

// Days since 1970-01-01 for a proleptic Gregorian date, and the inverse.
std::int64_t days_from_civil(std::int64_t y, unsigned m, unsigned d);
void civil_from_days(std::int64_t z, std::int64_t& y, unsigned& m, unsigned& d);

// YYYY-MM-DDTHH:MM:SS[.f+] followed by Z, z, +hh:mm or -hh:mm -> epoch ms UTC
// (fraction truncated to ms). The T may be lowercase (0.6).
bool parse_iso8601_ms(std::string_view s, std::int64_t& out);
// epoch ms -> YYYY-MM-DDTHH:MM:SS.fffZ. Throws std::domain_error outside years 0000-9999.
std::string format_iso8601_ms(std::int64_t ms);

void append_utf8(std::string& out, std::uint32_t cp);

std::string_view trim(std::string_view s);

}  // namespace goat_transformers::detail
