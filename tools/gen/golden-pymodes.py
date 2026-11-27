#!/usr/bin/env python3
"""golden-pymodes: golden vectors for packs/adsb from pyModeS, a reference
Mode S and ADS-B decoder (shared-model hardening, item 2: meaning is tested
against an implementation outside this project, not only engine agreement).

pyModeS decodes; it does not encode. The inputs are therefore real messages:
the DF17 messages of pyModeS's own test suite at the commit of its v3.7.0 tag,
from the recorded capture tests/data/sample_data_adsb.csv (the first three of
each type code and subtype) and the messages written into tests/*.py. Each is
decoded with pyModeS 3.7.0 and written as
packs/adsb/vectors/golden-<kind>-<n>.json:

  input, expect  the message as recorded, and its canonical form (lowercase
                 hex): a round trip
  model          "@kind" and, under the pack's keys, what pyModeS decodes:
                 the fields it reports raw (ICAO address, type code, category,
                 callsign, CPR format and the 17-bit CPR latitude and longitude,
                 velocity subtype, NACv, surveillance status, the status flags),
                 and the fields it reports scaled turned back into the raw field
                 by the scaling DO-260B gives (and pyModeS applies), stated at
                 each: airspeed, heading, vertical rate, geometric minus
                 barometric altitude, selected altitude, heading and baro setting
  source         pyModeS, its version and the message's origin; no engine is run

Not compared: the barometric altitude (a Gillham or 25-foot code with a Q bit;
pyModeS reports feet), the ground velocity's east-west and north-south fields
(pyModeS reports speed and track, which do not give the components back
exactly), the squawk (Gillham-coded).

Usage (pyModeS 3.7.0 importable, as tools/gen/golden-pymodes.txt pins it with
its hash; the test files are fetched at the pinned commit and refused unless
their SHA-256 is the one below):

  python3 -I tools/gen/golden-pymodes.py [--cache DIR]           write
  python3 -I tools/gen/golden-pymodes.py --check [--cache DIR]   exit 1 when a
                                                                 vector differs
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "packs", "adsb", "vectors")
PYMODES = "3.7.0"
REPO, COMMIT = "junzis/pyModeS", "4bf083284c0d9878ca0c88f16b9b5f6514ca194a"   # tag v3.7.0
# test files read for messages, with their SHA-256 at COMMIT
FILES = [
    ("tests/data/sample_data_adsb.csv", "7534e8186adec1aa44589c27d6059d0cde102c12d7e77c2584041f33afb99d9f"),
]
TEST_FILES = {
    "tests/test_adsb.py": "02807ff086c893c22b05f992b0116c9a835f4c7e85b8ddf111a4aa4058b068be",
    "tests/test_batch.py": "44aeebc8453bce1906907779bf8e8726d5f998c629f067df305a121e19ba9c79",
    "tests/test_cpr.py": "08e0dc634211f1e8a3d5728ac8f3ca78ada93f9bb6bacab680479eb4ff237cb3",
    "tests/test_pipe.py": "b1a2f40232f4b5588d7d83a23246de5ff31e19f8288644fce8c2a761b50f6d64",
    "tests/test_bds09.py": "c6542212a70a09fc3f1d4195a9d5dd932a10d22bcc8b48567a0936c8a7088d27",
    "tests/test_bds61.py": "9848e077368ae2bac3e88399a0ed3bceaa87b6447f49420f2e0483cc623254c2",
    "tests/test_bds62.py": "7415f8e07d0f8e366b508c36a9eff196edcae3c3fe825bd6be0b8c35eaf08548",
    "tests/test_schema.py": "e86eb12a28359db47c20bcb5bc4b98d3c1cd2febdda8fec1ce9b33afcd1324a2",
}
PER_TYPE = 3
HEX = re.compile(r'"(8[CD][0-9A-Fa-f]{26})"')


def fetch(path, sha, cache):
    os.makedirs(cache, exist_ok=True)
    local = os.path.join(cache, sha + "-" + os.path.basename(path))
    if not os.path.exists(local):
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (REPO, COMMIT, path)
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        with open(local, "wb") as fh:
            fh.write(data)
    data = open(local, "rb").read()
    if hashlib.sha256(data).hexdigest() != sha:
        raise SystemExit("golden-pymodes: %s at %s does not have the recorded SHA-256 (%s)" % (path, COMMIT, local))
    return data


def kind_of(d):
    tc, st = d["typecode"], d.get("subtype")
    if 1 <= tc <= 4:
        return "identification-tc%d" % tc
    if 5 <= tc <= 8:
        return "surface-position-tc%d" % tc
    if 9 <= tc <= 18:
        return "airborne-position-baro-tc%d" % tc
    if 20 <= tc <= 22:
        return "airborne-position-gnss-tc%d" % tc
    if tc == 19:
        return {1: "airborne-velocity-ground-st1", 2: "airborne-velocity-ground-st2",
                3: "airborne-velocity-air-st3", 4: "airborne-velocity-air-st4"}.get(st)
    if tc == 28 and st == 1:
        return "aircraft-status-emergency"
    if tc == 29 and st == 1:
        return "target-state"
    if tc == 31:
        return {0: "operational-status-airborne", 1: "operational-status-surface"}.get(st)
    return None


def whole(x, what):
    """A raw field value from a scaled one: it must come out a whole number."""
    if x.denominator != 1:
        raise SystemExit("golden-pymodes: %s %s is not a whole raw value" % (what, x))
    return str(x.numerator)


def frac(v):
    return Fraction(repr(float(v)))


def model_of(d):
    m = {"adsb.df": "17", "adsb.icao": str(int(d["icao"], 16)), "adsb.tc": str(d["typecode"])}
    tc = d["typecode"]
    if 1 <= tc <= 4:
        m["adsb.category"] = str(d["category"])
        m["callsign"] = d["callsign"]
    if 5 <= tc <= 18 or 20 <= tc <= 22:
        m["adsb.cpr_odd"] = str(d["cpr_format"])
        m["adsb.cpr_lat"] = str(d["cpr_lat"])
        m["adsb.cpr_lon"] = str(d["cpr_lon"])
        if 9 <= tc <= 18 and "surveillance_status" in d:
            m["adsb.ss"] = str(d["surveillance_status"])
    if tc == 19:
        st = d["subtype"]
        m["adsb.velocity_subtype"] = str(st)
        m["adsb.nac_v"] = str(d["nac_v"])
        # vertical rate source: 0 GNSS, 1 barometric (DO-260B 2.2.3.2.6.1.8)
        m["adsb.vr_source"] = {"GNSS": "0", "BARO": "1"}[d["vr_source"]]
        vr = d.get("vertical_rate")
        if vr is not None:
            # rate = (raw - 1) x 64 ft/min, the sign bit set for descent
            m["adsb.vr_sign"] = "1" if vr < 0 else "0"
            m["adsb.vr_raw"] = whole(Fraction(abs(vr), 64) + 1, "vertical rate")
        gmb = d.get("geo_minus_baro")
        if gmb is not None:
            # difference = (raw - 1) x 25 ft, the sign bit set when geometric is below barometric
            m["adsb.galt_diff_sign"] = "1" if gmb < 0 else "0"
            m["adsb.galt_diff_raw"] = whole(Fraction(abs(gmb), 25) + 1, "geo minus baro")
        if st in (3, 4):
            if d.get("heading") is not None:
                # heading = raw x 360/1024 degrees, valid bit set
                m["adsb.heading_valid"] = "1"
                m["adsb.heading_raw"] = whole(frac(d["heading"]) * 1024 / 360, "heading")
            m["adsb.airspeed_true"] = {"IAS": "0", "TAS": "1"}[d["airspeed_type"]]
            if d.get("airspeed") is not None:
                # airspeed = (raw - 1) kt, x 4 for the supersonic subtype 4
                m["adsb.airspeed_raw"] = whole(Fraction(d["airspeed"]) / (4 if st == 4 else 1) + 1, "airspeed")
    if tc == 28:
        m["adsb.emergency_state"] = str(d["emergency_state"])
    if tc == 29:
        for f, k in (("nac_p", "nac_p"), ("nic_baro", "nic_baro"), ("sil", "sil")):
            m["adsb." + k] = str(int(d[f]))
        for f, k in (("autopilot", "autopilot"), ("vnav_mode", "vnav"), ("altitude_hold_mode", "alt_hold"),
                     ("approach_mode", "approach"), ("lnav_mode", "lnav"), ("tcas_operational", "tcas_operational")):
            m["adsb." + k] = "1" if d[f] else "0"
        m["adsb.sel_alt_fms"] = {"MCP/FCU": "0", "FMS": "1"}[d["selected_altitude_source"]]
        # selected altitude = (raw - 1) x 32 ft
        m["adsb.sel_alt_raw"] = whole(Fraction(d["selected_altitude"], 32) + 1, "selected altitude")
        # barometric setting = 800 + (raw - 1) x 0.8 hPa
        m["adsb.baro_setting_raw"] = whole((frac(d["baro_pressure_setting"]) - 800) / Fraction(4, 5) + 1, "baro setting")
        h = frac(d["selected_heading"])
        # selected heading: sign bit for 180 degrees and more, then raw x 180/256 degrees
        m["adsb.sel_heading_valid"] = "1"
        m["adsb.sel_heading_sign"] = "1" if h >= 180 else "0"
        m["adsb.sel_heading_raw"] = whole((h - (180 if h >= 180 else 0)) * 256 / 180, "selected heading")
    if tc == 31:
        for f, k in (("version", "version"), ("nic_supplement_a", "nic_supp_a"), ("nac_p", "nac_p"), ("sil", "sil"),
                     ("hrd", "hrd"), ("capability_class", "capability_class"),
                     ("operational_mode", "operational_mode"), ("nic_baro", "nic_baro"),
                     ("sil_supplement", "sil_supp")):
            if d.get(f) is not None:
                m["adsb." + k] = str(int(d[f]))
    return m


def messages(cache):
    """[(hex, origin)] in a fixed order: the capture's first PER_TYPE per type code and
    subtype, then the test files' own messages."""
    out, seen = [], set()
    capture = fetch(FILES[0][0], FILES[0][1], cache).decode("utf-8-sig")
    for row in csv.reader(io.StringIO(capture)):
        if len(row) > 1:
            out.append((row[1].upper(), FILES[0][0]))
    for path, sha in sorted(TEST_FILES.items()):
        for h in HEX.findall(fetch(path, sha, cache).decode("utf-8")):
            out.append((h.upper(), path))
    return out


