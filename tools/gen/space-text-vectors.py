#!/usr/bin/env python3
"""Write the vectors of the hand-written space text packs: celestrak-gp-csv and tle.

celestrak-gp-csv reads one data row of CelesTrak's GP data in CSV form, with the columns
in the order of the header CelesTrak sends (OBJECT_NAME ... MEAN_MOTION_DDOT, 17 columns).
tle reads one line of a NORAD two-line element set, or the name line before it, at the
columns of CelesTrak's format page. This script holds its own copy of those layouts, builds
each input from values written for these vectors, and works out the decoded values and the
outputs by the rules of spec/engine-spec.md (0.10, the text wire; 0.5, the json wire) and
of those packs. It reads no pack.def and calls no goat-transformers engine.

Inputs: none; every value is stated in this file. The same run always gives the same bytes.
With --check nothing is written and the exit status is 1 when a committed file differs from
what this script writes.

Usage: python3 -I tools/gen/space-text-vectors.py [--out DIR] [--check]
"""
import decimal
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

GP_REF = ("CelesTrak GP data documentation (gp-data-formats.php, read 2026-11-21): the CSV form "
          "uses the OMM keywords; column order of the CSV header of 2026-11-21; %s")
TLE_REF = ("CelesTrak, NORAD Two-Line Element Set Format (tle-fmt.php, read 2026-11-21): %s; "
           "line written by tools/gen/space-text-vectors.py")

# --------------------------------------------------------------------------
# numbers as the engines write them
# --------------------------------------------------------------------------

def num(x):
    """A float as `float` writes it: shortest round-trip decimal, plain notation
    (engine-spec 0.1.1 ruling 3; 0.5 for json)."""
    x = float(x)
    if x == int(x) and abs(x) < 2 ** 53:
        return str(int(x))
    r = repr(x)
    if "e" in r or "E" in r:
        r = format(decimal.Decimal(r), "f")
    return r


def round_half_away(v):
    return math.floor(v + 0.5) if v >= 0 else -math.floor(-v + 0.5)


def dec(x, f, w=None):
    """`dec:<f>` and `dec:<f>:<w>` encode (engine-spec 0.10)."""
    n = round_half_away(x * float(10 ** f))
    digits = str(abs(n)).rjust(f + 1, "0")
    text = digits[:-f] + "." + digits[-f:] if f else digits
    if w is not None:
        text = text.rjust(w, "0")
    return ("-" if n < 0 else "") + text


def column_num(text, length):
    """A numeric column: padded on the left with 0 after any `-` (engine-spec 0.10,
    Writing a record, step 2)."""
    sign = "-" if text.startswith("-") else ""
    body = text[len(sign):]
    out = sign + body.rjust(length - len(sign), "0")
    assert len(out) == length, (text, length)
    return out


def column_str(text, length):
    assert len(text) <= length
    return text.ljust(length)


# --------------------------------------------------------------------------
# celestrak-gp-csv
# --------------------------------------------------------------------------

# (column name, ckgp or ckgpcsv key, type: s string, f float, i int)
GP_COLS = [
    ("OBJECT_NAME", "ckgp.object_name", "s"),
    ("OBJECT_ID", "ckgp.object_id", "s"),
    ("EPOCH", "ckgp.epoch", "s"),
    ("MEAN_MOTION", "ckgp.mean_motion", "f"),
    ("ECCENTRICITY", "ckgp.eccentricity", "f"),
    ("INCLINATION", "ckgp.inclination", "f"),
    ("RA_OF_ASC_NODE", "ckgp.ra_of_asc_node", "f"),
    ("ARG_OF_PERICENTER", "ckgp.arg_of_pericenter", "f"),
    ("MEAN_ANOMALY", "ckgp.mean_anomaly", "f"),
    ("EPHEMERIS_TYPE", "ckgp.ephemeris_type", "i"),
    ("CLASSIFICATION_TYPE", "ckgp.classification_type", "s"),
    ("NORAD_CAT_ID", "ckgp.norad_cat_id", "i"),
    ("ELEMENT_SET_NO", "ckgp.element_set_no", "i"),
    ("REV_AT_EPOCH", "ckgp.rev_at_epoch", "i"),
    ("BSTAR", "ckgpcsv.bstar_text", "s"),
    ("MEAN_MOTION_DOT", "ckgpcsv.mean_motion_dot_text", "s"),
    ("MEAN_MOTION_DDOT", "ckgpcsv.mean_motion_ddot_text", "s"),
]
# the order of the celestrak-gp-json pack's field lines (its JSON members), with the key
JSON_ORDER = ["OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION",
              "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "EPHEMERIS_TYPE",
              "CLASSIFICATION_TYPE", "NORAD_CAT_ID", "ELEMENT_SET_NO", "REV_AT_EPOCH", "BSTAR",
              "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT"]


