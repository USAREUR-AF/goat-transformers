#!/usr/bin/env python3
"""Write the vectors of the ndbc-realtime2-stdmet, argo-index-prof and argo-index-meta packs.

The three packs read text records: one line of an NDBC realtime2 standard meteorological file
(fixed columns, wire `text` with no delimiter) and one data line of the Argo GDAC profile and
metadata directory files (wire `text`, delimiter `,`). This script holds its own copy of each
layout, takes records the sources publish (lines of the files as served on 2026-11-21) and
records written for these vectors, and works out the expected text and the decoded values by
the rules of spec/engine-spec.md for the text wire (0.10): column text with trailing spaces
removed (and leading spaces too for the numeric transforms), `int` written zero-padded to the
column's length, `string` padded on the right with spaces, `float` written as the shortest
decimal that reads back to the same double, an empty field absent. It reads no pack.def and
calls no goat-transformers engine.

Usage: python3 -I tools/gen/ocean-text-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/ocean-text-vectors.py from the record layouts and spec/engine-spec.md (text wire); no engine run"

# NDBC: (key, from, len, transform)
NDBC = [("year", 0, 4, "int"), ("month", 5, 2, "int"), ("day", 8, 2, "int"), ("hour", 11, 2, "int"),
        ("minute", 14, 2, "int"), ("wdir", 16, 4, "s"), ("wspd", 20, 5, "s"), ("gst", 25, 5, "s"),
        ("wvht", 30, 6, "s"), ("dpd", 36, 6, "s"), ("apd", 42, 6, "s"), ("mwd", 48, 4, "s"),
        ("pres", 52, 7, "s"), ("atmp", 59, 6, "s"), ("wtmp", 65, 6, "s"), ("dewp", 71, 6, "s"),
        ("vis", 77, 5, "s"), ("ptdy", 82, 5, "s"), ("tide", 87, 6, "s")]
PROF = [("file", "s"), ("date", "s"), ("latitude", "f"), ("longitude", "f"), ("ocean", "s"),
        ("profiler_type", "i"), ("institution", "s"), ("date_update", "s")]
META = [("file", "s"), ("profiler_type", "i"), ("institution", "s"), ("date_update", "s")]


def ndbc_decode(line):
    m = {}
    for k, f, n, t in NDBC:
        col = line[f:f + n].rstrip(" ")
        if t == "int":
            col = col.lstrip(" ")
        if col == "":
            continue
        m["ndbcstdmet." + k] = str(int(col)) if t == "int" else col
    return m


def ndbc_encode(m):
    """Each present column written at its place; characters no column writes are spaces, up to
    the end of the furthest column written."""
    present = [(f, n, t, m["ndbcstdmet." + k]) for k, f, n, t in NDBC if "ndbcstdmet." + k in m]
    if not present:
        return ""
    out = [" "] * max(f + n for f, n, _, _ in present)
    for f, n, t, v in present:
        text = str(int(v)).zfill(n) if t == "int" else v.ljust(n)
        out[f:f + n] = list(text)
    return "".join(out)


def fmt_float(x):
    r = repr(float(x))
    if "e" in r or "E" in r:
        raise ValueError(r)
    return r[:-2] if r.endswith(".0") else r


def csv_decode(line, layout, mod):
    fields = line.split(",")
    m = {}
    for i, (k, t) in enumerate(layout):
        v = fields[i] if i < len(fields) else ""
        if v == "":
            continue
        if t == "f":
            m[mod + "." + k] = fmt_float(float(v))
        elif t == "i":
            m[mod + "." + k] = str(int(v))
        else:
            m[mod + "." + k] = v
    return m


def csv_encode(m, layout, mod):
    out = []
    for k, t in layout:
        v = m.get(mod + "." + k)
        out.append("" if v is None else v)
    return ",".join(out)


def vec(name, fmt, inp, expect=None, model=None, error=None, ref=""):
    v = {"name": name, "from": fmt, "to": fmt, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = ref
    return v


def build_vectors():
    V = {}
    ref = "NDBC realtime2 standard meteorological file, record as served 2026-11-21"
    # station 46042 (Monterey), a full record, and station 44013 with several missing values (MM)
    lines = [("01-record-roundtrip", "2026 11 21 01 20 340  2.0  5.0   2.9    12   8.7 299 1018.5  14.7  20.2   8.9   MM   MM    MM"),
             ("02-missing-values-roundtrip", "2026 11 21 01 30 360  1.0  1.0    MM    MM    MM  MM 1025.0  12.9  11.7   7.7   MM   MM    MM")]
    for name, line in lines:
        m = ndbc_decode(line)
        assert ndbc_encode(m) == line, (ndbc_encode(m), line)
        V["ndbc-realtime2-stdmet", name] = vec(name, "ndbc-realtime2-stdmet", line, line, m,
                                                ref=ref + "; columns at fixed positions; missing values are MM, kept as text")
    # a record written for these vectors with a value cut short: the time columns are numbers
    # and leading zeros are written back; a measurement column keeps its text as written
    inp = "2026 01 02 03 04  10  0.5"
    m = ndbc_decode(inp)
    exp = ndbc_encode(m)
    V["ndbc-realtime2-stdmet", "03-short-record"] = vec("short-record", "ndbc-realtime2-stdmet", inp, exp, m,
                                                         ref="a record that ends after the wind speed: the missing columns are absent")
    V["ndbc-realtime2-stdmet", "04-header-line-is-not-a-record"] = vec(
        "header-line-is-not-a-record", "ndbc-realtime2-stdmet",
        "#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE",
        error="transform-decode", ref="the header line's year column is not a number")
    # Argo profile index: lines of the file as served, and one written for these vectors
    aref = "Argo GDAC ar_index_global_prof.txt, format version 2.0"
    for name, line in [("01-profile-line-roundtrip", "aoml/13857/profiles/D13857_001.nc,19970729200300,0.267,-16.032,A,845,AO,20260220143529"),
                       ("02-profile-line-roundtrip", "aoml/13857/profiles/D13857_002.nc,19970809192112,0.072,-17.659,A,845,AO,20260220143529")]:
        m = csv_decode(line, PROF, "argoidxprof")
        assert csv_encode(m, PROF, "argoidxprof") == line
        V["argo-index-prof", name] = vec(name, "argo-index-prof", line, line, m, ref=aref)
    inp = "nmdis/2901633/profiles/R2901633_071.nc,20260101120000,,,P,846,NM,20260102080000"
    m = csv_decode(inp, PROF, "argoidxprof")
    V["argo-index-prof", "03-no-position"] = vec("no-position", "argo-index-prof", inp,
                                                 csv_encode(m, PROF, "argoidxprof"), m,
                                                 ref=aref + "; a profile with no position: the empty fields are absent")
    inp = "aoml/13857/profiles/D13857_003.nc,19970820184545,0.5430,-19.6220,A,845,AO,20260220143530"
    m = csv_decode(inp, PROF, "argoidxprof")
    V["argo-index-prof", "04-trailing-zeros"] = vec("trailing-zeros", "argo-index-prof", inp,
                                                    csv_encode(m, PROF, "argoidxprof"), m,
                                                    ref=aref + "; a float is written back as its shortest decimal")
    mref = "Argo GDAC ar_index_global_meta.txt, format version 2.0"
    line = "aoml/13857/13857_meta.nc,845,AO,20181011200014"
    m = csv_decode(line, META, "argoidxmeta")
    V["argo-index-meta", "01-metadata-line-roundtrip"] = vec("metadata-line-roundtrip", "argo-index-meta", line, line, m, ref=mref)
    V["argo-index-meta", "02-profiler-type-not-a-number"] = vec(
        "profiler-type-not-a-number", "argo-index-meta", "aoml/13857/13857_meta.nc,X45,AO,20181011200014",
        error="transform-decode", ref=mref + "; profiler_type is an integer code")
    return V


def build(out):
    written = {}
    for (pack, name), v in build_vectors().items():
        out.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("ocean-text-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
