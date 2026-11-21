#!/usr/bin/env python3
"""ais-regional-vectors: write the vectors of pack ais-binary-regional.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of the St. Lawrence Seaway AIS Data Messaging Formats and
Specifications, Revision 4.1 (sections 1 to 9 and Appendix A): fields most significant bit first,
payloads armored six bits a character with zero fill.

Inputs: payloads built here from values chosen here; none is taken from the document's examples or a
capture. MMSIs are of a test form; station and vessel names are invented.

`expect` of every round trip is this program's armoring of the packed values, which for these
payloads is the input; `model` holds values that were packed.

Usage: python3 -I tools/gen/ais-regional-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

P = "ais-binary-regional"
SOURCE = "built by tools/gen/ais-regional-vectors.py from values chosen there; layout restated from the St. Lawrence Seaway AIS specification R4.1, %s; expect derived there, no engine run"


def vec(name, inp, model=None, error=None, ref=""):
    v = {"name": name, "from": P, "to": P, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


def bits(fields):
    out = []
    for v, w in fields:
        if v < 0:
            v += 1 << w
        assert 0 <= v < (1 << w), (v, w)
        out.append(format(v, "0%db" % w))
    return "".join(out)


def armor(b):
    b += "0" * (-len(b) % 6)
    return "".join(chr(0x30 + v if v < 40 else 0x38 + v) for v in (int(b[i:i + 6], 2) for i in range(0, len(b), 6)))


def six(text, n):
    t = text.ljust(n, "@")
    assert len(t) == n
    return "".join(format(ord(c) - 0x40 if ord(c) >= 0x40 else ord(c), "06b") for c in t)


def broadcast(dac, fid, mid):
    return bits([(8, 6), (0, 2), (3160001, 30), (0, 2), (dac, 10), (fid, 6), (0, 2), (mid, 6)])


def addressed(dac, fid, mid):
    return bits([(6, 6), (0, 2), (3160001, 30), (1, 2), (316000222, 30), (0, 1), (0, 1), (dac, 10), (fid, 6), (0, 2), (mid, 6)])


def tt(mo, d, h, mi):
    return bits([(mo, 4), (d, 5), (h, 5), (mi, 6)])


def stn(name, lon, lat, when=(5, 29, 0, 34)):
    return tt(*when) + six(name, 7) + bits([(lon, 25), (lat, 24)])


LON, LAT = -4521000, 2671800   # 75.35 W, 44.53 N in thousandths of a minute


def vectors():
    out = []
    w = broadcast(316, 1, 2) + stn("ABAY", LON, LAT) + bits([(32, 10), (40, 10), (293, 9), (0, 4)]) + \
        stn("TIBRDG", LON + 6000, LAT + 3000) + bits([(1023, 10), (1023, 10), (511, 9), (0, 4)])
    out.append(("01-wind-two-stations-roundtrip.json", vec("wind-two-stations-roundtrip", armor(w),
                {"aisbin.dac": "316", "aisbin.fid": "1", "aisregion.message_id": "2", "aisregion.reports.#": "2",
                 "aisregion.reports[0].aisregion.station_id": "ABAY", "aisregion.reports[0].aisregion.lon": str(LON),
                 "aisregion.reports[0].aisregion.wind_speed": "32", "aisregion.reports[0].aisregion.wind_dir": "293",
                 "aisregion.reports[1].aisregion.wind_gust": "1023", "aisregion.reports[1].aisregion.wind_dir": "511"},
                ref="section 3; two wind reports, the second not available")))
    wx = broadcast(366, 1, 1) + stn("ABAY", LON, LAT) + bits([(55, 10), (70, 10), (225, 9), (10132, 14), (-35, 10, ), (-80, 10), (120, 8), (-512, 10)])
    out.append(("02-weather-station-roundtrip.json", vec("weather-station-roundtrip", armor(wx),
                {"aisbin.dac": "366", "aisregion.message_id": "1", "aisregion.reports.#": "1",
                 "aisregion.reports[0].aisregion.pressure": "10132", "aisregion.reports[0].aisregion.air_temp": "-35",
                 "aisregion.reports[0].aisregion.dew_point": "-80", "aisregion.reports[0].aisregion.visibility": "120",
                 "aisregion.reports[0].aisregion.water_temp": "-512"},
                ref="section 4; one weather station report below freezing, water temperature not available")))
    wl = broadcast(316, 1, 3) + stn("IROQUOI", LON, LAT) + bits([(0, 1), (7425, 16), (1, 2), (0, 2), (0, 12)]) + \
        stn("SNELL", LON - 1000, LAT - 1000) + bits([(0, 1), (-32768, 16), (1, 2), (1, 2), (0, 12)])
    out.append(("03-water-level-roundtrip.json", vec("water-level-roundtrip", armor(wl),
                {"aisregion.message_id": "3", "aisregion.reports.#": "2", "aisregion.reports[0].aisregion.level": "7425",
                 "aisregion.reports[0].aisregion.level_datum": "1", "aisregion.reports[1].aisregion.level": "-32768",
                 "aisregion.reports[1].aisregion.reading_type": "1"},
                ref="section 5; two water level reports on IGLD-85, the second estimated and not available")))
    wf = broadcast(316, 1, 6) + stn("MOSES", LON, LAT) + bits([(7100, 14), (0, 19)])
    out.append(("04-water-flow-roundtrip.json", vec("water-flow-roundtrip", armor(wf),
                {"aisregion.message_id": "6", "aisregion.reports[0].aisregion.water_flow": "7100"},
                ref="section 6; one water flow report")))
    hc = broadcast(366, 1, 4) + stn("PAWS01", LON, LAT) + bits([(15, 8), (90, 9), (0, 16)])
    out.append(("05-pawss-hydro-current-roundtrip.json", vec("pawss-hydro-current-roundtrip", armor(hc),
                {"aisregion.message_id": "4", "aisregion.reports[0].aisregion.current_speed": "15",
                 "aisregion.reports[0].aisregion.current_dir": "90"},
                ref="Appendix A, Hydro/Current; one report")))
    hs = broadcast(366, 1, 5) + stn("PAWS02", LON, LAT) + bits([(305, 10), (-15, 10), (0, 13)])
    out.append(("06-pawss-salinity-temperature-roundtrip.json", vec("pawss-salinity-temperature-roundtrip", armor(hs),
                {"aisregion.message_id": "5", "aisregion.reports[0].aisregion.salinity": "305",
                 "aisregion.reports[0].aisregion.water_temp": "-15"},
                ref="Appendix A, Hydro/Salinity Temp; one report")))
    lo = broadcast(316, 2, 1) + tt(6, 2, 14, 5) + six("SNELL", 7) + bits([(LON, 25), (LAT, 24), (0, 9)]) + \
        six("LAKE CARRIER ON", 15) + bits([(1, 1)]) + tt(6, 2, 15, 30) + bits([(0, 9)]) + \
        six("TEST BULKER", 15) + bits([(0, 1)]) + tt(6, 2, 16, 45) + bits([(0, 9)])
    out.append(("07-lockage-order-roundtrip.json", vec("lockage-order-roundtrip", armor(lo),
                {"aisbin.fid": "2", "aisregion.message_id": "1", "aisregion.lock_id": "SNELL", "aisregion.hour": "14",
                 "aisregion.schedule.#": "2", "aisregion.schedule[0].aisregion.vessel_name": "LAKE CARRIER ON",
                 "aisregion.schedule[0].aisregion.upbound": "1", "aisregion.schedule[1].aisregion.eta_minute": "45"},
                ref="section 7; a lockage order with two vessels")))
    et = addressed(366, 2, 2) + tt(6, 2, 12, 0) + six("TEST BULKER", 15) + six("CAPE", 7) + tt(6, 2, 11, 10) + \
        six("SNELL", 7) + tt(6, 2, 13, 0) + six("EISENHO", 7) + tt(6, 2, 14, 20) + six("@", 7) + bits([(0, 4)])
    out.append(("08-estimated-lock-times-addressed-roundtrip.json", vec("estimated-lock-times-addressed-roundtrip", armor(et),
                {"ais.msg_type": "6", "ais.dest_mmsi": "316000222", "aisregion.message_id": "2",
                 "aisregion.vessel_name": "TEST BULKER", "aisregion.last_location": "CAPE", "aisregion.first_lock": "SNELL",
                 "aisregion.first_eta_hour": "13", "aisregion.second_lock": "EISENHO", "aisregion.second_eta_minute": "20",
                 "aisregion.locktimes_spare": "0"},
                ref="section 8; an addressed estimated lock times message with no delayed lock (all @)")))
    vm = broadcast(316, 32, 1) + bits([(4, 8), (1, 8), (0, 8)])
    out.append(("09-version-roundtrip.json", vec("version-roundtrip", armor(vm),
                {"aisbin.fid": "32", "aisregion.message_id": "1", "aisregion.major_version": "4",
                 "aisregion.minor_version": "1"}, ref="section 9; version 4.1")))
    other = armor(broadcast(366, 1, 9) + "0" * 120)
    out.append(("10-unknown-message-id-is-no-kind.json", vec("unknown-message-id-is-no-kind", other, error="no-kind",
                ref="section 1.1; FI 1 message ID 9, not assigned")))
    out.append(("11-cut-report-is-malformed.json", vec("cut-report-is-malformed", armor(wf)[:20], error="malformed-wire",
                ref="section 6; the water flow message of vector 04 cut inside its report")))
    return out


def build_files(out):
    written = {}
    for fname, v in vectors():
        out.write("packs/%s/vectors/%s" % (P, fname), json.dumps(v, indent=2) + "\n")
        written[P] = written.get(P, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("ais-regional-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