def gp_row(values):
    return ",".join(values.get(c, "") for c, _, _ in GP_COLS)


def gp_decode(values):
    """The model of a row: every non-empty column by its key; OBJECT_ID also as uid."""
    m = {}
    for c, key, t in GP_COLS:
        text = values.get(c, "")
        if text == "":
            continue
        m[key] = text if t == "s" else num(float(text)) if t == "f" else str(int(text))
        if c == "OBJECT_ID":
            m["uid"] = text
    return m


def gp_encode(model):
    """A row from a model: each column's key as its transform writes it; empty when
    absent; all 17 fields (no line is optional)."""
    out = []
    for c, key, t in GP_COLS:
        v = model.get(key)
        if v is None and c == "OBJECT_ID":
            v = model.get("uid")
        out.append("" if v is None else v)
    return ",".join(out)


def gp_to_json(model):
    """The celestrak-gp-json form of a model: members in that pack's line order; strings
    as JSON strings, numbers as `float` and `int` write them; ckgpcsv keys are not keys of
    that pack."""
    types = {c: t for c, _, t in GP_COLS}
    keys = {c: k for c, k, _ in GP_COLS}
    parts = []
    for c in JSON_ORDER:
        k = keys[c]
        if not k.startswith("ckgp."):
            continue
        v = model.get(k)
        if v is None and c == "OBJECT_ID":
            v = model.get("uid")
        if v is None:
            continue
        parts.append(json.dumps(c) + ":" + (json.dumps(v) if types[c] == "s" else v))
    return "{" + ",".join(parts) + "}"


