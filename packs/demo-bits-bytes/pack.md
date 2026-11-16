# Pack: demo-bits-bytes

A synthetic byte-oriented binary format (`spec/engine-spec.md`, Version 0.5,
fields that run past their word). It belongs to no real standard. It uses
`word_bytes 1` and addresses every field by bit offset from the start of the
message, most-significant-bit-first. Byte 0 is the constant `0x47`, byte 1 the
kind code, bytes 3 to 6 a big-endian 32-bit time.

| Kind | Code | Bytes | Holds |
|---|---|---|---|
| `long` | 2 | 19 | latitude and longitude as big-endian 32-bit integers in units of 1e-7 degree, 4-byte `ascii` callsign |
| `short` | 1 | 7 | one flag byte |

Input longer than the kind's length is accepted and the extra bytes are ignored;
shorter input is `malformed-wire`. I/O is hex text.
