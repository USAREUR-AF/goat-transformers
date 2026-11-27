# PROVENANCE: the XTCE databases read by tools/gen/xtce2pack.py

The generator reads these files from the directory given by `--src` and refuses
a file whose SHA-256 differs. The files are not kept in this repository.

| Item | Value |
|---|---|
| repository | https://github.com/CesarCoelho/xtcetools |
| commit | `14b7f51c5a93faa0bae7c655dbb8d1d1f466fcf6` |
| directory | `src/main/resources/org/xtce/toolkit/database/examples/` |
| LICENSE | Apache-2.0, sha256 `aeccbc69b907fb6fbf4dbc8527c70ae5a83d84acf4e0e849887ea32d5d249079` |

| File | SHA-256 | Licence | Name |
|---|---|---|---|
| `BogusSAT-2.xml` | `7b64301164c6313257202c9fa69eed5df62afe10eca3b3e4b0caa934a6ee842b` | Apache-2.0 | bogussat2 |
| `Diagnostic_Log_Packets.xml` | `df17b82659d32ab96a81223a3217a0a9c75e06a730121f29caac447fcc1648c9` | Apache-2.0 | diaglog |

Each file states its own licence in a header comment: Apache License 2.0, by its
author (copyright 2015 and 2017). The repository's `GovSat_2_0_1.xml` is not read:
it carries no notice of its own and its origin is not stated.

The meaning of the containers, parameter types and encodings is that of XTCE,
CCSDS 660.0-B-2 (OMG XTCE 1.2). Its notice grants a licence to use the standard to
create and distribute software based on it; the generator was written from its
text in our own words, and no part of it, or of its schema, is copied here.
