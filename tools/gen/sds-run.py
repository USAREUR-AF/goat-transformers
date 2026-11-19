#!/usr/bin/env python3
"""sds-run: regenerate the Space Data Standards packs, one pack per standard.

Usage: python3 -I tools/gen/sds-run.py [--check] <checkout of spacedatastandards.org> <goat-transformers checkout>

`tools/gen/sds-run.sh` is the usual way in: it checks the commit and every SHA-256 first.
This script checks them again, so it can be run alone.

<checkout of spacedatastandards.org> is a git checkout of
https://github.com/DigitalArsenal/spacedatastandards.org at COMMIT (checked). A sparse
checkout of `LICENSE`, `NOTICE` and `lib/fbjson/*/main.fb.schema.json` is enough.
`tools/gen/sources/sds-sha256.txt` lists those files with their SHA-256 (checked
before any is read). For every standard listed there (`lib/fbjson/<NAME>/`) and not in SKIPPED, this
runs tools/gen/jsonschema2pack.py on the standard's `main.fb.schema.json` alone,
with its root table (`#/definitions/<NAME>`) as the message, and writes
packs/sds-<name>/ (pack.def, pack.md, vectors, PROVENANCE.md),
model/sds<name>.def and tools/gen/names/sds-<name>.json.

Form: the JSON form of each standard, the shape its JSON Schema (draft 2019-09)
describes. Wire `json`. The `x-flatbuffer-*` annotations of the schemas are not read
by the generator; the FlatBuffers binary form is not carried.

With --check nothing is written: every run compares what it would write with the
checkout, all runs are made, and the exit status is 1 when any file differs.
Python 3 standard library only.
"""
import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio              # noqa: E402  (the directory of this file is put on the path above)
import jsonschema2pack    # noqa: E402

REPO_URL = "https://github.com/DigitalArsenal/spacedatastandards.org"
COMMIT = "0a61c131bc8a849360a0bba57855cc6dd8dde70a"
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources", "sds-sha256.txt")

# The member of the root table bound to `uid`, and only where the schema's own
# description of that member states it identifies the record or the object the
# record is about: `ID` described as an identifier of the record; `OBJECT_ID`
# described as the international designator (or the identifier) of the one object
# the message is about; `UID`, `ENTITY_ID` described as the identifier of the event
# or entity; in TMS, a state of a track, `TRACK_ID`, described as held constant over
# every state of one track. The description is quoted in each pack.md. Every other
# standard: none.
UID = {
    "ACM": "OBJECT_ID", "ANI": "ID", "ATD": "ID", "AVL": "ID", "BEM": "ID", "BUS": "ID",
    "CAT": "OBJECT_ID", "CMS": "ID", "CNP": "ID", "COA": "ID", "COT": "UID", "CRM": "ID",
    "CSO": "ID", "DCL": "ID", "DFH": "ID", "DOA": "ID", "EOO": "ID", "ETM": "ENTITY_ID",
    "GDI": "ID", "GEO": "ID", "GNO": "ID", "GNP": "ID", "IDM": "ID", "ION": "ID", "IQC": "ID",
    "IRO": "ID", "LDM": "ID", "LKS": "ID", "LND": "ID", "LNE": "ID", "MNF": "ID", "MNV": "ID",
    "MPE": "ENTITY_ID", "MPL": "ID", "MST": "ID", "MTI": "ID", "OBD": "ID", "OBT": "ID",
    "OMM": "OBJECT_ID", "OOA": "ID", "OOB": "ID", "OOE": "ID", "OOI": "ID", "OOS": "ID",
    "OOT": "ID", "OPP": "ID", "OSM": "OBJECT_ID", "RDM": "OBJECT_ID", "RDO": "ID", "RFB": "ID",
    "RFE": "ID", "RFO": "ID", "SAR": "ID", "SEN": "ID", "SEO": "ID", "SIT": "ID", "SKI": "ID",
    "SOI": "ID", "SSY": "ID", "STR": "ID", "STX": "ID", "SWR": "ID", "TBP": "ID", "TBS": "ID",
    "TFN": "ID", "TMS": "TRACK_ID", "TRK": "ID", "TXS": "ID", "VEP": "ID", "WTH": "ID",
}

