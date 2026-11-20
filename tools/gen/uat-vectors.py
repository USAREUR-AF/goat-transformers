#!/usr/bin/env python3
"""Vectors of the uat pack (UAT 978 MHz ADS-B downlink payloads).

The payload bytes are built by a bit writer that places each field at the byte
and bit dump978 reads it from (`RawMessage::Bits(first_byte, first_bit,
last_byte, last_bit)`, bytes from 1, bit 1 the most significant), so the
positions here are written in dump978's numbering, not in the pack's 0-based
offsets. The expected model values follow dump978's decode arithmetic
(uat_message.cc): latitude raw x 360/2^24, minus 180 above 90; longitude raw x
360/2^24, minus 360 above 180; altitude (raw - 41) x 25 ft; selected altitude
(raw - 1) x 32 ft; pressure setting 800 + (raw - 1) x 0.8 hPa; ground track
raw x 360/512 degrees. Nothing here imports an engine.

GeoJSON text is written by hand to the rules of engine-spec 0.1.1 (rulings 3,
4 and 5): members type, geometry, properties; coordinates [lon, lat]; floats as
the shortest round-trip decimal.

    python3 -I tools/gen/uat-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys
from decimal import Decimal

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "dump978 f40aa9a0 uat_message.cc; bytes by tools/gen/uat-vectors.py"


class Payload:
    """A payload of `n` bytes; put() writes a value at dump978's (byte, bit) span."""

    def __init__(self, n):
        self.bits = [0] * (8 * n)

    def put(self, fb, fbit, lb, lbit, value):
        first = (fb - 1) * 8 + fbit - 1
        last = (lb - 1) * 8 + lbit - 1
        width = last - first + 1
        assert 0 <= value < (1 << width), (fb, fbit, value)
        for i in range(width):
            self.bits[first + i] = (value >> (width - 1 - i)) & 1

    def hex(self):
        return bytes(int("".join(map(str, self.bits[i:i + 8])), 2)
                     for i in range(0, len(self.bits), 8)).hex()


def fmt(x):
    if isinstance(x, float):
        if x == int(x):
            return str(int(x))
        r = repr(x)
        return format(Decimal(r), "f") if "e" in r else r
    return str(x)


def lat_of(raw):
    v = raw * 360.0 / 16777216.0
    return v - 180 if v > 90 else v


def lon_of(raw):
    v = raw * 360.0 / 16777216.0
    return v - 360 if v > 180 else v


def header(p, ptype, aq, addr):
    p.put(1, 1, 1, 5, ptype)
    p.put(1, 6, 1, 8, aq)
    p.put(2, 1, 4, 8, addr)
    return {"uat.payload_type": ptype, "uat.address_qualifier": aq, "uat.address": addr}


def state_vector(p, sv):
    """sv: raw values. Returns the model keys the pack decodes."""
    m = {}
    p.put(5, 1, 7, 7, sv["lat"])
    p.put(7, 8, 10, 7, sv["lon"])
    if sv["lat"] or sv["lon"]:
        m["lat"], m["lon"] = lat_of(sv["lat"]), lon_of(sv["lon"])
    p.put(10, 8, 10, 8, sv["alt_type"])
    m["uat.altitude_type"] = sv["alt_type"]
    p.put(11, 1, 12, 4, sv["alt"])
    if sv["alt"]:
        m["uat.geometric_altitude_ft" if sv["alt_type"] else "uat.pressure_altitude_ft"] = (sv["alt"] - 41) * 25
    p.put(12, 5, 12, 8, sv["nic"])
    m["uat.nic"] = sv["nic"]
    p.put(13, 1, 13, 2, sv["ag"])
    m["uat.air_ground_state"] = sv["ag"]
    m["uat.sv_reserved_98"] = 0
    if sv["ag"] in (0, 1):
        for (fb, fbit, lb, lbit), k in [((13, 4, 13, 4), "north_south_sign"), ((13, 5, 14, 6), "north_south_velocity_raw"),
                                        ((14, 7, 14, 7), "east_west_sign"), ((14, 8, 16, 1), "east_west_velocity_raw"),
                                        ((16, 2, 16, 2), "vertical_velocity_source"), ((16, 3, 16, 3), "vertical_velocity_sign"),
                                        ((16, 4, 17, 4), "vertical_velocity_raw")]:
            p.put(fb, fbit, lb, lbit, sv[k])
            m["uat." + k] = sv[k]
    elif sv["ag"] == 2:
        for (fb, fbit, lb, lbit), k in [((13, 5, 14, 6), "ground_speed_raw"), ((14, 7, 14, 8), "track_heading_type"),
                                        ((15, 1, 16, 1), "track_heading_raw"), ((16, 2, 16, 5), "aircraft_size"),
                                        ((16, 7, 16, 7), "gps_offset_longitudinal"), ((16, 8, 17, 4), "gps_offset_raw")]:
            p.put(fb, fbit, lb, lbit, sv[k])
            m["uat." + k] = sv[k]
        m["uat.ground_reserved_99"] = 0
        m["uat.ground_reserved_125"] = 0
        if sv["track_heading_type"] == 1:
            m["course"] = sv["track_heading_raw"] * 360.0 / 512.0
    if sv["aq"] in (0, 1, 4, 5):
        p.put(17, 5, 17, 5, sv["utc"])
        p.put(17, 6, 17, 8, sv["feedback"])
        m["uat.utc_coupled"], m["uat.uplink_feedback"] = sv["utc"], sv["feedback"]
    elif sv["aq"] in (2, 3, 6):
        p.put(17, 5, 17, 8, sv["site"])
        m["uat.tisb_site_id"] = sv["site"]
    return m


