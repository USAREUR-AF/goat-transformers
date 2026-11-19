#!/usr/bin/env python3
"""Write the vectors of the proprietary sentences of the pack `nmea0183`
(files v01-... in packs/nmea0183/vectors; vectors 01-43 are maintained by hand
and 44 and up by nmea0183-more-vectors.py, and neither is written or removed
here).

Every sentence below is written for these vectors; none is copied from a source
or from the examples in its comments. The layout of each sentence is this
script's own restatement of gpsd drivers/driver_nmea0183.c
(https://gitlab.com/gpsd/gpsd, BSD-2-Clause, commit c59fc6d): the field each
value stands in and what it means.

The script builds each sentence from its fields, computes the checksum (the XOR
of every byte between `$` and `*`, two uppercase hexadecimal digits), works out
the decoded values with its own readings of the text transforms of
spec/engine-spec.md 0.10 (dm, hms, hms_dmy, dec, int, float) and of the derived
keys of model/nmea0183.def and model/track.def, and writes the GeoJSON form by
the canonical rules of the geojson pack. It reads no pack.def and calls no
goat-transformers engine.

Inputs: none; every value is stated in this file. The same run always gives the
same bytes. With --check nothing is written and the exit status is 1 when a
committed file differs from what this script writes.

Usage: python3 -I tools/gen/nmea0183-vendor-vectors.py [--out DIR] [--check]
"""
import calendar
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

PACK = "nmea0183"
SRC = "gpsd drivers/driver_nmea0183.c (BSD-2-Clause, commit c59fc6d): layout and meaning, restated"


def checksum(body):
    c = 0
    for ch in body.encode("ascii"):
        c ^= ch
    return "%02X" % c


def sentence(fields):
    body = ",".join(fields)
    return "$" + body + "*" + checksum(body)


def num(x):
    """Shortest round-trip decimal, plain notation (engine-spec 0.1.1 ruling 3)."""
    if x == int(x) and abs(x) < 2 ** 53:
        return str(int(x))
    r = repr(float(x))
    assert "e" not in r and "E" not in r
    return r


# ---------------------------------------------------------------- readings (engine-spec 0.10)

def dm(text, letter, neg):
    i = text.index(".") if "." in text else len(text)
    deg, minutes = int(text[:i - 2]), float(text[i - 2:])
    v = minutes / 60 + deg
    return -v if letter == neg else v


def hms(text):
    return (int(text[0:2]) * 3600 + int(text[2:4]) * 60) + float(text[4:])


def hms_dmy_ms(t, d):
    h, m, s = int(t[0:2]), int(t[2:4]), int(t[4:6])
    frac = t[7:] if len(t) > 6 else ""
    ms = int((frac + "000")[:3]) if frac else 0
    yy = int(d[4:6])
    year = 1900 + yy if yy >= 80 else 2000 + yy
    return calendar.timegm((year, int(d[2:4]), int(d[0:2]), h, m, s)) * 1000 + ms


def read(kind, fields, idx):
    """The model text of one line: kind is "s" string, "i" int, "f" float/dec, "hms",
    ("dm", neg) on a pair (idx is (i, j)), "hms_dmy" on a pair."""
    if isinstance(idx, tuple):
        a, b = fields[idx[0]], fields[idx[1]]
        if kind == "hms_dmy":
            return str(hms_dmy_ms(a, b))
        return num(dm(a, b, kind[1]))
    t = fields[idx]
    if kind == "s":
        return t
    if kind == "i":
        return str(int(t))
    if kind == "hms":
        return num(hms(t))
    return num(float(t))


def model_of(kind_name, fields, lines, extra=None):
    """lines: [(key, field index or pair, reading)]; an empty field gives no key."""
    m = {"@kind": kind_name}
    for key, idx, kind in lines:
        parts = idx if isinstance(idx, tuple) else (idx,)
        if any(p >= len(fields) or fields[p] == "" for p in parts):
            continue
        m[key] = read(kind, fields, idx)
    if extra:
        m.update(extra)
    return m


N = "nmea0183."


def geojson(lat=None, lon=None, hae=None, props=()):
    if lat is None or lon is None:
        geom = "null"
    else:
        c = [num(lon), num(lat)] + ([num(hae)] if hae is not None else [])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(c)
    order = ["type", "time_ms", "how", "ce", "le", "callsign", "course", "speed_ms"]
    p = dict(props)
    body = ",".join('"%s":%s' % (k, num(p[k])) for k in order if k in p)
    return '{"type":"Feature","geometry":%s,"properties":{%s}}' % (geom, body)