def gp_vectors():
    base = {"OBJECT_NAME": "TESTSAT 1", "OBJECT_ID": "2026-123A", "EPOCH": "2026-05-03T04:05:06.789012",
            "MEAN_MOTION": "15.5", "ECCENTRICITY": ".0001234", "INCLINATION": "51.5",
            "RA_OF_ASC_NODE": "120.25", "ARG_OF_PERICENTER": "90.125", "MEAN_ANOMALY": "270.5",
            "EPHEMERIS_TYPE": "0", "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": "70001",
            "ELEMENT_SET_NO": "999", "REV_AT_EPOCH": "1234", "BSTAR": ".12345E-3",
            "MEAN_MOTION_DOT": ".5E-5", "MEAN_MOTION_DDOT": "0"}
    m = gp_decode(base)
    v = [{
        "name": "row-round-trip", "from": "celestrak-gp-csv", "to": "celestrak-gp-csv",
        "input": gp_row(base), "expect": gp_encode(m), "model": m, "source": "constructed",
        "reference": GP_REF % ("a float column is rewritten as `float` writes it (the leading 0 of "
                               ".0001234 appears); the exponent-notation columns are strings and keep their text"),
    }]
    analyst = dict(base, OBJECT_NAME="", OBJECT_ID="", NORAD_CAT_ID="270001")
    m2 = gp_decode(analyst)
    v.append({
        "name": "row-without-designator", "from": "celestrak-gp-csv", "to": "celestrak-gp-csv",
        "input": gp_row(analyst), "expect": gp_encode(m2), "model": m2, "source": "constructed",
        "reference": GP_REF % ("an object of the analyst range has no name and no international designator; "
                               "the empty columns are absent, so uid is absent, and are written empty"),
    })
    v.append({
        "name": "header-row-is-not-a-message", "from": "celestrak-gp-csv", "to": "celestrak-gp-csv",
        "input": ",".join(c for c, _, _ in GP_COLS), "expect_error": "transform-decode",
        "source": "constructed",
        "reference": GP_REF % "the header row holds the column names, and MEAN_MOTION is not a decimal number",
    })
    v.append({
        "name": "row-to-celestrak-gp-json", "from": "celestrak-gp-csv", "to": "celestrak-gp-json",
        "input": gp_row(base), "expect": gp_to_json(m), "source": "constructed",
        "reference": GP_REF % ("the ckgp keys are those of celestrak-gp-json and carry over; BSTAR, "
                               "MEAN_MOTION_DOT and MEAN_MOTION_DDOT are text keys of ckgpcsv here and "
                               "are not written"),
    })
    quoted = dict(base, OBJECT_NAME='"TESTSAT, 1"')
    v.append({
        "name": "quoted-comma-shifts-columns", "from": "celestrak-gp-csv", "to": "celestrak-gp-csv",
        "input": gp_row(quoted), "expect_error": "transform-decode", "source": "constructed",
        "reference": GP_REF % ("the text wire has no quoting: the comma inside the quotation marks splits "
                               "the name, every later column moves one place, and the EPOCH text reaches "
                               "the MEAN_MOTION column"),
    })
    accented = dict(base, OBJECT_NAME="TESTSAT É")
    v.append({
        "name": "non-ascii-name", "from": "celestrak-gp-csv", "to": "celestrak-gp-csv",
        "input": gp_row(accented), "expect_error": "malformed-wire", "source": "constructed",
        "reference": GP_REF % "the text wire accepts characters 0x20 to 0x7E only (engine-spec 0.10, step 2)",
    })
    # the other way: from the JSON pack (the vector lives in the pack of its input)
    jm = {k: x for k, x in m.items() if not k.startswith("ckgpcsv.")}
    jin = '{"OBJECT_NAME":"TESTSAT 1","OBJECT_ID":"2026-123A","EPOCH":"2026-05-03T04:05:06.789012",' \
          '"MEAN_MOTION":15.5,"ECCENTRICITY":0.0001234,"INCLINATION":51.5,"RA_OF_ASC_NODE":120.25,' \
          '"ARG_OF_PERICENTER":90.125,"MEAN_ANOMALY":270.5,"EPHEMERIS_TYPE":0,"CLASSIFICATION_TYPE":"U",' \
          '"NORAD_CAT_ID":70001,"ELEMENT_SET_NO":999,"REV_AT_EPOCH":1234,"BSTAR":0.00012345,' \
          '"MEAN_MOTION_DOT":5e-06,"MEAN_MOTION_DDOT":0}'
    v.append({
        "name": "json-to-row", "from": "celestrak-gp-json", "to": "celestrak-gp-csv",
        "input": jin, "expect": gp_encode(jm), "source": "constructed",
        "reference": GP_REF % ("the ckgp keys carry over; BSTAR, MEAN_MOTION_DOT and MEAN_MOTION_DDOT are "
                               "float keys of ckgp, which the CSV pack does not map, so their columns are "
                               "written empty"),
    })
    return v


# --------------------------------------------------------------------------
# tle
# --------------------------------------------------------------------------

def checksum(line68):
    s = 0
    for ch in line68:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    return str(s % 10)


def put(buf, start, text):
    for i, ch in enumerate(text):
        buf[start + i] = ch


def line1(f, padded=None):
    """Line 1 as a producer writes it. `padded` maps a column name to the text to write
    there in place of the zero-padded form (a producer that pads with spaces)."""
    padded = padded or {}
    b = [" "] * 68
    b[0] = "1"
    put(b, 2, padded.get("sat", "%05d" % f["sat"]))
    b[7] = f["cls"]
    put(b, 9, "%02d" % f["ly"])
    put(b, 11, "%03d" % f["ln"])
    put(b, 14, f["lp"].ljust(3))
    put(b, 18, "%02d" % f["ey"])
    put(b, 20, f["ed"])
    put(b, 33, f["ndot"])
    put(b, 44, f["nddot"])
    put(b, 53, f["bstar"])
    b[62] = str(f["eph"])
    put(b, 64, padded.get("elset", "%04d" % f["elset"]))
    s = "".join(b)
    return s + checksum(s)