def mode_status(p, ms):
    m = {}
    for (fb, fbit, lb, lbit), k in [((18, 1, 19, 8), "callsign_word1"), ((20, 1, 21, 8), "callsign_word2"),
                                    ((22, 1, 23, 8), "callsign_word3"), ((24, 1, 24, 3), "emergency_status"),
                                    ((24, 4, 24, 6), "mops_version"), ((24, 7, 24, 8), "sil"),
                                    ((25, 1, 25, 6), "transmit_mso"), ((25, 7, 25, 8), "sda"),
                                    ((26, 1, 26, 4), "nac_p"), ((26, 5, 26, 7), "nac_v"), ((26, 8, 26, 8), "nic_baro"),
                                    ((27, 1, 27, 1), "cc_uat_in"), ((27, 2, 27, 2), "cc_es_in"),
                                    ((27, 3, 27, 3), "cc_tcas_operational"), ((27, 4, 27, 4), "om_tcas_ra_active"),
                                    ((27, 5, 27, 5), "om_ident_active"), ((27, 6, 27, 6), "om_atc_services"),
                                    ((27, 7, 27, 7), "csid"), ((27, 8, 27, 8), "sil_supplement"),
                                    ((28, 1, 28, 2), "gva"), ((28, 3, 28, 3), "single_antenna"),
                                    ((28, 4, 28, 4), "nic_supplement")]:
        p.put(fb, fbit, lb, lbit, ms[k])
        m["uat." + k] = ms[k]
    m["uat.ms_reserved"] = 0
    return m


def base40(chars, emitter=None):
    """The three 16-bit words of an 8-character callsign (dump978 DecodeMS, inverted)."""
    a = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ *??"
    c = [a.index(ch) for ch in chars.ljust(8)]
    return ((emitter or 0) * 1600 + c[0] * 40 + c[1], c[2] * 1600 + c[3] * 40 + c[4], c[5] * 1600 + c[6] * 40 + c[7])


def auxsv(p, alt_type, raw):
    p.put(30, 1, 31, 4, raw)
    m = {"uat.auxsv_reserved": 0}
    if raw:
        m["uat.pressure_altitude_ft" if alt_type else "uat.geometric_altitude_ft"] = (raw - 41) * 25
    return m


def target_state(p, s, ts):
    m = {}
    for (o1, b1, o2, b2), k in [((0, 1, 0, 1), "selected_altitude_type"), ((0, 2, 1, 4), "selected_altitude_raw"),
                                ((1, 5, 2, 5), "bps_raw"), ((2, 6, 2, 6), "selected_heading_valid"),
                                ((2, 7, 2, 7), "selected_heading_sign"), ((2, 8, 3, 7), "selected_heading_raw"),
                                ((3, 8, 3, 8), "mode_indicators_valid"), ((4, 1, 4, 1), "mode_autopilot"),
                                ((4, 2, 4, 2), "mode_vnav"), ((4, 3, 4, 3), "mode_altitude_hold"),
                                ((4, 4, 4, 4), "mode_approach"), ((4, 5, 4, 5), "mode_lnav")]:
        p.put(s + o1, b1, s + o2, b2, ts[k])
        if k == "selected_altitude_raw":
            if ts[k]:
                m["uat.selected_altitude_ft"] = (ts[k] - 1) * 32
        elif k == "bps_raw":
            if ts[k]:
                m["uat.barometric_pressure_setting_hpa"] = 799.2 + ts[k] * 0.8
        else:
            m["uat." + k] = ts[k]
    m["uat.ts_reserved"] = 0
    return m


def geojson(lat, lon, course=None):
    props = "" if course is None else '"course":%s' % fmt(course)
    geom = '{"type":"Point","coordinates":[%s,%s]}' % (fmt(lon), fmt(lat)) if lat is not None else "null"
    return '{"type":"Feature","geometry":%s,"properties":{%s}}' % (geom, props)


