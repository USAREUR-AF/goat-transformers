# Provenance: m17-packet-frame pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| M17 Protocol Specification (M17 Project) | https://github.com/M17-Project/M17_spec | `9ae2874d8bd44e2d32fae85f7650a23f6bcee5d3` |

| File read | SHA-256 |
|---|---|
| `M17_spec.tex` (chapters Data Link Layer, Application Layer, Address Encoding) | `c0fa8cb9f2a619e8d5cc27fd939414f17e4d623c9e77e84ee3ec742f400382a7` |
| `LICENSE` | `8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643` |

## Licence

The specification states "Copyright (C) 2023-2026 M17 Project" and grants permission to copy, distribute
and modify the document under the GNU Free Documentation License 1.3 or later (no invariant sections);
the software in it is under the GPL version 2 or later, and the repository's `LICENSE` is the GPL-2.0
text. (The brief expected CC BY-SA; the document itself names the GFDL.)

This pack restates the frame layouts, field widths and scale factors (facts of the protocol) in its own
words; no text, table or code of the specification is copied or adapted, so the pack is not a modified
version of the document and keeps the default Apache-2.0 label, as for other restated specifications.
The vectors are built by `tools/gen/hamdig-vectors.py` from values chosen there; the CRC and the address
encoding are computed there from the specification's description (its CRC test values were used to check
that computation, not copied into the vectors); expected bytes are derived there, without an engine.

## Attribution

Layouts from the M17 Protocol Specification, https://github.com/M17-Project/M17_spec (Copyright (C)
2023-2026 M17 Project, GNU FDL 1.3 or later), restated.
