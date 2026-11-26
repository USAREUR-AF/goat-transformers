#!/usr/bin/env python3
"""Write the vectors of the crsf, msp, msp-v2 and ltm packs.

The four packs read hobby and small-UAS telemetry frames without their final check byte:
CRSF broadcast telemetry (TBS CRSF specification, CC BY-SA 4.0), MSP v1 and v2 replies
(INAV msp_messages.json, GPL-3.0-or-later) and LTM frames (INAV ltm.c). This script holds
its own copy of every frame layout (offsets, sizes, signedness, byte order, scale), builds
each frame octet by octet from values written for these vectors, and works out the
expected bytes, the decoded values and the GeoJSON forms by the rules of
spec/engine-spec.md (bits wire, 0.5 uscale/sscale with fraction factors, kinds and
requires, defaults) and of the geojson pack. It reads no pack.def and calls no
goat-transformers engine.

A vector lives under the pack that owns its input (`from`): a geojson-to-<pack> vector is
written to packs/geojson/vectors/to-<pack>-<name>.json. The script writes only the files
it names and removes nothing else.

Usage: python3 -I tools/gen/rc-telemetry-vectors.py [--out DIR] [--check]
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/rc-telemetry-vectors.py from the frame layouts and spec/engine-spec.md; no engine run"
REF = {
    "crsf": "TBS CRSF specification (CRSFv3), crsf.md at a73f7dc, sections Frame Construction and Broadcast Frame Types",
    "msp": "INAV msp_messages.json at 21adf64 (MSP v1 reply frame)",
    "msp-v2": "INAV msp_messages.json and docs/development/msp at 21adf64 (MSP v2 reply frame)",
    "ltm": "INAV src/main/telemetry/ltm.c at 21adf64",
}


def num(x):
    """Canonical text of a model float: shortest round-trip, an integral value without a point."""
    if isinstance(x, float) and x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return repr(x)


def frac(v, n, d):
    """sscale/uscale decode with a fraction factor: v * n / d in doubles (ruling 1 of 0.5)."""
    return float(v) * n / d


def enc(x, n, d):
    """Encode: x * d / n, then round half away from zero."""
    q = x * d / n
    return int(q + 0.5) if q >= 0 else -int(-q + 0.5)


def vec(name, frm, to, inp, expect=None, model=None, error=None, note=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    ref = REF.get(frm, REF.get(to))
    v["reference"] = ref + ("; " + note if note else "")
    return v


# ---------------------------------------------------------------- CRSF (big-endian)

def crsf_frame(ftype, payload, sync=0xC8):
    return bytes([sync, len(payload) + 2, ftype]) + payload


def crsf_vectors():
    V = {}
    # GPS 0x02
    lat_i, lon_i, gs, hdg, alt, sats = 473977419, 85455939, 1236, 27150, 1432, 14
    p = struct.pack(">iiHHHB", lat_i, lon_i, gs, hdg, alt, sats)
    f = crsf_frame(0x02, p)
    m = {"@kind": "gps", "crsf.sync": "200", "lat": num(frac(lat_i, 1, 10000000)),
         "lon": num(frac(lon_i, 1, 10000000)), "speed_ms": num(frac(gs, 1, 36)),
         "crsf.gps_heading": str(hdg), "crsf.gps_altitude": str(alt), "crsf.gps_satellites": str(sats)}
    V["crsf", "01-gps-roundtrip"] = vec("gps-roundtrip", "crsf", "crsf", f.hex(), f.hex(), m,
                                         note="15-byte payload, length byte 17; latitude and longitude in 1e-7 degrees, ground speed in tenths of km/h")
    gps = f
    # the same GPS frame to geojson: lon, lat and speed_ms; the raw keys have no line there
    exp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"speed_ms":%s}}' % (
        num(frac(lon_i, 1, 10000000)), num(frac(lat_i, 1, 10000000)), num(frac(gs, 1, 36)))
    V["crsf", "02-gps-to-geojson"] = vec("gps-to-geojson", "crsf", "geojson", gps.hex(), exp,
                                          note="geometry before properties, no id")
    # GPS extended 0x06
    vals = (3, -125, 340, -50, 35, 12, 512, 180, 260, 0, 9, 14)
    p = struct.pack(">BhhhhhhhhBBB", *vals)
    f = crsf_frame(0x06, p)
    m = {"@kind": "gps_extended", "crsf.gpsx_fix_type": "3",
         "track.vel_north_ms": num(frac(-125, 1, 100)), "track.vel_east_ms": num(frac(340, 1, 100)),
         "track.vel_up_ms": num(frac(-50, 1, 100)), "crsf.gpsx_h_speed_acc": "35", "crsf.gpsx_track_acc": "12",
         "hae": "512", "crsf.gpsx_h_acc": "180", "crsf.gpsx_v_acc": "260", "crsf.gpsx_reserved": "0",
         "crsf.gpsx_hdop": "9", "crsf.gpsx_vdop": "14"}
    V["crsf", "03-gps-extended-roundtrip"] = vec("gps-extended-roundtrip", "crsf", "crsf", f.hex(), f.hex(), m,
                                                  note="20-byte payload, length byte 22; velocities in cm/s, height above the ellipsoid in metres")
    # vario 0x07
    f = crsf_frame(0x07, struct.pack(">h", -42))
    V["crsf", "04-vario-roundtrip"] = vec("vario-roundtrip", "crsf", "crsf", f.hex(), f.hex(),
                                           {"@kind": "vario", "crsf.vario_v_speed": "-42"})
    # battery 0x08 without and with the optional id byte
    bp = struct.pack(">hh", 168, 123) + (4321).to_bytes(3, "big") + bytes([57])
    f = crsf_frame(0x08, bp)
    V["crsf", "05-battery-roundtrip"] = vec("battery-roundtrip", "crsf", "crsf", f.hex(), f.hex(),
                                             {"@kind": "battery", "crsf.battery_voltage": "168", "crsf.battery_current": "123",
                                              "crsf.battery_capacity_used": "4321", "crsf.battery_remaining": "57"},
                                             note="8-byte payload, the capacity a 24-bit value")
    f = crsf_frame(0x08, bp + bytes([2]))
    V["crsf", "06-battery-id-roundtrip"] = vec("battery-id-roundtrip", "crsf", "crsf", f.hex(), f.hex(),
                                                {"@kind": "battery_id", "crsf.battery_voltage": "168", "crsf.battery_id": "2"},
                                                note="the optional sensor id byte present: length byte 11")
    # link statistics 0x14
    lp = bytes([65, 70, 100]) + struct.pack(">b", -3) + bytes([1, 2, 3, 72, 98]) + struct.pack(">b", 7)
    f = crsf_frame(0x14, lp)
    V["crsf", "07-link-statistics-roundtrip"] = vec("link-statistics-roundtrip", "crsf", "crsf", f.hex(), f.hex(),
                                                     {"@kind": "link_statistics", "crsf.link_up_rssi_ant1": "65",
                                                      "crsf.link_up_snr": "-3", "crsf.link_down_snr": "7",
                                                      "crsf.link_down_quality": "98"})
    # attitude 0x1E, sent to a device address in place of the serial sync byte
    f = crsf_frame(0x1E, struct.pack(">hhh", 1745, -873, 31000), sync=0xEA)
    V["crsf", "08-attitude-roundtrip"] = vec("attitude-roundtrip", "crsf", "crsf", f.hex(), f.hex(),
                                              {"@kind": "attitude", "crsf.sync": "234", "crsf.attitude_pitch": "1745",
                                               "crsf.attitude_roll": "-873", "crsf.attitude_yaw": "31000"},
                                              note="angles in units of 100 microradians; the first byte a device address (0xEA)")
    # an unmapped frame type (0x09 barometric altitude) selects no kind
    f = crsf_frame(0x09, bytes(5))
    V["crsf", "09-unmapped-type-is-no-kind"] = vec("unmapped-type-is-no-kind", "crsf", "crsf", f.hex(), error="no-kind")
    # from geojson: lat, lon, speed_ms; the gps kind is the first whose requires hold
    lat, lon, spd = 47.3977419, 8.5455939, 12.5
    feat = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,450.5]},"properties":{"speed_ms":%s},"id":"rc-1"}' % (num(lon), num(lat), num(spd))
    out = crsf_frame(0x02, struct.pack(">iiHHHB", enc(lat, 1, 10000000), enc(lon, 1, 10000000), enc(spd, 1, 36), 0, 0, 0))
    V["geojson", "to-crsf-gps"] = vec("geojson-to-crsf-gps", "geojson", "crsf", feat, out.hex(),
                                      note="gps is the first kind whose requires (lat, lon) hold; sync takes its default 0xC8; fields with no value are zero; hae has no line in the gps kind")
    return V


# ---------------------------------------------------------------- MSP (little-endian)

def msp1(cmd, payload):
    return b"$M>" + bytes([len(payload), cmd]) + payload


def msp2(cmd, payload, flag=0):
    return b"$X>" + bytes([flag]) + struct.pack("<HH", cmd, len(payload)) + payload


def msp_payloads():
    """(kind, code, payload, model values without the module prefix, shared keys)"""
    out = []
    lat_i, lon_i, alt, spd, crs, hdop = 515012345, -1234567, 87, 1550, 2705, 120
    p = struct.pack("<BBiihhhH", 2, 11, lat_i, lon_i, alt, spd, crs, hdop)
    out.append(("raw_gps", 106, p, {"raw_gps_fix_type": "2", "raw_gps_num_sat": "11", "raw_gps_altitude": "87",
                                    "raw_gps_hdop": "120"},
                {"lat": num(frac(lat_i, 1, 10000000)), "lon": num(frac(lon_i, 1, 10000000)),
                 "speed_ms": num(frac(spd, 1, 100)), "course": num(frac(crs, 1, 10))}))
    p = struct.pack("<hhh", -35, 120, 271)
    out.append(("attitude", 108, p, {"attitude_roll": "-35", "attitude_pitch": "120", "attitude_yaw": "271"}, {}))
    p = struct.pack("<ihi", 12345, -60, 12010)
    out.append(("altitude", 109, p, {"altitude_estimated": "12345", "altitude_variometer": "-60", "altitude_baro": "12010"}, {}))
    p = struct.pack("<BHHh", 162, 850, 1010, -250)
    out.append(("analog", 110, p, {"analog_vbat": "162", "analog_mah_drawn": "850", "analog_rssi": "1010",
                                   "analog_amperage": "-250"}, {}))
    return out


def msp_vectors():
    V = {}
    for i, (kind, code, p, raw, shared) in enumerate(msp_payloads(), 1):
        f = msp1(code, p)
        m = {"@kind": kind}
        m.update(shared)
        m.update({"msp." + k: v for k, v in raw.items()})
        V["msp", "%02d-%s-roundtrip" % (i, kind.replace("_", "-"))] = vec(
            "%s-roundtrip" % kind, "msp", "msp", f.hex(), f.hex(), m,
            note="command %d, payload %d bytes" % (code, len(p)))
        g = msp2(code, p)
        m2 = {"@kind": kind, "msp2.flag": "0"}
        m2.update(shared)
        m2.update({"msp2." + k: v for k, v in raw.items()})
        V["msp-v2", "%02d-%s-roundtrip" % (i, kind.replace("_", "-"))] = vec(
            "%s-roundtrip" % kind, "msp-v2", "msp-v2", g.hex(), g.hex(), m2,
            note="the v1 command %d carried in a v2 frame: command and size as 16-bit values" % code)
    # MSP2_INAV_ANALOG, v2 only
    p = struct.pack("<BHhIIIIBH", 0x41, 1620, 250, 4050, 850, 9300, 1350, 61, 1010)
    g = msp2(8194, p, flag=0)
    V["msp-v2", "05-inav-analog-roundtrip"] = vec(
        "inav-analog-roundtrip", "msp-v2", "msp-v2", g.hex(), g.hex(),
        {"@kind": "inav_analog", "msp2.inav_analog_battery_flags": "65", "msp2.inav_analog_vbat": "1620",
         "msp2.inav_analog_power_draw": "4050", "msp2.inav_analog_rssi": "1010"},
        note="command 0x2002, 24-byte payload")
    # raw GPS to geojson (v1)
    kind, code, p, raw, shared = msp_payloads()[0]
    f = msp1(code, p)
    exp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"course":%s,"speed_ms":%s}}' % (
        shared["lon"], shared["lat"], shared["course"], shared["speed_ms"])
    V["msp", "06-raw-gps-to-geojson"] = vec("raw-gps-to-geojson", "msp", "geojson", f.hex(), exp,
                                             note="altitude is above mean sea level and has no line in geojson")
    # a request frame ('<') is not a reply: no kind
    V["msp", "07-request-is-no-kind"] = vec("request-is-no-kind", "msp", "msp", (b"$M<" + bytes([0, 106])).hex(),
                                             error="no-kind")
    # from geojson to MSP v1 raw GPS
    lat, lon, crs, spd = 51.5012345, -0.1234567, 270.5, 15.5
    feat = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"course":%s,"speed_ms":%s}}' % (
        num(lon), num(lat), num(crs), num(spd))
    out = msp1(106, struct.pack("<BBiihhhH", 0, 0, enc(lat, 1, 10000000), enc(lon, 1, 10000000), 0,
                                enc(spd, 1, 100), enc(crs, 1, 10), 0))
    V["geojson", "to-msp-raw-gps"] = vec("geojson-to-msp-raw-gps", "geojson", "msp", feat, out.hex(),
                                         note="raw_gps is the first kind whose requires (lat, lon) hold; fields with no value are zero")
    return V


# ---------------------------------------------------------------- LTM (little-endian)

def ltm(letter, payload):
    return b"$T" + letter.encode() + payload


def ltm_vectors():
    V = {}
    lat_i, lon_i, gs, alt, fix, sats = 451234567, 72345678, 17, 4520, 3, 12
    f = ltm("G", struct.pack("<iiBiB", lat_i, lon_i, gs, alt, (sats << 2) | fix))
    m = {"@kind": "g", "lat": num(frac(lat_i, 1, 10000000)), "lon": num(frac(lon_i, 1, 10000000)),
         "speed_ms": "17", "ltm.g_altitude": "4520", "ltm.g_fix_type": "3", "ltm.g_satellites": "12"}
    V["ltm", "01-g-roundtrip"] = vec("g-roundtrip", "ltm", "ltm", f.hex(), f.hex(), m,
                                      note="satellites in the top six bits and the fix type in the low two bits of the last byte")
    exp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"speed_ms":17}}' % (
        m["lon"], m["lat"])
    V["ltm", "02-g-to-geojson"] = vec("g-to-geojson", "ltm", "geojson", f.hex(), exp)
    f = ltm("A", struct.pack("<hhh", -4, 12, 271))
    V["ltm", "03-a-roundtrip"] = vec("a-roundtrip", "ltm", "ltm", f.hex(), f.hex(),
                                      {"@kind": "a", "ltm.a_pitch": "-4", "ltm.a_roll": "12", "ltm.a_heading": "271"})
    f = ltm("S", struct.pack("<HHBBB", 16420, 850, 200, 14, (9 << 2) | 0b01))
    V["ltm", "04-s-roundtrip"] = vec("s-roundtrip", "ltm", "ltm", f.hex(), f.hex(),
                                      {"@kind": "s", "ltm.s_vbat": "16420", "ltm.s_armed": "1", "ltm.s_failsafe": "0",
                                       "ltm.s_flight_mode": "9"},
                                      note="status byte: armed bit 0, failsafe bit 1, flight mode bits 2 to 7")
    f = ltm("O", struct.pack("<iiiBB", 451200000, 72300000, 21300, 1, 1))
    V["ltm", "05-o-roundtrip"] = vec("o-roundtrip", "ltm", "ltm", f.hex(), f.hex(),
                                      {"@kind": "o", "ltm.o_home_lat": "451200000", "ltm.o_home_lon": "72300000",
                                       "ltm.o_home_alt": "21300", "ltm.o_osd_on": "1", "ltm.o_home_fix": "1"},
                                      note="the home position stays raw: it is not the vehicle's position")
    # no GPS: ltm.c leaves lat, lon and ground speed 0 and fix type 0; no fix: fix type 1 with
    # the solution's values. Neither is a position (the gate holds only for fix type 2 or 3);
    # the raw keys keep the bytes
    f0 = ltm("G", struct.pack("<iiBiB", 0, 0, 0, 1250, 0))
    V["ltm", "07-g-no-gps-to-geojson"] = vec("g-no-gps-to-geojson", "ltm", "geojson", f0.hex(),
                                             '{"type":"Feature","geometry":null,"properties":{}}',
                                             {"@kind": "g", "@absent": ["lat", "lon", "speed_ms"],
                                              "ltm.g_lat": "0", "ltm.g_lon": "0", "ltm.g_fix_type": "0"},
                                             note="fix type 0: no GPS; lat, lon and speed are not a position")
    f1 = ltm("G", struct.pack("<iiBiB", lat_i, lon_i, 0, alt, (5 << 2) | 1))
    V["ltm", "08-g-no-fix-roundtrip"] = vec("g-no-fix-roundtrip", "ltm", "ltm", f1.hex(), f1.hex(),
                                            {"@kind": "g", "@absent": ["lat", "lon", "speed_ms"],
                                             "ltm.g_lat": str(lat_i), "ltm.g_lon": str(lon_i),
                                             "ltm.g_fix_type": "1"},
                                            note="fix type 1: no fix; the frame comes back byte for byte from the raw keys")
    V["ltm", "06-g-frame-cut-short"] = vec("g-frame-cut-short", "ltm", "ltm", ltm("G", bytes(6)).hex(),
                                            error="malformed-wire", note="a G frame needs 14 payload bytes")
    lat, lon, spd = 45.1234567, 7.2345678, 17.0
    feat = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"speed_ms":%s}}' % (
        num(lon), num(lat), num(spd))
    # the gate on the fix type holds for 2 or 3: with no fix type given, encode writes the
    # smallest value it holds for, 2 (engine-spec 0.17 encode step 3)
    out = ltm("G", struct.pack("<iiBiB", enc(lat, 1, 10000000), enc(lon, 1, 10000000), enc(spd, 1, 1), 0, 2))
    V["geojson", "to-ltm-g"] = vec("geojson-to-ltm-g", "geojson", "ltm", feat, out.hex(),
                                   note="g is the first kind whose requires (lat, lon) hold; the fix type is written 2")
    return V


def build(out):
    written = {}
    for V in (crsf_vectors(), msp_vectors(), ltm_vectors()):
        for (pack, name), v in V.items():
            assert v["from"] == pack, (pack, name)
            out.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
            written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("rc-telemetry-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