def build(pms, cache):
    vecs, count, done = {}, {}, set()
    for msg, origin in messages(cache):
        if msg in done:
            continue
        try:
            d = dict(pms.decode(msg))
        except Exception:
            continue
        if d.get("df") != 17 or not d.get("crc_valid"):
            continue
        kind = kind_of(d)
        if kind is None or count.get(kind, 0) >= PER_TYPE:
            continue
        done.add(msg)
        count[kind] = count.get(kind, 0) + 1
        name = "golden-%s-%d" % (kind, count[kind])
        vecs[name + ".json"] = {
            # input as recorded; the expected output is its canonical form, lowercase hex (vector-format)
            "name": name, "from": "adsb", "to": "adsb", "input": msg, "expect": msg.lower(),
            "model": dict({"@kind": kind}, **model_of(d)),
            "source": "pyModeS %s: pyModeS.decode of a message from %s at %s (github.com/%s). Written by "
                      "tools/gen/golden-pymodes.py; no engine is run." % (PYMODES, origin, COMMIT[:7], REPO),
            "reference": "DF17 type code %d as pyModeS (GPL-3.0) decodes it; raw fields that pyModeS reports scaled "
                         "are turned back by the DO-260B scaling named in tools/gen/golden-pymodes.py." % d["typecode"],
        }
    return vecs


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-pymodes", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".cache", "golden-pymodes"))
    args = ap.parse_args(argv)
    try:
        import pyModeS as pms
        from importlib.metadata import version
        if version("pyModeS") != PYMODES:
            raise ImportError(version("pyModeS"))
    except ImportError as e:
        print("golden-pymodes: pyModeS %s is not importable (%s); pip install --require-hashes -r "
              "tools/gen/golden-pymodes.txt" % (PYMODES, e), file=sys.stderr)
        return 1
    vecs = build(pms, args.cache)
    have = {n for n in os.listdir(OUT) if n.startswith("golden-") and n.endswith(".json")}
    if args.check:
        bad = sorted(n for n in set(vecs) | have
                     if n not in vecs or n not in have or open(os.path.join(OUT, n), encoding="utf-8").read() != text(vecs[n]))
        if bad:
            print("golden-pymodes: %d vector(s) differ from what pyModeS writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-pymodes: --check: ok, %d vectors" % len(vecs))
        return 0
    for n in have - set(vecs):
        os.remove(os.path.join(OUT, n))
    for n, v in vecs.items():
        with open(os.path.join(OUT, n), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-pymodes: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
