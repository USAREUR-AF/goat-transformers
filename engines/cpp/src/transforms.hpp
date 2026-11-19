// Transform function set (engine-spec.md, Transforms; bits transforms in v0.2).
#pragma once

#include <cstdint>
#include <string>
#include <string_view>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

// Parse a field's transform token into `f.transform` and its scale arguments.
// Returns false with `err` set on an unknown transform or bad arguments.
bool parse_transform(std::string_view token, FieldLine& f, std::string& err);

// v0.10: the transforms of the text wire that take parameters: `int:<w>`,
// `dec:<f>[:<w>]`, `dm:<d>:<f>:<PN>`, `hms:<f>`, `hms_dmy:<f>`, and the bare
// names `dec`, `dm`, `hms`, `hms_dmy`. Returns 0 when the token is none of
// them, 1 when it is one with valid parameters (set in `f`), and -1 with `err`
// set when its parameters are not valid (bad-directive).
int parse_text_transform(std::string_view token, FieldLine& f, std::string& err);

// True for the transforms valid only on the text wire.
bool transform_is_text_only(Transform t);

// A scale factor: a decimal number, or the fraction <num>/<den> of two decimal
// integers (ruling 1 of 0.5). Returns false with `err` set.
bool parse_scale_factor(std::string_view text, bool& fraction, double& factor, double& num, double& den,
                        std::string& err);

// Wire text -> typed model value (text wires). Throws std::invalid_argument on failure.
Value decode_value(Transform t, const std::string& text);
// Model value -> wire text (text wires). Coerces between model kinds where lossless.
// Throws std::invalid_argument on failure.
std::string encode_value(Transform t, const Value& v);

// True when the transform's wire value is text (JSON string), false for numbers.
bool transform_is_textual(Transform t);

// True for the bits-wire transforms; false for text and protobuf transforms.
bool transform_is_bits(Transform t);

// Bit-field value -> typed model value, for every bits transform but `ascii`.
// `raw` holds the field's `len` bits as an unsigned integer. Throws
// std::invalid_argument for an `f32` or `f64` that is infinity or not a number.
Value decode_bits_value(const FieldLine& f, std::uint64_t raw, std::uint32_t len);
// Model value -> the `len` bits to write, for every bits transform but `ascii`.
// Throws std::invalid_argument when the model value cannot be represented.
std::uint64_t encode_bits_value(const FieldLine& f, const Value& v, std::uint32_t len);

// `ascii`: the field's bytes in wire order -> text, trailing NULs removed, and with
// `trim` the trailing spaces after them. Throws std::invalid_argument on a byte
// above 0x7E or below 0x20 other than the trailing NULs.
Value decode_ascii(const std::string& bytes, bool trim = false);
// `ascii`: text -> `nbytes` bytes, NUL-padded. Throws std::invalid_argument on
// longer text and on a byte outside 0x20-0x7E.
std::string encode_ascii(const Value& v, std::size_t nbytes);

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
