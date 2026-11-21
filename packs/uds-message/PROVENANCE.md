# Provenance: uds-message pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| python-udsoncan (Pier-Yves Lessard) | https://github.com/pylessard/python-udsoncan | `07d7be1fcfd17e41af9a30f1c5573774e45bcdbd` |

| File read | SHA-256 |
|---|---|
| `udsoncan/Request.py` | `6d09a5e35620daf93c0ba7dce90dd950d5d8f5bd85b56337aedc0fbe7f2eded9` |
| `udsoncan/Response.py` | `2a47cd4e3dbac08e4dd5e6d6834a9cb972b44c19d31dfab455ee679078854380` |
| `udsoncan/services/DiagnosticSessionControl.py` | `cac2a8e60bfbf05490c5113c9e62b2d38e44f0d22797a4f856beb41d730e2172` |
| `udsoncan/services/ECUReset.py` | `9deecebd16c5abed7637b4058800c445f5587fa48352a9231ac599022cadecea` |
| `udsoncan/services/ReadDataByIdentifier.py` | `140f2980da8cee249ff1a614ddde6c7226b78ca438bc2b0abeba52c77d051214` |
| `udsoncan/services/WriteDataByIdentifier.py` | `fa76ed1e4ee8c8e6635bb58c2b9effbd754225ea241c7720814f3aeac17417e7` |
| `udsoncan/services/SecurityAccess.py` | `211dbdf620371c93a5ac1bbaf665b2ec74d1d1976164914b07b98b0f5b8bf56b` |
| `udsoncan/services/RoutineControl.py` | `da34d80d9b3ef62e1172561f7c2e66833023b6a743e6213955bcb0ea87d28105` |
| `udsoncan/services/TesterPresent.py` | `30e64ffc7a39741cf4d0a23ad13d1aba04a58c38a615baed926692b26cac46be` |
| `LICENSE.txt` | `aae122e22b842c7fe113e6968ff00a52619d3a11b37f7791eebecb7fc7042103` |

## Licence

`LICENSE.txt` at that commit is the MIT License, "Copyright (c) 2017 Pier-Yves Lessard". Under this
project's rule for code sources the restated layouts carry the default Apache-2.0 label.

This pack restates the layouts (field order, sizes, codes) in its own words; no code, comment or table
of the source is copied. ISO 14229-1, a paid document, was not used. The vectors are built by `tools/gen/vehnet-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layouts from python-udsoncan, https://github.com/pylessard/python-udsoncan (MIT License, Copyright (c)
2017 Pier-Yves Lessard), restated.
