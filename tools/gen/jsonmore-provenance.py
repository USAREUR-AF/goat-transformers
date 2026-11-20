#!/usr/bin/env python3
"""jsonmore-provenance: write PROVENANCE.md of the STIX, CloudEvents, GOFS, OpenC2 and CACAO packs.

Usage: python3 -I tools/gen/jsonmore-provenance.py <stix|cloudevents|gofs|openc2|cacao> [--check] <source checkout> <goat-transformers checkout>

<source checkout> is the checkout the family's run script reads (tools/gen/stix-run.sh,
cloudevents-run.sh, gofs-run.sh call this script last, with the same checkout). For each
pack of the family it lists the files the generator reads with their SHA-256, the
repository and commit, and the license, quoted from the repository's LICENSE. Every file
goes through tools/gen/genio.py: with --check nothing is written and the exit status is 1
when a file differs. Python 3 standard library only.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

READ_ON = "2026-11-19"

FAMILIES = {
    "stix": {
        "repo": "https://github.com/oasis-open/cti-stix2-json-schemas",
        "raw": "https://raw.githubusercontent.com/oasis-open/cti-stix2-json-schemas",
        "publisher": "OASIS Cyber Threat Intelligence (CTI) Technical Committee, TC Open Repository",
        "run": "tools/gen/stix-run.sh",
        "full_license": True,
        "license_intro": ("The repository's `LICENSE` is the BSD 3-Clause License with the copyright of "
                          "OASIS Open. Its README states that the repository is an OASIS TC Open "
                          "Repository whose contributions are under that license, and that its "
                          "governance is separate from the OASIS TC Process. The license asks that "
                          "its notice be kept with redistributions; in full:"),
        "spec": ("The schemas are not normative; they follow the STIX Version 2.1 OASIS Standard "
                 "(https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html). The pack takes "
                 "no text of the standard; its notes name the section they rely on in this "
                 "project's words."),
    },
    "cloudevents": {
        "repo": "https://github.com/cloudevents/spec",
        "raw": "https://raw.githubusercontent.com/cloudevents/spec",
        "publisher": "CloudEvents project (CNCF)",
        "run": "tools/gen/cloudevents-run.sh",
        "full_license": False,
        "license_intro": "The repository's `LICENSE` is the Apache License, Version 2.0; it opens:",
        "spec": ("The specification text (`cloudevents/spec.md`, `cloudevents/formats/json-format.md`) "
                 "is in the same repository under the same license. The pack takes no text of it."),
    },
    "openc2": {
        "repo": "https://github.com/oasis-open/openc2-custom-aps",
        "raw": "https://raw.githubusercontent.com/oasis-open/openc2-custom-aps",
        "publisher": "OASIS Open Command and Control (OpenC2) Technical Committee, TC Open Repository",
        "run": "tools/gen/openc2-cacao-run.sh",
        "read_on": "2026-11-20",
        "full_license": False,
        "license_intro": ("The repository's `LICENSE.md` is the Apache License, Version 2.0. Its README states "
                          "that the repository is an OASIS TC Open Repository whose contributions are under "
                          "that license, and that its governance is separate from the OASIS TC Process. It "
                          "opens:"),
        "license_file": "LICENSE.md",
        "spec": ("The schemas restate the data types of the OpenC2 Language Specification 1.1 and the "
                 "Stateless Packet Filtering actuator profile 1.1, OASIS Committee Specifications whose "
                 "text is under the OASIS IPR policy. The pack takes no text of them."),
    },
    "cacao": {
        "repo": "https://github.com/oasis-open/cacao-json-schemas",
        "raw": "https://raw.githubusercontent.com/oasis-open/cacao-json-schemas",
        "publisher": "OASIS Collaborative Automated Course of Action Operations (CACAO) Technical Committee, TC Open Repository",
        "run": "tools/gen/openc2-cacao-run.sh",
        "read_on": "2026-11-20",
        "full_license": False,
        "license_intro": ("The repository's `LICENSE` is the Apache License, Version 2.0. Its README states "
                          "that the repository is an OASIS TC Open Repository whose contributions are under "
                          "that license, and that its governance is separate from the OASIS TC Process. It "
                          "opens:"),
        "spec": ("The schemas follow CACAO Security Playbooks Version 2.0, an OASIS Committee "
                 "Specification (https://docs.oasis-open.org/cacao/security-playbooks/v2.0/security-playbooks-v2.0.html). "
                 "The pack takes no text of it."),
    },
    "gofs": {
        "repo": "https://github.com/MobilityData/gofs",
        "raw": "https://raw.githubusercontent.com/MobilityData/gofs",
        "publisher": "MobilityData",
        "run": "tools/gen/gofs-run.sh",
        "full_license": False,
        "license_intro": "The repository's `LICENSE` is the Apache License, Version 2.0; it opens:",
        "spec": ("The specification (`reference.md`) is in the same repository under the same "
                 "license. Its `schema/README.md` calls the schemas partial and a work in "
                 "progress. The pack takes no text of the specification."),
    },
    "overture": {
        "repo": "https://github.com/OvertureMaps/schema",
        "raw": "https://raw.githubusercontent.com/OvertureMaps/schema",
        "publisher": "Overture Maps Foundation",
        "tag": "v2.0.0",
        "read_on": "2026-11-20",
        "quote_lines": ["Attribution 4.0 International",
                        "Creative Commons Attribution 4.0 International Public License"],
        "run": "tools/gen/overture-run.sh",
        "full_license": False,
        "license_intro": ("The repository's `LICENSE` is the Creative Commons Attribution 4.0 International "
                          "Public License (CC BY 4.0); its title lines:"),
        "spec": ("The schema files under `schema/` are covered by that `LICENSE`. The Python packages "
                 "under `packages/` declare the MIT license in their `pyproject.toml`; they are not read. "
                 "Overture's map data carries its own licenses, which do not apply here: only the schema "
                 "is used. Attribution: the pack is derived from the Overture Maps schema (CC BY 4.0), "
                 "restated with keys of this project's naming."),
    },
    "cds": {
        "repo": "https://github.com/openmobilityfoundation/cds-openapi",
        "raw": "https://raw.githubusercontent.com/openmobilityfoundation/cds-openapi",
        "publisher": "Open Mobility Foundation",
        "run": "tools/gen/cds-run.sh",
        "read_on": "2026-11-20",
        "full_license": False,
        "quote_lines": ["Creative Commons Attribution 4.0 International Public License"],
        "license_intro": ("The repository's `LICENSE` is the Creative Commons Attribution 4.0 International "
                          "Public License (CC BY 4.0); its title line:"),
        "spec": ("The repository is the OpenAPI form of the Curb Data Specification 1.1.0 "
                 "(https://github.com/openmobilityfoundation/curb-data-specification, tag 1.1.0, also CC BY "
                 "4.0), as its CHANGELOG.MD states; it has no release tags. Attribution: the pack is derived "
                 "from the CDS OpenAPI data models (CC BY 4.0), restated with keys of this project's naming."),
    },
    "tomp": {
        "repo": "https://github.com/TOMP-WG/TOMP-API",
        "raw": "https://raw.githubusercontent.com/TOMP-WG/TOMP-API",
        "publisher": "TOMP Working Group (House of TOMP)",
        "run": "tools/gen/tomp-run.sh",
        "tag": "v2.0",
        "read_on": "2026-11-20",
        "full_license": False,
        "license_intro": "The repository's `LICENSE` is the Apache License, Version 2.0; it opens:",
        "spec": ("`openapi.json` is the merged OpenAPI 3.0 document of TOMP-API 2.0.0; its `info.license` "
                 "also names Apache 2.0. The pack takes no description text of it."),
    },
    "osdm": {
        "repo": "https://github.com/UnionInternationalCheminsdeFer/OSDM",
        "raw": "https://raw.githubusercontent.com/UnionInternationalCheminsdeFer/OSDM",
        "publisher": "UIC (International Union of Railways), OSDM",
        "run": "tools/gen/osdm-run.sh",
        "tag": "v3.11",
        "read_on": "2026-11-20",
        "full_license": False,
        "license_intro": "The repository's `LICENSE` is the Apache License, Version 2.0; it opens:",
        "spec": ("`specification/OSDM-online-api.yml` (its `info.version` reads 3.9.0 at this tag) and the "
                 "schema files it refers to; its `info.license` also names Apache 2.0. Only message objects "
                 "that carry a place or a time are packs. The pack takes no description text."),
    },
    "open311": {
        "repo": "https://github.com/open311/open311.github.io",
        "raw": "https://raw.githubusercontent.com/open311/open311.github.io",
        "publisher": "Open311 community",
        "run": "tools/gen/open311-run.sh",
        "read_on": "2026-11-20",
        "full_license": False,
        "license_file": "data/georeport_v2-1.yaml",
        "quote_lines": ["name: CC BY 3.0", "url: 'http://creativecommons.org/licenses/by/3.0/'"],
        "license_intro": ("The repository has no LICENSE file; the GeoReport v2 OpenAPI document states its own "
                          "license in `info.license`, Creative Commons Attribution 3.0 (CC BY 3.0)"),
        "spec": ("The document is the Swagger 2.0 form of Open311 GeoReport v2 (http://wiki.open311.org/GeoReport_v2/). "
                 "Attribution: the pack is derived from it (CC BY 3.0), restated with keys of this project's "
                 "naming."),
    },
}

CDS = [("cds-curb-zone", "curb_zone"), ("cds-curb-area", "curb_area"), ("cds-curb-space", "curb_space"),
       ("cds-curb-object", "curb_object"), ("cds-curb-event", "curb_event"), ("cds-curb-status", "curb_status"),
       ("cds-session", "session"), ("cds-aggregate", "aggregate")]
TOMP = [("tomp-package", "package"), ("tomp-search-offer-request", "searchOfferRequest"),
        ("tomp-offer-collection", "offerCollection"), ("tomp-asset-collection", "assetCollection"),
        ("tomp-travel-documents", "travelDocuments"), ("tomp-support-ticket", "supportTicket"),
        ("tomp-customer-account", "customerAccount")]
OSDM = [("osdm-place", "Place"), ("osdm-stop-place", "StopPlace"), ("osdm-trip", "Trip"),
        ("osdm-booking", "Booking"), ("osdm-offer", "Offer")]
OPEN311 = [("open311-request", "Request"), ("open311-request-response", "RequestResponse"),
           ("open311-service", "Service")]

# Overture: (format, theme directory, feature file base name)
OVERTURE = [("overture-address", "addresses", "address"), ("overture-bathymetry", "base", "bathymetry"),
            ("overture-infrastructure", "base", "infrastructure"), ("overture-land", "base", "land"),
            ("overture-land-cover", "base", "land_cover"), ("overture-land-use", "base", "land_use"),
            ("overture-water", "base", "water"), ("overture-building", "buildings", "building"),
            ("overture-building-part", "buildings", "building_part"), ("overture-division", "divisions", "division"),
            ("overture-division-area", "divisions", "division_area"),
            ("overture-division-boundary", "divisions", "division_boundary"),
            ("overture-place", "places", "place"), ("overture-connector", "transportation", "connector"),
            ("overture-segment", "transportation", "segment")]


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def closure(path):
    todo, seen = [os.path.abspath(path)], set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        with open(f, encoding="utf-8") as fh:
            doc = json.load(fh)
        stack = [doc]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                r = x.get("$ref")
                if isinstance(r, str) and not r.startswith("#"):
                    todo.append(os.path.normpath(os.path.join(os.path.dirname(f), r.split("#")[0])))
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return sorted(seen)


def packs(family, src):
    """[(format, title, [relative file], main file)]"""
    out = []
    if family == "stix":
        for d in ("sdos", "sros", "observables"):
            for f in sorted(os.listdir(os.path.join(src, "schemas", d))):
                if f.endswith(".json"):
                    t = f[:-5]
                    main = os.path.join(src, "schemas", d, f)
                    files = [os.path.relpath(p, src) for p in closure(main)]
                    out.append(("stix-" + t, "STIX 2.1 `%s` object, JSON Schema" % t, files,
                                os.path.relpath(main, src)))
    elif family == "openc2":
        base = "Schema-Template/v1.1/JSON-Schema/"
        for fmt, f, what in (("openc2-lang", "oc2ls-v1.1-lang.json", "OpenC2 Language Specification 1.1"),
                             ("openc2-slpf", "oc2slpf-v1.1.json", "OpenC2 Stateless Packet Filtering profile 1.1")):
            out.append((fmt, "%s, JSON Schema of the Command and the Response" % what, [base + f], base + f))
    elif family == "cacao":
        main = os.path.join(src, "schemas", "playbook.json")
        out.append(("cacao-playbook", "CACAO Security Playbooks 2.0, JSON Schema of the playbook",
                    [os.path.relpath(p, src) for p in closure(main)], "schemas/playbook.json"))
    elif family == "cds":
        files = sorted("Shared Data Models/" + f for f in os.listdir(os.path.join(src, "Shared Data Models"))
                       if f.endswith(".yaml"))
        for fmt, base in CDS:
            out.append((fmt, "Curb Data Specification (CDS) 1.1.0 data model `%s`, OpenAPI YAML" % base, files,
                        "Shared Data Models/%s.yaml" % base))
    elif family == "tomp":
        for fmt, name in TOMP:
            out.append((fmt, "TOMP-API 2.0.0 schema `%s`, OpenAPI 3.0" % name, ["openapi.json"], "openapi.json"))
    elif family == "osdm":
        spec = os.path.join(src, "specification")
        files = ["specification/OSDM-online-api.yml"] + sorted(
            os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(os.path.join(spec, "schemas"))
            for f in fs if f.endswith(".yml"))
        for fmt, name in OSDM:
            out.append((fmt, "OSDM online API, schema `%s`, OpenAPI 3.0 YAML" % name, files,
                        "specification/OSDM-online-api.yml"))
    elif family == "open311":
        for fmt, name in OPEN311:
            out.append((fmt, "Open311 GeoReport v2, definition `%s`, Swagger 2.0 YAML" % name,
                        ["data/georeport_v2-1.yaml"], "data/georeport_v2-1.yaml"))
    elif family == "overture":
        for fmt, theme, base in OVERTURE:
            rel = "schema/%s/%s.yaml" % (theme, base)
            files = ["schema/defs.yaml"]
            if os.path.exists(os.path.join(src, "schema", theme, "defs.yaml")):
                files.append("schema/%s/defs.yaml" % theme)
            out.append((fmt, "Overture Maps schema, feature type `%s` (theme `%s`), JSON Schema in YAML"
                        % (base, theme), files + [rel], rel))
    elif family == "cloudevents":
        rel = "cloudevents/formats/cloudevents.json"
        out.append(("cloudevents", "CloudEvents 1.0.2, JSON Schema of the JSON event format", [rel], rel))
    else:
        for f in sorted(os.listdir(os.path.join(src, "schema"))):
            if f.endswith(".json"):
                rel = "schema/" + f
                out.append(("gofs-" + f[:-5].replace("_", "-"),
                            "General On-demand Feed Specification (GOFS), JSON Schema of `%s`" % f, [rel], rel))
    return out


def text_for(family, fmt, title, files, main, src, commit):
    c = FAMILIES[family]
    lic = os.path.join(src, c.get("license_file", "LICENSE"))
    with open(lic, encoding="utf-8") as fh:
        lic_text = fh.read().strip("\n")
    if c["full_license"]:
        quote = lic_text.split("\n")
    else:
        quote = [l.strip() for l in lic_text.split("\n") if l.strip()][:3]
    if c.get("quote_lines"):
        stripped = [l.strip() for l in lic_text.split("\n")]
        for l in c["quote_lines"]:
            if l not in stripped:
                raise SystemExit("jsonmore-provenance: LICENSE has no line %r" % l)
        quote = c["quote_lines"]
    w = ["# Provenance of the %s pack\n" % fmt,
         "`tools/gen/jsonschema2pack.py` (run script `%s`) reads the files below and nothing" % c["run"],
         "else. They are not kept in this repository. Read on %s.\n" % c.get("read_on", READ_ON),
         "| | |\n|---|---|",
         "| Document | %s |" % title,
         "| Publisher | %s |" % c["publisher"],
         "| Repository | %s at %scommit `%s` |" % (c["repo"], ("tag `%s`, " % c["tag"]) if c.get("tag") else "", commit),
         "| Download | `%s/%s/%s` |" % (c["raw"], commit, main), "",
         "| File | SHA-256 |\n|---|---|"]
    for f in files:
        w.append("| `%s` | `%s` |" % (f, sha256(os.path.join(src, f))))
    w += ["", "## License\n",
          "%s (SHA-256 of `%s`: `%s`)\n" % (c["license_intro"], c.get("license_file", "LICENSE"), sha256(lic)),
          "\n".join(("> " + l) if l.strip() else ">" for l in quote), "",
          c["spec"], "",
          "The pack restates the schema's structure (member names, types, nesting) with keys of this",
          "project's naming. It is not endorsed by the publisher.", ""]
    return "\n".join(w)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jsonmore-provenance", description=__doc__.split("\n\n")[0])
    ap.add_argument("family", choices=sorted(FAMILIES))
    ap.add_argument("source")
    ap.add_argument("checkout")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    src, gt = os.path.abspath(a.source), os.path.abspath(a.checkout)
    commit = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    out = genio.Output(gt, check=a.check)
    for fmt, title, files, main_file in packs(a.family, src):
        out.write("packs/%s/PROVENANCE.md" % fmt, text_for(a.family, fmt, title, files, main_file, src, commit))
    return out.report("jsonmore-provenance %s" % a.family)


if __name__ == "__main__":
    sys.exit(main())
