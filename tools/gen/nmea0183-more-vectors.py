#!/usr/bin/env python3
"""Write the vectors 44 and up of the pack `nmea0183`: those of the sentences
added after the first edition (GNS, HDM, HDG, THS, ROT, VHW, MWV, MWD, DBT,
DPT, MTW, TTM, TLL, OSD, DTM). Vectors 01-43 are maintained by hand and are
not written or removed here.

Every sentence below is written for these vectors; none is copied from a
standard or from a source's examples. The field order of each sentence is
pynmea2's (https://github.com/Knio/pynmea2, MIT, commit d8240dc,
pynmea2/types/talker.py) and the meaning and units gpsd's
(https://gitlab.com/gpsd/gpsd, BSD-2-Clause, commit c59fc6d,
drivers/driver_nmea0183.c), restated here as this script's own tables.

The script builds each sentence from its fields, computes the checksum (the
XOR of every byte between `$` and `*`, two uppercase hexadecimal digits),
works out the decoded values with its own readings of the text transforms of
spec/engine-spec.md 0.10 (dm, hms, hms_dmy, dec, int) and the derived keys of
model/nmea0183.def, and writes the GeoJSON and CoT forms by the canonical rules
of those packs. It reads no pack.def and calls no goat-transformers engine.

Inputs: none; every value is stated in this file. The same run always gives the
same bytes. With --check nothing is written and the exit status is 1 when a
committed file differs from what this script writes.

Usage: python3 -I tools/gen/nmea0183-more-vectors.py [--out DIR] [--check]
"""
import calendar
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

PACK = "nmea0183"


# ---------------------------------------------------------------- sentences

def checksum(body):
    c = 0
    for ch in body.encode("ascii"):
        c ^= ch
    return "%02X" % c


def sentence(talker, code, fields):
    body = ",".join([talker + code] + list(fields))
    return "$" + body + "*" + checksum(body)


# ---------------------------------------------------------------- readings (engine-spec 0.10)

def dm(text, letter, neg):
    """dm decode: degrees + minutes / 60, the minutes read as the nearest double."""
    i = text.index(".") if "." in text else len(text)
    deg, minutes = int(text[:i - 2]), float(text[i - 2:])
    v = minutes / 60 + deg
    return -v if letter == neg else v


def hms(text):
    h, m = int(text[0:2]), int(text[2:4])
    return (h * 3600 + m * 60) + float(text[4:])


def hms_dmy_ms(t, d):
    h, m, s = int(t[0:2]), int(t[2:4]), int(t[4:6])
    frac = t[7:] if len(t) > 6 else ""
    ms = int((frac + "000")[:3]) if frac else 0
    yy = int(d[4:6])
    year = 1900 + yy if yy >= 80 else 2000 + yy
    return (calendar.timegm((year, int(d[2:4]), int(d[0:2]), h, m, s)) * 1000) + ms


def iso(ms):
    s, r = divmod(ms, 1000)
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(s)) + ".%03dZ" % r


def num(x):
    """Shortest round-trip decimal, plain notation, no point on an integer value
    (engine-spec 0.1.1 ruling 3)."""
    if x == int(x) and abs(x) < 2 ** 53:
        return str(int(x))
    r = repr(float(x))
    assert "e" not in r and "E" not in r
    return r


def dec(x, f):
    """dec:<f> encode: n = round half away from zero of x * 10^f."""
    y = x * (10.0 ** f)
    n = int(math.floor(abs(y) + 0.5)) * (1 if y >= 0 else -1)
    digits = str(abs(n)).rjust(f + 1, "0")
    t = digits[:-f] + "." + digits[-f:] if f else digits
    return ("-" if n < 0 else "") + t


# ---------------------------------------------------------------- canonical forms of the other packs

def geojson(lat=None, lon=None, props=()):
    geom = "null" if lat is None or lon is None else \
        '{"type":"Point","coordinates":[%s,%s]}' % (num(lon), num(lat))
    order = ["type", "time_ms", "how", "ce", "le", "callsign", "course", "speed_ms"]
    p = dict(props)
    body = ",".join('"%s":%s' % (k, json.dumps(p[k]) if isinstance(p[k], str) else num(p[k]))
                    for k in order if k in p)
    return '{"type":"Feature","geometry":%s,"properties":{%s}}' % (geom, body)


