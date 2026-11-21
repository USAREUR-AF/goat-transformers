#!/usr/bin/env python3
"""maritime-vectors: write the vectors of the maritime packs.

Packs: rtz-route, nmea-tag-block, nmea0183-pubx, ais-area-notice.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of the CIRM RTZ 1.2 schema, gpsd's AIVDM document (NMEA Tag Blocks;
IMO289 Area Notice, Subarea Types and Payloads) and gpsd's NMEA Revealed (PUBX 00, 01, 03, 04).

Inputs: documents, sentences and payloads built here from values chosen here; none is taken from a
document's examples or a capture. Positions are invented; MMSIs are of the 9-digit test form.

`expect` of every vector is this program's writing of the decoded values in the canonical form of
its wire (XML attributes in the order the pack names them, numbers in their shortest form; NMEA
fields as the transforms write them; AIS payload six bits a character with zero fill), which for
these inputs is the input; `model` holds values that were written.

Usage: python3 -I tools/gen/maritime-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import sys
from functools import reduce

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/maritime-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_RTZ = "the CIRM RTZ 1.2 schema"
R_TAG = "gpsd AIVDM.adoc, NMEA Tag Blocks"
R_PUBX = "gpsd NMEA.adoc, PUBX 00, 01, 03 and 04"
R_AREA = "gpsd AIVDM.adoc, IMO289 Area Notice and its sub-area tables"


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


# ---------------------------------------------------------------- RTZ

NS = "http://www.cirm.org/RTZ/1/2"


def attrs(pairs):
    return "".join(' %s="%s"' % (k, v) for k, v in pairs)


def el(name, pairs=(), children=""):
    return "<%s%s/>" % (name, attrs(pairs)) if not children else "<%s%s>%s</%s>" % (name, attrs(pairs), children, name)


def waypoint(wid, rev, lat, lon, name=None, radius=None, leg=()):
    a = [("id", wid), ("revision", rev)] + ([("name", name)] if name else []) + ([("radius", radius)] if radius else [])
    return el("waypoint", a, el("position", [("lat", lat), ("lon", lon)]) + (el("leg", leg) if leg else ""))


def rtz_vectors():
    p = "rtz-route"
    out = []
    info = [("routeName", "Harbour approach"), ("routeAuthor", "Planner A"), ("routeStatus", "planned"),
            ("validityPeriodStart", "2026-03-01T06:00:00Z"), ("vesselName", "TEST VESSEL"), ("vesselMMSI", "123456789"),
            ("vesselIMO", "9000001"), ("vesselSpeedMax", "18.5")]
    wps = (el("defaultWaypoint", [("radius", "0.5")], el("leg", [("starboardXTD", "0.1"), ("portsideXTD", "0.1")])) +
           waypoint("1", "0", "53.5", "8.125", "Start") +
           waypoint("2", "1", "53.75", "8.25", "Turn", "0.3", [("starboardXTD", "0.2"), ("portsideXTD", "0.15"),
                                                               ("geometryType", "Loxodrome"), ("speedMax", "12")]) +
           waypoint("3", "0", "54", "8.5", "End"))
    sch = el("schedules", (), el("schedule", [("id", "1"), ("name", "Base")],
                                 el("manual", (), el("scheduleElement", [("waypointId", "1"), ("etd", "2026-03-01T06:00:00Z")]) +
                                    el("scheduleElement", [("waypointId", "3"), ("eta", "2026-03-01T09:30:00Z"), ("speed", "11.5")]))))
    doc = el("route", [("xmlns", NS), ("version", "1.2")], el("routeInfo", info) + el("waypoints", (), wps) + sch)
    out.append((p, "01-route-with-schedule-roundtrip.json", vec(p, "route-with-schedule-roundtrip", doc,
                {"rtz.route_name": "Harbour approach", "rtz.vessel_mmsi": "123456789", "rtz.vessel_speed_max": "18.5",
                 "rtz.default_radius": "0.5", "rtz.default_starboard_xtd": "0.1", "rtz.waypoints.#": "3",
                 "rtz.waypoints[1].rtz.id": "2", "rtz.waypoints[1].rtz.lat": "53.75", "rtz.waypoints[1].rtz.radius": "0.3",
                 "rtz.waypoints[1].rtz.geometry_type": "Loxodrome", "rtz.waypoints[1].rtz.speed_max": "12",
                 "rtz.schedule_id": "1", "rtz.manual_elements.#": "2",
                 "rtz.manual_elements[1].rtz.eta": "2026-03-01T09:30:00Z", "rtz.manual_elements[1].rtz.speed": "11.5"},
                ref=R_RTZ + "; route information, a default waypoint, three waypoints with a leg, and a manual schedule")))
    doc2 = el("route", [("xmlns", NS), ("version", "1.2")],
              el("routeInfo", [("routeName", "Minimal")]) + el("waypoints", (), waypoint("10", "2", "-33.875", "151.25") +
                                                                 waypoint("11", "2", "-34", "151.5")))
    out.append((p, "02-minimal-route-roundtrip.json", vec(p, "minimal-route-roundtrip", doc2,
                {"rtz.route_name": "Minimal", "rtz.waypoints.#": "2", "rtz.waypoints[0].rtz.lat": "-33.875",
                 "rtz.waypoints[1].rtz.lon": "151.5"},
                ref=R_RTZ + "; the least a route holds: its name and two waypoints")))
    calc = el("route", [("xmlns", NS), ("version", "1.2")],
              el("routeInfo", [("routeName", "Optimized"), ("optimizationMethod", "fuel")]) +
              el("waypoints", (), waypoint("1", "0", "10", "20") + waypoint("2", "0", "10.5", "20.5")) +
              el("schedules", (), el("schedule", [("id", "7")], el("calculated", (), el("scheduleElement", [
                  ("waypointId", "2"), ("eta", "2026-04-02T12:00:00Z"), ("speed", "14.25"), ("windSpeed", "22"),
                  ("windDirection", "270"), ("rpm", "95"), ("relFuelSave", "3.5")])))))
    out.append((p, "03-calculated-schedule-roundtrip.json", vec(p, "calculated-schedule-roundtrip", calc,
                {"rtz.optimization_method": "fuel", "rtz.schedule_id": "7", "rtz.calculated_elements.#": "1",
                 "rtz.calculated_elements[0].rtz.wind_direction": "270", "rtz.calculated_elements[0].rtz.rpm": "95",
                 "rtz.calculated_elements[0].rtz.rel_fuel_save": "3.5"},
                ref=R_RTZ + "; an optimized route with a calculated schedule element")))
    v11 = el("route", [("xmlns", "http://www.cirm.org/RTZ/1/1"), ("version", "1.1")],
             el("routeInfo", [("routeName", "Old")]) + el("waypoints", (), waypoint("1", "0", "1", "2") + waypoint("2", "0", "3", "4")))
    out.append((p, "04-rtz-1-1-is-no-kind.json", vec(p, "rtz-1-1-is-no-kind", v11, error="no-kind",
                ref=R_RTZ + "; a document in the RTZ 1.1 namespace")))
    return out


# ---------------------------------------------------------------- NMEA text

def nmea_checksum(body):
    return "%02X" % reduce(lambda c, ch: c ^ ord(ch), body, 0)


def tag_vectors():
    p = "nmea-tag-block"
    out = []
    body = "g:1-2-4401,s:station7,c:1767225600"
    a = body + "*" + nmea_checksum(body)
    out.append((p, "01-group-source-time-roundtrip.json", vec(p, "group-source-time-roundtrip", a,
                {"nmeatag.parameters.#": "3", "nmeatag.parameters[0].nmeatag.parameter": "g:1-2-4401",
                 "nmeatag.parameters[2].nmeatag.parameter": "c:1767225600"},
                ref=R_TAG + "; sentence group, source and UNIX time parameters")))
    body = "s:r1,n:42"
    b = body + "*" + nmea_checksum(body)
    out.append((p, "02-source-line-count-roundtrip.json", vec(p, "source-line-count-roundtrip", b,
                {"nmeatag.parameters.#": "2", "nmeatag.parameters[1].nmeatag.parameter": "n:42"},
                ref=R_TAG + "; source and line count")))
    out.append((p, "03-bad-checksum-is-malformed.json", vec(p, "bad-checksum-is-malformed", "s:r1,n:42*00",
                error="malformed-wire", ref=R_TAG + "; a checksum that does not match")))
    return out


def sentence(body):
    return "$" + body + "*" + nmea_checksum(body)


def pubx_vectors():
    p = "nmea0183-pubx"
    out = []
    a = sentence("PUBX,00,123519.00,4807.038000,N,01131.000000,E,512.3,G3,2.1,3.4,0.5,77.5,-0.1,,0.9,1.2,0.8,8,0,0")
    out.append((p, "01-pubx-00-roundtrip.json", vec(p, "pubx-00-roundtrip", a,
                {"pubx.time_s": "45319", "lat": repr(48 + 7.038 / 60), "lon": repr(11 + 31.0 / 60), "pubx.alt": "512.3",
                 "pubx.nav_status": "G3", "pubx.sog": "0.5", "pubx.vvel": "-0.1", "pubx.gps_used": "8"},
                ref=R_PUBX + "; a 3D position (latitude and longitude in the NMEA ddmm form)")))
    b = sentence("PUBX,01,101010.00,467125.245,E,5236949.763,N,498.2,D3,1.9,2.0,0.0,0.0,0.0,,0.8,0.9,0.5,10,0,0")
    out.append((p, "02-pubx-01-roundtrip.json", vec(p, "pubx-01-roundtrip", b,
                {"pubx.easting": "467125.245", "pubx.northing_ns": "N", "pubx.nav_status": "D3"},
                ref=R_PUBX + "; a UTM position")))
    c = sentence("PUBX,03,2,5,U,120,45,40,30,12,-,,,22,0")
    out.append((p, "03-pubx-03-roundtrip.json", vec(p, "pubx-03-roundtrip", c,
                {"pubx.sat_count": "2", "pubx.satellites.#": "2", "pubx.satellites[0].pubx.sv_id": "5",
                 "pubx.satellites[0].pubx.azimuth": "120", "pubx.satellites[1].pubx.sv_status": "-",
                 "pubx.satellites[1].pubx.cno": "22"},
                ref=R_PUBX + "; satellite status for two satellites, the second without azimuth or elevation")))
    d = sentence("PUBX,04,073731.00,091226,113851.00,2400,113851.00,1930035,-2660.664,43")
    out.append((p, "04-pubx-04-roundtrip.json", vec(p, "pubx-04-roundtrip", d,
                {"pubx.time_s": "27451", "pubx.date": "091226", "pubx.week": "2400", "pubx.clock_drift": "-2660.664"},
                ref=R_PUBX + "; time of day and clock information")))
    out.append((p, "05-pubx-02-is-no-kind.json", vec(p, "pubx-02-is-no-kind", sentence("PUBX,02,1"), error="no-kind",
                ref=R_PUBX + "; there is no PUBX 02")))
    return out


# ---------------------------------------------------------------- AIS area notice

def bits(fields):
    out = []
    for v, w in fields:
        if v < 0:
            v += 1 << w
        assert 0 <= v < (1 << w), (v, w)
        out.append(format(v, "0%db" % w))
    return "".join(out)


def armor(bitstr):
    bitstr += "0" * (-len(bitstr) % 6)
    chars = []
    for i in range(0, len(bitstr), 6):
        v = int(bitstr[i:i + 6], 2)
        chars.append(chr(0x30 + v if v < 40 else 0x38 + v))
    return "".join(chars)


def six(text, n):
    t = text.ljust(n, "@")
    return "".join(format(ord(c) - 0x40 if 0x40 <= ord(c) <= 0x5F else ord(c), "06b") for c in t)


def header(linkage, notice, month, day, hour, minute, duration):
    return bits([(linkage, 10), (notice, 7), (month, 4), (day, 5), (hour, 5), (minute, 6), (duration, 18)])


def circle(scale, lon, lat, prec, radius):
    return bits([(0, 3), (scale, 2), (lon, 25), (lat, 24), (prec, 3), (radius, 12), (0, 18)])


def rect(scale, lon, lat, prec, e, n, orient):
    return bits([(1, 3), (scale, 2), (lon, 25), (lat, 24), (prec, 3), (e, 8), (n, 8), (orient, 9), (0, 5)])


def sector(scale, lon, lat, prec, radius, left, right):
    return bits([(2, 3), (scale, 2), (lon, 25), (lat, 24), (prec, 3), (radius, 12), (left, 9), (right, 9)])


def poly(shape, scale, pts):
    f = [(shape, 3), (scale, 2)]
    for b, d in pts:
        f += [(b, 10), (d, 10)]
    return bits(f + [(0, 2)])


def textarea(t):
    return bits([(5, 3)]) + six(t, 14)


def area_vectors():
    p = "ais-area-notice"
    out = []
    lon, lat = 492000, 3229800   # 8.2 E and 53.83 N in thousandths of a minute
    bc = bits([(8, 6), (0, 2), (123456789, 30), (0, 2), (1, 10), (22, 6)]) + header(17, 35, 3, 14, 9, 30, 1440)
    a = armor(bc + circle(1, lon, lat, 4, 250))
    assert len(bc) + 87 == 198
    out.append((p, "01-broadcast-circle-roundtrip.json", vec(p, "broadcast-circle-roundtrip", a,
                {"ais.msg_type": "8", "ais.mmsi": "123456789", "aisbin.dac": "1", "aisbin.fid": "22",
                 "aisarea.linkage": "17", "aisarea.notice": "35", "aisarea.month": "3", "aisarea.day": "14",
                 "aisarea.hour": "9", "aisarea.minute": "30", "aisarea.duration": "1440", "aisarea.subareas.#": "1",
                 "aisarea.subareas[0].aisarea.shape": "0", "aisarea.subareas[0].aisarea.scale": "1",
                 "aisarea.subareas[0].aisarea.lon": str(lon), "aisarea.subareas[0].aisarea.lat": str(lat),
                 "aisarea.subareas[0].aisarea.radius": "250"},
                ref=R_AREA + "; a broadcast notice (entry prohibited, 24 hours) of one circle of 2500 m")))
    b = armor(bc + circle(0, -1000, -2000, 2, 0) + poly(4, 2, [(90, 15), (180, 15), (270, 15), (720, 0)]) +
              textarea("KEEP CLEAR"))
    out.append((p, "02-broadcast-polygon-text-roundtrip.json", vec(p, "broadcast-polygon-text-roundtrip", b,
                {"aisarea.subareas.#": "3", "aisarea.subareas[0].aisarea.lon": "-1000", "aisarea.subareas[0].aisarea.lat": "-2000",
                 "aisarea.subareas[1].aisarea.shape": "4", "aisarea.subareas[1].aisarea.bearing_2": "180",
                 "aisarea.subareas[1].aisarea.bearing_4": "720", "aisarea.subareas[2].aisarea.shape": "5",
                 "aisarea.subareas[2].aisarea.text": "KEEP CLEAR"},
                ref=R_AREA + "; a point, a polygon of three vertices from it (the fourth not available), and associated text")))
    ad = (bits([(6, 6), (0, 2), (211000001, 30), (1, 2), (211000002, 30), (0, 1), (0, 1), (1, 10), (23, 6)]) +
          header(5, 8, 0, 0, 24, 60, 262143))
    c = armor(ad + rect(1, lon, lat, 4, 20, 10, 45) + sector(2, lon, lat, 3, 5, 30, 120))
    out.append((p, "03-addressed-rectangle-sector-roundtrip.json", vec(p, "addressed-rectangle-sector-roundtrip", c,
                {"ais.msg_type": "6", "aisbin.seqno": "1", "ais.dest_mmsi": "211000002", "aisbin.fid": "23",
                 "aisarea.notice": "8", "aisarea.hour": "24", "aisarea.duration": "262143",
                 "aisarea.subareas[0].aisarea.east": "20", "aisarea.subareas[0].aisarea.orientation": "45",
                 "aisarea.subareas[1].aisarea.left": "30", "aisarea.subareas[1].aisarea.right": "120"},
                ref=R_AREA + "; an addressed notice (traffic congestion, no start time or duration) of a rectangle and a sector")))
    other = armor(bits([(8, 6), (0, 2), (123456789, 30), (0, 2), (1, 10), (31, 6)]) + "0" * 100)
    out.append((p, "04-other-fi-is-no-kind.json", vec(p, "other-fi-is-no-kind", other, error="no-kind",
                ref=R_AREA + "; a type 8 message of DAC 1 FI 31, not an area notice")))
    out.append((p, "05-cut-header-is-malformed.json", vec(p, "cut-header-is-malformed", a[:12], error="malformed-wire",
                ref=R_AREA + "; the payload of vector 01 cut inside the notice header")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in rtz_vectors() + tag_vectors() + pubx_vectors() + area_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("maritime-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
