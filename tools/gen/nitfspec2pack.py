#!/usr/bin/env python3
"""nitfspec2pack: one `text`-wire pack per flat NITF TRE, from GDAL's nitf_spec.xml.

Python 3 standard library only. Reads GDAL's description of the NITF Tagged
Record Extensions (frmts/nitf/data/nitf_spec.xml, MIT) and writes, for every TRE
whose content is a fixed sequence of fixed-width fields:

  <out>/model/nitftre.def                         one raw key per TRE field
  <out>/packs/nitf-tre-<tre>/pack.def             the pack: `wire text`, `delimiter none`,
                                                  one column locator per field
  <out>/packs/nitf-tre-<tre>/pack.md              what is mapped, and the TREs not built
  <out>/packs/nitf-tre-<tre>/PROVENANCE.md        the source, its SHA-256 and terms
  <out>/packs/nitf-tre-<tre>/vectors/gen-*.json   a round trip, and for BLOCKA the shared keys

A TRE is flat when every element is a `field`, or a `loop` with a fixed
`iterations` count holding only fields (unrolled, numbered from 01). A TRE with
a `loop` whose count is read from the data, an `if`, an `if_remaining_bytes`,
an `rpf_component`, a `length_var` or a binary field type is not built; pack.md
lists each with the construct it needs.

A message of a pack is the TRE's CEDATA: the bytes after the 6-character tag and
the 5-digit length. The vectors are computed by this program's own column codec
and decoder; no engine is run. After writing, the output is loaded with
gtcheck.py, the loader written from the specification.

Usage: python3 -I tools/gen/nitfspec2pack.py --spec nitf_spec.xml --out DIR
           [--check] [--tre NAME ...] [--spec-commit SHA] [--core-def FILE]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

GDAL_URL = "https://github.com/OSGeo/gdal"
SPEC_PATH = "frmts/nitf/data/nitf_spec.xml"
MODULE = "nitftre"
BINARY_TYPES = {"UnsignedInt_BigEndian"}

# Shared keys a TRE binds, by evidence (pack.md of the TRE states it). BLOCKA
# repeats the IGEOLO corners of the image subheader at higher precision (GDAL
# frmts/nitf/nitfimage.c, "According to the BLOCKA specification, it repeats
# earth coordinates image corner locations described by IGEOLO"), and the
# default geodetic reference of IGEOLO is WGS 84 (MIL-STD-2500C, ICORDS). The
# corner FRFC (first row, first column) is image coordinate (0,0), IGEOLO's
# first corner. Its decimal form is +-dd.dddddd+-ddd.dddddd; the degrees,
# minutes and seconds form is not read by any text transform.
BIND = {"BLOCKA": {"field": "FRFC_LOC", "lat": (0, 10), "lon": (10, 11)}}


class GenError(Exception):
    pass


def snake(name):
    return name.strip().lower().replace(" ", "_").replace("-", "_")


class Field:
    def __init__(self, name, offset, length, kind, fixed, unit, gdal_type):
        self.name, self.offset, self.length = name, offset, length
        self.kind = kind            # "int" or "string"
        self.fixed, self.unit, self.gdal_type = fixed, unit, gdal_type


def why_not_flat(tre):
    """The construct a TRE needs that a flat text pack cannot state, or None."""
    for el in tre.iter():
        if el is tre:
            continue
        if el.tag == "loop":
            if not el.get("iterations"):
                return "a repeat whose count is a decimal text field read earlier in the TRE (`loop counter`/`formula`)"
            if any(c.tag != "field" for c in el):
                return "a fixed repeat holding more than plain fields"
        elif el.tag == "if":
            return "a part present only when an earlier field holds a given value (`if cond`)"
        elif el.tag == "if_remaining_bytes":
            return "a part present only when bytes remain (`if_remaining_bytes`)"
        elif el.tag == "rpf_component":
            return "an RPF component located by offsets (`rpf_component`)"
        elif el.tag == "field":
            if el.get("length_var"):
                return "a field whose length is a decimal text field read earlier (`length_var`)"
            if el.get("type") in BINARY_TYPES:
                return "a binary integer field (%s): the text wire reads characters 0x20 to 0x7E only" % el.get("type")
            if not el.get("length"):
                return "a field with no stated length"
        elif el.tag not in ("loop",):
            return "an element `%s`" % el.tag
    return None


def fields_of(tre):
    out, offset = [], 0

    def add(el, name):
        nonlocal offset
        length = int(el.get("length"))
        gtype = el.get("type") or ""
        minval = el.get("minval")
        signed = minval is not None and minval.strip().startswith("-")
        kind = "int" if gtype == "integer" and not signed else "string"
        out.append(Field(name, offset, length, kind, el.get("fixed_value"), el.get("unit"), gtype))
        offset += length

    for el in tre:
        if el.tag == "field":
            name = el.get("name") or ""
            add(el, name if name else None)
        elif el.tag == "loop":
            base = el.get("name") or el.get("md_prefix", "ITEM").split("%")[0].rstrip("_")
            for i in range(1, int(el.get("iterations")) + 1):
                for f in el:
                    inner = f.get("name") or ""
                    add(f, "%s_%02d%s" % (base, i, ("_" + inner) if inner else ""))
    for f in out:
        if f.name is None:
            f.name = "RESERVED_%d" % f.offset
    names = [f.name for f in out]
    if len(set(names)) != len(names):
        raise GenError("%s: two fields with one name" % tre.get("name"))
    stated = tre.get("length")
    if stated and int(stated) != offset:
        raise GenError("%s: fields add up to %d, the TRE states %s" % (tre.get("name"), offset, stated))
    return out, offset


def const_ok(value):
    return value and value.strip() == value and all(0x20 <= ord(c) <= 0x7E for c in value)


def key_of(tre, f):
    return "%s.%s_%s" % (MODULE, snake(tre), snake(f.name))


# ---- the vectors' own codec -------------------------------------------------

def sample(tre_name, i, f):
    """A value for field i, written for the vectors: digits for an integer field,
    letters and digits for the others; never ending in a space."""
    if f.fixed is not None:
        return f.fixed
    if f.kind == "int":
        n = (37 * (i + 1) + len(tre_name)) % (10 ** min(f.length, 9)) or 1
        return str(n).zfill(f.length)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(alphabet[(i * 7 + j * 3) % len(alphabet)] for j in range(f.length))


def record(fields, values):
    return "".join(values[f.name].ljust(f.length)[:f.length] for f in fields)


def decoded(tre, fields, text):
    """Model values as the text wire reads each column (engine-spec 0.10, Locators)."""
    m = {}
    for f in fields:
        col = text[f.offset:f.offset + f.length].rstrip(" ")
        if f.fixed is not None and f.name.startswith("RESERVED_"):
            continue
        if f.kind == "int":
            col = col.lstrip(" ")
            if col:
                m[key_of(tre, f)] = str(int(col))
        elif col:
            m[key_of(tre, f)] = col
    return m


def plain(x):
    if x == int(x):
        return str(int(x))
    r = repr(x)
    assert "e" not in r
    return r


# ---- writing ----------------------------------------------------------------

def pack_text(tre, fields, total, sources):
    name = tre.lower()
    lines = ["# NITF TRE %s: the CEDATA of the extension, %d characters. Public." % (tre, total),
             "# GENERATED by tools/gen/nitfspec2pack.py from GDAL's nitf_spec.xml; edit the generator,",
             "# not this file. pack.md states what is mapped and what is not.",
             "format        nitf-tre-%s" % name, "version       0.1.0", "distribution  public"]
    lines += ["source        %s" % json.dumps(s) for s in sources]
    lines += ["uses          %s" % MODULE, "wire          text", "delimiter     none", ""]
    bind = BIND.get(tre)
    for f in fields:
        loc = "0:%d:%d" % (f.offset, f.length)
        if f.name.startswith("RESERVED_") and f.fixed is not None:
            if const_ok(f.fixed):
                lines.append("const     %-12s %s" % (loc, f.fixed))
            continue
        lines.append("field     %-44s %-12s %s" % (key_of(tre, f), loc, "int" if f.kind == "int" else "string"))
    if bind:
        f = next(x for x in fields if x.name == bind["field"])
        sign = "0:%d:1" % f.offset
        lat = "0:%d:%d" % (f.offset + bind["lat"][0], bind["lat"][1])
        lon = "0:%d:%d" % (f.offset + bind["lon"][0], bind["lon"][1])
        req = key_of(tre, f)
        lines += ["",
                  "# %s in decimal degrees (+-dd.dddddd+-ddd.dddddd) gives lat and lon. The raw" % bind["field"],
                  "# key above is written first on encode, so the field keeps its own text.",
                  "kind      %s-decimal-north" % snake(bind["field"]).replace("_", "-"),
                  "when      %s  +" % sign, "requires  %s" % req,
                  "field     lat  %s  float" % lat, "field     lon  %s  float" % lon, "",
                  "kind      %s-decimal-south" % snake(bind["field"]).replace("_", "-"),
                  "when      %s  -" % sign, "requires  %s" % req,
                  "field     lat  %s  float" % lat, "field     lon  %s  float" % lon, "",
                  "kind      %s-other" % snake(bind["field"]).replace("_", "-"),
                  "requires  %s" % req]
    return "\n".join(lines) + "\n"


def module_text(built, sources):
    lines = ["# The %s module: the fields of NITF Tagged Record Extensions, one raw key per" % MODULE,
             "# TRE field, named <tre>_<field>. GENERATED by tools/gen/nitfspec2pack.py from",
             "# GDAL's nitf_spec.xml; edit the generator, not this file.",
             "module        %s" % MODULE, "version       0.1.0", "distribution  public"]
    lines += ["source        %s" % json.dumps(s) for s in sources]
    for tre, fields, _total in built:
        lines.append("# %s" % tre)
        for f in fields:
            if f.name.startswith("RESERVED_") and f.fixed is not None:
                continue
            what = "%s field %s, %d characters at offset %d of the CEDATA" % (tre, f.name, f.length, f.offset)
            if f.unit:
                what += ", %s" % f.unit
            if f.gdal_type:
                what += ", %s" % f.gdal_type
            lines.append('key  %-48s %-6s -  %s' % (key_of(tre, f).split(".", 1)[1], f.kind, json.dumps(what)))
    return "\n".join(lines) + "\n"


def pack_md(tre, fields, total, skipped, spec_sha, commit):
    rows = "\n".join("| %d | %d | `%s` | %s | %s |" % (
        f.offset, f.length, f.name, "`const %s`" % f.fixed if (f.name.startswith("RESERVED_") and f.fixed is not None)
        else "`%s` (`%s`)" % (key_of(tre, f), "int" if f.kind == "int" else "string"), f.gdal_type or "")
        for f in fields)
    bind = BIND.get(tre)
    shared = "None. Every field is a raw key of `%s`." % MODULE
    if bind:
        shared = ("`lat` and `lon` from `%s` (first row, first column: the image corner (0,0), the first corner of the "
                  "image subheader's IGEOLO), only in its decimal form `+-dd.dddddd+-ddd.dddddd`, selected by the "
                  "kinds on its first character (`+` or `-`); in the degrees-minutes-seconds form the kind `%s-other` "
                  "binds nothing. Evidence: GDAL `frmts/nitf/nitfimage.c` states that BLOCKA repeats the IGEOLO corner "
                  "locations at higher precision, and MIL-STD-2500C gives WGS 84 as the default geodetic reference "
                  "of IGEOLO (ICORDS). The other three corners are raw keys: the model has one position. The kinds "
                  "require the raw key, so an entity from another format selects none (`no-kind`): the text "
                  "transforms write no `+`, and the raw key keeps the field's text on a same-format round trip."
                  % (bind["field"], snake(bind["field"]).replace("_", "-")))
    not_built = "\n".join("| %s | %s |" % (n, why) for n, why in skipped)
    return """# Pack: nitf-tre-%(lo)s

