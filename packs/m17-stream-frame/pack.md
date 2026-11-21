# Pack: m17-stream-frame

The contents of one M17 Stream Frame as Type 1 bits (18 octets before coding): the LICH (a 40-bit chunk
of the LSF, its 3-bit counter, 5 reserved bits), the 16-bit frame number (its top bit marks the last
frame) and 16 octets of stream data. Wire `bits`, `layout sequential`, `bit_order msb`. Written by
`tools/gen/hamdig-pack.py`.

## Shared keys

None.

## Not mapped

- **LSF reassembly** from six LICH chunks (one message is one frame).
- **The stream data** decoded (Codec 2 speech, or data in voice-and-data mode): hex.
- **Coding** (Golay for the LICH, convolutional coding and puncturing for the contents): below this pack.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the 24 octets (6 LICH octets and the 18 contents
octets).

## Vectors

`tools/gen/hamdig-vectors.py`, without an engine: a frame with LSF chunk 1; the last frame with chunk 5;
a cut frame (`malformed-wire`).
