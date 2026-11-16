# Pack: demo-kinds-bits

A synthetic binary format that exercises message kinds on the `bits` wire
(`spec/engine-spec.md`, Version 0.5). It belongs to no real standard. Words are
8 bytes, least-significant-bit-first. Every message starts with a 32-bit time
(`0:0:32`) and a 4-bit kind code (`0:32:4`).

| Kind | Code | Words | Holds |
|---|---|---|---|
| `precise` | 3 | 5 | 8-byte `ascii` callsign, `f64` latitude and longitude, `f32` circular error |
| `motion` | 2 | 3 | scaled position, `uscale` course and speed, `sscale` east and north velocity; the north velocity runs past word 1 into word 2 |
| `position` | 1 | 2 | scaled position, height as `uscale` with an offset of -1000 m |
| `status` | 0 | 1 | two one-bit flags |

On encode from another format the first kind whose `requires` keys the entity
holds is chosen, in the order above; `status` has no `requires` and takes
whatever is left. A kind code other than 0 to 3 is `no-kind`. I/O is hex text.