The NITF Tagged Record Extension %(tre)s: its CEDATA, %(total)d characters of fixed
width fields. Public. Generated by `tools/gen/nitfspec2pack.py` from GDAL's
`%(path)s` (MIT, commit `%(commit)s`, sha256 `%(sha)s`).
Wire `text` with `delimiter none`: the CEDATA is one field, and each TRE field
is a column `0:<offset>:<length>`. Needs engine version 0.10.

## Message convention

A message is the CEDATA only: the bytes after the 6-character tag (CETAG) and
the 5-digit length (CEL) in the extension area of a NITF header or subheader.
Finding a TRE in that area needs the tag and length of each extension read in
turn, which the pack language cannot state (see the file header pack).

The `text` wire accepts characters 0x20 to 0x7E only. A column's trailing
spaces are removed on decode, and for `int` its leading spaces too; a column
that is then empty is absent, and encode writes spaces there. An `int` column
is written zero-padded to its width. A TRE whose last fields are blank is
written without those trailing spaces.

## Fields

| Offset | Length | Field | Line | GDAL type |
|---|---|---|---|---|
%(rows)s

Integer fields with no negative range are `int`; every other field is a
`string` holding the text as written (real numbers in NITF carry signs,
exponents and fixed widths that no text transform writes back unchanged).
Fields GDAL lists without a name are `RESERVED_<offset>`; a reserved field
with a fixed non-blank value is a `const`.