AIR = {"ag": 0, "north_south_sign": 0, "north_south_velocity_raw": 121, "east_west_sign": 1,
       "east_west_velocity_raw": 81, "vertical_velocity_source": 1, "vertical_velocity_sign": 1,
       "vertical_velocity_raw": 9, "utc": 1, "feedback": 3, "aq": 0}
# 45.5 N, 122.75 W: 45.5 x 2^24/360 = 2120454.4 -> 2120454; west longitude 360 - 122.75 = 237.25 ->
# 237.25 x 2^24/360 = 11056332.8 -> 11056333
LAT_N, LON_W = 2120454, 11056333
MS = {"emergency_status": 0, "mops_version": 2, "sil": 3, "transmit_mso": 17, "sda": 2, "nac_p": 10,
      "nac_v": 2, "nic_baro": 1, "cc_uat_in": 1, "cc_es_in": 0, "cc_tcas_operational": 0,
      "om_tcas_ra_active": 0, "om_ident_active": 1, "om_atc_services": 0, "csid": 1, "sil_supplement": 0,
      "gva": 2, "single_antenna": 0, "nic_supplement": 0}
TS = {"selected_altitude_type": 0, "selected_altitude_raw": 282, "bps_raw": 268, "selected_heading_valid": 1,
      "selected_heading_sign": 0, "selected_heading_raw": 64, "mode_indicators_valid": 1, "mode_autopilot": 1,
      "mode_vnav": 0, "mode_altitude_hold": 1, "mode_approach": 0, "mode_lnav": 1}


def message(ptype, sv, ms=None, ts_at=None, aux=None, n=34, aq=0, addr=0xA1B2C3):
    p = Payload(n)
    m = header(p, ptype, aq, addr)
    sv = dict(sv, aq=aq)
    m.update(state_vector(p, sv))
    if ms is not None:
        w1, w2, w3 = base40(ms[0], ms[1])
        m.update(mode_status(p, dict(MS, callsign_word1=w1, callsign_word2=w2, callsign_word3=w3)))
    if ts_at is not None:
        m.update(target_state(p, ts_at, TS))
    if aux is not None:
        m.update(auxsv(p, sv["alt_type"], aux))
    return p, m


def reserved(m, spans):
    for s, e in spans:
        while s <= e:
            n = min(64, e - s + 1)
            m["uat.reserved_bits_%d_%d" % (s, s + n - 1)] = 0
            s += n


def vec(name, frm, to, inp, expect, model=None, kind=None, ref=""):
    v = {"name": name, "from": frm, "to": to, "input": inp, "expect": expect}
    if model is not None:
        mm = {"@kind": kind} if kind else {}
        mm.update({k: fmt(x) for k, x in model.items()})
        v["model"] = mm
    v["source"] = "constructed"
    v["reference"] = SOURCE + ("; " + ref if ref else "")
    return v


