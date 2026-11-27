# sbp-system-var

The messages of the SBP package `swiftnav.sbp.system` whose payload length is not fixed, as one
`layout sequential` pack written by `tools/gen/sbp2pack.py` from libsbp v6.5.2 (commit 925825dea5174f069b5d6e23548f213e09f0235c).
The messages of fixed length are in `sbp-system`. Each kind is selected by the message type;
the payload is a `length 8 bytes` extent. An array or a text that runs to the end of
the frame is a `rest` group (a text one byte per item), and an array counted by an
earlier field is a group counted by it, whose line is then the count (engine-spec 0.21).
No field binds a shared key. The CRC is left to a framer.

A text that runs to the end of the frame is a list of byte values, not one text key:
the pack language has no text field whose length is what remains of its extent, so
a model check can test single bytes but not the text as a whole.

| Kind | Message | Id | Lines |
|---|---|---:|---:|
| `dgnss_status` | MSG_DGNSS_STATUS | 65282 | 6 |
| `status_report` | MSG_STATUS_REPORT | 65534 | 9 |
| `status_journal` | MSG_STATUS_JOURNAL | 65533 | 10 |
| `csac_telemetry` | MSG_CSAC_TELEMETRY | 65284 | 4 |
| `csac_telemetry_labels` | MSG_CSAC_TELEMETRY_LABELS | 65285 | 4 |
| `group_meta` | MSG_GROUP_META | 65290 | 6 |

6 round-trip vectors `rt-*`, written by the generator's serializer from the definitions; each
group holds two items. Vectors `derived-*` were derived by hand from the definitions,
independently of the generator and of every engine; the generator keeps them.

Do not edit `pack.def`, `PROVENANCE.md`, the module or the vectors by hand: change the
generator or its inputs and run it again.
