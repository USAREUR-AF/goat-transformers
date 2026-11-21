#!/usr/bin/env python3
"""ais-apps-vectors: write the vectors of pack ais-binary-apps.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of gpsd's AIVDM document (IMO236 Tidal Window, IMO289 Dangerous Cargo
Indication, Route Information, Tidal Window (IMO289), VTS-Generated/Synthetic
targets, IMO289 Environmental): fields most significant bit first, payloads armored six bits a
character with zero fill.

Inputs: payloads built here from values chosen here; none is taken from the document or a capture.
MMSIs are of a test form.

`expect` of every round trip is this program's armoring of the packed values, which for these
payloads is the input; `model` holds values that were packed.

Usage: python3 -I tools/gen/ais-apps-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

P = "ais-binary-apps"
SOURCE = "built by tools/gen/ais-apps-vectors.py from values chosen there; layout restated from gpsd AIVDM.adoc, %s; expect derived there, no engine run"


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
    return "".join(format(ord(c) - 0x40 if ord(c) >= 0x40 else ord(c), "06b") for c in t)


def addressed(fid):
    return bits([(6, 6), (0, 2), (211000001, 30), (0, 2), (211000002, 30), (0, 1), (0, 1), (1, 10), (fid, 6)])


def broadcast(fid):
    return bits([(8, 6), (0, 2), (211000001, 30), (0, 2), (1, 10), (fid, 6)])


def report(sensor, day, hour, minute, site, payload):
    assert len(payload) == 85, (sensor, len(payload))
    return bits([(sensor, 4), (day, 5), (hour, 5), (minute, 6), (site, 7)]) + payload


def vectors():
    out = []
    t236 = addressed(14) + bits([(5, 4), (20, 5)])
    for lat, lon, fh, fm, th, tm, cd, cs in [(32298000, 4920000, 6, 0, 8, 30, 90, 25), (-100, -200, 18, 15, 20, 45, 270, 126)]:
        t236 += bits([(lat, 27), (lon, 28), (fh, 5), (fm, 6), (th, 5), (tm, 6), (cd, 9), (cs, 7)])
    out.append(("01-tidal-window-imo236-roundtrip.json", vec("tidal-window-imo236-roundtrip", armor(t236),
                {"aisbin.fid": "14", "aisapp.month": "5", "aisapp.day": "20", "aisapp.tidals.#": "2",
                 "aisapp.tidals[0].aisapp.tw_lat": "32298000", "aisapp.tidals[0].aisapp.to_min": "30",
                 "aisapp.tidals[1].aisapp.tw_lon": "-200", "aisapp.tidals[1].aisapp.cspeed": "126"},
                ref="IMO236 Tidal Window; two predictions")))
    t289 = addressed(32) + bits([(0, 4), (0, 5)])
    for lon, lat, cs in [(492000, 3229800, 250), (492100, 3229900, 251), (181000, 91000, 255)]:
        t289 += bits([(lon, 25), (lat, 24), (24, 5), (60, 6), (24, 5), (60, 6), (360, 9), (cs, 8)])
    out.append(("02-tidal-window-imo289-roundtrip.json", vec("tidal-window-imo289-roundtrip", armor(t289),
                {"aisbin.fid": "32", "aisapp.tidals.#": "3", "aisapp.tidals[0].aisapp.tw_lon": "492000",
                 "aisapp.tidals[1].aisapp.cspeed": "251", "aisapp.tidals[2].aisapp.tw_lat": "91000",
                 "aisapp.tidals[2].aisapp.cdir": "360"},
                ref="Tidal Window (IMO289); three predictions, the last not available")))
    cg = addressed(25) + bits([(1, 2), (500, 10), (1, 4), (3, 13), (2, 4), (1203, 13)])
    out.append(("03-dangerous-cargo-imo289-roundtrip.json", vec("dangerous-cargo-imo289-roundtrip", armor(cg),
                {"aisbin.fid": "25", "aisapp.cargo_unit": "1", "aisapp.cargo_amount": "500", "aisapp.cargos.#": "2",
                 "aisapp.cargos[1].aisapp.cargo_code": "2", "aisapp.cargos[1].aisapp.cargo_subtype": "1203"},
                ref="IMO289 Dangerous Cargo Indication; an IMDG class and a UN number")))
    wps = [(4920000, 32298000), (4921000, 32299000), (-1000000, -2000000)]
    ra = addressed(28) + bits([(7, 10), (1, 3), (2, 5), (6, 4), (1, 5), (12, 5), (0, 6), (120, 18), (len(wps), 5)])
    for lon, lat in wps:
        ra += bits([(lon, 28), (lat, 27)])
    out.append(("04-route-addressed-roundtrip.json", vec("route-addressed-roundtrip", armor(ra),
                {"aisbin.fid": "28", "aisapp.linkage": "7", "aisapp.sender": "1", "aisapp.route_type": "2",
                 "aisapp.duration": "120", "aisapp.waypoints.#": "3", "aisapp.waypoints[2].aisapp.wp_lon": "-1000000",
                 "aisapp.waypoints[2].aisapp.wp_lat": "-2000000"},
                ref="IMO289 Route Information (addressed); three waypoints")))
    rb = broadcast(27) + bits([(9, 10), (0, 3), (5, 5), (0, 4), (0, 5), (24, 5), (60, 6), (262143, 18), (1, 5), (4920000, 28), (32298000, 27)])
    out.append(("05-route-broadcast-roundtrip.json", vec("route-broadcast-roundtrip", armor(rb),
                {"aisbin.fid": "27", "aisapp.route_type": "5", "aisapp.duration": "262143", "aisapp.waypoints.#": "1"},
                ref="IMO289 Route Information (broadcast); one waypoint, no start time")))
    # 06 (text description broadcast, 11 characters) was dropped: its last character leaves 6 bits, and a
    # list to the end of the payload stops when fewer than 8 bits remain (engine-spec 0.21, the message
    # counted in bytes), so the character reads as padding; an engine found it, so rule 16 of the brief
    # drops the vector, and the text descriptions (FI 29 and 30) are not built (pack.md). 07 (text
    # addressed) went with them.
    vt = broadcast(17)
    vt += bits([(0, 2), (211000009, 42), (0, 4), (3229800, 24), (492000, 25), (45, 9), (30, 6), (12, 10)])
    vt += bits([(2, 2)]) + six("ABC1234", 7) + bits([(0, 4), (-91000 + 1000, 24), (181000, 25), (360, 9), (60, 6), (255, 10)])
    out.append(("08-vts-targets-roundtrip.json", vec("vts-targets-roundtrip", armor(vt),
                {"aisbin.fid": "17", "aisapp.targets.#": "2", "aisapp.targets[0].aisapp.idtype": "0",
                 "aisapp.targets[0].aisapp.target_id": "211000009", "aisapp.targets[0].aisapp.speed": "12",
                 "aisapp.targets[1].aisapp.idtype": "2", "aisapp.targets[1].aisapp.target_name": "ABC1234",
                 "aisapp.targets[1].aisapp.target_lat": "-90000"},
                ref="VTS-Generated/Synthetic targets; one by MMSI, one by call sign")))
    site = bits([(4920000, 28), (32298000, 27), (12, 11), (5, 4), (2, 3), (0, 12)])
    wind = bits([(15, 7), (22, 7), (250, 9), (255, 9), (2, 3), (18, 7), (25, 7), (260, 9), (14, 5), (12, 5), (0, 6), (60, 8), (0, 3)])
    wx = bits([(-55, 11), (2, 3), (0, 2), (120, 8), (-80, 10), (2, 3), (213, 9), (1, 2), (2, 3), (0, 9), (0, 25)])
    e1 = broadcast(26) + report(0, 14, 10, 0, 7, site) + report(2, 14, 10, 0, 7, wind) + report(9, 14, 10, 0, 7, wx)
    out.append(("09-environmental-site-wind-weather-roundtrip.json", vec("environmental-site-wind-weather-roundtrip", armor(e1),
                {"aisbin.fid": "26", "aisapp.reports.#": "3", "aisapp.reports[0].aisapp.sensor": "0",
                 "aisapp.reports[0].aisapp.site_alt": "12", "aisapp.reports[0].aisapp.owner": "5",
                 "aisapp.reports[1].aisapp.wind_gust_dir": "255", "aisapp.reports[1].aisapp.fc_duration": "60",
                 "aisapp.reports[2].aisapp.air_temp": "-55", "aisapp.reports[2].aisapp.dew_point": "-80",
                 "aisapp.reports[2].aisapp.air_pressure": "213"},
                ref="IMO289 Environmental; site location, wind and weather reports")))
    lvl = bits([(1, 1), (-150, 16), (2, 2), (11, 5), (1, 3), (1, 1), (-1400, 16), (15, 5), (6, 5), (30, 6), (180, 8), (0, 17)])
    sea = bits([(15, 8), (9, 6), (200, 9), (4, 4), (1, 3), (250, 10), (5, 7), (1, 3), (12, 8), (6, 6), (210, 9), (1, 3), (350, 9)])
    gap = bits([(1850, 13), (2400, 13), (1, 2), (2350, 13), (15, 5), (8, 5), (0, 6), (0, 28)])
    e2 = broadcast(26) + report(3, 15, 6, 0, 3, lvl) + report(7, 15, 6, 0, 3, sea) + report(10, 15, 6, 0, 3, gap)
    out.append(("10-environmental-level-sea-airgap-roundtrip.json", vec("environmental-level-sea-airgap-roundtrip", armor(e2),
                {"aisapp.reports.#": "3", "aisapp.reports[0].aisapp.level": "-150", "aisapp.reports[0].aisapp.level_datum": "11",
                 "aisapp.reports[0].aisapp.fc_level": "-1400", "aisapp.reports[1].aisapp.sea_state": "4",
                 "aisapp.reports[1].aisapp.salinity": "350", "aisapp.reports[2].aisapp.air_gap": "2400",
                 "aisapp.reports[2].aisapp.fc_air_gap": "2350"},
                ref="IMO289 Environmental; water level, sea state and air gap reports")))
    sta = six("PIER 7 GAUGE", 14) + bits([(0, 1)])
    c2 = bits([(15, 8), (90, 9), (5, 9), (12, 8), (95, 9), (10, 9), (9, 8), (100, 9), (20, 9), (2, 3), (0, 4)])
    sal = bits([(250, 10), (45, 10), (100, 16), (350, 9), (0, 2), (2, 3), (0, 35)])
    c3 = bits([(5, 8), (6, 8), (1, 8), (5, 9), (4, 8), (7, 8), (0, 8), (10, 9), (2, 3), (0, 16)])
    hz = bits([(45, 9), (100, 7), (8, 8), (50, 9), (3, 9), (135, 9), (50, 7), (6, 8), (60, 9), (6, 9), (0, 1)])
    e3 = (broadcast(26) + report(1, 1, 0, 0, 9, sta) + report(4, 1, 0, 0, 9, c2) + report(8, 1, 0, 0, 9, sal) +
          report(5, 1, 0, 0, 9, c3) + report(6, 1, 0, 0, 9, hz))
    out.append(("11-environmental-five-reports-roundtrip.json", vec("environmental-five-reports-roundtrip", armor(e3),
                {"aisapp.reports.#": "5", "aisapp.reports[0].aisapp.station_name": "PIER 7 GAUGE",
                 "aisapp.reports[1].aisapp.cdir3": "100", "aisapp.reports[2].aisapp.conductivity": "45",
                 "aisapp.reports[3].aisapp.cnorth1": "5", "aisapp.reports[4].aisapp.hdistance2": "50"},
                ref="IMO289 Environmental; the largest message, five reports: station ID, 2D current, salinity, 3D current, "
                    "horizontal current")))
    other = armor(broadcast(31) + "0" * 100)
    out.append(("12-other-fi-is-no-kind.json", vec("other-fi-is-no-kind", other, error="no-kind",
                ref="a type 8 DAC 1 FI 31 message, which ais-binary reads")))
    cut = broadcast(27) + bits([(9, 10), (0, 3), (5, 5), (0, 4), (0, 5), (24, 5), (60, 6), (262143, 18), (3, 5), (4920000, 28), (32298000, 27)])
    out.append(("13-route-short-of-its-count-is-malformed.json", vec("route-short-of-its-count-is-malformed", armor(cut),
                error="malformed-wire", ref="IMO289 Route Information (broadcast); a waypoint count of 3 with one waypoint")))
    return out


def build_files(out):
    written = {}
    for fname, v in vectors():
        out.write("packs/%s/vectors/%s" % (P, fname), json.dumps(v, indent=2) + "\n")
        written[P] = written.get(P, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("ais-apps-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
