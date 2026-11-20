# Provenance of the covjson-domain pack

The pack and the module `covjson` (shared by `covjson-domain`, `covjson-coverage` and
`covjson-coverage-collection`) are written by hand from the text of the OGC CoverageJSON
Community Standard; the vectors by `tools/gen/covjson-vectors.py` from documents written for
them. No source file is kept in this repository. Read on 2026-11-20.

## Source

| Fact | Value |
|---|---|
| standard | OGC CoverageJSON Community Standard, version 1.0, OGC document 21-069r2 |
| repository | https://github.com/opengeospatial/CoverageJSON |
| tag, commit | `V1.0.0`, `5e9b6f5e8eec77d60d6338b3d4d9a152f98429c0` (the commit whose `standard/document.adoc` names document 21-069r2) |
| file read | `standard/clause_specification_text.adoc`, SHA-256 `abd49267c1d504cc6c6a07783db6202d25fe4d91ad17d5ea02d9eb8007ffe171` |
| licence file | `LICENSE` at that commit, SHA-256 `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |

The JSON Schema fragments under `standard/schema/` were added to the repository after that tag
(for the 21-069r3 draft); they were looked at, not used: they select the axes of each domain
type with `if`/`then` and `dependentSchemas`, which the generator `jsonschema2pack.py` does not
follow, and `domain` is a string or an object.

## Licence

The repository's `LICENSE` file covers the files of the standard's text. It begins:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

and is the Apache License 2.0 text; the copyright line of its appendix is left as the template, so the file names no holder. The front matter of the standard (`standard/clause_0_front_material.adoc`,
SHA-256 `31a98fe1e1b6fadca3591e0e3dd653335dbf142b4e3c8f3b20507173c576314b`) adds that the
format came out of the European Union project MELODIES and was released by the University of
Reading under a Creative Commons 4.0 licence. Label: `Apache-2.0`, as the repository states it.

The pack restates the structure of the documents the standard defines, in this project's words;
no text, table or example of the standard is copied. It is a change that OGC has not reviewed or
approved.
