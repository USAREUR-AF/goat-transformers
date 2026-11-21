#!/usr/bin/env python3
"""rinex-vectors: write the vectors of the RINEX packs rinex-obs-line and rinex-nav-line.

Python 3 standard library only; imports no engine and reads no pack.def. The column layouts below
are this program's own restatement of RINEX 4.01 Tables A2, A3, A7, A9 and A30-A34 (and 3.05, whose
observation columns are the same): each value placed at its column, text left-justified, numbers
right-justified with spaces, as a RINEX writer formats them.

Inputs: lines built here from values chosen here; none is copied from the documents' examples. Station
names, receivers and values are invented.

`expect` of every vector is the line as this program writes it, which is the input: the packs keep
every value as its column text, and header lines run to column 80.

Usage: python3 -I tools/gen/rinex-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/rinex-vectors.py from values chosen there; columns restated from %s; expect derived there, no engine run"
R_OBS = "RINEX 4.01 Tables A2 and A3"
R_NAV = "RINEX 4.01 Tables A7, A9 and A30-A32"


def line(*parts):
    """parts: (start, text, width or None); text left-justified in its width; gaps are spaces."""
    buf = []
    for start, text, width in parts:
        t = text.ljust(width) if width else text
        if len(buf) < start:
            buf.extend(" " * (start - len(buf)))
        for i, ch in enumerate(t):
            pos = start + i
            if pos < len(buf):
                buf[pos] = ch
            else:
                buf.append(ch)
    return "".join(buf)


def header(label, *parts):
    return line(*parts, (60, label, 20))


def f(value, width, fmt):
    return (fmt % value).rjust(width)


def vec(pack, name, inp, model=None, error=None, ref=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


def obs_vectors():
    p = "rinex-obs-line"
    O = "rinexobs."
    out = []
    a = header("RINEX VERSION / TYPE", (0, f(4.01, 9, "%.2f"), 9), (20, "O", 1), (21, "BSERVATION DATA", 19), (40, "M", 1),
               (41, ": MIXED", 19))
    out.append((p, "01-version-line-roundtrip.json", vec(p, "version-line-roundtrip", a,
                {O + "format_version": "     4.01", O + "file_type": "O", O + "file_type_text": "BSERVATION DATA",
                 O + "satellite_system": "M", O + "satellite_system_text": ": MIXED"},
                ref=R_OBS + "; the version and type line of a mixed observation file")))
    b = header("APPROX POSITION XYZ", (0, f(4027881.3280, 14, "%.4f"), 14), (14, f(306998.7120, 14, "%.4f"), 14),
               (28, f(4919499.0010, 14, "%.4f"), 14))
    out.append((p, "02-approx-position-roundtrip.json", vec(p, "approx-position-roundtrip", b,
                {O + "approx_x": "  4027881.3280", O + "approx_y": "   306998.7120", O + "approx_z": "  4919499.0010"},
                ref=R_OBS + "; the approximate position, geocentric metres (ECEF), kept as written")))
    c = header("SYS / # / OBS TYPES", (0, "G", 1), (3, f(4, 3, "%d"), 3), (7, "C1C", 3), (11, "L1C", 3), (15, "D1C", 3), (19, "S1C", 3))
    out.append((p, "03-obs-types-roundtrip.json", vec(p, "obs-types-roundtrip", c,
                {O + "obs_system": "G", O + "obs_type_count": "  4", O + "obs_type_1": "C1C", O + "obs_type_4": "S1C"},
                ref=R_OBS + "; four GPS observation types")))
    d = header("TIME OF FIRST OBS", (0, f(2026, 6, "%d"), 6), (6, f(3, 6, "%d"), 6), (12, f(14, 6, "%d"), 6), (18, f(0, 6, "%d"), 6),
               (24, f(0, 6, "%d"), 6), (30, f(0.0, 13, "%.7f"), 13), (48, "GAL", 3))
    out.append((p, "04-time-of-first-obs-roundtrip.json", vec(p, "time-of-first-obs-roundtrip", d,
                {O + "first_year": "  2026", O + "first_second": "    0.0000000", O + "first_time_system": "GAL"},
                ref=R_OBS + "; the first observation epoch, in the time system named GAL, kept raw")))
    e = header("END OF HEADER")
    out.append((p, "05-end-of-header-roundtrip.json", vec(p, "end-of-header-roundtrip", e, ref=R_OBS + "; the last header line")))
    g = line((0, ">", 1), (2, "2026", 4), (7, "03", 2), (10, "14", 2), (13, "00", 2), (16, "00", 2), (18, f(30.0, 11, "%.7f"), 11),
             (31, "0", 1), (32, f(2, 3, "%d"), 3))
    out.append((p, "06-epoch-roundtrip.json", vec(p, "epoch-roundtrip", g,
                {O + "year": "2026", O + "month": "03", O + "second": " 30.0000000", O + "epoch_flag": "0",
                 O + "satellite_count_epoch": "  2"},
                ref=R_OBS + "; an epoch line with flag 0, two satellites, no clock offset")))
    g2 = line((0, ">", 1), (2, "2026", 4), (7, "03", 2), (10, "14", 2), (13, "00", 2), (16, "00", 2), (18, f(30.0, 11, "%.7f"), 11),
              (31, "0", 1), (32, f(2, 3, "%d"), 3), (41, f(-0.000123456789, 15, "%.12f"), 15))
    out.append((p, "07-epoch-with-clock-offset-roundtrip.json", vec(p, "epoch-with-clock-offset-roundtrip", g2,
                {O + "clock_offset": "-0.000123456789"}, ref=R_OBS + "; an epoch line with the receiver clock offset")))
    h = line((0, "G05", 3), (3, f(23619095.450, 14, "%.3f"), 14), (18, "7", 1), (19, f(124121316.328, 14, "%.3f"), 14), (33, "0", 1),
             (34, "7", 1), (35, f(-1234.567, 14, "%.3f"), 14), (51, f(44.250, 14, "%.3f"), 14))
    out.append((p, "08-gps-observations-roundtrip.json", vec(p, "gps-observations-roundtrip", h,
                {O + "satellite_system": "G", O + "satellite_number": "05", O + "obs_1": "  23619095.450", O + "ssi_1": "7",
                 O + "obs_2": " 124121316.328", O + "lli_2": "0", O + "obs_3": "     -1234.567", O + "obs_4": "        44.250"},
                ref=R_OBS + "; a GPS satellite's four observations with LLI and SSI digits where given")))
    i = line((0, "R12", 3), (3, f(21000000.125, 14, "%.3f"), 14), (35, f(110.5, 14, "%.3f"), 14))
    out.append((p, "09-glonass-missing-observation-roundtrip.json", vec(p, "glonass-missing-observation-roundtrip", i,
                {O + "satellite_system": "R", O + "satellite_number": "12", O + "obs_1": "  21000000.125", O + "obs_3": "       110.500"},
                ref=R_OBS + "; a GLONASS line whose second observation is blank")))
    j = header("GLONASS SLOT / FRQ #", (0, "  2 R01  1 R02 -4", 60))
    out.append((p, "10-glonass-slot-frq-content-roundtrip.json", vec(p, "glonass-slot-frq-content-roundtrip", j,
                {O + "content": "  2 R01  1 R02 -4"}, ref=R_OBS + "; a header line the pack keeps as its 60 columns")))
    k = header("FUTURE LABEL", (0, "anything", 60))
    out.append((p, "11-unknown-label-is-header-other-roundtrip.json", vec(p, "unknown-label-is-header-other-roundtrip", k,
                {O + "content": "anything", O + "label": "FUTURE LABEL"}, ref=R_OBS + "; a header label the pack does not know")))
    out.append((p, "12-blank-line-is-no-kind.json", vec(p, "blank-line-is-no-kind", "x", error="no-kind",
                ref=R_OBS + "; a line that is no header, epoch or observation line")))
    return out


def e19(v):
    return ("%.12E" % v).rjust(19)


def nav_vectors():
    p = "rinex-nav-line"
    N = "rinexnav."
    out = []
    a = header("RINEX VERSION / TYPE", (0, f(4.01, 9, "%.2f"), 9), (20, "N", 1), (21, ": GNSS NAV DATA", 19), (40, "M", 1),
               (41, ": MIXED", 19))
    out.append((p, "01-version-line-roundtrip.json", vec(p, "version-line-roundtrip", a,
                {N + "file_type": "N", N + "satellite_system": "M"}, ref=R_NAV + "; the version line of a mixed navigation file")))
    b = header("LEAP SECONDS", (0, f(18, 6, "%d"), 6), (6, f(18, 6, "%d"), 6), (12, f(1929, 6, "%d"), 6), (18, f(7, 6, "%d"), 6))
    out.append((p, "02-leap-seconds-roundtrip.json", vec(p, "leap-seconds-roundtrip", b,
                {N + "leap_seconds": "    18", N + "leap_week": "  1929", N + "leap_day": "     7"},
                ref=R_NAV + "; the leap seconds line")))
    c = line((0, ">", 1), (2, "EPH", 3), (6, "G", 1), (7, "05", 2), (10, "LNAV", 4))
    out.append((p, "03-record-line-roundtrip.json", vec(p, "record-line-roundtrip", c,
                {N + "record_type": "EPH", N + "satellite_system": "G", N + "satellite_number": "05", N + "message_type": "LNAV"},
                ref=R_NAV + "; a version 4 record line for a GPS LNAV ephemeris")))
    d = line((0, "G05", 3), (4, "2026", 4), (9, "03", 2), (12, "14", 2), (15, "02", 2), (18, "00", 2), (21, "00", 2),
             (23, e19(-1.234567890123e-4), 19), (42, e19(-2.273736754432e-12), 19), (61, e19(0.0), 19))
    out.append((p, "04-satellite-epoch-roundtrip.json", vec(p, "satellite-epoch-roundtrip", d,
                {N + "satellite_system": "G", N + "satellite_number": "05", N + "year": "2026", N + "hour": "02",
                 N + "value_1": "-1.234567890123E-04", N + "value_3": " 0.000000000000E+00"},
                ref=R_NAV + "; the first line of a GPS LNAV record: Toc and the clock bias, drift and drift rate")))
    e = line((4, e19(44.0), 19), (23, e19(-58.71875), 19), (42, e19(4.506973452533e-9), 19), (61, e19(1.023456789012), 19))
    out.append((p, "05-values-roundtrip.json", vec(p, "values-roundtrip", e,
                {N + "value_0": " 4.400000000000E+01", N + "value_1": "-5.871875000000E+01"},
                ref=R_NAV + "; a broadcast orbit line of four values")))
    g = line((4, e19(345600.0), 19), (23, e19(4.0), 19))
    out.append((p, "06-short-values-line-roundtrip.json", vec(p, "short-values-line-roundtrip", g,
                {N + "value_0": " 3.456000000000E+05", N + "value_1": " 4.000000000000E+00"},
                ref=R_NAV + "; a last orbit line of two values (the others blank)")))
    h = line((4, "2026", 4), (9, "03", 2), (12, "14", 2), (15, "00", 2), (18, "00", 2), (21, "00", 2), (24, "GPUT", 18))
    out.append((p, "07-sto-epoch-roundtrip.json", vec(p, "sto-epoch-roundtrip", h,
                {N + "year": "2026", N + "value_1": " GPUT"},
                ref=R_NAV + "; the epoch line of a system time offset record (GPS-UTC), its identifier kept with the column")))
    out.append((p, "08-tab-character-is-malformed.json", vec(p, "tab-character-is-malformed", "G05\t2026", error="malformed-wire",
                ref=R_NAV + "; a line holding a tab, which RINEX lines do not (only characters 0x20-0x7E)")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in obs_vectors() + nav_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("rinex-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
