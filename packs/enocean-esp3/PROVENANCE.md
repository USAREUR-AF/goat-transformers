# Provenance: enocean-esp3 pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| kipe/enocean (Kimmo Huoman and contributors) | https://github.com/kipe/enocean | `80a253bcea1e3cb99295f53f04c0558190dca5f3` |

| File read | SHA-256 |
|---|---|
| `enocean/protocol/packet.py` | `0045e665d22b7973310d6d0e03bf3283e01a5143c3731c5588f528d11f62a9fb` |
| `enocean/protocol/constants.py` | `7eb7f87c76c2bbec7e6dcfc8a0578fe4a1a5b3332b3cbcb47035b08c22720064` |
| `enocean/protocol/crc8.py` | `bb10915ef1b52431fb20828cb72cba0d2c0bb3cba9c953b77b43fd619dd47237` |
| `LICENSE` | `7f54a057c4364bec3faa86baf609c7bf7c5b99c5c599ebf0472d4015afa46850` |

## Licence

`LICENSE` is the MIT License, "Copyright (c) 2014-2016 Kimmo Huoman". Under this project's rule for code
sources the restated layout carries the default Apache-2.0 label. The EnOcean ESP3 specification (a public
download from EnOcean with its own terms) was not used.

This pack restates the layout in its own words; no code or comment is copied. The vectors are built by
`tools/gen/smarthome-vectors.py` from values chosen there (the CRCs computed there with the polynomial the
source's table encodes); their expected bytes are derived there, without an engine.

## Attribution

Layout from kipe/enocean, https://github.com/kipe/enocean (MIT License, Copyright (c) 2014-2016 Kimmo
Huoman), restated.