## Shared keys

%(shared)s

## TREs not built

GDAL's file describes these TREs with constructs a flat text pack cannot state:

| TRE | Needs |
|---|---|
%(not_built)s

## Vectors

`vectors/gen-*.json`, computed by the generator's own column codec: a
round trip with every field filled%(extra)s.
""" % {"lo": tre.lower(), "tre": tre, "total": total, "path": SPEC_PATH, "commit": commit, "sha": spec_sha,
       "rows": rows, "shared": shared, "not_built": not_built,
       "extra": "; for the decimal FRFC corner a conversion to GeoJSON, a south-west corner, and the "
                "degrees-minutes-seconds form with no shared key" if bind else ""}


def provenance(tre, spec_sha, commit):
    return """# Provenance: nitf-tre-%(lo)s pack

Generated by `tools/gen/nitfspec2pack.py`. No source file is copied into this tree.

| | |
|---|---|
| Source | GDAL, `%(path)s` (and `nitf_spec.xsd`, its schema), %(url)s |
| Version | commit `%(commit)s` |
| SHA-256 | `%(sha)s` |
| License | the file's header: "Copyright (c) 2011, Even Rouault", "SPDX-License-Identifier: MIT" |

What is taken: the field names, lengths, order and GDAL type of TRE %(tre)s. GDAL
restates the TRE from STDI-0002 (its comments cite "STDI-0002-1-v5.0"). The TRE
definitions are published on the NSG registry; STDI-0002 itself was not read.