def build(out):
    files = []
    sv_air = dict(AIR, lat=LAT_N, lon=LON_W, alt_type=0, alt=221, nic=8)        # 4500 ft pressure
    # 01 basic, payload type 0
    p, m = message(0, sv_air, n=18)
    reserved(m, [(136, 143)])
    files.append(("01-basic-roundtrip.json", vec("uat-basic-roundtrip", "uat", "uat", p.hex(), p.hex(), m, "basic",
                                                   "payload type 0, airborne, pressure altitude 4500 ft")))
    files.append(("02-basic-to-geojson.json", vec("uat-basic-to-geojson", "uat", "geojson", p.hex(),
                                                    geojson(m["lat"], m["lon"]), ref="geojson by hand: pressure altitude is not hae")))
    # 03 type 1: SV + MS + AUXSV, geometric altitude primary
    sv1 = dict(sv_air, alt_type=1, alt=245)
    p, m = message(1, sv1, ms=("N978UA", 1), aux=221)
    files.append(("03-sv-ms-auxsv-roundtrip.json", vec("uat-long-type1-roundtrip", "uat", "uat", p.hex(), p.hex(), m,
                                                        "long-sv-ms-auxsv", "callsign N978UA, emitter category 1; "
                                                        "geometric 5100 ft in the state vector, pressure 4500 ft in AUXSV")))
    # 04, 05 types 2 and 5: SV + AUXSV
    for fn, t in (("04-sv-auxsv-type2-roundtrip.json", 2), ("05-sv-auxsv-type5-roundtrip.json", 5)):
        p, m = message(t, sv_air, aux=245)
        reserved(m, [(136, 183), (184, 231)])
        files.append((fn, vec("uat-long-type%d-roundtrip" % t, "uat", "uat", p.hex(), p.hex(), m, "long-sv-auxsv",
                              "payload type %d keeps its code through the raw payload_type key" % t)))
    # 06 type 3: SV on the ground with a true track, MS, TS at byte 30
    sv_gnd = {"lat": 3000000, "lon": 2000000, "alt_type": 0, "alt": 41, "nic": 9, "ag": 2,
              "ground_speed_raw": 13, "track_heading_type": 1, "track_heading_raw": 300, "aircraft_size": 3,
              "gps_offset_longitudinal": 1, "gps_offset_raw": 5, "utc": 0, "feedback": 1}
    p, m = message(3, sv_gnd, ms=("UAL123", 3), ts_at=30)
    files.append(("06-ground-ms-ts-roundtrip.json", vec("uat-long-type3-ground-roundtrip", "uat", "uat", p.hex(), p.hex(), m,
                                                         "long-sv-ms-ts", "on the ground, true track 300 x 360/512 = 210.9375 degrees")))
    files.append(("07-ground-to-geojson.json", vec("uat-ground-to-geojson", "uat", "geojson", p.hex(),
                                                    geojson(m["lat"], m["lon"], m["course"]),
                                                    ref="geojson by hand: course carried, altitude not")))
    # 08 type 4: SV + TS at byte 30
    p, m = message(4, sv_air, ts_at=30)
    reserved(m, [(136, 183), (184, 231)])
    files.append(("08-sv-ts-roundtrip.json", vec("uat-long-type4-roundtrip", "uat", "uat", p.hex(), p.hex(), m,
                                                  "long-sv-ts", "selected altitude (282-1) x 32 = 8992 ft, 1013.6 hPa")))
    # 09 type 6: SV + TS at byte 25 + AUXSV, TIS-B track file address
    sv6 = dict(sv_air, site=11)
    p, m = message(6, sv6, ts_at=25, aux=0, aq=3)
    reserved(m, [(136, 191)])
    files.append(("09-tisb-ts25-auxsv-roundtrip.json", vec("uat-long-type6-tisb-roundtrip", "uat", "uat", p.hex(), p.hex(), m,
                                                            "long-sv-ts25-auxsv", "TIS-B track file (qualifier 3), site 11; AUXSV altitude 0 is no data")))
    # 10 type 9: SV only; southern and eastern position
    sv9 = dict(sv_air, lat=8388608 - 1398101, lon=1677721)
    p, m = message(9, sv9)
    reserved(m, [(136, 271)])
    files.append(("10-sv-type9-roundtrip.json", vec("uat-long-type9-roundtrip", "uat", "uat", p.hex(), p.hex(), m,
                                                     "long-sv", "latitude raw 6990507 is above 90 degrees, so 6990507 x 360/2^24 - 180")))
    files.append(("11-sv-type9-to-geojson.json", vec("uat-long-type9-to-geojson", "uat", "geojson", p.hex(),
                                                       geojson(m["lat"], m["lon"]))))
    # 12 header only, payload type 12
    p = Payload(34)
    m = header(p, 12, 1, 0x00ABCD)
    reserved(m, [(32, 91), (92, 151), (152, 211), (212, 271)])
    files.append(("12-header-only-roundtrip.json", vec("uat-header-only-roundtrip", "uat", "uat", p.hex(), p.hex(), m,
                                                        "header-only", "payload types 11-31 carry only the header for dump978")))
    # 13 no position: latitude and longitude zero, geometry null
    p, m = message(0, dict(sv_air, lat=0, lon=0), n=18)
    files.append(("13-no-position-to-geojson.json", vec("uat-no-position-to-geojson", "uat", "geojson", p.hex(),
                                                         geojson(None, None), ref="lat and lon raw 0: no position")))
    # 14 geojson to uat, the basic kind
    lat, lon = lat_of(2120454), lon_of(11056333)
    p = Payload(18)
    p.put(5, 1, 7, 7, 2120454)
    p.put(7, 8, 10, 7, 11056333)
    files.append(("../../geojson/vectors/to-uat-basic.json", vec("geojson-to-uat-basic", "geojson", "uat", geojson(lat, lon), p.hex(),
                                                   ref="the basic kind requires lat and lon; every other bit 0")))
    # 15 short input
    files.append(("15-short-input.json", {"name": "uat-basic-short", "from": "uat", "to": "uat",
                                          "input": "00a1b2c3" + "00" * 6, "expect_error": "malformed-wire",
                                          "source": "constructed", "reference": "a basic payload is 18 bytes; 10 given"}))
    for fn, v in files:
        out.write(os.path.normpath("packs/uat/vectors/" + fn).replace(os.sep, "/"), json.dumps(v, indent=2) + "\n")
    return {"uat": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("uat-vectors", __doc__.split("\n")[0], build))
