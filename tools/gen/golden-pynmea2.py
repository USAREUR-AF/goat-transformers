#!/usr/bin/env python3
"""golden-pynmea2: golden vectors for packs/nmea0183 from pynmea2, a reference
NMEA 0183 parser (shared-model hardening, item 2: meaning is tested against
an implementation outside this project, not only engine agreement).

For RMC, GGA, GLL and VTG it builds sentences with pynmea2 from field text
written in the pack's canonical forms (hms:2, dm:2:5 and dm:3:5, dec:N,
int:N), so the sentence is also the pack's canonical form, and writes
packs/nmea0183/vectors/golden-<kind>-<n>.json:

  input, expect  the sentence as pynmea2 renders it, checksum included: a
                 round trip
  model          "@kind", the talker, and the values pynmea2 itself parses
                 from that sentence (its decimal latitude and longitude, its
                 date and time, its speeds and courses, its fix fields), under
                 the pack's keys
  source         pynmea2, its version; no engine is run

Usage (pynmea2 1.19.0 importable; standard library otherwise):

  python3 -I tools/gen/golden-pynmea2.py            write the vectors
  python3 -I tools/gen/golden-pynmea2.py --check    exit 1 when a committed
                                                    vector differs (CI)
"""
import argparse
import calendar
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "packs", "nmea0183", "vectors")
PYNMEA2 = "1.19.0"

# (talker, latitude deg, longitude deg, hh, mm, ss.ss, day, month, two-digit year)
# in every quadrant, near the poles and the antimeridian; dates in 2026
POINTS = [
    ("GP", 48.1251234, 11.5823456, 9, 45, 12.50, 15, 3, 26),
    ("GN", -33.8688197, 151.2092955, 23, 59, 59.99, 31, 12, 26),
    ("GP", 40.7127753, -74.0059728, 0, 0, 0.00, 1, 1, 26),
    ("GL", -54.8019121, -68.3029511, 12, 30, 45.25, 29, 2, 24),
    ("GN", 78.2231722, 15.6267229, 6, 7, 8.09, 21, 6, 26),
    ("GP", -0.0012345, 179.9876543, 18, 1, 2.30, 10, 11, 26),
]


def dm(value, deg_digits):
    """Degrees to the pack's dm form: degrees zero-padded, minutes with two
    integer and five fraction digits, and the hemisphere letter."""
    a = abs(value)
    d = int(a)
    m = round((a - d) * 60, 5)
    if m >= 60:
        d, m = d + 1, 0.0
    return "%0*d%08.5f" % (deg_digits, d, m)


def hemi(value, pos, neg):
    return pos if value >= 0 else neg


def hms(h, m, s):
    return "%02d%02d%05.2f" % (h, m, s)