# Geodetic positions (and, in TMS, the ground speed in metres per second and the course
# over ground in degrees true), bound only where the schema states WGS 84 for the member or, for
# latitude and longitude stated as geodetic, for the altitude beside them in the same
# table; `hae` only where the height is stated in metres above the WGS 84 ellipsoid.
# The description is quoted in each pack.md. Orbital states are not positions here.
POSITION = {
    "GNO": ["LATITUDE=lat", "LONGITUDE=lon"],
    "GNP": ["LATITUDE=lat", "LONGITUDE=lon"],
    "SEN": ["LATITUDE=lat", "LONGITUDE=lon"],
    "TMS": ["LATITUDE=lat", "LONGITUDE=lon", "ALTITUDE_M=hae",
            "GROUND_SPEED_MPS=speed_ms", "COURSE_DEG=course"],
}

# Not generated, though listed in the manifest. Listed so the skip is a decision.
#   XTC  restates XTCE 1.2 (OMG and CCSDS 660.0-B-2), a telemetry and command database,
#        not a message. This project does not build XTCE: the OMG document notice
#        restricts reuse (docs/coverage-roadmap.md). A person decides whether the
#        Apache-2.0 restatement changes that.
#   REC  a collection whose records are a union of every other standard: its keys
#        repeat the other packs (19,000 keys, 12.7 MB at depth 8).
SKIPPED = {"XTC": "restates XTCE; not built, see docs/coverage-roadmap.md",
           "REC": "a union of every other standard; repeats their packs"}

# Size limits. A standard whose pack, module and names file come to more than 1 MB at
# the generator's default depth (8) gets the deepest --max-depth at which they stay
# within 1 MB. NAME: (depth, MB at depth 8). pack.md states the limit and the reason,
# and lists every place it cuts under Not mapped.
DEPTH = {"SCC": (5, 9.5), "CQR": (4, 6.2), "SCN": (4, 4.2), "LAM": (4, 1.9), "REM": (5, 1.5)}

# Conversion vectors from the hand-written geojson vector (its `id` is `uid`).
CROSS = {"GNP", "OMM", "SEN", "TMS"}