def line1_model(f):
    s = line1(f)
    return {"tle.satellite_number": str(f["sat"]), "tle.classification": f["cls"],
            "tle.launch_year": str(f["ly"]), "tle.launch_number": str(f["ln"]),
            "tle.launch_piece": f["lp"].rstrip(), "tle.epoch_year": str(f["ey"]),
            "tle.epoch_day": num(float(f["ed"])), "tle.mean_motion_dot": f["ndot"].rstrip(),
            "tle.mean_motion_ddot": f["nddot"].rstrip(), "tle.bstar": f["bstar"].rstrip(),
            "tle.ephemeris_type": str(f["eph"]), "tle.element_number": str(f["elset"]),
            "tle.checksum": s[68]}


def line1_encode(f, cs):
    """What tle writes for a line-1 model: each column by its transform."""
    b = [" "] * 69
    put(b, 0, column_str("1", 2))
    put(b, 2, column_num(str(f["sat"]), 5))
    put(b, 7, column_str(f["cls"], 1))
    put(b, 9, column_num(str(f["ly"]), 2))
    put(b, 11, column_num(str(f["ln"]), 3))
    put(b, 14, column_str(f["lp"].rstrip(), 3))
    put(b, 18, column_num(str(f["ey"]), 2))
    put(b, 20, column_num(dec(float(f["ed"]), 8, 12), 12))
    put(b, 33, column_str(f["ndot"].rstrip(), 10))
    put(b, 44, column_str(f["nddot"].rstrip(), 8))
    put(b, 53, column_str(f["bstar"].rstrip(), 8))
    put(b, 62, column_num(str(f["eph"]), 1))
    put(b, 64, column_num(str(f["elset"]), 4))
    put(b, 68, column_num(cs, 1))
    return "".join(b)


def line2(f, padded=None):
    padded = padded or {}
    b = [" "] * 68
    b[0] = "2"
    put(b, 2, "%05d" % f["sat"])
    for start, name, w in ((8, "incl", 8), (17, "raan", 8), (34, "argp", 8), (43, "ma", 8)):
        put(b, start, padded.get(name, ("%.4f" % f[name]).rjust(w)))
    put(b, 26, "%07d" % f["ecc"])
    put(b, 52, padded.get("mm", ("%.8f" % f["mm"]).rjust(11)))
    put(b, 63, ("%d" % f["rev"]).rjust(5))
    s = "".join(b)
    return s + checksum(s)


def line2_model(f):
    s = line2(f)
    return {"tle.satellite_number": str(f["sat"]), "tle.inclination": num(f["incl"]),
            "tle.ra_of_asc_node": num(f["raan"]), "tle.eccentricity_digits": str(f["ecc"]),
            "tle.arg_of_perigee": num(f["argp"]), "tle.mean_anomaly": num(f["ma"]),
            "tle.mean_motion": num(f["mm"]), "tle.rev_number": str(f["rev"]), "tle.checksum": s[68]}


def line2_encode(f, cs):
    b = [" "] * 69
    put(b, 0, column_str("2", 2))
    put(b, 2, column_num(str(f["sat"]), 5))
    put(b, 8, column_num(dec(f["incl"], 4, 8), 8))
    put(b, 17, column_num(dec(f["raan"], 4, 8), 8))
    put(b, 26, column_num(str(f["ecc"]), 7))
    put(b, 34, column_num(dec(f["argp"], 4, 8), 8))
    put(b, 43, column_num(dec(f["ma"], 4, 8), 8))
    put(b, 52, column_num(dec(f["mm"], 8, 11), 11))
    put(b, 63, column_num(str(f["rev"]), 5))
    put(b, 68, column_num(cs, 1))
    return "".join(b)


