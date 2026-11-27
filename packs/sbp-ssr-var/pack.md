# sbp-ssr-var

The messages of the SBP package `swiftnav.sbp.ssr` whose payload length is not fixed, as one
`layout sequential` pack written by `tools/gen/sbp2pack.py` from libsbp v6.5.2 (commit 925825dea5174f069b5d6e23548f213e09f0235c).
The messages of fixed length are in `sbp-ssr`. Each kind is selected by the message type;
the payload is a `length 8 bytes` extent. An array or a text that runs to the end of
the frame is a `rest` group (a text one byte per item), and an array counted by an
earlier field is a group counted by it, whose line is then the count (engine-spec 0.21).
No field binds a shared key. The CRC is left to a framer.

A text that runs to the end of the frame is a list of byte values, not one text key:
the pack language has no text field whose length is what remains of its extent, so
a model check can test single bytes but not the text as a whole.

| Kind | Message | Id | Lines |
|---|---|---:|---:|
| `ssr_code_biases` | MSG_SSR_CODE_BIASES | 1505 | 10 |
| `ssr_phase_biases` | MSG_SSR_PHASE_BIASES | 1510 | 17 |
| `ssr_stec_correction_dep` | MSG_SSR_STEC_CORRECTION_DEP | 1531 | 17 |
| `ssr_stec_correction` | MSG_SSR_STEC_CORRECTION | 1533 | 19 |
| `ssr_gridded_correction` | MSG_SSR_GRIDDED_CORRECTION | 1532 | 19 |
| `ssr_gridded_correction_bounds` | MSG_SSR_GRIDDED_CORRECTION_BOUNDS | 1534 | 29 |
| `ssr_satellite_apc_dep` | MSG_SSR_SATELLITE_APC_DEP | 1540 | 30 |
| `ssr_satellite_apc` | MSG_SSR_SATELLITE_APC | 1541 | 35 |
| `ssr_stec_correction_dep_a` | MSG_SSR_STEC_CORRECTION_DEP_A | 1515 | 15 |
| `ssr_gridded_correction_no_std_dep_a` | MSG_SSR_GRIDDED_CORRECTION_NO_STD_DEP_A | 1520 | 15 |
| `ssr_gridded_correction_dep_a` | MSG_SSR_GRIDDED_CORRECTION_DEP_A | 1530 | 17 |
| `ssr_grid_definition_dep_a` | MSG_SSR_GRID_DEFINITION_DEP_A | 1525 | 9 |
| `ssr_orbit_clock_bounds` | MSG_SSR_ORBIT_CLOCK_BOUNDS | 1502 | 20 |
| `ssr_code_phase_biases_bounds` | MSG_SSR_CODE_PHASE_BIASES_BOUNDS | 1516 | 17 |

14 round-trip vectors `rt-*`, written by the generator's serializer from the definitions; each
group holds two items. Vectors `derived-*` were derived by hand from the definitions,
independently of the generator and of every engine; the generator keeps them.

Do not edit `pack.def`, `PROVENANCE.md`, the module or the vectors by hand: change the
generator or its inputs and run it again.