def cot(lat, lon, time_ms=None, callsign=None, course=None, speed=None):
    attrs = ['version="2.0"', 'type="a-u-X"']
    if time_ms is not None:
        attrs += ['time="%s"' % iso(time_ms), 'start="%s"' % iso(time_ms)]
    point = '<point lat="%s" lon="%s" hae="9999999" ce="9999999" le="9999999"/>' % (num(lat), num(lon))
    detail = ""
    if callsign is not None:
        detail += '<contact callsign="%s"/>' % callsign
    track = (['course="%s"' % num(course)] if course is not None else []) + \
            (['speed="%s"' % num(speed)] if speed is not None else [])
    if track:
        detail += "<track %s/>" % " ".join(track)
    return "<event %s>%s%s</event>" % (" ".join(attrs), point, "<detail>%s</detail>" % detail if detail else "")


# ---------------------------------------------------------------- vectors

SRC = "pynmea2 talker.py (field order) and gpsd driver_nmea0183.c (meaning and units)"


def vec(name, frm, to, inp, expect=None, error=None, model=None, ref=""):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = ref + "; sentence and checksum computed by tools/gen/nmea0183-more-vectors.py"
    return v


def roundtrip(name, talker, code, fields, model, ref):
    s = sentence(talker, code, fields)
    m = {"@kind": code.lower(), "nmea0183.talker": talker}
    m.update(model)
    return vec(name, PACK, PACK, s, s, model=m, ref=SRC + ": " + ref)


