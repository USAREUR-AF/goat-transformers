# sbp-piksi-var

The messages of the SBP package `swiftnav.sbp.piksi` whose payload length is not fixed, as one
`layout sequential` pack written by `tools/gen/sbp2pack.py` from libsbp v6.5.2 (commit 925825dea5174f069b5d6e23548f213e09f0235c).
The messages of fixed length are in `sbp-piksi`. Each kind is selected by the message type;
the payload is a `length 8 bytes` extent. An array or a text that runs to the end of
the frame is a `rest` group (a text one byte per item), and an array counted by an
earlier field is a group counted by it, whose line is then the count (engine-spec 0.21).
No field binds a shared key. The CRC is left to a framer.

A text that runs to the end of the frame is a list of byte values, not one text key:
the pack language has no text field whose length is what remains of its extent, so
a model check can test single bytes but not the text as a whole.

| Kind | Message | Id | Lines |
|---|---|---:|---:|
| `command_req` | MSG_COMMAND_REQ | 184 | 4 |
| `command_output` | MSG_COMMAND_OUTPUT | 188 | 4 |
| `network_bandwidth_usage` | MSG_NETWORK_BANDWIDTH_USAGE | 189 | 7 |
| `cell_modem_status` | MSG_CELL_MODEM_STATUS | 190 | 5 |
| `specan_dep` | MSG_SPECAN_DEP | 80 | 10 |
| `specan` | MSG_SPECAN | 81 | 11 |

6 round-trip vectors `rt-*`, written by the generator's serializer from the definitions; each
group holds two items. Vectors `derived-*` were derived by hand from the definitions,
independently of the generator and of every engine; the generator keeps them.

Do not edit `pack.def`, `PROVENANCE.md`, the module or the vectors by hand: change the
generator or its inputs and run it again.
