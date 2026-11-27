# sbp-fixture-var

The messages of the SBP package `swiftnav.sbp.fixture` whose payload length is not fixed, as one
`layout sequential` pack written by `tools/gen/sbp2pack.py` from libsbp v0.0.0-fixture (commit 0123456789abcdef0123456789abcdef01234567).
The messages of fixed length are in `sbp-fixture`. Each kind is selected by the message type;
the payload is a `length 8 bytes` extent. An array or a text that runs to the end of
the frame is a `rest` group (a text one byte per item), and an array counted by an
earlier field is a group counted by it, whose line is then the count (engine-spec 0.21).
No field binds a shared key. The CRC is left to a framer.

A text that runs to the end of the frame is a list of byte values, not one text key:
the pack language has no text field whose length is what remains of its extent, so
a model check can test single bytes but not the text as a whole.

| Kind | Message | Id | Lines |
|---|---|---:|---:|
| `trailing` | MSG_TRAILING | 28674 | 4 |
| `trailing_text` | MSG_TRAILING_TEXT | 28675 | 4 |
| `counted` | MSG_COUNTED | 28676 | 6 |

3 round-trip vectors `rt-*`, written by the generator's serializer from the definitions; each
group holds two items. Vectors `derived-*` were derived by hand from the definitions,
independently of the generator and of every engine; the generator keeps them.

Do not edit `pack.def`, `PROVENANCE.md`, the module or the vectors by hand: change the
generator or its inputs and run it again.
