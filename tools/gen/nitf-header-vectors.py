#!/usr/bin/env python3
"""Write the vectors of the packs `nitf-file-header` and `nitf-image-subheader`.

The field order and sizes below are this script's own restatement of
MIL-STD-2500C (NITF 2.1, 01 May 2006; Distribution Statement A per ASSIST),
appendix A, table A-1 (file header, FHDR through NUMI) and table A-3 (image
subheader, IM through ICORDS, IGEOLO, NICOM). Every header is written for these
vectors from those tables; no example of the standard is copied. Expected text,
decoded values and the GeoJSON and CoT forms are worked out here by the rules of
spec/engine-spec.md 0.10 (column locators) and of those packs. It reads no
pack.def and calls no goat-transformers engine.

Inputs: none. The same run always gives the same bytes. With --check nothing is
written and the exit status is 1 when a committed file differs.

Usage: python3 -I tools/gen/nitf-header-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

# (field, size, i = BCS-N integer read as int, s = text)
FILE_HEADER = [("FHDR", 4, "s"), ("FVER", 5, "s"), ("CLEVEL", 2, "i"), ("STYPE", 4, "s"), ("OSTAID", 10, "s"),
               ("FDT", 14, "s"), ("FTITLE", 80, "s"), ("FSCLAS", 1, "s"), ("FSCLSY", 2, "s"), ("FSCODE", 11, "s"),
               ("FSCTLH", 2, "s"), ("FSREL", 20, "s"), ("FSDCTP", 2, "s"), ("FSDCDT", 8, "s"), ("FSDCXM", 4, "s"),
               ("FSDG", 1, "s"), ("FSDGDT", 8, "s"), ("FSCLTX", 43, "s"), ("FSCATP", 1, "s"), ("FSCAUT", 40, "s"),
               ("FSCRSN", 1, "s"), ("FSSRDT", 8, "s"), ("FSCTLN", 15, "s"), ("FSCOP", 5, "i"), ("FSCPYS", 5, "i"),
               ("ENCRYP", 1, "i"), ("FBKGC", 3, "s"), ("ONAME", 24, "s"), ("OPHONE", 18, "s"), ("FL", 12, "i"),
               ("HL", 6, "i"), ("NUMI", 3, "i")]
IMAGE_SUBHEADER = [("IM", 2, "s"), ("IID1", 10, "s"), ("IDATIM", 14, "s"), ("TGTID", 17, "s"), ("IID2", 80, "s"),
                   ("ISCLAS", 1, "s"), ("ISCLSY", 2, "s"), ("ISCODE", 11, "s"), ("ISCTLH", 2, "s"),
                   ("ISREL", 20, "s"), ("ISDCTP", 2, "s"), ("ISDCDT", 8, "s"), ("ISDCXM", 4, "s"), ("ISDG", 1, "s"),
                   ("ISDGDT", 8, "s"), ("ISCLTX", 43, "s"), ("ISCATP", 1, "s"), ("ISCAUT", 40, "s"),
                   ("ISCRSN", 1, "s"), ("ISSRDT", 8, "s"), ("ISCTLN", 15, "s"), ("ENCRYP", 1, "i"),
                   ("ISORCE", 42, "s"), ("NROWS", 8, "i"), ("NCOLS", 8, "i"), ("PVTYPE", 3, "s"), ("IREP", 8, "s"),
                   ("ICAT", 8, "s"), ("ABPP", 2, "i"), ("PJUST", 1, "s"), ("ICORDS", 1, "s")]


def text(table, values):
    out = ""
    for name, size, kind in table:
        v = values.get(name, "")
        if kind == "i" and v != "":
            v = str(int(v)).zfill(size)
        assert len(v) <= size, (name, v)
        out += v.ljust(size)
    return out


def model(table, values, prefix):
    m = {}
    for name, size, kind in table:
        v = values.get(name, "").rstrip(" ")
        if kind == "i":
            v = v.lstrip(" ")
            if v:
                m["nitf.%s%s" % (prefix, name.lower())] = str(int(v))
        elif v:
            m["nitf.%s%s" % (prefix, name.lower())] = v
    return m


def num(x):
    if x == int(x):
        return str(int(x))
    r = repr(float(x))
    assert "e" not in r
    return r


REF = "MIL-STD-2500C appendix A, %s; header written by tools/gen/nitf-header-vectors.py"

FH = {"FHDR": "NITF", "FVER": "02.10", "CLEVEL": "3", "STYPE": "BF01", "OSTAID": "GTTEST", "FDT": "20261119081530",
      "FTITLE": "Example file for the goat-transformers vectors", "FSCLAS": "U", "FSCOP": "0", "FSCPYS": "0",
      "ENCRYP": "0", "FBKGC": "   ", "ONAME": "Example Originator", "OPHONE": "+1 555 0100", "FL": "1234567",
      "HL": "404", "NUMI": "1"}
IS = {"IM": "IM", "IID1": "IMG0000001", "IDATIM": "20261119081500", "TGTID": "", "IID2": "Example image",
      "ISCLAS": "U", "ENCRYP": "0", "ISORCE": "Example sensor", "NROWS": "1024", "NCOLS": "2048", "PVTYPE": "INT",
      "IREP": "MONO", "ICAT": "VIS", "ABPP": "8", "PJUST": "R"}


def vec(name, frm, to, inp, expect=None, error=None, model=None, ref=""):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = ref
    return v


def file_header_vectors():
    p = "nitf-file-header"
    out = []
    h = text(FILE_HEADER, FH)
    assert len(h) == 363
    m = {"@kind": "nitf-2-1"}
    m.update(model(FILE_HEADER, FH, "fh_"))
    out.append(vec("nitf-2-1-round-trip", p, p, h, h, model=m,
                   ref=REF % "table A-1, FHDR through NUMI (363 characters)"))
    ns = dict(FH, FHDR="NSIF", FVER="01.00")
    hn = text(FILE_HEADER, ns)
    out.append(vec("nsif-1-0-round-trip", p, p, hn, hn, model={"@kind": "nsif-1-0", "nitf.fh_fhdr": "NSIF"},
                   ref=REF % "table A-1; NSIF 1.0 has the NITF 2.1 header layout"))
    out.append(vec("rest-of-file-not-carried", p, p, h + "000" + "000000" * 0 + "IM" + "X" * 20, h,
                   model={"@kind": "nitf-2-1", "nitf.fh_numi": "1"},
                   ref=REF % "table A-1: the bytes after NUMI (the image segment lengths that NUMI counts, and "
                             "the rest of the file) are not mapped; encode writes FHDR through NUMI"))
    out.append(vec("nitf-2-0-is-no-kind", p, p, text(FILE_HEADER, dict(FH, FVER="02.00")), error="no-kind",
                   ref=REF % "FVER 02.00 is NITF 2.0 (MIL-STD-2500A), another layout"))
    bad = h[:h.index("   Example Originator")] + "\u0000\u0000\u0000" + h[h.index("Example Originator"):]
    assert len(bad) == 363
    out.append(vec("binary-background-colour-is-malformed", p, p, bad, error="malformed-wire",
                   ref="FBKGC 0x000000 (black), three unsigned binary bytes; the text wire accepts characters "
                       "0x20 to 0x7E only (engine-spec 0.10, Reading a record, step 2)"))
    out.append(vec("header-cut-short-reads-what-is-there", p, p, h[:200], h[:200].rstrip(" "),
                   model={"@kind": "nitf-2-1", "nitf.fh_ostaid": "GTTEST"},
                   ref="a header cut at 200 characters: the columns past the end are absent, so encode writes "
                       "the fields up to FSCLAS (engine-spec 0.10, Locators: a column the field does not reach)"))
    return p, out


def image_subheader_vectors():
    p = "nitf-image-subheader"
    out = []
    corners = ["+45.123-122.654", "+45.124-122.600", "+45.050-122.599", "+45.049-122.653"]
    geolo = "".join(corners)
    assert len(geolo) == 60
    d = text(IMAGE_SUBHEADER, dict(IS, ICORDS="D")) + geolo + "0"
    assert len(d) == 433
    m = {"@kind": "geo-decimal-degrees", "lat": "45.123", "lon": "-122.654", "nitf.is_igeolo": geolo,
         "nitf.is_nicom": "0"}
    m.update(model(IMAGE_SUBHEADER, dict(IS, ICORDS="D"), "is_"))
    out.append(vec("decimal-degrees-round-trip", p, p, d, d, model=m,
                   ref=REF % "table A-3, IM through ICORDS, IGEOLO with ICORDS D (+-dd.ddd+-ddd.ddd four times, "
                             "WGS 84 by default), NICOM; the first corner is image (0,0)"))
    out.append(vec("decimal-degrees-to-geojson", p, "geojson", d,
                   '{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.654,45.123]},"properties":{}}',
                   ref=REF % "the first IGEOLO corner as the point; geojson canonical form by hand"))
    out.append(vec("decimal-degrees-to-cot-xml", p, "cot-xml", d,
                   '<event version="2.0" type="a-u-X"><point lat="45.123" lon="-122.654" hae="9999999" '
                   'ce="9999999" le="9999999"/><detail/></event>',
                   ref=REF % "the first IGEOLO corner; cot-xml canonical form by hand from its pack"))
    short = ["+45.1  -122.6  "] * 4
    ds = text(IMAGE_SUBHEADER, dict(IS, ICORDS="D")) + "".join(short) + "0"
    out.append(vec("decimal-degrees-with-blank-digits", p, p, ds, ds,
                   model={"@kind": "geo-decimal-degrees", "lat": "45.1", "lon": "-122.6"},
                   ref=REF % "digits beyond the known precision are spaces (table A-3, IGEOLO); the column's "
                             "spaces are removed before the number is read"))
    g = text(IMAGE_SUBHEADER, dict(IS, ICORDS="G")) + "451230N1223914W451230N1223600W450300N1223554W450256N1223912W" + "1"
    out.append(vec("geographic-dms-is-text-only", p, p, g, g,
                   model={"@kind": "geo-other", "nitf.is_icords": "G", "nitf.is_nicom": "1"},
                   ref=REF % "ICORDS G: ddmmssXdddmmssY four times; no text transform reads degrees, minutes and "
                             "seconds, so IGEOLO stays text and no position is bound"))
    n = text(IMAGE_SUBHEADER, dict(IS, ICORDS="")) + "0"
    out.append(vec("no-coordinates", p, p, n, n, model={"@kind": "no-location", "nitf.is_nicom": "0"},
                   ref=REF % "ICORDS a space: IGEOLO is omitted and NICOM follows ICORDS"))
    out.append({"name": "geojson-to-image-subheader-is-no-kind", "from": "geojson", "to": p,
                "input": '{"type":"Feature","geometry":{"type":"Point","coordinates":[1,2]},"properties":{}}',
                "expect_error": "no-kind", "source": "constructed",
                "reference": "every kind requires a raw key of the subheader; the text transforms write no + "
                             "sign, so a position from another format is not written into IGEOLO"})
    out.append(vec("not-an-image-subheader", p, p, "GS" + d[2:], error="no-kind",
                   ref="file part type GS (a graphic subheader), not IM"))
    return p, out


def build(out):
    written = {}
    for make in (file_header_vectors, image_subheader_vectors):
        pack, vecs = make()
        names = {}
        for i, v in enumerate(vecs, 1):
            if v["from"] == pack:
                rel = "packs/%s/vectors/%02d-%s.json" % (pack, i, v["name"])
            else:
                rel = "packs/%s/vectors/to-%s-%s.json" % (v["from"], pack, v["name"])
            names.setdefault(rel.rsplit("/", 1)[0], set()).add(rel.rsplit("/", 1)[1])
            out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        for d, keep in names.items():
            prefix = "" if d.endswith(pack + "/vectors") else "to-%s-" % pack
            for old in out.listdir(d):
                if old.startswith(prefix) and old.endswith(".json") and old not in keep:
                    out.remove(d + "/" + old)
        written[pack] = len(vecs)
    return written


def main(argv=None):
    return genio.vector_main("nitf-header-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
