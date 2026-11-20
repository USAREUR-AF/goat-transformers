#!/usr/bin/env python3
"""labelled-json-provenance: write PROVENANCE.md of the labelled JSON packs.

Usage: python3 -I tools/gen/labelled-json-provenance.py [--check] [--out DIR] [FAMILY ...]

Families: signalk, wis2, massrobotics, aisstream, gcn, openadr3, openaq, ocpp, opensky
(all when none is named). For each pack of a family it writes packs/<pack>/PROVENANCE.md:
the SPDX licence identifier on the first line, the source (publisher, address, version or
commit, the run script), the files read with their size and SHA-256, and the licence or
terms text the source states, quoted, or where it was looked for when it states none.

The file list of a generated pack is read from the "Sources" table of its pack.md, which
the generator writes; the hand-written opensky packs list theirs here. The licence text
of each family is held here, quoted from the source as read on the date given. Every file
goes through tools/gen/genio.py: with --check nothing is written and the exit status is 1
when a file differs. Python 3 standard library only; reads no source file and runs no
engine.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

READ_ON = "2026-11-20"

UNSTATED = ("`LicenseRef-unstated` (LICENSES/LicenseRef-unstated.txt): commercial use is "
            "unknown until the owner states terms.")

FAMILIES = {
    "signalk": {
        "spdx": "CC-BY-SA-2.0",
        "prefix": ["signalk-"],
        "publisher": "Signal K project",
        "address": "https://github.com/SignalK/specification",
        "version": "tag v1.8.6, commit 739ea90561750a76a7bdb30d5683a628205e1b41",
        "where": "`schemas/` of the repository",
        "run": "tools/gen/signalk-run.sh",
        "licence": """The repository's `LICENSE` is the Creative Commons Attribution-ShareAlike 2.0
licence; it opens with its title line:

> Creative Commons Attribution-ShareAlike 2.0

and the repository's `package.json` states:

> "license": "CC-BY-SA-2.0",

A pack generated from the schemas is an adaptation of them, so it carries the same
licence: `CC-BY-SA-2.0`. Attribution: Signal K, https://signalk.org, schemas of the Signal K
specification. Share-alike: an adaptation of this pack must carry the same licence (or a
later version with the same elements). The pack is in the `open+copyleft` profile.""",
    },
    "wis2": {
        "spdx": "LicenseRef-unstated",
        "prefix": ["wis2-"],
        "publisher": "World Meteorological Organization (WMO), Standing Committee on Information Management and Technology",
        "address": "https://github.com/wmo-im/wis2-notification-message",
        "version": "tag 1.3.0, commit 64a79fc3ec92584054c4194d2862ca71b9a3d4df",
        "where": "`schemas/` of the repository",
        "run": "tools/gen/wis2-run.sh",
        "licence": """No licence was found. The repository has no LICENSE file; neither the README nor
`schemas/README.md` nor the schema states one. The standard's source,
`standard/index.adoc`, states a copyright and no licence:

> :copyright: Copyright © 2024-2026 World Meteorological Organization (WMO)