def vec(name, inp, expect=None, error=None, model=None, to=PACK, ref=""):
    v = {"name": name, "from": PACK, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = ref
    return v


# ---------------------------------------------------------------- the sentences

def build():
    out = []

    def rt(name, kind_name, fields, lines, ref, extra=None):
        s = sentence(fields)
        out.append(vec(name, s, s, model=model_of(kind_name, fields, lines, extra), ref=SRC + "; " + ref))
        return s, fields

    tag = (N + "proprietary_tag", 0, "s")

    # PASHR,POS
    pos = ["PASHR", "POS", "1", "09", "123519.50", "4807.03800", "N", "01131.00000", "E", "545.40",
           "", "84.4", "36.0", "-0.2", "1.9", "1.0", "1.6", "1.2"]
    pos_lines = [tag, (N + "pashr_pos_type", 2, "i"), (N + "sats_used", 3, "i"), (N + "utc_s", 4, "hms"),
                 ("lat", (5, 6), ("dm", "S")), ("lon", (7, 8), ("dm", "W")), ("hae", 9, "f"),
                 (N + "pashr_track_deg", 11, "f"), (N + "sog_kmh", 12, "f"), (N + "pashr_climb", 13, "f"),
                 (N + "pdop", 14, "f"), (N + "hdop", 15, "f"), (N + "vdop", 16, "f"), (N + "tdop", 17, "f")]
    rt("pashr-pos-round-trip", "pashr-pos", pos, pos_lines,
       "PASHR,POS: field 9 is height above the WGS 84 ellipsoid (the driver: 'altitude is already WGS 84'); "
       "field 10 has no stated meaning and is left empty")
    lat, lon = dm("4807.03800", "N", "S"), dm("01131.00000", "E", "W")
    out.append(vec("pashr-pos-to-geojson", sentence(pos),
                   geojson(lat, lon, 545.4, {"speed_ms": 36.0 * 1000 / 3600}),
                   model={"lat": num(lat), "lon": num(lon), "hae": "545.4"}, to="geojson",
                   ref=SRC + "; lat/lon/hae by hand; speed_ms = 36 km/h x 1000 / 3600 = 10 by the module's "
                             "derive of nmea0183.sog_kmh"))
    sat = ["PASHR", "SAT", "3", "12", "045", "67", "48", "U", "25", "210", "12", "31", "", "31", "300", "05", "22", "U"]
    s = sentence(sat)
    m = {"@kind": "pashr-sat", N + "proprietary_tag": "PASHR", N + "pashr_sat_count": "3",
         N + "pashr_satellites.#": "3",
         N + "pashr_satellites[0]." + N + "sv_id": "12", N + "pashr_satellites[0]." + N + "azimuth_deg": "45",
         N + "pashr_satellites[0]." + N + "elevation_deg": "67", N + "pashr_satellites[0]." + N + "pashr_snr": "48",
         N + "pashr_satellites[0]." + N + "pashr_sat_used": "U",
         N + "pashr_satellites[1]." + N + "sv_id": "25", N + "pashr_satellites[2]." + N + "pashr_sat_used": "U"}
    expect = sentence(["PASHR", "SAT", "3", "12", "45", "67", "48", "U", "25", "210", "12", "31", "",
                       "31", "300", "5", "22", "U"])
    out.append(vec("pashr-sat-numbers-rewritten", s, expect, model=m,
                   ref=SRC + "; PASHR,SAT: five fields per satellite; `int` writes 045 and 05 as 45 and 5"))
    rid = ["PASHR", "RID", "G4", "BP00"]
    rt("pashr-rid-round-trip", "pashr-rid", rid,
       [tag, (N + "receiver_model", 2, "s"), (N + "receiver_version", 3, "s")], "PASHR,RID: receiver and version")
    ack = ["PASHR", "ACK"]
    s = sentence(ack)
    out.append(vec("pashr-ack-is-proprietary", s, s, model={"@kind": "proprietary", N + "proprietary_tag": "PASHR"},
                   ref=SRC + "; PASHR,ACK carries nothing the driver reads: it decodes as `proprietary`, field 1 "
                             "as residue"))

    # Garmin
    rt("pgrme-round-trip", "pgrme", ["PGRME", "15.0", "M", "45.0", "M", "25.0", "M"],
       [tag, (N + "pgrme_hpe_m", 1, "f"), (N + "pgrme_vpe_m", 3, "f"), (N + "pgrme_spe_m", 5, "f")],
       "PGRME: three error estimates in metres; their confidence level is not stated, so no ce/le")
    f = ["PGRMF", "2350", "302412", "140326", "120012", "18", "5213.1439", "N", "02100.6511", "E", "A", "2",
         "36", "271", "2", "1"]
    f_lines = [tag, (N + "gps_week", 1, "i"), (N + "gps_tow_s", 2, "i"), ("time_ms", (4, 3), "hms_dmy"),
               (N + "utc_s", 4, "hms"), (N + "leap_seconds", 5, "i"), ("lat", (6, 7), ("dm", "S")),
               ("lon", (8, 9), ("dm", "W")), (N + "pgrmf_mode", 10, "s"), (N + "pgrmf_fix_type", 11, "i"),
               (N + "sog_kmh", 12, "f"), ("course", 13, "f"), (N + "pdop", 14, "f"), (N + "tdop", 15, "f")]
    rt("pgrmf-round-trip", "pgrmf", f, f_lines,
       "PGRMF: field 3 the UTC date ddmmyy and field 4 the UTC time; field 13 course over ground, degrees true")
    lat, lon = dm("5213.1439", "N", "S"), dm("02100.6511", "E", "W")
    t = hms_dmy_ms("120012", "140326")
    out.append(vec("pgrmf-to-geojson", sentence(f),
                   geojson(lat, lon, props={"time_ms": t, "course": 271, "speed_ms": 10}),
                   model={"lat": num(lat), "lon": num(lon), "time_ms": str(t), "course": "271"}, to="geojson",
                   ref=SRC + "; time_ms from 14 March 2026 12:00:12 UTC; speed_ms = 36 km/h = 10 m/s by the "
                             "module's derive"))
    rt("pgrmm-round-trip", "pgrmm", ["PGRMM", "WGS 84"], [tag, (N + "map_datum", 1, "s")],
       "PGRMM: the name of the map datum")
    rt("pgrmt-round-trip", "pgrmt", ["PGRMT", "GPS 18x 4.00", "P", "P", "R", "R", "P", "C", "31", "R"],
       [tag, (N + "receiver_model", 1, "s"), (N + "pgrmt_rom_test", 2, "s"), (N + "pgrmt_receiver", 3, "s"),
        (N + "pgrmt_stored", 4, "s"), (N + "pgrmt_clock", 5, "s"), (N + "pgrmt_oscillator", 6, "s"),
        (N + "pgrmt_collecting", 7, "s"), (N + "pgrmt_temp_c", 8, "s"), (N + "pgrmt_config", 9, "s")],
       "PGRMT: nine status fields")
    v = ["PGRMV", "0.0", "5.0", "-0.4"]
    rt("pgrmv-round-trip", "pgrmv", v,
       [tag, ("track.vel_east_ms", 1, "f"), ("track.vel_north_ms", 2, "f"), ("track.vel_up_ms", 3, "f")],
       "PGRMV: true east, north and up velocity, metres per second")
    out.append(vec("pgrmv-to-geojson", sentence(v), geojson(props={"course": 0, "speed_ms": 5}),
                   model={"track.vel_east_ms": "0", "track.vel_north_ms": "5"}, to="geojson",
                   ref=SRC + "; speed_ms = hypot(0, 5) = 5 and course = bearing(0, 5) = 0 by the derived keys of "
                             "model/track.def; no position"))
    rt("pgrmz-round-trip", "pgrmz", ["PGRMZ", "1493", "f", "3"],
       [tag, (N + "pgrmz_alt_ft", 1, "i"), (N + "pgrmz_fix_mode", 3, "i")],
       "PGRMZ: altitude in feet, read by gpsd as above mean sea level, so not hae")

    # MediaTek
    rt("pmtk001-round-trip", "pmtk001", ["PMTK001", "220", "3"],
       [tag, (N + "mtk_command", 1, "i"), (N + "mtk_ack_flag", 2, "i")], "PMTK001: command number and result")
    rt("pmtk424-round-trip", "pmtk424", ["PMTK424", "0", "1", "1", "0", "127875"],
       [tag, (N + "mtk_tsip", 1, "i"), (N + "mtk_antenna", 2, "i"), (N + "mtk_pps", 3, "i"),
        (N + "mtk_pps_timing", 4, "i"), (N + "mtk_pps_width", 5, "i")], "PMTK424: five settings")

    # SiRF
    rt("psrfepe-round-trip", "psrfepe", ["PSRFEPE", "100542.000", "A", "0.7", "6.82", "10.69", "0.1", "180.5"],
       [tag, (N + "utc_s", 1, "hms"), (N + "status", 2, "s"), (N + "hdop", 3, "f"), (N + "sirf_ehpe_m", 4, "f"),
        (N + "sirf_evpe_m", 5, "f"), (N + "sirf_ehve", 6, "f"), (N + "sirf_ehe_deg", 7, "f")],
       "PSRFEPE: time, status, HDOP and four error estimates")

    # SkyTraq
    p30 = ["PSTI", "030", "081530.250", "A", "2502.3412345", "N", "12130.5098765", "E", "41.5", "0.3", "-1.2",
           "0.05", "190326", "R", "1.4", "999.9"]
    p30_lines = [tag, ("time_ms", (2, 12), "hms_dmy"), (N + "utc_s", 2, "hms"), (N + "status", 3, "s"),
                 ("lat", (4, 5), ("dm", "S")), ("lon", (6, 7), ("dm", "W")), (N + "alt_msl_m", 8, "f"),
                 ("track.vel_east_ms", 9, "f"), ("track.vel_north_ms", 10, "f"), ("track.vel_up_ms", 11, "f"),
                 (N + "faa_mode", 13, "s"), (N + "rtk_age_s", 14, "f"), (N + "rtk_ratio", 15, "f")]
    rt("psti030-round-trip", "psti030", p30, p30_lines,
       "PSTI,030: field 12 the UTC date; fields 9-11 east, north, up velocity in metres per second; field 8 "
       "above mean sea level")
    base = ["081530.250", "190326", "A", "R", "0.603", "-0.837", "-0.089", "1.036", "144.22", "", "", "", "", ""]
    b_lines = [tag, ("time_ms", (2, 3), "hms_dmy"), (N + "utc_s", 2, "hms"), (N + "status", 4, "s"),
               (N + "rtk_mode", 5, "s"), (N + "baseline_east_m", 6, "f"), (N + "baseline_north_m", 7, "f"),
               (N + "baseline_up_m", 8, "f"), (N + "baseline_length_m", 9, "f"),
               (N + "baseline_course_deg", 10, "f")]
    p32 = ["PSTI", "032"] + base
    s = sentence(p32)
    out.append(vec("psti032-reserved-fields-dropped", s, sentence(p32[:11]),
                   model=model_of("psti032", p32, b_lines),
                   ref=SRC + "; PSTI,032: fields 11-15 are reserved and empty; the pack writes up to field 10"))
    rt("psti035-round-trip", "psti035", ["PSTI", "035"] + base[:9], b_lines,
       "PSTI,035: the moving-base form of PSTI,032")
    rt("psti036-round-trip", "psti036", ["PSTI", "036", "054314.000", "030521", "191.69", "-16.35", "0", "R"],
       [tag, ("time_ms", (2, 3), "hms_dmy"), (N + "utc_s", 2, "hms"), (N + "attitude_heading_deg", 4, "f"),
        (N + "attitude_pitch_deg", 5, "f"), (N + "attitude_roll_deg", 6, "f"), (N + "faa_mode", 7, "s")],
       "PSTI,036: heading, pitch and roll in degrees, and a mode letter")

    # iSync, True North
    rt("ptnta-round-trip", "ptnta", ["PTNTA", "20260319081530", "2", "T4", "120", "-480", "3", "3", "3"],
       [tag, (N + "isync_datetime", 1, "s"), (N + "isync_osc_quality", 2, "i"),
        (N + "isync_pps_interval_ns", 4, "i"), (N + "isync_fine_phase_ns", 5, "i"), (N + "isync_status", 6, "i"),
        (N + "isync_gps_messages", 7, "i"), (N + "isync_transfer_quality", 8, "i")],
       "PTNTA: field 3 is always T4, a `when` of the kind")
    rt("ptnthtm-round-trip", "ptnthtm", ["PTNTHTM", "14223", "N", "169", "N", "-43", "N", "13641", "2454"],
       [tag, (N + "htm_heading", 1, "s"), (N + "htm_mag_status", 2, "s"), (N + "htm_pitch", 3, "s"),
        (N + "htm_pitch_status", 4, "s"), (N + "htm_roll", 5, "s"), (N + "htm_roll_status", 6, "s"),
        (N + "htm_dip", 7, "s"), (N + "htm_horizontal", 8, "s")],
       "PTNTHTM: angles in the compass's own integer units, kept as text")

    # Quectel
    g = ["PQTMGPS", "671335", "463792.25", "31.8220846", "117.1152211", "59.426", "63.042", "2.5", "-171.7101",
         "5.989", "1.33", "2.11", "3", "18"]
    rt("pqtmgps-round-trip", "pqtmgps", g,
       [tag, (N + "uptime_ms", 1, "i"), (N + "quectel_tow_s", 2, "f"), ("lat", 3, "f"), ("lon", 4, "f"),
        ("hae", 5, "f"), (N + "alt_msl_m", 6, "f"), ("speed_ms", 7, "f"), (N + "heading_2d_deg", 8, "f"),
        (N + "h_acc_m", 9, "f"), (N + "hdop", 10, "f"), (N + "pdop", 11, "f"), (N + "quectel_fix_type", 12, "i"),
        (N + "sats_used", 13, "i")],
       "PQTMGPS: latitude and longitude in degrees, field 5 height above the ellipsoid, field 7 ground speed "
       "in metres per second")
    out.append(vec("pqtmgps-to-geojson", sentence(g),
                   geojson(31.8220846, 117.1152211, 59.426, {"speed_ms": 2.5}),
                   model={"lat": "31.8220846", "lon": "117.1152211", "hae": "59.426", "speed_ms": "2.5"},
                   to="geojson", ref=SRC + "; written by hand from the decimal degrees"))
    rt("pqtmins-round-trip", "pqtmins", ["PQTMINS", "42529", "1", "31.822038", "117.1151828", "67.681", "", "", "",
                                         "-0.392663", "1.300793", "0.030088"],
       [tag, (N + "uptime_ms", 1, "i"), (N + "ins_solution", 2, "i"), ("lat", 3, "f"), ("lon", 4, "f"),
        (N + "ins_height_m", 5, "f"), (N + "ins_vel_north", 6, "f"), (N + "ins_vel_east", 7, "f"),
        (N + "ins_vel_down", 8, "f"), (N + "attitude_roll_deg", 9, "f"), (N + "attitude_pitch_deg", 10, "f"),
        (N + "attitude_heading_deg", 11, "f")],
       "PQTMINS: empty velocity fields are absent")
    rt("pqtmimu-round-trip", "pqtmimu", ["PQTMIMU", "42634", "-0.006832", "-0.022814", "1.014552", "0.315",
                                         "-0.4025", "-0.3325", "0", "0"],
       [tag, (N + "uptime_ms", 1, "i"), (N + "imu_acc_x_g", 2, "f"), (N + "imu_acc_y_g", 3, "f"),
        (N + "imu_acc_z_g", 4, "f"), (N + "imu_rate_x_dps", 5, "f"), (N + "imu_rate_y_dps", 6, "f"),
        (N + "imu_rate_z_dps", 7, "f"), (N + "imu_ticks", 8, "i"), (N + "imu_tick_ms", 9, "i")],
       "PQTMIMU: accelerations in g and angular rates in degrees per second")

    # proprietary sentences no kind maps
    c = sentence(["PGRMC", "A", "218.8", "100", "", "", "", "", "", "", "", "2", "1", "2"])
    out.append(vec("pgrmc-is-proprietary-not-rmc", c, c,
                   model={"@kind": "proprietary", N + "proprietary_tag": "PGRMC"},
                   ref="columns 2-4 of the tag PGRMC are RMC: the `proprietary` kind, before the standard kinds, "
                       "takes it, keeps the tag whole and the other fields as residue"))
    u = sentence(["PUBX", "00", "081350.00", "4717.11364", "N", "00833.91565", "E", "546.589", "G3"])
    out.append(vec("pubx-is-proprietary", u, u, model={"@kind": "proprietary", N + "proprietary_tag": "PUBX"},
                   ref="the driver lists PUBX without a layout (pack.md): `proprietary`, the fields as residue"))
    return out


def build_files(out):
    vecs = build()
    assert len({v["name"] for v in vecs}) == len(vecs)
    vdir = "packs/%s/vectors" % PACK
    names = set()
    for i, v in enumerate(vecs, 1):
        name = "v%02d-%s.json" % (i, v["name"])
        out.write(vdir + "/" + name, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        names.add(name)
    for old in out.listdir(vdir):
        if old.startswith("v") and old[1:3].isdigit() and old not in names:
            out.remove(vdir + "/" + old)
    return {PACK: len(vecs)}


def main(argv=None):
    return genio.vector_main("nmea0183-vendor-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
