// Transform function set (engine-spec.md, Transforms; bits transforms in v0.2).
#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

// Parse a field's transform token into `f.transform` and its parameters
// (0.11 ruling 4d, the text transforms of 0.10 and the transforms of 0.15).
// Returns 0, -1 with `err`
// set when the parameters are not valid (bad-directive), or -2 when the name,
// the text before the first `:`, is not a transform (unknown-transform).
int parse_any_transform(std::string_view token, FieldLine& f, std::string& err);

// v0.10: the transforms of the text wire that take parameters: `int:<w>`,
// `dec:<f>[:<w>]`, `dm:<d>:<f>:<PN>`, `hms:<f>`, `hms_dmy:<f>`, and the bare
// names `dec`, `dm`, `hms`, `hms_dmy`. Returns 0 when the token is none of
// them, 1 when it is one with valid parameters (set in `f`), and -1 with `err`
// set when its parameters are not valid (bad-directive).
int parse_text_transform(std::string_view token, FieldLine& f, std::string& err);

// True for the transforms valid only on the text wire.
bool transform_is_text_only(Transform t);

// A scale factor: number text, or the fraction <num>/<den> (ruling 1 of 0.5).
// With `transform` (the float scale transforms: 0.11 ruling 4d, 0.15 ruling
// 25) the fraction is of two unsigned decimal integers, neither zero, and a
// factor that reads as zero is refused; otherwise (the `scale` derive
// function, 2c) <num> is integer text and <den> an unsigned decimal integer
// other than zero. Returns false with `err` set.
bool parse_scale_factor(std::string_view text, bool& fraction, double& factor, double& num, double& den,
                        std::string& err, bool transform = false);

// Wire text -> typed model value (text wires). Throws std::invalid_argument on failure.
Value decode_value(const FieldLine& f, const std::string& text);
// A JSON number's text through a field's transform (0.11 ruling 2d): `float`
// the nearest double, finite; `int` the exact value, an integer within 64
// bits. Other transforms (`scale`, `iscale` of 0.15) read the text as
// decode_value does. Throws std::invalid_argument.
Value decode_json_number(const FieldLine& f, const std::string& text);
// Model value -> wire text (text wires). Coerces between model kinds where lossless.
// Throws std::invalid_argument on failure.
std::string encode_value(const FieldLine& f, const Value& v);

// True for the transforms valid only on the tlv wire (v0.13): utf8 and hex.
bool transform_is_tlv_only(Transform t);

// True when the transform's wire value is text (JSON string), false for numbers.
bool transform_is_textual(Transform t);

// True for the bits-wire transforms; false for text and protobuf transforms.
bool transform_is_bits(Transform t);
// True for the transforms of 0.15, which a wire they do not list makes bad-directive.
bool transform_is_v015(Transform t);
// `scale` and `iscale`: xml, json and geojson.
bool transform_is_text_scale(Transform t);
// The character width of a `chars` transform; 0 for any other.
unsigned chars_width(Transform t);
// The bit lengths a bits transform allows (bad-directive otherwise).
bool bits_len_allowed(Transform t, std::uint32_t len);
// `chars`: the character codes, first character first -> text, trailing
// padding removed. Throws std::invalid_argument on a code the set does not define.
Value decode_chars(Transform t, const std::vector<std::uint8_t>& codes);
// `chars`: text -> `count` codes, padded. Throws std::invalid_argument.
std::vector<std::uint8_t> encode_chars(Transform t, const Value& v, std::size_t count);

// Bit-field value -> typed model value, for every bits transform but `ascii`.
// `raw` holds the field's `len` bits as an unsigned integer. Throws
// std::invalid_argument for an `f32` or `f64` that is infinity or not a number.
Value decode_bits_value(const FieldLine& f, std::uint64_t raw, std::uint32_t len);
// Model value -> the `len` bits to write, for every bits transform but `ascii`.
// Throws std::invalid_argument when the model value cannot be represented.
std::uint64_t encode_bits_value(const FieldLine& f, const Value& v, std::uint32_t len);

// v0.19, an `int:` locator of a UPER pack: the integer value `v` through
// `uint`, `twos` (both `v`), `uscale` or `sscale` (`v * f + o`), and back
// (`round((x - o) / f)`). Encode throws std::invalid_argument when the value is
// not an integer of 64 signed bits.
Value decode_uper_int(const FieldLine& f, std::int64_t v);
std::int64_t encode_uper_int(const FieldLine& f, const Value& v);

// `ascii`: the field's bytes in wire order -> text, trailing NULs removed, and with
// `trim` the trailing spaces after them. Throws std::invalid_argument on a byte
// above 0x7E or below 0x20 other than the trailing NULs.
Value decode_ascii(const std::string& bytes, bool trim = false);
// `ascii`: text -> `nbytes` bytes, NUL-padded. Throws std::invalid_argument on
// longer text and on a byte outside 0x20-0x7E.
std::string encode_ascii(const Value& v, std::size_t nbytes);

// v0.14 `sixbit`: `codes` holds one six-bit value per character, first to
// last -> text, `@` to `_` for 0 to 31 and space to `?` for 32 to 63, trailing
// `@` removed, and with `trim` the whole trailing run of `@` and space.
Value decode_sixbit(const std::string& codes, bool trim = false);
// `sixbit`: text -> `nchars` six-bit values, padded with 0 (`@`). Throws
// std::invalid_argument on longer text and on a character outside 0x20-0x5F.
std::string encode_sixbit(const Value& v, std::size_t nchars);

// Model value coerced to an integer / a double; throws std::invalid_argument.
std::int64_t model_int(const Value& v);
double model_double(const Value& v);

// True for the protobuf-wire transforms (pstring/pvarint/psint/pdouble/pfloat).
bool transform_is_protobuf(Transform t);

// The protobuf wire type a transform binds to: 0 varint, 1 fixed64, 2 length-
// delimited, 5 fixed32.
int protobuf_wire_type(Transform t);

// Protobuf leaf wire value -> typed model value. For a length-delimited field
// (wire type 2) `bytes` holds the payload; otherwise `scalar` holds the varint,
// fixed64 or fixed32 bits. The codec checks the wire type first. Throws
// std::invalid_argument for a `pdouble` or `pfloat` that is infinity or not a number.
Value decode_protobuf_value(Transform t, std::uint64_t scalar, const std::string& bytes);

// Model value -> protobuf leaf. For a length-delimited field fills `bytes`;
// otherwise fills `scalar`. Throws std::invalid_argument when the model value
// cannot be represented by the transform.
void encode_protobuf_value(Transform t, const Value& v, std::uint64_t& scalar,
                           std::string& bytes);

}  // namespace goat_transformers::detail
