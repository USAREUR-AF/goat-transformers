# Provenance: gmti-segment

Same sources, versions, SHA-256 and release basis as `packs/gmti/PROVENANCE.md`
(AEDP-4607 Edition A Version 1 and AEDP-4607.1 Edition A Version 1, NSG
Standards Registry). `distribution public`. NATO is acknowledged as the source
of the layouts, which are restated in this project's own words.

Taken: the segment layouts of AEDP-4607 chapters 3 and 4, as `gmti` takes them, without the packet header.

## Observed vectors: pentlandedge/s4607

The vectors `*-observed-s4607-*` take their segment bodies from the test files of
s4607, an Erlang STANAG 4607 decoder and encoder:

| | |
|---|---|
| Source | https://github.com/pentlandedge/s4607, commit `be131209068384529116950ae902fbf90bcb7edd` (2022-01-13) |
| Licence | Apache License, Version 2.0 (`LICENSE.md`); the test files state "Copyright 2016 Pentland Edge Ltd." (or 2018) and the Apache-2.0 notice |

| File | SHA-256 |
|---|---|
| `LICENSE.md` | `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |
| `test/mission_tests.erl` | `b1955d56f6dd48ab88d0ed799858050b825e3e284a1f6e3ea259e261eb90fb9b` |
| `test/platform_loc_tests.erl` | `810273e5c0d65a22bc1b4cffa85c99d922b908154b433e8314f51efe98bc8553` |
| `test/test_status_tests.erl` | `386f639105eec78a9525887d0650f382da77783f0091ab209a9ea9ddbfb9950b` |
| `test/job_req_tests.erl` | `ed0bde06a159c05a0b38f621d41656de060031078a12c8b2d117e6ff7f4e8fef` |
| `test/job_ack_tests.erl` | `c34804e291b996f48b124e19cc74ae39236e1166f8bfe5438f486e17f3089637` |
| `test/free_text_tests.erl` | `37e045c45adefeb6ef3b202a4b562f78f9a3412d5e4f1d989818c724759c5abf` |

Each vector's input is a sample segment body exactly as the named test function
holds it, behind a 5-byte segment header (type and size) that
`tools/gmti/vectors.py` writes. Its expected bytes and model values are decoded by
that program with `struct` from its own statement of the layouts; where s4607's
test asserts a decoded value for the same bytes (location time, latitude,
longitude, height, track and speed; test and status indexes and time; the mission
date), the program checks its own value against it. No s4607 code is copied or
run. The s4607 tests hold no dwell or HRR segment as bytes (they build those
with the library), so no dwell is observed here.
