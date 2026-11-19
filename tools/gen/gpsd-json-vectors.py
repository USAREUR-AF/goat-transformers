#!/usr/bin/env python3
"""Write the vectors of the gpsd-json pack.

The pack reads one gpsd JSON response or report (gpsd_json(5), gitlab.com/gpsd/gpsd
commit a9266948, man/gpsd_json.adoc, BSD-2-Clause), its kind chosen by the
member "class". This script holds its own copy of the member lists of each
class in the order the pack lists them, builds every message from values
written for these vectors (none is taken from the document's examples), and
works out the canonical output, the decoded values and the GeoJSON and CoT
forms by the rules of spec/engine-spec.md (0.5 json wire, 0.6, 0.7 groups) and
of the geojson and cot-xml packs. It reads no pack.def and calls no
goat-transformers engine.

Canonical json (0.5): mapped and `when` members in line order, then residue
scalars in input order; numbers shortest round-trip, an integer value without
a point (ruling 3 of 0.1.1); `bool` writes true/false. Items of a group carry
no residue (0.7). iso8601_ms writes YYYY-MM-DDTHH:MM:SS.fffZ.

Usage: python3 -I tools/gen/gpsd-json-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "gpsd_json(5), gitlab.com/gpsd/gpsd commit a9266948f59b3785ad93bb28f487f0308ed03cfe, man/gpsd_json.adoc"
SOURCE = "derived by tools/gen/gpsd-json-vectors.py from the member tables of gpsd_json(5) and spec/engine-spec.md; no engine run"

# Member lists, in pack line order: (member, transform, model key). Transforms:
# s string, f float, i int, b bool, t iso8601_ms. `class` is the kind's `when`.
TPV = [("device", "s", "gpsd.device"), ("mode", "i", "gpsd.mode"), ("alt", "f", "gpsd.alt"),
       ("altHAE", "f", "hae"), ("altMSL", "f", "gpsd.alt_msl"), ("ant", "i", "gpsd.ant"),
       ("antPwr", "i", "gpsd.ant_pwr"), ("climb", "f", "gpsd.climb"), ("clockbias", "f", "gpsd.clockbias"),
       ("clockdrift", "f", "gpsd.clockdrift"), ("datum", "s", "gpsd.datum"), ("depth", "f", "gpsd.depth"),
       ("dgpsAge", "f", "gpsd.dgps_age"), ("dgpsSta", "i", "gpsd.dgps_sta"), ("ecefx", "f", "gpsd.ecefx"),
       ("ecefy", "f", "gpsd.ecefy"), ("ecefz", "f", "gpsd.ecefz"), ("ecefpAcc", "f", "gpsd.ecef_p_acc"),
       ("ecefvx", "f", "gpsd.ecefvx"), ("ecefvy", "f", "gpsd.ecefvy"), ("ecefvz", "f", "gpsd.ecefvz"),
       ("ecefvAcc", "f", "gpsd.ecef_v_acc"), ("epc", "f", "gpsd.epc"), ("epd", "f", "gpsd.epd"),
       ("eph", "f", "gpsd.eph"), ("eps", "f", "gpsd.eps"), ("ept", "f", "gpsd.ept"), ("epx", "f", "gpsd.epx"),
       ("epy", "f", "gpsd.epy"), ("epv", "f", "gpsd.epv"), ("geoidSep", "f", "gpsd.geoid_sep"),
       ("jam", "i", "gpsd.jam"), ("lat", "f", "lat"), ("leapseconds", "i", "gpsd.leapseconds"),
       ("lon", "f", "lon"), ("magdev", "f", "gpsd.magdev"), ("magtrack", "f", "gpsd.magtrack"),
       ("magvar", "f", "gpsd.magvar"), ("relD", "f", "gpsd.rel_d"), ("relE", "f", "gpsd.rel_e"),
       ("relN", "f", "gpsd.rel_n"), ("sep", "f", "gpsd.sep"), ("speed", "f", "speed_ms"),
       ("status", "i", "gpsd.status"), ("temp", "f", "gpsd.temp"), ("time", "t", "time_ms"),
       ("track", "f", "course"), ("velD", "f", "gpsd.vel_d"), ("velE", "f", "gpsd.vel_e"),
       ("velN", "f", "gpsd.vel_n"), ("wanglem", "f", "gpsd.wanglem"), ("wangler", "f", "gpsd.wangler"),
       ("wanglet", "f", "gpsd.wanglet"), ("wspeedr", "f", "gpsd.wspeedr"), ("wspeedt", "f", "gpsd.wspeedt"),
       ("wtemp", "f", "gpsd.wtemp")]
SAT = [("PRN", "i", "gpsd.prn"), ("az", "f", "gpsd.az"), ("el", "f", "gpsd.el"), ("freqid", "i", "gpsd.freqid"),
       ("gnssid", "i", "gpsd.gnssid"), ("health", "i", "gpsd.health"), ("ss", "f", "gpsd.ss"),
       ("sigid", "i", "gpsd.sigid"), ("svid", "i", "gpsd.svid"), ("used", "b", "gpsd.used")]
# ("satellites", None, ...) marks the group's place in the line order
SKY = [("device", "s", "gpsd.device"), ("nSat", "i", "gpsd.n_sat"), ("gdop", "f", "gpsd.gdop"),
       ("hdop", "f", "gpsd.hdop"), ("pdop", "f", "gpsd.pdop"), ("pr", "f", "gpsd.pr"),
       ("prRate", "f", "gpsd.pr_rate"), ("prRes", "f", "gpsd.pr_res"), ("qual", "i", "gpsd.qual"),
       ("satellites", None, "gpsd.satellites"), ("tdop", "f", "gpsd.tdop"), ("time", "t", "time_ms"),
       ("uSat", "i", "gpsd.u_sat"), ("vdop", "f", "gpsd.vdop"), ("xdop", "f", "gpsd.xdop"), ("ydop", "f", "gpsd.ydop")]
GST = [("device", "s", "gpsd.device"), ("time", "t", "time_ms"), ("rms", "f", "gpsd.gst_rms"),
       ("major", "f", "gpsd.gst_major"), ("minor", "f", "gpsd.gst_minor"), ("orient", "f", "gpsd.gst_orient"),
       ("alt", "f", "gpsd.gst_alt"), ("lat", "f", "gpsd.gst_lat"), ("lon", "f", "gpsd.gst_lon"),
       ("ve", "f", "gpsd.gst_ve"), ("vn", "f", "gpsd.gst_vn"), ("vu", "f", "gpsd.gst_vu")]
ATT = [("device", "s", "gpsd.device"), ("time", "t", "time_ms"), ("timeTag", "s", "gpsd.time_tag"),
       ("heading", "f", "gpsd.heading"), ("mag_st", "s", "gpsd.mag_st"), ("mheading", "f", "gpsd.mheading"),
       ("pitch", "f", "gpsd.pitch"), ("pitch_st", "s", "gpsd.pitch_st"), ("rot", "f", "gpsd.rot"),
       ("yaw", "f", "gpsd.yaw"), ("yaw_st", "s", "gpsd.yaw_st"), ("roll", "f", "gpsd.roll"),
       ("roll_st", "s", "gpsd.roll_st"), ("dip", "f", "gpsd.dip"), ("mag_len", "f", "gpsd.mag_len"),
       ("mag_x", "f", "gpsd.mag_x"), ("mag_y", "f", "gpsd.mag_y"), ("mag_z", "f", "gpsd.mag_z"),
       ("acc_len", "f", "gpsd.acc_len"), ("acc_x", "f", "gpsd.acc_x"), ("acc_y", "f", "gpsd.acc_y"),
       ("acc_z", "f", "gpsd.acc_z"), ("gyro_x", "f", "gpsd.gyro_x"), ("gyro_y", "f", "gpsd.gyro_y"),
       ("gyro_z", "f", "gpsd.gyro_z"), ("depth", "f", "gpsd.att_depth"), ("temp", "f", "gpsd.att_temp")]
TOFF = [("device", "s", "gpsd.device"), ("real_sec", "i", "gpsd.real_sec"), ("real_nsec", "i", "gpsd.real_nsec"),
        ("clock_sec", "i", "gpsd.clock_sec"), ("clock_nsec", "i", "gpsd.clock_nsec")]
PPS = TOFF + [("precision", "i", "gpsd.precision"), ("shm", "s", "gpsd.shm"), ("qErr", "f", "gpsd.q_err")]
OSC = [("device", "s", "gpsd.device"), ("running", "b", "gpsd.running"), ("reference", "b", "gpsd.reference"),
       ("disciplined", "b", "gpsd.disciplined"), ("delta", "f", "gpsd.delta")]
VERSION = [("release", "s", "gpsd.release"), ("rev", "s", "gpsd.rev"), ("proto_major", "i", "gpsd.proto_major"),
           ("proto_minor", "i", "gpsd.proto_minor"), ("remote", "s", "gpsd.remote")]
DEVICE = [("bps", "i", "gpsd.bps"), ("cycle", "f", "gpsd.cycle"), ("driver", "s", "gpsd.driver"),
          ("flags", "i", "gpsd.flags"), ("hexdata", "s", "gpsd.hexdata"), ("mincycle", "f", "gpsd.mincycle"),
          ("native", "i", "gpsd.native"), ("parity", "s", "gpsd.parity"), ("path", "s", "gpsd.path"),
          ("readonly", "b", "gpsd.readonly"), ("sernum", "s", "gpsd.sernum"), ("stopbits", "i", "gpsd.stopbits"),
          ("subtype", "s", "gpsd.subtype"), ("subtype1", "s", "gpsd.subtype1")]
DEVICES = [("devices", None, "gpsd.devices"), ("remote", "s", "gpsd.remote")]
WATCH = [("enable", "b", "gpsd.enable"), ("json", "b", "gpsd.json"), ("nmea", "b", "gpsd.nmea"),
         ("raw", "i", "gpsd.raw"), ("scaled", "b", "gpsd.scaled"), ("split24", "b", "gpsd.split24"),
         ("pps", "b", "gpsd.pps"), ("device", "s", "gpsd.device"), ("remote", "s", "gpsd.remote")]
POLL = [("time", "t", "time_ms"), ("active", "i", "gpsd.active"), ("tpv", None, "gpsd.poll_tpv"),
        ("sky", None, "gpsd.poll_sky")]
ERROR = [("message", "s", "gpsd.message")]
ACK = []
SUBFRAME = [("device", "s", "gpsd.device"), ("frame", "i", "gpsd.frame"), ("gnssId", "i", "gpsd.gnss_id"),
            ("scaled", "b", "gpsd.scaled"), ("tSV", "i", "gpsd.t_sv"), ("TOW17", "i", "gpsd.tow17")]

KINDS = [("tpv", "TPV", TPV), ("sky", "SKY", SKY), ("gst", "GST", GST), ("att", "ATT", ATT), ("imu", "IMU", ATT),
         ("pps", "PPS", PPS), ("toff", "TOFF", TOFF), ("osc", "OSC", OSC), ("version", "VERSION", VERSION),
         ("devices", "DEVICES", DEVICES), ("device", "DEVICE", DEVICE), ("watch", "WATCH", WATCH),
         ("poll", "POLL", POLL), ("error", "ERROR", ERROR), ("subframe", "SUBFRAME", SUBFRAME), ("ack", "ACK", ACK)]
# group item lines: (member list, a `const class` value or None, nested groups)
GROUPS = {"satellites": (SAT, None), "devices": (DEVICE, "DEVICE"), "tpv": (TPV, "TPV"), "sky": (SKY, "SKY")}


# -- values ---------------------------------------------------------------------

def num(x):
    """JSON number text the encoder writes (ruling 3 of 0.1.1)."""
    x = float(x)
    if x == 0:
        return "0"
    r = repr(x)
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
    return r[:-2] if r.endswith(".0") else r


def iso_ms(text):
    t = text
    off = datetime.timedelta(0)
    if t[-1] in "Zz":
        t = t[:-1]
    else:
        sign = 1 if t[-6] == "+" else -1
        off = sign * datetime.timedelta(hours=int(t[-5:-3]), minutes=int(t[-2:]))
        t = t[:-6]
    ms = 0
    if "." in t:
        t, frac = t.split(".")
        ms = int((frac + "000")[:3])
    d = datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc) - off
    return int(d.timestamp()) * 1000 + ms


def ms_iso(ms):
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def jstr(s):
    return json.dumps(s, ensure_ascii=False)


def value_text(v, tr):
    if tr == "s":
        return jstr(v)
    if tr == "b":
        return "true" if v else "false"
    if tr == "t":
        return jstr(ms_iso(iso_ms(v)))
    if tr == "i":
        return str(int(v))
    return num(v)


def model_text(v, tr):
    if tr == "b":
        return "1" if v else "0"
    if tr == "t":
        return str(iso_ms(v))
    if tr == "f":
        return num(v)
    if tr == "i":
        return str(int(v))
    return v


def canon(obj, members, cls=None, residue=True):
    """Canonical text of one gpsd object: `class` (the `when`, or a `const` in
    an item), mapped members in line order, then residue scalars in input order."""
    parts = []
    if cls is not None:
        parts.append('"class":%s' % jstr(cls))
    mapped = {"class"}
    for m, tr, _ in members:
        mapped.add(m)
        if m not in obj:
            continue
        if tr is None:
            items_members, item_cls = GROUPS[m]
            parts.append('"%s":[%s]' % (m, ",".join(canon(it, items_members, item_cls, residue=False)
                                                    for it in obj[m])))
        else:
            parts.append('"%s":%s' % (m, value_text(obj[m], tr)))
    if residue:
        for k, v in obj.items():
            if k in mapped or isinstance(v, (list, dict)) or v is None:
                continue
            parts.append('"%s":%s' % (k, json.dumps(v)))
    return "{" + ",".join(parts) + "}"


def model_of(obj, members, prefix=""):
    m = {}
    for name, tr, key in members:
        if name not in obj:
            continue
        if tr is None:
            m[prefix + key + ".#"] = str(len(obj[name]))
            items_members = GROUPS[name][0]
            for j, it in enumerate(obj[name][:1]):
                for k, v in model_of(it, items_members, "%s%s[%d]." % (prefix, key, j)).items():
                    m[k] = v
        else:
            m[prefix + key] = model_text(obj[name], tr)
    return m


def vec(name, frm, to, inp, expect=None, model=None, error=None, note=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = REF + ("; " + note if note else "")
    return v


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


# -- the messages, written for these vectors ------------------------------------------

def tpv_full():
    vals = {"device": "/dev/ttyACM0", "mode": 3, "alt": 512.25, "altHAE": 559.5, "altMSL": 512.25, "ant": 2,
            "antPwr": 2, "climb": -0.25, "clockbias": 120345, "clockdrift": -12.5, "datum": "WGS84",
            "depth": 4.5, "dgpsAge": 3.0, "dgpsSta": 517, "ecefx": 4205315.5, "ecefy": 822163.25,
            "ecefz": 4712843.75, "ecefpAcc": 2.5, "ecefvx": 0.5, "ecefvy": -0.25, "ecefvz": 0.125,
            "ecefvAcc": 0.75, "epc": 1.5, "epd": 12.25, "eph": 3.5, "eps": 0.625, "ept": 0.005, "epx": 2.75,
            "epy": 3.25, "epv": 5.5, "geoidSep": 47.25, "jam": 12, "lat": 47.9123456, "leapseconds": 18,
            "lon": 11.4567891, "magdev": 0.5, "magtrack": 92.5, "magvar": -3.25, "relD": 0.25, "relE": -1.5,
            "relN": 2.75, "sep": 6.25, "speed": 12.5, "status": 2, "temp": 31.5,
            "time": "2026-03-04T05:06:07.123Z", "track": 95.75, "velD": 0.25, "velE": 12.25, "velN": -2.5,
            "wanglem": 45.5, "wangler": 30.25, "wanglet": 47.75, "wspeedr": 6.5, "wspeedt": 5.25,
            "wtemp": 14.5}
    obj = {"class": "TPV"}
    obj.update(vals)
    return obj


def build_vectors():
    V = {}
    # 01 TPV: every member, written in an order of its own; unknown members are residue
    obj = tpv_full()
    shuffled = dict(sorted(obj.items(), key=lambda kv: kv[0][::-1]))
    shuffled["extraNote"] = "kept"
    m = model_of(obj, TPV)
    m["@kind"] = "tpv"
    V["01-tpv-roundtrip"] = vec("tpv-roundtrip", "gpsd-json", "gpsd-json", js(shuffled),
        canon(shuffled, TPV, "TPV"), m,
        note="every member of the TPV table; class first, members in the pack's line order, then the member no line maps (residue); dgpsAge 3.0 is written 3; time gains milliseconds")

    # 02 SKY with satellites
    sky = {"class": "SKY", "device": "/dev/ttyACM0", "time": "2026-03-04T05:06:07Z", "nSat": 3, "uSat": 2,
           "hdop": 0.85, "vdop": 1.25, "pdop": 1.5, "gdop": 1.75, "tdop": 0.75, "xdop": 0.5, "ydop": 0.625,
           "satellites": [
               {"PRN": 5, "gnssid": 0, "svid": 5, "az": 120.5, "el": 45.25, "ss": 42.5, "used": True, "health": 1},
               {"PRN": 72, "gnssid": 6, "svid": 8, "freqid": 9, "sigid": 0, "az": 300, "el": 12.5, "ss": 31,
                "used": False},
               {"PRN": 133, "gnssid": 1, "svid": 133, "az": 210.75, "el": 33, "ss": 38.5, "used": True}]}
    m = model_of(sky, SKY)
    m["@kind"] = "sky"
    m["gpsd.satellites[2].gpsd.prn"] = "133"
    V["02-sky-roundtrip"] = vec("sky-roundtrip", "gpsd-json", "gpsd-json", js(sky), canon(sky, SKY, "SKY"), m,
        note="satellites is a group; each satellite item's members are written in the pack's order; used is a JSON boolean")

    # 03 GST: its lat, lon and alt are standard deviations in metres, not a position
    gst = {"class": "GST", "device": "/dev/ttyACM0", "time": "2026-03-04T05:06:07.5Z", "rms": 2.25,
           "major": 1.75, "minor": 1.25, "orient": 33.5, "lat": 1.5, "lon": 1.125, "alt": 2.75,
           "ve": 0.25, "vn": 0.375, "vu": 0.5}
    m = model_of(gst, GST)
    m["@kind"] = "gst"
    V["03-gst-roundtrip"] = vec("gst-roundtrip", "gpsd-json", "gpsd-json", js(gst), canon(gst, GST, "GST"), m,
        note="lat, lon and alt of GST are error standard deviations in metres: raw keys, not the shared position")

    # 04 ATT, 05 IMU: same members, kind by class; mode is not in the table and is residue
    att = {"class": "ATT", "device": "/dev/ttyUSB1", "time": "2026-03-04T05:06:08Z", "mode": 3,
           "heading": 271.5, "mag_st": "N", "mheading": 268.25, "pitch": 2.5, "pitch_st": "N", "roll": -1.25,
           "roll_st": "N", "yaw": 271.5, "yaw_st": "N", "rot": 3.5, "dip": 64.25, "mag_len": 48.5,
           "mag_x": 21.25, "mag_y": -3.5, "mag_z": 43.75, "acc_len": 9.875, "acc_x": 0.125, "acc_y": -0.25,
           "acc_z": 9.75, "gyro_x": 0.5, "gyro_y": -0.75, "gyro_z": 1.25, "depth": 12.5, "temp": 18.5,
           "timeTag": "t-001"}
    m = model_of(att, ATT)
    m["@kind"] = "att"
    V["04-att-roundtrip"] = vec("att-roundtrip", "gpsd-json", "gpsd-json", js(att), canon(att, ATT, "ATT"), m,
        note="heading is degrees from true north of the vehicle's attitude, not its course over ground: raw; mode is outside the ATT table and is residue")
    imu = dict(att)
    imu["class"] = "IMU"
    del imu["mode"]
    m = model_of(imu, ATT)
    m["@kind"] = "imu"
    V["05-imu-roundtrip"] = vec("imu-roundtrip", "gpsd-json", "gpsd-json", js(imu), canon(imu, ATT, "IMU"), m,
        note="IMU has the members of ATT; the kind is chosen by class")

    # 06 PPS, 07 TOFF
    pps = {"class": "PPS", "device": "/dev/pps0", "real_sec": 1772600767, "real_nsec": 0,
           "clock_sec": 1772600767, "clock_nsec": 1043, "precision": -20, "shm": "NTP0", "qErr": -1250}
    m = model_of(pps, PPS)
    m["@kind"] = "pps"
    V["06-pps-roundtrip"] = vec("pps-roundtrip", "gpsd-json", "gpsd-json", js(pps), canon(pps, PPS, "PPS"), m)
    toff = {"class": "TOFF", "device": "/dev/ttyACM0", "real_sec": 1772600767, "real_nsec": 125000000,
            "clock_sec": 1772600767, "clock_nsec": 131072000, "precision": -1}
    m = model_of(toff, TOFF)
    m["@kind"] = "toff"
    V["07-toff-roundtrip"] = vec("toff-roundtrip", "gpsd-json", "gpsd-json", js(toff), canon(toff, TOFF, "TOFF"), m,
        note="precision is not in the TOFF table and is residue, written after the mapped members")

    # 08 OSC
    osc = {"class": "OSC", "device": "/dev/ttyACM0", "running": True, "reference": True, "disciplined": False,
           "delta": -38}
    m = model_of(osc, OSC)
    m["@kind"] = "osc"
    V["08-osc-roundtrip"] = vec("osc-roundtrip", "gpsd-json", "gpsd-json", js(osc), canon(osc, OSC, "OSC"), m)

    # 09 VERSION
    ver = {"class": "VERSION", "release": "3.27", "rev": "release-3.27-12-gabcdef0", "proto_major": 3,
           "proto_minor": 17}
    m = model_of(ver, VERSION)
    m["@kind"] = "version"
    V["09-version-roundtrip"] = vec("version-roundtrip", "gpsd-json", "gpsd-json", js(ver),
                                    canon(ver, VERSION, "VERSION"), m)

    # 10 DEVICES with two DEVICE items
    devs = {"class": "DEVICES", "devices": [
        {"class": "DEVICE", "path": "/dev/ttyACM0", "driver": "u-blox", "subtype": "SW EXT CORE 1.00",
         "bps": 115200, "parity": "N", "stopbits": 1, "native": 1, "cycle": 1.0, "mincycle": 0.125, "flags": 1},
        {"class": "DEVICE", "path": "tcp://192.0.2.10:2101", "driver": "RTCM104V3", "flags": 4,
         "readonly": True}]}
    m = model_of(devs, DEVICES)
    m["@kind"] = "devices"
    m["gpsd.devices[1].gpsd.path"] = "tcp://192.0.2.10:2101"
    V["10-devices-roundtrip"] = vec("devices-roundtrip", "gpsd-json", "gpsd-json", js(devs),
                                    canon(devs, DEVICES, "DEVICES"), m,
        note="devices is a group whose items are DEVICE objects; their class is a const of the group; cycle 1.0 is written 1")

    # 11 DEVICE, its activated member as a time stamp (not mapped: residue)
    dev = {"class": "DEVICE", "path": "/dev/ttyUSB0", "activated": "2026-03-04T05:00:00.000Z",
           "driver": "NMEA0183", "bps": 9600, "parity": "N", "stopbits": 1, "native": 0, "cycle": 1,
           "sernum": "SN-1042", "subtype1": "PROTVER=18.00", "hexdata": "b5620a0400000e34"}
    m = model_of(dev, DEVICE)
    m["@kind"] = "device"
    V["11-device-roundtrip"] = vec("device-roundtrip", "gpsd-json", "gpsd-json", js(dev),
                                   canon(dev, DEVICE, "DEVICE"), m,
        note="activated is not mapped: the table says a time stamp string, gpsd also sends 0 for a deactivated device; as residue it round-trips either way")

    # 12 WATCH
    watch = {"class": "WATCH", "enable": True, "json": True, "nmea": False, "raw": 0, "scaled": False,
             "split24": False, "pps": True, "device": "/dev/ttyACM0"}
    m = model_of(watch, WATCH)
    m["@kind"] = "watch"
    V["12-watch-roundtrip"] = vec("watch-roundtrip", "gpsd-json", "gpsd-json", js(watch),
                                  canon(watch, WATCH, "WATCH"), m)

    # 13 POLL with one TPV and one SKY with one satellite
    poll = {"class": "POLL", "time": "2026-03-04T05:06:09.250Z", "active": 1,
            "tpv": [{"class": "TPV", "device": "/dev/ttyACM0", "mode": 3, "time": "2026-03-04T05:06:09Z",
                     "lat": -33.856784, "lon": 151.215297, "altHAE": 23.5, "speed": 0.25, "track": 180}],
            "sky": [{"class": "SKY", "device": "/dev/ttyACM0", "hdop": 1.25,
                     "satellites": [{"PRN": 12, "az": 45, "el": 60.5, "ss": 40, "used": True}]}]}
    m = model_of(poll, POLL)
    m["@kind"] = "poll"
    m["gpsd.poll_tpv[0].lat"] = "-33.856784"
    m["gpsd.poll_sky[0].gpsd.satellites.#"] = "1"
    V["13-poll-roundtrip"] = vec("poll-roundtrip", "gpsd-json", "gpsd-json", js(poll), canon(poll, POLL, "POLL"), m,
        note="tpv and sky are groups whose items are TPV and SKY objects; a SKY item has its own satellites group")

    # 14 ERROR, 15 ACK, 16 SUBFRAME header
    err = {"class": "ERROR", "message": "Unrecognized request '?NOPE'"}
    V["14-error-roundtrip"] = vec("error-roundtrip", "gpsd-json", "gpsd-json", js(err), canon(err, ERROR, "ERROR"),
                                  {"@kind": "error", "gpsd.message": err["message"]})
    V["15-ack-roundtrip"] = vec("ack-roundtrip", "gpsd-json", "gpsd-json", '{"class":"ACK"}', '{"class":"ACK"}',
                                {"@kind": "ack"})
    sub = {"class": "SUBFRAME", "device": "/dev/ttyACM0", "tSV": 7, "TOW17": 102345, "frame": 4, "gnssId": 0,
           "scaled": True}
    m = model_of(sub, SUBFRAME)
    m["@kind"] = "subframe"
    V["16-subframe-header-roundtrip"] = vec("subframe-header-roundtrip", "gpsd-json", "gpsd-json", js(sub),
                                            canon(sub, SUBFRAME, "SUBFRAME"), m,
        note="the SUBFRAME header members; the page sub-object is not mapped")

    # 17 TPV to geojson, 18 TPV to cot-xml
    t = {"class": "TPV", "device": "/dev/ttyACM0", "mode": 3, "time": "2026-03-04T05:06:07.123Z",
         "lat": 47.9123456, "lon": 11.4567891, "altHAE": 559.5, "altMSL": 512.25, "speed": 12.5, "track": 95.75,
         "eph": 3.5}
    ms = iso_ms(t["time"])
    gj = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,%s]},'
          '"properties":{"time_ms":%d,"course":%s,"speed_ms":%s}}') % (num(t["lon"]), num(t["lat"]), num(t["altHAE"]),
                                                                     ms, num(t["track"]), num(t["speed"]))
    V["17-tpv-to-geojson"] = vec("tpv-to-geojson", "gpsd-json", "geojson", js(t), gj,
        {"lat": num(t["lat"]), "lon": num(t["lon"]), "hae": num(t["altHAE"]), "time_ms": str(ms),
         "speed_ms": num(t["speed"]), "course": num(t["track"]), "@kind": "tpv"},
        note="altHAE is the third coordinate; altMSL, eph and the other members have no geojson line")
    cot = ('<event version="2.0" type="a-u-X" time="%s" start="%s"><point lat="%s" lon="%s" hae="%s" '
           'ce="9999999" le="9999999"/><detail><track course="%s" speed="%s"/></detail></event>') % (
        ms_iso(ms), ms_iso(ms), num(t["lat"]), num(t["lon"]), num(t["altHAE"]), num(t["track"]), num(t["speed"]))
    V["18-tpv-to-cot-xml"] = vec("tpv-to-cot-xml", "gpsd-json", "cot-xml", js(t), cot,
        note="cot-xml writes its defaults for type, ce and le; eph is not bound to ce (its confidence is not stated)")

    # 19..21 errors
    V["19-unknown-class-is-no-kind"] = vec("unknown-class-is-no-kind", "gpsd-json", "gpsd-json",
        '{"class":"AIS","type":1,"device":"/dev/ttyUSB2"}', error="no-kind",
        note="AIS reports are an extension whose members the document defers to another document; no kind")
    V["20-no-class-is-no-kind"] = vec("no-class-is-no-kind", "gpsd-json", "gpsd-json",
        '{"lat":1.5,"lon":2.5}', error="no-kind", note="every response has a class; without it no kind holds")
    V["21-latitude-as-text"] = vec("latitude-as-text", "gpsd-json", "gpsd-json",
        '{"class":"TPV","mode":2,"lat":"47.5","lon":11.5}', error="transform-decode",
        note="lat is numeric; a JSON string under float is a transform failure (0.5 json transforms)")
    V["22-time-without-designator"] = vec("time-without-designator", "gpsd-json", "gpsd-json",
        '{"class":"TPV","mode":3,"time":"2026-03-04T05:06:07"}', error="transform-decode",
        note="time is ISO 8601 UTC; without Z or an offset iso8601_ms fails")
    return V


def geojson_to_tpv():
    ms = iso_ms("2026-03-04T05:06:07.123Z")
    inp = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[11.4567891,47.9123456,559.5]},'
           '"properties":{"time_ms":%d,"course":95.75,"speed_ms":12.5,"callsign":"UNIT 7"},"id":"u7"}') % ms
    exp = canon({"altHAE": 559.5, "lat": 47.9123456, "lon": 11.4567891, "speed": 12.5,
                 "time": ms_iso(ms), "track": 95.75}, TPV, "TPV")
    return vec("to-gpsd-json-tpv", "geojson", "gpsd-json", inp, exp,
               note="encode picks the first kind whose requires hold (tpv: lat lon); the when writes class; callsign and id have no gpsd line; mode, which gpsd always sends, has no source here and is not written")


def cot_to_tpv():
    inp = ('<event uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g">'
           '<point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/>'
           '<detail><contact callsign="GATOR"/><track course="270" speed="4.5"/></detail></event>')
    exp = canon({"altHAE": -42.6, "lat": 30.0090027, "lon": -85.9578182, "speed": 4.5,
                 "time": "2021-02-27T20:00:00.000Z", "track": 270}, TPV, "TPV")
    return vec("to-gpsd-json-tpv", "cot-xml", "gpsd-json", inp, exp,
               note="lat, lon, hae, time, course and speed carry; ce and le have no gpsd line (eph and epv state no confidence)")


def build(out):
    written = {}
    for fn, v in build_vectors().items():
        out.write("packs/gpsd-json/vectors/%s.json" % fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written["gpsd-json"] = written.get("gpsd-json", 0) + 1
    out.write("packs/geojson/vectors/96-to-gpsd-json-tpv.json",
              json.dumps(geojson_to_tpv(), indent=2, ensure_ascii=False) + "\n")
    out.write("packs/cot-xml/vectors/21-to-gpsd-json-tpv.json",
              json.dumps(cot_to_tpv(), indent=2, ensure_ascii=False) + "\n")
    written["geojson"] = written["cot-xml"] = 1
    return written


def main(argv=None):
    return genio.vector_main("gpsd-json-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