def build(pynmea2):
    out = {}
    for i, (talker, lat, lon, h, mi, s, day, mon, yy) in enumerate(POINTS, 1):
        course = "%.2f" % ((37.5 + 61.25 * i) % 360)
        mag = "%.2f" % ((33.25 + 61.25 * i) % 360)
        sog_kn = "%.3f" % (0.125 + 7.25 * i)
        sog_kmh = "%.3f" % (float(sog_kn) * 1.852)
        common = [dm(lat, 2), hemi(lat, "N", "S"), dm(lon, 3), hemi(lon, "E", "W")]
        sentences = {
            "rmc": pynmea2.RMC(talker, "RMC", [hms(h, mi, s), "A"] + common +
                               [sog_kn, course, "%02d%02d%02d" % (day, mon, yy), "%.1f" % (1.5 + i / 10), "EW"[i % 2], "A"]),
            "gga": pynmea2.GGA(talker, "GGA", [hms(h, mi, s)] + common +
                               [str(1 + i % 2), "%02d" % (6 + i), "%.2f" % (0.75 + i / 4), "%.1f" % (123.4 + 37 * i), "M",
                                "%.1f" % (47.5 - 20 * i), "M", "", ""]),
            "gll": pynmea2.GLL(talker, "GLL", common + [hms(h, mi, s), "A", "AD"[i % 2]]),
            "vtg": pynmea2.VTG(talker, "VTG", [course, "T", mag, "M", sog_kn, "N", sog_kmh, "K", "A"]),
        }
        for kind, msg in sentences.items():
            text = str(msg)
            back = pynmea2.parse(text)      # pynmea2's own reading of the sentence
            model = {"@kind": kind, "nmea0183.talker": back.talker}
            if kind in ("rmc", "gga", "gll"):
                model["lat"] = repr(back.latitude)
                model["lon"] = repr(back.longitude)
            if kind == "rmc":
                dt = back.datetime
                model["time_ms"] = str(calendar.timegm(dt.utctimetuple()) * 1000 + dt.microsecond // 1000)
                model["nmea0183.status"] = back.status
                model["nmea0183.sog_kn"] = repr(float(back.spd_over_grnd))
                model["course"] = repr(float(back.true_course))
            if kind == "gga":
                model["nmea0183.quality"] = str(back.gps_qual)
                model["nmea0183.sats_used"] = str(int(back.num_sats))
                model["nmea0183.hdop"] = repr(float(back.horizontal_dil))
                model["nmea0183.alt_msl_m"] = repr(float(back.altitude))
                model["nmea0183.geoid_sep_m"] = repr(float(back.geo_sep))
            if kind == "gll":
                model["nmea0183.status"] = back.status
                model["nmea0183.faa_mode"] = back.faa_mode
            if kind == "vtg":
                model["course"] = repr(float(back.true_track))
                model["nmea0183.course_mag_deg"] = repr(float(back.mag_track))
                model["nmea0183.sog_kn"] = repr(float(back.spd_over_grnd_kts))
                model["nmea0183.sog_kmh"] = repr(float(back.spd_over_grnd_kmph))
                model["nmea0183.faa_mode"] = back.faa_mode
            name = "golden-%s-%d" % (kind, i)
            out[name + ".json"] = {
                "name": name,
                "from": "nmea0183",
                "to": "nmea0183",
                "input": text,
                "expect": text,
                "model": model,
                "source": "pynmea2 %s: pynmea2.%s(%r, %r, fields).render, then pynmea2.parse of that sentence for "
                          "the model values. Written by tools/gen/golden-pynmea2.py; no engine is run."
                          % (PYNMEA2, kind.upper(), talker, kind.upper()),
                "reference": "NMEA 0183 %s as pynmea2 reads it: latitude and longitude from ddmm.mmmmm and dddmm.mmmmm "
                             "with the hemisphere, time from hhmmss.ss%s. Field text is written in the pack's "
                             "canonical forms (packs/nmea0183/pack.def), so the sentence round-trips unchanged."
                             % (kind.upper(), " and the date ddmmyy" if kind == "rmc" else ""),
            }
    return out


def text(vec):
    return json.dumps(vec, indent=1, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="golden-pynmea2", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        import pynmea2
    except ImportError:
        print("golden-pynmea2: pynmea2 %s is not importable (pip install pynmea2==%s)" % (PYNMEA2, PYNMEA2), file=sys.stderr)
        return 1
    vecs = build(pynmea2)
    have = {n for n in os.listdir(OUT) if n.startswith("golden-") and n.endswith(".json")}
    if args.check:
        bad = sorted(n for n in set(vecs) | have
                     if n not in vecs or n not in have or open(os.path.join(OUT, n), encoding="utf-8").read() != text(vecs[n]))
        if bad:
            print("golden-pynmea2: %d vector(s) differ from what pynmea2 writes: %s" % (len(bad), ", ".join(bad[:10])),
                  file=sys.stderr)
            return 1
        print("golden-pynmea2: --check: ok, %d vectors" % len(vecs))
        return 0
    for n in have - set(vecs):
        os.remove(os.path.join(OUT, n))
    for n, v in vecs.items():
        with open(os.path.join(OUT, n), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text(v))
    print("golden-pynmea2: wrote %d vectors" % len(vecs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
