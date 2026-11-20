SPDX licence: LicenseRef-OpenSky

# Provenance of the opensky-states pack

Written by hand from the response table of the API documentation; the vectors are written by `tools/gen/opensky-vectors.py`. The documentation is not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Publisher | OpenSky Network |
| Address | https://github.com/openskynetwork/opensky-api (rendered at https://openskynetwork.github.io/opensky-api/rest.html) |
| Version | commit 98fecf7438dfbd23c4a26c8a7286a25b805eb2d3 |
| Files | under `docs/free/` of the repository |

| File | Bytes | SHA-256 |
|---|---|---|
| `states-response.rst` | 9387 | `cc37bfd2dab4c0d6390c2b4b584551902b9948bfd16852e96eb5d629b5313660` |

## Licence

The documentation is part of a repository whose `LICENSE.txt` is the GNU General Public
License, version 3. The documentation and the repository's README direct API users to the
OpenSky terms of use, https://opensky-network.org/about/terms-of-use. Those terms license
OpenSky data for non-profit research and non-profit education only, and require a written
licence for any use by a commercial entity and for any operational use of the REST API;
LICENSES/LicenseRef-OpenSky.txt quotes them (from the Internet Archive copy of
2026-11-10, since the page refused an automated request on 2026-11-20).

The pack states the layout of a response in this project's words; it holds no OpenSky
data, and its vectors are values written for them. Reading OpenSky API responses with it
is use of the API, under those terms.
