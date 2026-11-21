# Provenance: ofx-stmttrn pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| ofxparse (Jerry Seutter and contributors) | https://github.com/jseutter/ofxparse | `25aa80072be71da9f4ea0924ae1d1aaea2d5820c` |

| File read | SHA-256 |
|---|---|
| `ofxparse/ofxparse.py` | `04b05ae98894aa01f01d44e962b390f16575dba96b302c413c5c9718ba81dd79` |
| `tests/fixtures/checking.ofx` (element order) | `f428bb3c0c7b7a4c14f20eaca577d37b2b31845ef88de4c2816fc99ea462f8a2` |
| `tests/fixtures/anzcc.ofx` (DTUSER's place) | `619e9708cbe2b83d7e4716add867406812fcbec48218c4c254c4baa3477d0fcf` |
| `tests/fixtures/bank_medium.ofx`, `fidelity.ofx`, `suncorp.ofx` (OFX 2 XML form) | `107a4e9314aa87e2a3c247b2be6d5360f84fb072beae9830bda3b1f3c9938a52`, `daa1abb520d5931d431fdea2a0c88d627443645f8f71e978f25d64f8ecfb6fc3`, `963b7d6d00b0451f777a2315b1f687915dac90bd32cd7dccfe1a1b4787abad82` |
| `LICENSE` | `25e75507d0e1d9d2487c12fc839780f2905b18553a60ab1895ac9d999db30370` |

## Licence

`LICENSE` is the MIT License, "Copyright (c) 2009 Jerry Seutter". The element names are those the parser
looks for; the order is the order in the project's test fixtures (sample files in the repository, not
copied here). The OFX specification (Financial Data Exchange / ofx.net) was not used.

This pack restates the layout in its own words; no code, comment or sample is copied. Under this project's
rule for code sources the restated layout carries the default Apache-2.0 label. The vectors are built by
`tools/gen/finance-vectors.py` from values chosen there; their expected bytes or text are derived there,
without an engine.

## Attribution

Element names and order from ofxparse, https://github.com/jseutter/ofxparse (MIT License, Copyright (c) 2009
Jerry Seutter), restated.