def tle_vectors():
    l1 = {"sat": 70001, "cls": "U", "ly": 26, "ln": 123, "lp": "A", "ey": 26, "ed": "123.50000000",
          "ndot": " .00001234", "nddot": " 00000-0", "bstar": " 12345-4", "eph": 0, "elset": 1234}
    l2 = {"sat": 70001, "incl": 101.5, "raan": 120.25, "ecc": 1234, "argp": 190.125, "ma": 270.5,
          "mm": 14.25, "rev": 12345}
    v = []
    s1 = line1(l1)
    v.append({"name": "line1-round-trip", "from": "tle", "to": "tle", "input": s1,
              "expect": line1_encode(l1, s1[68]), "model": line1_model(l1), "source": "constructed",
              "reference": TLE_REF % "line 1, every numeric column full width, so the line is written back unchanged"})
    s2 = line2(l2)
    v.append({"name": "line2-round-trip", "from": "tle", "to": "tle", "input": s2,
              "expect": line2_encode(l2, s2[68]), "model": line2_model(l2), "source": "constructed",
              "reference": TLE_REF % "line 2, every angle of three integer digits, so the line is written back unchanged"})
    l2b = dict(l2, incl=51.64, raan=7.5, argp=45.0, ma=315.25, mm=1.0027, rev=42)
    s2b = line2(l2b)
    v.append({"name": "line2-space-padded", "from": "tle", "to": "tle", "input": s2b,
              "expect": line2_encode(l2b, s2b[68]), "model": line2_model(l2b), "source": "constructed",
              "reference": TLE_REF % ("the producer pads the angles, the mean motion and the revolution number "
                                      "with spaces; decode drops leading spaces of a numeric column and encode "
                                      "pads with 0 (engine-spec 0.10), which leaves the checksum unchanged, as "
                                      "both count 0")})
    l1b = dict(l1, elset=12)
    s1b = line1(l1b, padded={"elset": "  12"})
    v.append({"name": "line1-space-padded-element-number", "from": "tle", "to": "tle", "input": s1b,
              "expect": line1_encode(l1b, s1b[68]), "model": line1_model(l1b), "source": "constructed",
              "reference": TLE_REF % "an element number of two digits padded with spaces is written with zeros"})
    l1c = dict(l1, ndot="-.00001234", bstar="-11606-4")
    s1c = line1(l1c)
    v.append({"name": "line1-negative-derivative", "from": "tle", "to": "tle", "input": s1c,
              "expect": line1_encode(l1c, s1c[68]), "model": line1_model(l1c), "source": "constructed",
              "reference": TLE_REF % ("the mean-motion derivative and BSTAR are strings: the sign column is "
                                      "kept as written, a space when positive and - when negative")})
    name = "TESTSAT 1"
    v.append({"name": "name-line-padded", "from": "tle", "to": "tle", "input": name.ljust(24),
              "expect": name.ljust(24), "model": {"tle.name": name}, "source": "constructed",
              "reference": TLE_REF % ("line 0, the name padded to 24 characters; matches neither line kind and "
                                      "reads as kind name; trailing spaces of the column are not part of the value")})
    v.append({"name": "name-line-short", "from": "tle", "to": "tle", "input": name,
              "expect": name.ljust(24), "model": {"tle.name": name}, "source": "constructed",
              "reference": TLE_REF % "a name line without its padding reads the same and is written padded to 24"})
    s1d = "1 A0001" + s1[7:68]
    s1d = s1d + checksum(s1d)
    v.append({"name": "alpha5-number-refused", "from": "tle", "to": "tle", "input": s1d,
              "expect_error": "transform-decode", "source": "constructed",
              "reference": TLE_REF % ("the satellite number is five digits; a letter in its first column (a scheme "
                                      "some producers use beyond 99999) is not an int")})
    v.append({"name": "line-terminator", "from": "tle", "to": "tle", "input": s2 + "\r\n",
              "expect": line2_encode(l2, s2[68]), "model": line2_model(l2), "source": "constructed",
              "reference": TLE_REF % ("CelesTrak ends each line with CR LF; decode removes one terminator "
                                      "(engine-spec 0.10, step 1) and encode writes none")})
    return v


def build(out):
    written = {}
    by_dir = {}
    for v in gp_vectors() + tle_vectors():
        by_dir.setdefault(v["from"], []).append(v)
    for pack, vecs in by_dir.items():
        vdir = "packs/%s/vectors" % pack
        names = set()
        for i, v in enumerate(vecs, 1):
            # a vector lives in the pack that owns its input; in a generated pack's directory
            # the hand-derived files are named to-<pack>-*, which the generator leaves alone
            if pack in ("celestrak-gp-csv", "tle"):
                fn = "%02d-%s.json" % (i, v["name"])
            else:
                fn = "to-%s-%s.json" % (v["to"], v["name"])
            names.add(fn)
            out.write(vdir + "/" + fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        for old in out.listdir(vdir):
            mine = pack in ("celestrak-gp-csv", "tle") or old.startswith("to-celestrak-gp-csv-")
            if mine and old not in names:
                out.remove(vdir + "/" + old)
        written[pack] = len(vecs)
    return written


def main(argv=None):
    return genio.vector_main("space-text-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
