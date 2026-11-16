# Pack: demo-bits

A synthetic binary format that exercises the `bits` wire: a 16-bit unsigned id,
a 21-bit and a 22-bit linearly scaled signed position field, and a 9-bit course,
across two 9-byte words. It belongs to no real standard; it exists so the engine's
binary bit-field path is proven in public without any controlled content. I/O is
hex text (`spec/engine-spec.md`, bits wire).
