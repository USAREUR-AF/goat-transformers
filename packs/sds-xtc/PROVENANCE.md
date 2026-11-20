# Provenance of the sds-xtc pack

SPDX licence: Apache-2.0

`tools/gen/sds-run.sh` runs `tools/gen/jsonschema2pack.py` on the standard's
`main.fb.schema.json` and nothing else. The file is not kept in this repository.
Read on 2026-11-20.

| | |
|---|---|
| Document | Space Data Standards, standard `XTC`, JSON Schema (draft 2019-09) |
| Publisher | Edgesource Corporation (spacedatastandards.org) |
| Repository | https://github.com/DigitalArsenal/spacedatastandards.org at commit `0a61c131bc8a849360a0bba57855cc6dd8dde70a` |
| Download | `https://raw.githubusercontent.com/DigitalArsenal/spacedatastandards.org/0a61c131bc8a849360a0bba57855cc6dd8dde70a/lib/fbjson/XTC/main.fb.schema.json` |

| File | SHA-256 | Read by the generator |
|---|---|---|
| `lib/fbjson/XTC/main.fb.schema.json` | `eff75119761a591d57464dda980750e1b47e034c466a2787b4e3d64c72003c8d` | yes |
| `LICENSE` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` | no |
| `NOTICE` | `2de8b5a632486b70ee1cdbaa05803b67b1dec872ec5ebf1651b543f9c9c779e0` | no |

## License

Apache-2.0. The repository's `README.md`, section License: "Copyright 2026 Edgesource Corporation. This project is licensed under the Apache License, Version 2.0." Its `NOTICE` begins: "Space Data Standards. Copyright 2026 Edgesource Corporation. Licensed under the Apache License 2.0." and states that every file of the repository is covered by the License except the third-party components it lists; `lib/fbjson/` is not among them. `LICENSE` is the text of the Apache License, Version 2.0, January 2004.

Attribution: the pack is derived from the Space Data Standards schema `XTC`; it restates the schema's structure with keys of this project's naming and is not endorsed by the publisher.

## The standard it restates

The schema restates the structure of XTCE, the XML Telemetric and Command Exchange standard: OMG XTCE 1.2 (OMG document formal/18-10-04, https://www.omg.org/spec/XTCE/1.2/, PDF SHA-256 `f31d140f3493b417aa542bbcc3465b58a7cb089e8ca9b794978f4d3aa994fa49`, read on 2026-11-20), also published as CCSDS 660.0-B-2. Neither document, nor the XTCE XML schema, is read by the generator or copied here. The OMG document's notice (Copyright 2014-2018 Object Management Group, Inc., and the companies it lists) grants, in its section Licenses, a license "to use this specification to create and distribute software and special purpose specifications that are based upon this specification"; its other conditions (no copies posted on a network, no resale, no modification) apply to copies of the document, and this repository holds none. The pack is labelled Apache-2.0, the licence of the SDS schema it is generated from; it is not endorsed by the OMG or the CCSDS.