def build_vectors():
    out = []
    R = out.append

    gns = ["101112.00", "4012.50000", "N", "07401.25000", "W", "AN", "10", "1.10", "12.0", "-33.5", "", ""]
    glat, glon = dm("4012.50000", "N", "S"), dm("07401.25000", "W", "W")
    R(roundtrip("gns-round-trip", "GN", "GNS", gns, {
        "lat": num(glat), "lon": num(glon), "nmea0183.gns_mode": "AN", "nmea0183.sats_used": "10",
        "nmea0183.alt_msl_m": "12", "nmea0183.geoid_sep_m": "-33.5", "nmea0183.utc_s": num(hms("101112.00"))},
        "GNS fields 1-12; the GGA keys hold the same values here"))
    R(vec("gns-to-geojson", PACK, "geojson", sentence("GN", "GNS", gns), geojson(glat, glon),
          ref=SRC + ": position only; the MSL altitude is not hae"))
    R(roundtrip("hdm-round-trip", "HC", "HDM", ["271.00", "M"], {"nmea0183.heading_mag_deg": "271"}, "HDM fields 1-2"))
    R(roundtrip("hdg-round-trip", "HC", "HDG", ["271.00", "1.50", "E", "3.1", "W"], {
        "nmea0183.heading_sensor_deg": "271", "nmea0183.deviation_deg": "1.5", "nmea0183.deviation_dir": "E",
        "nmea0183.magvar_deg": "3.1", "nmea0183.magvar_dir": "W"}, "HDG fields 1-5"))
    R(roundtrip("ths-round-trip", "HE", "THS", ["274.15", "A"], {
        "nmea0183.heading_true_deg": "274.15", "nmea0183.ths_mode": "A"}, "THS fields 1-2"))
    R(roundtrip("rot-negative-to-port", "HE", "ROT", ["-12.50", "A"], {
        "nmea0183.rot_deg_min": "-12.5", "nmea0183.status": "A"}, "ROT fields 1-2"))
    R(roundtrip("vhw-round-trip", "VW", "VHW", ["274.10", "T", "271.00", "M", "6.20", "N", "11.48", "K"], {
        "nmea0183.heading_true_deg": "274.1", "nmea0183.stw_kn": "6.2", "nmea0183.stw_kmh": "11.48"},
        "VHW fields 1-8; speed through the water is not speed_ms"))
    R(roundtrip("mwv-round-trip", "WI", "MWV", ["35.0", "R", "14.2", "N", "A"], {
        "nmea0183.wind_angle_deg": "35", "nmea0183.wind_reference": "R", "nmea0183.wind_speed": "14.2",
        "nmea0183.wind_speed_unit": "N"}, "MWV fields 1-5"))
    R(roundtrip("mwd-round-trip", "WI", "MWD", ["310.0", "T", "313.1", "M", "14.2", "N", "7.3", "M"], {
        "nmea0183.wind_dir_true_deg": "310", "nmea0183.wind_speed_kn": "14.2", "nmea0183.wind_speed_ms": "7.3"},
        "MWD fields 1-8"))
    R(roundtrip("dbt-round-trip", "SD", "DBT", ["40.0", "f", "12.2", "M", "6.7", "F"], {
        "nmea0183.dbt_depth_ft": "40", "nmea0183.dbt_depth_m": "12.2", "nmea0183.dbt_depth_fathom": "6.7"},
        "DBT fields 1-6"))
    R(roundtrip("dpt-round-trip", "SD", "DPT", ["12.2", "-0.5", "100.0"], {
        "nmea0183.dpt_depth_m": "12.2", "nmea0183.dpt_offset_m": "-0.5", "nmea0183.dpt_range_m": "100"},
        "DPT fields 1-3"))
    s = sentence("SD", "DPT", ["12.2", "-0.5"])
    R(vec("dpt-without-range-field", PACK, PACK, s, s, model={"@kind": "dpt", "nmea0183.dpt_depth_m": "12.2"},
          ref=SRC + ": the range field is a later addition and optional: the shorter form round-trips"))
    R(roundtrip("mtw-round-trip", "YX", "MTW", ["14.5", "C"], {
        "nmea0183.water_temp": "14.5", "nmea0183.water_temp_unit": "C"}, "MTW fields 1-2"))
    ttm = ["07", "2.35", "112.4", "T", "8.5", "245.0", "T", "0.40", "12.5", "N", "TGT07", "T", "", "081530.00", "A"]
    R(roundtrip("ttm-round-trip", "RA", "TTM", ttm, {
        "nmea0183.target_number": "7", "nmea0183.target_distance": "2.35", "nmea0183.target_bearing_deg": "112.4",
        "callsign": "TGT07", "nmea0183.target_status": "T", "nmea0183.target_course_deg": "245",
        "nmea0183.utc_s": num(hms("081530.00"))},
        "TTM fields 1-15; the target speed and course are raw (their unit and reference are other fields)"))
    R(vec("ttm-to-geojson", PACK, "geojson", sentence("RA", "TTM", ttm), geojson(props={"callsign": "TGT07"}),
          ref=SRC + ": TTM has range and bearing, no position: geometry null, the target name as callsign"))
    tll = ["07", "4807.50000", "N", "01131.00000", "E", "TGT07", "081530.00", "T", ""]
    tlat, tlon = dm("4807.50000", "N", "S"), dm("01131.00000", "E", "W")
    R(roundtrip("tll-round-trip", "RA", "TLL", tll, {
        "lat": num(tlat), "lon": num(tlon), "callsign": "TGT07", "nmea0183.target_number": "7"},
        "TLL fields 1-9"))
    R(vec("tll-to-cot-xml", PACK, "cot-xml", sentence("RA", "TLL", tll), cot(tlat, tlon, callsign="TGT07"),
          ref=SRC + ": the target's position and name; TLL has a time and no date, so no time_ms"))
    R(vec("tll-to-geojson", PACK, "geojson", sentence("RA", "TLL", tll),
          geojson(tlat, tlon, {"callsign": "TGT07"}), ref=SRC + ": the target's position and name"))
    R(roundtrip("osd-round-trip", "RA", "OSD", ["274.10", "A", "270.0", "B", "6.2", "W", "45.0", "0.5", "N"], {
        "nmea0183.heading_true_deg": "274.1", "nmea0183.osd_course_deg": "270", "nmea0183.osd_speed": "6.2",
        "nmea0183.osd_speed_unit": "N"}, "OSD fields 1-9"))
    R(roundtrip("dtm-round-trip", "GP", "DTM", ["W84", "", "0.0000", "N", "0.0000", "E", "0.0", "W84"], {
        "nmea0183.datum_local": "W84", "nmea0183.datum_reference": "W84"}, "DTM fields 1-8"))
    R(vec("tll-minutes-of-60-fail", PACK, PACK,
          sentence("RA", "TLL", ["07", "4860.00000", "N", "01131.00000", "E", "TGT07", "081530.00", "T", ""]),
          error="transform-decode", ref="60 minutes in a dm field (engine-spec 0.10, transform rule 3)"))
    return out


FIRST = 44      # vectors 01-43 of the pack are maintained by hand


def build(out):
    vdir = "packs/%s/vectors" % PACK
    vecs = build_vectors()
    assert len({v["name"] for v in vecs}) == len(vecs)
    names = set()
    for i, v in enumerate(vecs, FIRST):
        rel = "%s/%02d-%s.json" % (vdir, i, v["name"])
        names.add(rel.split("/")[-1])
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    for old in out.listdir(vdir):
        if old[:2].isdigit() and int(old.split("-")[0]) >= FIRST and old not in names:
            out.remove(vdir + "/" + old)
    return {PACK: len(vecs)}


def main(argv=None):
    return genio.vector_main("nmea0183-more-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