Looked in: the repository root, `schemas/`, `standard/index.adoc` and its sections, and the
repository's metadata on the hosting service (no licence named). """ + UNSTATED,
    },
    "massrobotics": {
        "spdx": "LicenseRef-unstated",
        "prefix": ["massrobotics-"],
        "publisher": "MassRobotics, AMR Interoperability Working Group",
        "address": "https://github.com/MassRobotics-AMR/AMR_Interop_Standard",
        "version": "commit f9357a423ecabc3f7112e6d10025a5231943ec50 (head of the default branch; tag 1.0 is earlier)",
        "where": "the repository root",
        "run": "tools/gen/massrobotics-run.sh",
        "licence": """No licence was found. The repository has no LICENSE file; the README and the schema
state none. The standard (`AMR_Interop_Standard.pdf`, same commit) has a legal section that
says the standard's use is voluntary, and states:

> © 2021 MassRobotics

Looked in: the repository root, the README, the schema, the PDF of the standard, and the
repository's metadata on the hosting service (no licence named). """ + UNSTATED,
    },
    "aisstream": {
        "spdx": "LicenseRef-unstated",
        "prefix": ["aisstream"],
        "publisher": "aisstream.io",
        "address": "https://github.com/aisstream/ais-message-models",
        "version": "commit 8650fc5bf8c308264bc0c18e9ddc83c3ec5d10b8 (head of the default branch; tag v0.1.0 is earlier)",
        "where": "the repository root (`type-definition.yaml`); `aisstream-envelopes.json` is the run script's own wrapper, see pack.md",
        "run": "tools/gen/aisstream-run.sh",
        "extra": "Units of the position report: https://aisstream.io/documentation, read 2026-11-20.",
        "licence": """The statements conflict and no licence text exists. The README states:

> This project is licensed under the MIT License - see the LICENSE file for details.

but the repository has no LICENSE file, and its `package.json` states:

> "license": "ISC"

The documentation page at aisstream.io carries only `© 2026 AIS Stream`. With no licence
text and two different names, the pack is labelled """ + UNSTATED,
    },
    "gcn": {
        "spdx": "LicenseRef-unstated",
        "prefix": ["gcn-"],
        "publisher": "NASA General Coordinates Network (GCN) and the mission teams that contribute schemas",
        "address": "https://github.com/nasa-gcn/gcn-schema",
        "version": "tag v7.3.0, commit 388eb34d1327b75e355ecb9c54756cc63c973696",
        "where": "`gcn/` of the repository (each path relative to the deepest directory the files share)",
        "run": "tools/gen/gcn-run.sh",
        "licence": """No licence was found. The repository has no LICENSE file; its `package.json` has no
`license` member; the README and the schemas state none. The schemas are contributed by
mission teams outside NASA as well as by NASA, so the public-domain status of United
States Government works cannot be assumed for all of them.

Looked in: the repository root, `package.json`, the README, the schema files, and the
repository's metadata on the hosting service (no licence named). """ + UNSTATED,
    },
    "openadr3": {
        "spdx": "Apache-2.0",
        "prefix": ["openadr3-"],
        "publisher": "OpenADR Alliance (specification); grid-coordination (public mirror)",
        "address": "https://github.com/grid-coordination/openadr3-specification",
        "version": ("commit 17b91725e0f07203574ddc946e28def31cb11e44; file `3.1.0/openadr3-UPSTREAM.yaml`, "
                    "the mirror's byte-for-byte copy of upstream oadr3-org/specification commit ddd2cc5"),
        "where": "`3.1.0/` of the mirror",
        "run": "tools/gen/openadr3-run.sh",
        "licence": """The OpenAPI document declares its own licence in `info.license`:

> name: Apache 2.0
> url: 'http://www.apache.org/licenses/LICENSE-2.0.html'

The pack is labelled `Apache-2.0` on that statement. The OpenADR Alliance publishes the
specification at no charge but behind an account registration, and its own repository is
not public; the mirror's NOTICE says it republishes the artifacts unmodified, quotes the
Alliance describing its specifications as "license free but copyright of the OpenADR
Alliance", and notes that the Definition and User Guide documents carry the Alliance's
copyright without a separate grant. The pack takes nothing from those documents. No
endorsement by the OpenADR Alliance is implied.""",
    },
    "openaq": {
        "spdx": "LicenseRef-OpenAQ",
        "prefix": ["openaq-"],
        "publisher": "OpenAQ",
        "address": ("https://api.openaq.org/openapi.json, served 2026-11-20; the document has no versioned "
                    "address, so this copy is pinned by its SHA-256"),
        "version": "OpenAPI 3.1.0, `info.version` 3.0.0",
        "where": "the API's address",
        "run": "tools/gen/openaq-run.sh",
        "licence": """The OpenAPI document states no licence. The OpenAQ terms of use,
https://docs.openaq.org/about/terms (read 2026-11-20), govern the API; the parts that bear
on this pack are quoted in LICENSES/LicenseRef-OpenAQ.txt. In short, quoted:

> Attribution to OpenAQ as the source data is also required when using OpenAQ
> services for accessing the data.

and the terms prohibit using the hosted API to build products or services that
substantially duplicate or directly compete with OpenAQ's core offerings. The pack holds
no OpenAQ data; its vectors are values written for them.""",
    },
    "ocpp": {
        "spdx": "LicenseRef-unstated",
        "prefix": ["ocpp16-", "ocpp201-"],
        "publisher": "Open Charge Alliance (schemas); The Mobility House (the library that carries the copies)",
        "address": "https://github.com/mobilityhouse/ocpp",
        "version": "tag 2.1.0, commit 91f4f89140a2198dc5a300cfea88d947ac91ae28",
        "where": "`ocpp/v16/schemas/` (OCPP 1.6) or `ocpp/v201/schemas/` (OCPP 2.0.1) of the repository",
        "run": "tools/gen/ocpp-run.sh",
        "licence": """No licence was found for the schemas. The schema files carry no licence or copyright
notice (the 2.0.1 files have a comment naming the version only). The library's `LICENSE`
is the MIT License with the copyright of The Mobility House; it covers the library, and
the schemas in it are the Open Charge Alliance's. The Alliance publishes the schemas with
the OCPP specification at no charge after an account registration
(https://openchargealliance.org/download-ocpp/, read 2026-11-20); the terms attached at
that download were not read, since the download needs an account.

Looked in: the schema files, the library's LICENSE and README, the Alliance's download
page. """ + UNSTATED,
    },
    "opensky": {
        "spdx": "LicenseRef-OpenSky",
        "prefix": ["opensky-"],
        "publisher": "OpenSky Network",
        "address": "https://github.com/openskynetwork/opensky-api (rendered at https://openskynetwork.github.io/opensky-api/rest.html)",
        "version": "commit 98fecf7438dfbd23c4a26c8a7286a25b805eb2d3",
        "where": "`docs/free/` of the repository",
        "run": "written by hand; vectors by tools/gen/opensky-vectors.py",
        "files": {
            "opensky-states": [("states-response.rst", 9387, "cc37bfd2dab4c0d6390c2b4b584551902b9948bfd16852e96eb5d629b5313660")],
            "opensky-track": [("track-response.rst", 3622, "31ebefef70f0d51d06eb4c7b1e26823b43acd2eefc46ca93ba2ba6fe4bb0d243")],
        },
        "licence": """The documentation is part of a repository whose `LICENSE.txt` is the GNU General Public
License, version 3. The documentation and the repository's README direct API users to the
OpenSky terms of use, https://opensky-network.org/about/terms-of-use. Those terms license
OpenSky data for non-profit research and non-profit education only, and require a written
licence for any use by a commercial entity and for any operational use of the REST API;
LICENSES/LicenseRef-OpenSky.txt quotes them (from the Internet Archive copy of
2026-11-10, since the page refused an automated request on 2026-11-20).

The pack states the layout of a response in this project's words; it holds no OpenSky
data, and its vectors are values written for them. Reading OpenSky API responses with it
is use of the API, under those terms.""",
    },
}

