SPDX licence: LicenseRef-unstated

# Provenance of the aisstream pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/aisstream-run.sh`) reads the files below. They are not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Publisher | aisstream.io |
| Address | https://github.com/aisstream/ais-message-models |
| Version | commit 8650fc5bf8c308264bc0c18e9ddc83c3ec5d10b8 (head of the default branch; tag v0.1.0 is earlier) |
| Files | under the repository root (`type-definition.yaml`); `aisstream-envelopes.json` is the run script's own wrapper, see pack.md |
| Also | Units of the position report: https://aisstream.io/documentation, read 2026-11-20. |

| File | Bytes | SHA-256 |
|---|---|---|
| `aisstream-envelopes.json` | 12142 | `5a25cf583fe0490f9ef01b35673a088e2615d566084e34840e941fe30f9593c1` |
| `type-definition.yaml` | 34894 | `0c7492a6fbea64bf858401dbf2ac5bc8ea7482b5e88b8c8d19a366d609ed69ac` |

## Licence

The statements conflict and no licence text exists. The README states:

> This project is licensed under the MIT License - see the LICENSE file for details.

but the repository has no LICENSE file, and its `package.json` states:

> "license": "ISC"

The documentation page at aisstream.io carries only `© 2026 AIS Stream`. With no licence
text and two different names, the pack is labelled `LicenseRef-unstated` (LICENSES/LicenseRef-unstated.txt): commercial use is unknown until the owner states terms.