LICENSE_STATEMENT = (
    "The repository's `README.md`, section License: \"Copyright 2026 Edgesource Corporation. "
    "This project is licensed under the Apache License, Version 2.0.\" Its `NOTICE` begins: "
    "\"Space Data Standards. Copyright 2026 Edgesource Corporation. Licensed under the Apache "
    "License 2.0.\" and states that every file of the repository is covered by the License except "
    "the third-party components it lists; `lib/fbjson/` is not among them. `LICENSE` is the text "
    "of the Apache License, Version 2.0, January 2004.")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_manifest(path=None):
    """[(relative path, sha256)] in file order."""
    rows = []
    with open(path or MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                h, rel = line.split(None, 1)
                rows.append((rel.strip(), h))
    return rows


def standards(rows):
    """[(NAME, relative schema path, sha256)] of the manifest's schema files."""
    out = []
    for rel, h in rows:
        parts = rel.split("/")
        if len(parts) == 4 and parts[:2] == ["lib", "fbjson"] and parts[3] == "main.fb.schema.json":
            out.append((parts[2], rel, h))
    return out


def title_of(src, name, rel):
    with open(os.path.join(src, rel), encoding="utf-8") as fh:
        d = json.load(fh)
    desc = ((d.get("definitions") or {}).get(name) or {}).get("description") or ""
    first = desc.split("\n")[0].split(". ")[0].strip().rstrip(".")
    if not first or len(first) > 100 or any(c in first for c in "`|\""):
        return "Space Data Standards %s (JSON form)" % name
    return "Space Data Standards %s: %s (JSON form)" % (name, first)


def provenance(name, rel, h, fmt, rows):
    lic = dict(rows)
    out = ["# Provenance of the %s pack\n" % fmt,
           "`tools/gen/sds-run.sh` runs `tools/gen/jsonschema2pack.py` on the standard's",
           "`main.fb.schema.json` and nothing else. The file is not kept in this repository.",
           "Read on 2026-11-19.\n",
           "| | |\n|---|---|",
           "| Document | Space Data Standards, standard `%s`, JSON Schema (draft 2019-09) |" % name,
           "| Publisher | Edgesource Corporation (spacedatastandards.org) |",
           "| Repository | %s at commit `%s` |" % (REPO_URL, COMMIT),
           "| Download | `https://raw.githubusercontent.com/DigitalArsenal/spacedatastandards.org/%s/%s` |"
           % (COMMIT, rel), "",
           "| File | SHA-256 | Read by the generator |\n|---|---|---|",
           "| `%s` | `%s` | yes |" % (rel, h),
           "| `LICENSE` | `%s` | no |" % lic["LICENSE"],
           "| `NOTICE` | `%s` | no |" % lic["NOTICE"],
           "", "## License\n", "Apache-2.0. " + LICENSE_STATEMENT, "",
           "Attribution: the pack is derived from the Space Data Standards schema `%s`; it restates the "
           "schema's structure with keys of this project's naming and is not endorsed by the publisher." % name,
           ""]
    return "\n".join(out)


def git_head(path):
    return subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sds-run", description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="the checkout of spacedatastandards.org")
    ap.add_argument("checkout", help="the goat-transformers checkout to write into")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; compare every pack, module, names file and PROVENANCE.md "
                         "with the checkout and exit 1 when any file differs")
    ap.add_argument("--only", metavar="NAME,...",
                    help="run only these standards (names as in lib/fbjson/); the others are not "
                         "written or compared")
    ap.add_argument("--manifest", default=MANIFEST, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    src, gt = os.path.abspath(args.source), os.path.abspath(args.checkout)
    gen = os.path.join(gt, "tools", "gen")
    got = git_head(src)
    if got != COMMIT:
        print("sds-run: %s is at %s, not %s" % (src, got, COMMIT), file=sys.stderr)
        return 1
    rows = read_manifest(args.manifest)
    for rel, h in rows:
        p = os.path.join(src, rel)
        if not os.path.isfile(p) or sha256(p) != h:
            print("sds-run: %s: missing or SHA-256 is not %s" % (rel, h), file=sys.stderr)
            return 1
    out = genio.Output(gt, check=args.check)
    status = 0
    only = set(args.only.split(",")) if args.only else None
    todo = [s for s in standards(rows) if (only is None or s[0] in only) and s[0] not in SKIPPED]
    if only is not None and len(todo) != len(only):
        print("sds-run: --only names a standard the manifest does not list or SKIPPED holds: %s"
              % ", ".join(sorted(only - {s[0] for s in todo})), file=sys.stderr)
        return 2
    for name, rel, h in todo:
        low = name.lower()
        fmt, module = "sds-" + low, "sds" + low
        schema = os.path.join(src, rel)
        argv2 = ["--schema", schema, "--message", "%s=%s#/definitions/%s" % (name, schema, name),
                 "--format", fmt, "--module", module, "--title", title_of(src, name, rel),
                 "--license", "Apache-2.0, Edgesource Corporation (DigitalArsenal/spacedatastandards.org)",
                 "--source", "%s at commit %s, %s" % (REPO_URL, COMMIT, rel),
                 "--out", gt, "--model-dir", os.path.join(gt, "model"),
                 "--names-file", os.path.join(gen, "names", fmt + ".json"),
                 "--notes-file", os.path.join(gen, "notes", "sds.md")]
        if name in UID:
            argv2 += ["--map", "%s:%s=uid" % (name, UID[name])]
        for m in POSITION.get(name, []):
            argv2 += ["--map", "%s:%s" % (name, m)]
        if name in CROSS:
            argv2 += ["--cross", "%s=%s:input" % (os.path.join(gt, "packs", "geojson", "pack.def"),
                                                 os.path.join(gt, "packs", "geojson", "vectors",
                                                              "01-geojson-to-cot.json"))]
        if name in DEPTH:
            d, mb = DEPTH[name]
            argv2 += ["--max-depth", str(d), "--limit-reason",
                      "set so that the pack, its module and its names file stay within 1 MB; at the "
                      "default depth 8 they come to %.1f MB" % mb]
        if args.check:
            argv2.append("--check")
        # the generator in this process: its summary goes to /dev/null, its report to stderr
        with open(os.devnull, "w") as null, contextlib.redirect_stdout(null):
            run = jsonschema2pack.main(argv2)
        if run:
            status = 1
            if not args.check:
                print("sds-run: %s failed" % fmt, file=sys.stderr)
                return 1
        out.write("packs/%s/PROVENANCE.md" % fmt, provenance(name, rel, h, fmt, rows))
        if not args.check:
            print(fmt)
    return max(status, out.report("sds-run (PROVENANCE.md)"))


if __name__ == "__main__":
    sys.exit(main())
