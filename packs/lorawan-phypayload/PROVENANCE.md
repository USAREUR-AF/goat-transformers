# Provenance: lorawan-phypayload pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| brocaar/lorawan (Orne Brocaar) | https://github.com/brocaar/lorawan | `4bb09b3bdacba097680894e8d35dbcbc0d260c7e` |

| File read | SHA-256 |
|---|---|
| `phypayload.go` | `176f5d7d1bc2a75ce734dee94f48920b6c85653400cf21aa6e689fb31939fda1` |
| `fhdr.go` | `eeb3ea2fa0907f44dbb096d000b2b371cdbceeceb6416eb9f39a3bf94f33c6c3` |
| `macpayload.go` | `c680a9161a263cdc9d6f30db517e5fe92d9e96dea089907e9f834ba914b562ba` |
| `payload.go` | `4ead2e1708775ad99007d98691b018a38ae4b1b101b7c932193cf3c9f6de1374` |
| `netid.go` | `ac51bc6b89c1254e55001085921a7aaf74138d83f38a2aa26953b4c5b9bccb94` |
| `LICENSE` | `cac160cc47eb762b9b93724b229faef212ecff51121377dfc3e89f800c632633` |

## Licence

`LICENSE` is the MIT License, "Copyright (c) 2019 Orne Brocaar". Under this project's rule for code sources
the restated layouts carry the default Apache-2.0 label.

The LoRa Alliance specification itself (a free download behind a form with its own terms) was not used;
the layouts come from the code alone. This pack restates the layouts (field order, sizes, bit positions,
codes) in its own words; no code or comment is copied. The vectors are built by
`tools/gen/lpwan2-vectors.py` from values chosen there; their expected bytes are derived there, without an
engine.

## Attribution

Layouts from brocaar/lorawan, https://github.com/brocaar/lorawan (MIT License, Copyright (c) 2019 Orne
Brocaar), restated.