def pack_names(root, fam):
    out = []
    for name in sorted(os.listdir(os.path.join(root, "packs"))):
        if any(name.startswith(p) for p in FAMILIES[fam]["prefix"]):
            out.append(name)
    return out


def sources_of(text):
    """(file, bytes, sha256) rows of the Sources table of a generated pack.md."""
    rows, on = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            on = line.strip() == "## Sources"
            continue
        m = re.match(r"\| `([^`]+)` \| (\d+) \| `([0-9a-f]{64})` \|$", line) if on else None
        if m:
            rows.append((m.group(1), int(m.group(2)), m.group(3)))
    return rows


def text_for(fam, pack, files):
    f = FAMILIES[fam]
    out = ["SPDX licence: %s" % f["spdx"], "", "# Provenance of the %s pack" % pack, ""]
    if fam == "opensky":
        out.append("Written by hand from the response table of the API documentation; the vectors are "
                   "written by `tools/gen/opensky-vectors.py`. The documentation is not kept in this "
                   "repository. Read on %s." % READ_ON)
    else:
        out.append("`tools/gen/jsonschema2pack.py` (run script `%s`) reads the files below. They are not "
                   "kept in this repository. Read on %s." % (f["run"], READ_ON))
    out += ["", "## Source", "", "| | |", "|---|---|",
            "| Publisher | %s |" % f["publisher"],
            "| Address | %s |" % f["address"],
            "| Version | %s |" % f["version"],
            "| Files | under %s |" % f["where"]]
    if f.get("extra"):
        out.append("| Also | %s |" % f["extra"])
    out += ["", "| File | Bytes | SHA-256 |", "|---|---|---|"]
    for name, size, sha in files:
        out.append("| `%s` | %s | `%s` |" % (name, "-" if size is None else size, sha))
    out += ["", "## Licence", "", f["licence"], ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="labelled-json-provenance", description=__doc__.split("\n\n")[0])
    genio.add_arguments(ap, default_out=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("family", nargs="*", metavar="FAMILY")
    a = ap.parse_args(argv)
    for fam in a.family:
        if fam not in FAMILIES:
            ap.error("unknown family %s (one of %s)" % (fam, ", ".join(sorted(FAMILIES))))
    out = genio.Output(a.out, check=a.check)
    for fam in a.family or sorted(FAMILIES):
        packs = pack_names(out.root, fam)
        if not packs:
            print("labelled-json-provenance: no pack of family %s" % fam, file=sys.stderr)
            return 1
        for pack in packs:
            if "files" in FAMILIES[fam]:
                files = FAMILIES[fam]["files"][pack]
            else:
                files = sources_of(out.read("packs/%s/pack.md" % pack))
                if not files:
                    print("labelled-json-provenance: packs/%s/pack.md has no Sources table" % pack, file=sys.stderr)
                    return 1
            out.write("packs/%s/PROVENANCE.md" % pack, text_for(fam, pack, files))
    return out.report("labelled-json-provenance")


if __name__ == "__main__":
    sys.exit(main())
