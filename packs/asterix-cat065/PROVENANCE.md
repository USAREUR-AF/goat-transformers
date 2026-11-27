# Provenance: asterix-cat065

| Fact | Value |
|---|---|
| category | ASTERIX Category 065, SDPS Service Status Reports |
| edition | 1.6, dated 2023-03-21 in the definition |
| specified by | EUROCONTROL (https://www.eurocontrol.int/asterix) |
| definition read | `specs/cat065/cats/cat1.6/definition.json` of https://github.com/zoranbosnjak/asterix-specs |
| commit (branch `gh-pages`, the published JSON) | `64e9ffba964b92a1af3157bc6bdf7852a63bf700` |
| built from commit (branch `master`) | `5cf64b635424891b9f7e5d8fc51f6531e5790f89` |
| SHA-256 of the definition | `0fdcfcf19919d1c4b389539067894b04e367b9f6326495fb046779b3cddabfb4` |
| licence of the repository | BSD 3-Clause, copyright (c) 2019 KZPS (`LICENSE` at the `master` commit; verbatim in `sources/PROVENANCE.md`) |
| generator | `tools/gen/asterix2pack.py`; key names pinned in `tools/gen/names/asterix-cat065.json` |

## Golden vectors: asterix_decoder

`vectors/golden-*.json` are written by `tools/gen/golden-asterix.py` from asterix_decoder, Croatia Control's
ASTERIX decoder, whose category definitions are its own XML files, written apart from the asterix-specs
transcription this pack is generated from (shared-model hardening, item 2). It decodes only, so the inputs
are the recorded captures it ships, split into single-record blocks by the record lengths it reports.

| | |
|---|---|
| Package | asterix_decoder 0.7.11, sdist `asterix_decoder-0.7.11.tar.gz`, SHA-256 `3eb28379c576ad09c813f6ed482d1f5e397667814d3baaf8ff13dceec2146426`, built with setuptools 84.2.1 (wheel SHA-256 `ca140b45d5325a9478f880e351484f62fef15f336462e449ca0c03c873d589c2`); pinned in `tools/gen/golden-asterix.txt` and `golden-asterix-build.txt`, installed with `pip --require-hashes` |
| Captures | its `asterix/sample_data` files, each refused unless its SHA-256 is the one the script records |
| Licence | GPL-2.0 (the sdist's `LICENSE`). asterix_decoder is run, not copied: it is built outside the tree to write the vectors, and only its output and the bytes of its sample captures enter this repository; no line of its code or definitions does |