MIL-STD-2500C, read for the BLOCKA evidence and the NITF headers: Distribution
Statement A per the ASSIST listing, confirmed by the project maintainer on
2026-11-19. The copy read (the NGA NTB copy of 2500C.pdf, 01 May 2006, from the
Internet Archive, sha256
`f9bb6b8e816337e668285c9456750c079f919cc6097e3086f5ab0057c453a635`) carries no
distribution statement on its own cover.
""" % {"lo": tre.lower(), "tre": tre, "path": SPEC_PATH, "url": GDAL_URL, "commit": commit, "sha": spec_sha}


def vectors(tre, fields, total):
    name = "nitf-tre-" + tre.lower()
    values = {f.name: sample(tre, i, f) for i, f in enumerate(fields)}
    out = []
    bind = BIND.get(tre)
    if bind:
        f = next(x for x in fields if x.name == bind["field"])
        cases = [("decimal-north", "+45.123456-122.654321", (45.123456, -122.654321)),
                 ("decimal-south", "-33.856789+151.215123", (-33.856789, 151.215123)),
                 ("other", "453012.34N1223456.78W", None)]
        for label, text, pos in cases:
            values[f.name] = text
            rec = record(fields, values)
            m = {"@kind": "%s-%s" % (snake(bind["field"]).replace("_", "-"), label)}
            m.update(decoded(tre, fields, rec))
            if pos:
                m["lat"], m["lon"] = plain(pos[0]), plain(pos[1])
            out.append({"name": "%s-%s-round-trip" % (tre.lower(), label), "from": name, "to": name,
                        "input": rec, "expect": rec, "model": m, "source": "constructed",
                        "reference": "every field filled by tools/gen/nitfspec2pack.py; %s = %s" % (bind["field"], text)})
            if label == "decimal-north":
                gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{}}' % (
                    plain(pos[1]), plain(pos[0]))
                out.append({"name": "%s-to-geojson" % tre.lower(), "from": name, "to": "geojson", "input": rec,
                            "expect": gj, "source": "constructed",
                            "reference": "the FRFC corner in decimal degrees as the GeoJSON point; canonical form "
                                         "by hand (engine-spec 0.1.1 rulings 3 and 4)"})
        out.append({"name": "geojson-to-%s-is-no-kind" % tre.lower(), "from": "geojson", "to": name,
                    "input": '{"type":"Feature","geometry":{"type":"Point","coordinates":[1,2]},"properties":{}}',
                    "expect_error": "no-kind", "source": "constructed",
                    "reference": "every kind requires the raw corner key, which another format does not have"})
        return out
    rec = record(fields, values)
    assert len(rec) == total
    m = decoded(tre, fields, rec)
    out.append({"name": "%s-round-trip" % tre.lower(), "from": name, "to": name, "input": rec, "expect": rec,
                "model": m, "source": "constructed",
                "reference": "every field filled by tools/gen/nitfspec2pack.py with digits (int) or letters"})
    return out


def run(args):
    raw = open(args.spec, "rb").read()
    spec_sha = hashlib.sha256(raw).hexdigest()
    root = ET.fromstring(raw)
    tres = root.find("tres")
    if tres is None:
        raise GenError("%s: no <tres>" % args.spec)
    built, skipped = [], []
    wanted = set(args.tre) if args.tre else None
    for t in tres:
        name = t.get("name")
        why = why_not_flat(t)
        if why:
            skipped.append((name, why))
            continue
        if wanted is None or name in wanted:
            fields, total = fields_of(t)
            built.append((name, fields, total))
    if wanted:
        missing = wanted - {b[0] for b in built}
        if missing:
            raise GenError("not flat or not in the file: %s" % ", ".join(sorted(missing)))
    sources = ["GDAL %s at commit %s (MIT, Copyright (c) 2011 Even Rouault), sha256 %s: TRE field names, lengths "
               "and order" % (SPEC_PATH, args.spec_commit, spec_sha),
               "MIL-STD-2500C NITF 2.1 (Distribution Statement A per ASSIST): IGEOLO and its default WGS 84 "
               "reference, for the BLOCKA corner"]
    out = genio.Output(args.out, check=args.check)
    files = {"model/%s.def" % MODULE: module_text(built, sources)}
    for tre, fields, total in built:
        d = "packs/nitf-tre-%s" % tre.lower()
        files[d + "/pack.def"] = pack_text(tre, fields, total, sources[:1] + (sources[1:] if tre in BIND else []))
        files[d + "/pack.md"] = pack_md(tre, fields, total, skipped, spec_sha, args.spec_commit)
        files[d + "/PROVENANCE.md"] = provenance(tre, spec_sha, args.spec_commit)
        for i, v in enumerate(vectors(tre, fields, total), 1):
            # a vector lives in the pack that owns its input (spec/vector-format.md)
            if v["from"] == "nitf-tre-" + tre.lower():
                rel = "%s/vectors/gen-%02d-%s.json" % (d, i, v["name"])
            else:
                rel = "packs/%s/vectors/to-nitf-tre-%s-%s.json" % (v["from"], tre.lower(), v["name"])
            files[rel] = json.dumps(v, indent=2) + "\n"
    for rel, text in sorted(files.items()):
        out.write(rel, text)
    dirs = {"packs/nitf-tre-%s/vectors" % t.lower(): "gen-" for t, _f, _n in built}
    dirs.update({rel.rsplit("/", 1)[0]: "to-nitf-tre-" for rel in files if "/vectors/to-nitf-tre-" in rel})
    for d, prefix in sorted(dirs.items()):
        for old in out.listdir(d):
            if old.startswith(prefix) and "%s/%s" % (d, old) not in files:
                out.remove("%s/%s" % (d, old))
    # self-check: load what was written with the specification's load rules
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "model"))
        shutil.copy(args.core_def, os.path.join(tmp, "model", "core.def"))
        paths = []
        for rel, text in files.items():
            if rel.endswith(".def"):
                path = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                if rel.startswith("packs/"):
                    paths.append(path)
        gtcheck.check_output(os.path.join(tmp, "model"), sorted(paths))
    print("TREs built      %d" % len(built))
    print("TREs not built  %d" % len(skipped))
    print("self-check      ok")
    return out.report("nitfspec2pack")


def main(argv=None):
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, help="GDAL frmts/nitf/data/nitf_spec.xml")
    genio.add_arguments(ap, default_out=here)
    ap.add_argument("--tre", nargs="*", default=None, help="only these TREs (default: every flat one)")
    ap.add_argument("--spec-commit", default="fedfd3ec89d6674de030db8f351233f2ee164c30")
    ap.add_argument("--core-def", default=os.path.join(here, "model", "core.def"))
    args = ap.parse_args(argv)
    try:
        return run(args)
    except (GenError, gtcheck.CheckError) as e:
        print("nitfspec2pack: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
