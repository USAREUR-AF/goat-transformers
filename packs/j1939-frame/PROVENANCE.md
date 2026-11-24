# Provenance: j1939-frame pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| Linux kernel | https://github.com/torvalds/linux | `c44104f3642da720164042623e4832836aefdd8e` |
| python-can-j1939 (Frank Benkert and contributors) | https://github.com/juergenH87/python-can-j1939 | `01aba95cca43847bc272ec7ddb12048f587e6554` |

| File read | SHA-256 |
|---|---|
| Linux `Documentation/networking/j1939.rst` | `2e48c57da60816a3722f1051694ba18faffcfa07e83bdf81cf2e4380cca91b38` |
| Linux `include/uapi/linux/can.h` | `a1310c74795f8ac717f4d21653bc26c3f4764586859bf2d54ff92c5d5ece8811` |
| `j1939/message_id.py` | `00653eb20ef896a9aac6564534d1e3398cb3fe3b40483639913efac9bf361865` |
| `j1939/parameter_group_number.py` | `43553e199b9c918850888c403a33f52c6603cd03256b49dbdb7d85412e44f49c` |
| `j1939/name.py` | `c7e4ebe88d8c5130a111fdc2f4109041ef6a9ef3339b9a6c7aa4659d4aff3952` |
| `j1939/j1939_21.py` | `361ff6b68a53e0620e4e1a4762c14191867679df119ca9c850aa9faf457ff0f4` |
| `j1939/controller_application.py` | `f6e35598bfbb16b65b5f5bc1140a738f6a7f9588f40b5550a1b8484770d7c42d` |
| `j1939/diagnostic_messages.py` | `68baed7d600a9d66b2ade2cc4fb5100967f0934795864537d57c398e3a76d9c2` |
| `LICENSE` | `039aed7cdf86a3c6118fc87cd768f27702443d3e8d202d6b2d542d1df572393b` |

## Licence

- `j1939.rst` gives the SPDX licence identifier `(GPL-2.0 OR MIT)`.
- `can.h` gives the SPDX licence identifier `((GPL-2.0-only WITH Linux-syscall-note) OR BSD-3-Clause)`.
- python-can-j1939's `LICENSE` is the MIT License, "Copyright (c) 2018 Frank Benkert".

This pack restates the layouts (field order, sizes, bit positions, codes) in its own words; no code,
comment or table of the sources is copied. Under this project's rule for code sources the pack keeps
the default Apache-2.0 label. SAE J1939 and its terms: not read. The vectors are built by
`tools/gen/j1939-vectors.py` from values chosen there; their expected bytes are derived there, without
an engine.

## Attribution

Layouts from the Linux kernel's Documentation/networking/j1939.rst (GPL-2.0 OR MIT) and
include/uapi/linux/can.h, and from python-can-j1939, https://github.com/juergenH87/python-can-j1939 (MIT
License, Copyright (c) 2018 Frank Benkert), restated.
