# Pack: demo-bits-msb

A synthetic binary format in most-significant-bit-first order (`bit_order msb`,
`spec/engine-spec.md`, Version 0.5). It belongs to no real standard. Words are 4
bytes. The first two bytes are the course as a big-endian 16-bit integer in
hundredths of a degree; the next 3 bits are the kind code.

| Kind | Code | Words | Holds |
|---|---|---|---|
| `ident` | 2 | 8 | 6-byte `ascii` callsign, big-endian `f32` circular error, big-endian `f64` latitude and longitude |
| `overlap` | 3 | 2 | two 16-bit fields that share a byte, and a `when` on the low 4 bits of the second; on encode the earlier line holds the shared bits and the `when` is written over both |
| `fix` | 5 | 3 | 21-bit `sscale` latitude starting at bit 19, 22-bit `sscale` longitude, 18-bit `uscale` height with an offset of -500 m, 16-bit `twos` time |
| `raw` | 1 | 3 | a 64-bit `uint` time |
| `idle` | 0 | 1 | nothing beyond the header |

Fields of `fix` and `ident` run past the end of their word. I/O is hex text.
