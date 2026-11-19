#!/usr/bin/env python3
"""gdl90-vectors: write the conversion vectors of the gdl90 pack.

Python 3 standard library only; imports no engine and does not read any pack.def.
The payload layouts below are this program's own restatement of how Stratux
(https://github.com/cyoung/stratux, BSD-3-Clause, commit
36b504555408fb90dd5cf1171d4f91f99571e50c) builds each message: main/gen_gdl90.go
(makeHeartbeat, makeOwnshipReport, makeOwnshipGeometricAltitudeReport,
relayMessage, makeFFIDMessage, makeLatLng, prepareMessage), main/traffic.go
(makeTrafficReportMsg) and main/gps.go (makeFFAHRSMessage).

A layout is a list of (key, first bit, bit count, kind) with bits counted from
the most significant bit of payload byte 0. kind is "u" unsigned, "s" two's
complement, "le" unsigned 16-bit least significant byte first, "a" ASCII padded
with NUL, or a constant integer. Every expected hex string is pack()'s result.
Each reference also gives the framed form (flag, escapes, CRC) for reading a
capture; the pack itself does not hold the framing.

Version 0.2 of the pack names the values Stratux states mean "no value" with
the field option `absent` (engine-spec 0.9). This program holds its own table of
them (SENTINELS below): a field holding one decodes to no key, and an entity
without the key writes the sentinel.

Usage: python3 -I tools/gen/gdl90-vectors.py [--out DIR] [--check]
Writes packs/gdl90/vectors/*.json and, for a vector whose input is another
format, packs/<that format>/vectors/to-gdl90-<name>.json. With --check nothing is
written and the exit status is 1 when a committed file differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

LATLON = 180.0 / 8388608.0       # degrees per count of a 24-bit position (makeLatLng)

HEARTBEAT = [("id", 0, 8, 0),
             ("gdl90.hb_gps_valid", 8, 1, "u"), ("gdl90.hb_maint_required", 9, 1, "u"),
             ("gdl90.hb_status1_bit5", 10, 1, "u"), ("gdl90.hb_addr_talkback", 11, 1, "u"),
             ("gdl90.hb_status1_bits3_1", 12, 3, "u"), ("gdl90.hb_uat_initialized", 15, 1, "u"),
             ("gdl90.hb_time_bit16", 16, 1, "u"), ("gdl90.hb_status2_bits6_1", 17, 6, "u"),
             ("gdl90.hb_utc_ok", 23, 1, "u"), ("gdl90.hb_time_low16", 24, 16, "le"),
             ("gdl90.hb_msg_counts_raw", 40, 16, "u")]
UPLINK = [("id", 0, 8, 7), ("gdl90.uplink_tor_raw", 8, 24, "u")]


def report(msg_id):
    return [("id", 0, 8, msg_id),
            ("gdl90.alert_status", 8, 4, "u"), ("gdl90.address_type", 12, 4, "u"),
            ("gdl90.address", 16, 24, "u"), ("@lat", 40, 24, "s"), ("@lon", 64, 24, "s"),
            ("gdl90.alt_raw", 88, 12, "u"), ("gdl90.airborne", 100, 1, "u"),
            ("gdl90.extrapolated", 101, 1, "u"), ("gdl90.track_type", 102, 2, "u"),
            ("gdl90.nic", 104, 4, "u"), ("gdl90.nacp", 108, 4, "u"),
            ("gdl90.speed_kt", 112, 12, "u"), ("gdl90.vvel_raw", 124, 12, "s"),
            ("gdl90.track_raw", 136, 8, "u"), ("gdl90.emitter_category", 144, 8, "u"),
            ("callsign", 152, 64, "a"), ("gdl90.priority_status", 216, 4, "u"),
            ("gdl90.report_spare", 220, 4, "u")]


TRAFFIC, OWNSHIP = report(0x14), report(0x0A)
GEOALT = [("id", 0, 8, 0x0B), ("@geo", 8, 16, "s"), ("gdl90.geo_fom_raw", 24, 16, "u")]
FF_ID = [("id", 0, 8, 0x65), ("sub", 8, 8, 0), ("gdl90.ff_version", 16, 8, "u"),
         ("gdl90.ff_serial", 24, 64, "u"), ("gdl90.ff_short_name", 88, 64, "a"),
         ("gdl90.ff_long_name", 152, 128, "a"), ("gdl90.ff_reserved", 280, 24, "u"),
         ("gdl90.ff_capabilities", 304, 8, "u")]
FF_AHRS = [("id", 0, 8, 0x65), ("sub", 8, 8, 1), ("gdl90.ahrs_roll_tenths", 16, 16, "s"),
           ("gdl90.ahrs_pitch_tenths", 32, 16, "s"), ("gdl90.ahrs_heading_raw", 48, 16, "u"),
           ("gdl90.ahrs_ias_raw", 64, 16, "u"), ("gdl90.ahrs_tas_raw", 80, 16, "u")]


def pack(layout, v):
    nbits = max(first + n for _k, first, n, _t in layout)
    acc = 0
    for key, first, n, t in layout:
        if isinstance(t, int):
            x = t
        elif t == "a":
            raw = v.get(key, "").encode("ascii")
            assert len(raw) <= n // 8
            x = int.from_bytes(raw.ljust(n // 8, b"\0"), "big")
        else:
            x = v.get(key, 0)
            if t == "s":
                assert -(1 << (n - 1)) <= x < (1 << (n - 1)), (key, x)
                x &= (1 << n) - 1
            elif t == "le":
                assert 0 <= x < 65536
                x = int.from_bytes(x.to_bytes(2, "big"), "little")
            assert 0 <= x < (1 << n), (key, x)
        acc |= x << (nbits - first - n)
    return acc.to_bytes(nbits // 8, "big").hex()


def crc16(data):
    """CRC-16 with polynomial 0x1021, register starting at 0, table form, as
    Stratux crcInit / crcCompute state it."""
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
        table.append(crc)
    ret = 0
    for b in data:
        ret = (table[ret >> 8] ^ (ret << 8) ^ b) & 0xFFFF
    return ret


def framed(payload_hex):
    """prepareMessage: CRC low byte then high byte, escape 0x7E and 0x7D, flags."""
    data = bytes.fromhex(payload_hex)
    c = crc16(data)
    data += bytes([c & 0xFF, c >> 8])
    out = bytearray([0x7E])
    for b in data:
        if b in (0x7E, 0x7D):
            out += bytes([0x7D, b ^ 0x20])
        else:
            out.append(b)
    out.append(0x7E)
    return out.hex()


def plain(x):
    """Shortest round-trip decimal, plain notation, integer-valued without a point
    (engine-spec 0.1.1 ruling 3)."""
    if x == int(x):
        return str(int(x))
    r = repr(x)
    assert "e" not in r
    return r


REF = "Stratux commit 36b5045, %s; bytes computed by tools/gen/gdl90-vectors.py"


def vec(name, frm, to, inp, expect=None, error=None, model=None, ref=""):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = ref
    return v


# The "no value" codes Stratux states, as the raw unsigned value of the field:
# gen_gdl90.go makeOwnshipReport (altitude 0xFFF "invalid altitude", vertical
# velocity 0x800 "no information available"), traffic.go makeTrafficReportMsg
# (altitude 0xFFF "Invalid or unavailable"), makeOwnshipGeometricAltitudeReport
# (figure of merit 0x7FFF "Not available"), makeFFIDMessage (serial all 0xFF,
# "invalid"), gps.go makeFFAHRSMessage ("Values if invalid": 0x7FFF, 0xFFFF).
SENTINELS = {"gdl90.alt_raw": 0xFFF, "gdl90.vvel_raw": 0x800, "gdl90.geo_fom_raw": 0x7FFF,
             "gdl90.ff_serial": (1 << 64) - 1, "gdl90.ahrs_roll_tenths": 0x7FFF,
             "gdl90.ahrs_pitch_tenths": 0x7FFF, "gdl90.ahrs_heading_raw": 0xFFFF,
             "gdl90.ahrs_ias_raw": 0xFFFF, "gdl90.ahrs_tas_raw": 0xFFFF}
# keys a second line reads from the same bits, scaled (the raw key, the function)
SCALED = {"gdl90.pressure_alt_ft": ("gdl90.alt_raw", lambda v: v * 25 - 1000),
          "gdl90.vvel_fpm": ("gdl90.vvel_raw", lambda v: v * 64),
          "gdl90.ahrs_roll_deg": ("gdl90.ahrs_roll_tenths", lambda v: v * 1 / 10),
          "gdl90.ahrs_pitch_deg": ("gdl90.ahrs_pitch_tenths", lambda v: v * 1 / 10)}


def is_sentinel(key, value, n):
    return key in SENTINELS and (value & ((1 << n) - 1)) == SENTINELS[key]


def mdl(kind, values, layout):
    """The keys decode gives: a field holding its sentinel gives none."""
    m = {"@kind": kind}
    widths = {}
    for key, _f, n, t in layout:
        widths[key] = n
        if key in values and not key.startswith("@") and key != "id":
            if t != "a" and is_sentinel(key, values[key], n):
                continue
            m[key] = values[key] if t == "a" else str(values[key])
    for key, (raw, fn) in SCALED.items():
        if raw in values and raw in widths and not is_sentinel(raw, values[raw], widths[raw]):
            m[key] = plain(fn(values[raw]))
    return m


def build():
    out = []
    # heartbeat: 70000 s after 0000Z -> bit 16 set, low 16 bits 4464 (0x1170) sent 70 11
    hb = {"gdl90.hb_gps_valid": 1, "gdl90.hb_maint_required": 0, "gdl90.hb_addr_talkback": 1,
          "gdl90.hb_uat_initialized": 1, "gdl90.hb_time_bit16": 1, "gdl90.hb_utc_ok": 1,
          "gdl90.hb_time_low16": 70000 - 65536, "gdl90.hb_msg_counts_raw": 0,
          "gdl90.hb_status1_bit5": 0, "gdl90.hb_status1_bits3_1": 0, "gdl90.hb_status2_bits6_1": 0}
    h = pack(HEARTBEAT, hb)
    out.append(vec("heartbeat-roundtrip", "gdl90", "gdl90", h, h, model=mdl("heartbeat", hb, HEARTBEAT),
                   ref=REF % "makeHeartbeat" + ". GPS valid, address talkback, UAT initialized, UTC OK; "
                       "70000 s after 0000Z: bit 16 in byte 2, the low 16 bits 0x1170 least significant "
                       "byte first. Framed: " + framed(h)))
    hb2 = dict(hb, **{"gdl90.hb_status1_bit5": 1, "gdl90.hb_status1_bits3_1": 5,
                      "gdl90.hb_status2_bits6_1": 33, "gdl90.hb_msg_counts_raw": 0x1234,
                      "gdl90.hb_maint_required": 1, "gdl90.hb_time_bit16": 0, "gdl90.hb_time_low16": 1})
    h2 = pack(HEARTBEAT, hb2)
    out.append(vec("heartbeat-unnamed-bits-carried", "gdl90", "gdl90", h2, h2,
                   model=mdl("heartbeat", hb2, HEARTBEAT),
                   ref=REF % "makeHeartbeat" + ". Bits and bytes Stratux does not write are set; the pack "
                       "carries them as raw keys, so the message round-trips."))
    # uplink: 4 header bytes, then the 432-byte UAT uplink payload, which is not mapped
    up = {"gdl90.uplink_tor_raw": 0x0A0B0C}
    u = pack(UPLINK, up)
    payload = bytes((i * 7 + 3) % 256 for i in range(432)).hex()
    out.append(vec("uplink-payload-not-carried", "gdl90", "gdl90", u + payload, u,
                   model=mdl("uplink", up, UPLINK),
                   ref=REF % "relayMessage, UPLINK_FRAME_DATA_BYTES" + ". ID 7, 3 time bytes, a 432-byte "
                       "uplink payload; the payload is not mapped (no bytes transform), so encode writes "
                       "the 4 header bytes."))
    # traffic report: exact semicircle positions
    lat_c, lon_c = 2097152 + 12345, -4194304 - 54321
    tr = {"gdl90.alert_status": 1, "gdl90.address_type": 0, "gdl90.address": 0xA1B2C3,
          "@lat": lat_c, "@lon": lon_c, "gdl90.alt_raw": (4500 + 1000) // 25, "gdl90.airborne": 1,
          "gdl90.extrapolated": 0, "gdl90.track_type": 1, "gdl90.nic": 8, "gdl90.nacp": 9,
          "gdl90.speed_kt": 123, "gdl90.vvel_raw": -8, "gdl90.track_raw": 200,
          "gdl90.emitter_category": 1, "callsign": "N123AB", "gdl90.priority_status": 0,
          "gdl90.report_spare": 0}
    t = pack(TRAFFIC, tr)
    lat, lon = lat_c * 180 / 8388608, lon_c * 180 / 8388608
    mt = mdl("traffic", tr, TRAFFIC)
    mt.update({"lat": plain(lat), "lon": plain(lon)})
    out.append(vec("traffic-roundtrip", "gdl90", "gdl90", t, t, model=mt,
                   ref=REF % "makeTrafficReportMsg, makeLatLng" + ". Alert set, ICAO address A1B2C3, "
                       "4500 ft, airborne with true track, NIC 8, NACp 9, 123 kt, -512 ft/min, callsign "
                       "N123AB. Position counts 2109497 and -4248625 of 180/2^23 degrees. Framed: "
                       + framed(t)))
    gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"callsign":"N123AB"}}' % (
        plain(lon), plain(lat))
    out.append(vec("traffic-to-geojson", "gdl90", "geojson", t, gj, model=mt,
                   ref=REF % "makeTrafficReportMsg" + ". lat and lon are the 24-bit counts x 180/2^23 "
                       "(exact in a double); geojson canonical form by hand (0.1.1 rulings 3 and 4): no "
                       "altitude is carried (pressure altitude is not hae)."))
    cot = ('<event version="2.0" type="a-u-X"><point lat="%s" lon="%s" hae="9999999" ce="9999999" '
           'le="9999999"/><detail><contact callsign="N123AB"/></detail></event>' % (plain(lat), plain(lon)))
    out.append(vec("traffic-to-cot-xml", "gdl90", "cot-xml", t, cot,
                   ref=REF % "makeTrafficReportMsg" + ". cot-xml canonical form by hand from its pack: the "
                       "constant version, the type and point defaults, the callsign; no uid (the 24-bit "
                       "address is an integer, not bound to uid), no time."))
    # geojson -> gdl90: traffic kind by requires, defaults for altitude and vertical velocity
    g_in = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90,45]},"properties":{"callsign":"N9"}}'
    fromg = {"@lat": 2097152, "@lon": -4194304, "gdl90.alt_raw": 4095, "gdl90.vvel_raw": -2048,
             "callsign": "N9"}
    out.append({"name": "geojson-to-traffic", "from": "geojson", "to": "gdl90", "input": g_in,
                "expect": pack(TRAFFIC, fromg), "source": "constructed",
                "reference": REF % "makeTrafficReportMsg" + ". 45 and -90 degrees are 2097152 and -4194304 "
                             "counts; the entity has no altitude or vertical velocity, so the first sentinel of "
                             "each is written: 0xFFF and 0x800 (engine-spec 0.9, Encode); every other field zero."})
    out.append({"name": "geojson-longitude-180-out-of-range", "from": "geojson", "to": "gdl90",
                "input": '{"type":"Feature","geometry":{"type":"Point","coordinates":[180,0]},"properties":{}}',
                "expect_error": "transform-encode", "source": "constructed",
                "reference": "180 degrees is 8388608 counts, one more than a 24-bit two's complement field "
                             "holds (engine-spec 0.5, sscale range check)"})
    # ownship: same layout, ID 10, south and west, ownship sentinels
    own = {"gdl90.alert_status": 0, "gdl90.address_type": 1, "gdl90.address": 0xF00000,
           "@lat": -1234567, "@lon": 3456789, "gdl90.alt_raw": 4095, "gdl90.airborne": 1,
           "gdl90.extrapolated": 0, "gdl90.track_type": 1, "gdl90.nic": 8, "gdl90.nacp": 10,
           "gdl90.speed_kt": 4000, "gdl90.vvel_raw": -2048, "gdl90.track_raw": 255,
           "gdl90.emitter_category": 1, "callsign": "Stratux", "gdl90.priority_status": 0,
           "gdl90.report_spare": 0}
    o = pack(OWNSHIP, own)
    mo = mdl("ownship", own, OWNSHIP)
    mo.update({"lat": plain(-1234567 * 180 / 8388608), "lon": plain(3456789 * 180 / 8388608)})
    out.append(vec("ownship-roundtrip", "gdl90", "gdl90", o, o, model=mo,
                   ref=REF % "makeOwnshipReport" + ". Self-assigned address F00000 (address type 1), "
                       "pressure altitude invalid 0xFFF and vertical velocity 0x800 (no information): no "
                       "altitude or vertical velocity key, the sentinels written back; NIC 8, "
                       "track byte 255, callsign Stratux. Framed: " + framed(o)))
    # ownship geometric altitude: 5 ft per count, signed
    ga = {"@geo": -100, "gdl90.geo_fom_raw": 10}
    gh = pack(GEOALT, ga)
    out.append(vec("ownship-geometric-altitude-negative", "gdl90", "gdl90", gh, gh,
                   model={"@kind": "ownship-geometric-altitude", "gdl90.geo_alt_ft": "-500",
                          "gdl90.geo_fom_raw": "10"},
                   ref=REF % "makeOwnshipGeometricAltitudeReport" + ". -100 counts of 5 ft = -500 ft; "
                       "figure of merit 10 as Stratux writes it."))
    ga2 = {"@geo": 32767, "gdl90.geo_fom_raw": 0x7FFF}
    gh2 = pack(GEOALT, ga2)
    out.append(vec("ownship-geometric-altitude-largest", "gdl90", "gdl90", gh2, gh2,
                   model={"@kind": "ownship-geometric-altitude", "gdl90.geo_alt_ft": "163835"},
                   ref=REF % "makeOwnshipGeometricAltitudeReport" + ". The largest altitude count and the "
                       "figure of merit 0x7FFF, which Stratux names not available: no figure-of-merit key, "
                       "and the sentinel is written back."))
    # ForeFlight ID
    fid = {"gdl90.ff_version": 1, "gdl90.ff_serial": -1, "gdl90.ff_short_name": "Stratux",
           "gdl90.ff_long_name": "v1.6r1-eu032", "gdl90.ff_reserved": 0, "gdl90.ff_capabilities": 1}
    fv = dict(fid, **{"gdl90.ff_serial": (1 << 64) - 1})
    f = pack(FF_ID, fv)
    out.append(vec("foreflight-id-roundtrip", "gdl90", "gdl90", f, f,
                   model={"@kind": "foreflight-id", "gdl90.ff_version": "1",
                          "gdl90.ff_short_name": "Stratux", "gdl90.ff_long_name": "v1.6r1-eu032",
                          "gdl90.ff_capabilities": "1"},
                   ref=REF % "makeFFIDMessage" + ". Serial all 0xFF, which Stratux names invalid: no serial "
                       "key (absent 2^64-1), and the sentinel is written back; short name Stratux, a long name, "
                       "capability bit 0 (geometric altitude is MSL). Framed: " + framed(f)))
    # ForeFlight AHRS
    ah = {"gdl90.ahrs_roll_tenths": -153, "gdl90.ahrs_pitch_tenths": 42, "gdl90.ahrs_heading_raw": 65535,
          "gdl90.ahrs_ias_raw": 65535, "gdl90.ahrs_tas_raw": 65535}
    a = pack(FF_AHRS, ah)
    out.append(vec("foreflight-ahrs-roundtrip", "gdl90", "gdl90", a, a, model=mdl("foreflight-ahrs", ah, FF_AHRS),
                   ref=REF % "makeFFAHRSMessage" + ". Roll -15.3 and pitch 4.2 degrees in tenths, heading "
                       "and airspeeds 0xFFFF as Stratux always sends them (no keys); roll and pitch also in "
                       "degrees. Framed: " + framed(a)))
    ah2 = dict(ah, **{"gdl90.ahrs_roll_tenths": 32767, "gdl90.ahrs_pitch_tenths": 32767})
    a2 = pack(FF_AHRS, ah2)
    out.append(vec("foreflight-ahrs-invalid", "gdl90", "gdl90", a2, a2,
                   model=mdl("foreflight-ahrs", ah2, FF_AHRS),
                   ref=REF % "makeFFAHRSMessage" + ". Every value at its invalid marker (0x7FFF, 0xFFFF): "
                       "no key is set, and each marker is written back."))
    # errors
    out.append(vec("unknown-message-id-is-no-kind", "gdl90", "gdl90", "1e" + "00" * 27, error="no-kind",
                   ref="ID 0x1E (a pass-through basic report in Stratux, MSGTYPE_BASIC_REPORT) has no kind here"))
    out.append(vec("foreflight-unknown-sub-id-is-no-kind", "gdl90", "gdl90", "6502" + "00" * 10,
                   error="no-kind", ref="ForeFlight ID 0x65 with sub-ID 2: Stratux writes only 0 and 1"))
    out.append(vec("traffic-cut-short", "gdl90", "gdl90", t[:54], error="malformed-wire",
                   ref="27 bytes of a 28-byte traffic report"))
    out.append(vec("heartbeat-cut-short", "gdl90", "gdl90", h[:12], error="malformed-wire",
                   ref="6 bytes of a 7-byte heartbeat"))
    # added with version 0.2 of the pack, after the first edition's vectors so those keep their numbers
    # sentinels (engine-spec 0.9): decode leaves the key absent, so context may supply it
    # (ruling 6); without the key encode writes the sentinel
    own_ctx = dict(own, **{"gdl90.alt_raw": 60, "gdl90.vvel_raw": -3})
    v = vec("ownship-sentinels-decode-absent-context-fills-them", "gdl90", "gdl90", o, pack(OWNSHIP, own_ctx),
            ref=REF % "makeOwnshipReport" + ". The altitude 0xFFF and the vertical velocity 0x800 decode to no "
                "key, so the context values (altitude code 60 = 500 ft, vertical velocity -3 = -192 ft/min) "
                "fill them and are written (engine-spec 0.9 ruling 6)")
    v["context"] = {"gdl90.alt_raw": "60", "gdl90.vvel_raw": "-3"}
    out.append(v)
    v = vec("traffic-real-values-are-not-replaced-by-context", "gdl90", "gdl90", t, t,
            ref=REF % "makeTrafficReportMsg" + ". The altitude and vertical velocity hold values, not sentinels; "
                "context only fills keys the decode left absent")
    v["context"] = {"gdl90.alt_raw": "60", "gdl90.vvel_raw": "-3"}
    out.append(v)
    g_alt = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-90,45]},"properties":{}}'
    v = {"name": "geojson-to-traffic-pressure-altitude-from-context", "from": "geojson", "to": "gdl90",
         "input": g_alt, "context": {"gdl90.pressure_alt_ft": "4500"},
         "expect": pack(TRAFFIC, {"@lat": 2097152, "@lon": -4194304, "gdl90.alt_raw": 220,
                                  "gdl90.vvel_raw": -2048}),
         "source": "constructed",
         "reference": REF % "makeTrafficReportMsg" + ". 4500 ft in gdl90.pressure_alt_ft encodes as "
                      "(4500 + 1000) / 25 = 220 through the second line on the altitude bits; the vertical "
                      "velocity is absent and writes its sentinel 0x800"}
    out.append(v)
    ah3 = {"gdl90.ahrs_roll_tenths": 32767, "gdl90.ahrs_pitch_tenths": -450, "gdl90.ahrs_heading_raw": 65535,
           "gdl90.ahrs_ias_raw": 65535, "gdl90.ahrs_tas_raw": 65535}
    a3 = pack(FF_AHRS, ah3)
    v = vec("foreflight-ahrs-roll-sentinel-context-fills-degrees", "gdl90", "gdl90", a3,
            pack(FF_AHRS, dict(ah3, **{"gdl90.ahrs_roll_tenths": 125})),
            model=mdl("foreflight-ahrs", ah3, FF_AHRS),
            ref=REF % "makeFFAHRSMessage" + ". Roll 0x7FFF (invalid) decodes to no roll key, in tenths or in "
                "degrees; the context gives 12.5 degrees, written as 125 tenths through the degrees line")
    v["context"] = {"gdl90.ahrs_roll_deg": "12.5"}
    out.append(v)
    return out


def build_files(out):
    vecs = build()
    assert len({v["name"] for v in vecs}) == len(vecs)
    # A vector lives in the pack that owns its input (spec/vector-format.md):
    # the ones from another format go to that pack as to-gdl90-<name>.json.
    keep = {}
    for i, v in enumerate(vecs, 1):
        if v["from"] == "gdl90":
            rel = "packs/gdl90/vectors/%02d-%s.json" % (i, v["name"])
        else:
            rel = "packs/%s/vectors/to-gdl90-%s.json" % (v["from"], v["name"])
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        d, name = rel.rsplit("/", 1)
        keep.setdefault(d, set()).add(name)
    for d in ["packs/gdl90/vectors"] + sorted({k for k in keep if k != "packs/gdl90/vectors"}):
        for old in out.listdir(d):
            ours = d == "packs/gdl90/vectors" or old.startswith("to-gdl90-")
            if ours and old not in keep.get(d, set()):
                out.remove(d + "/" + old)
    return {"gdl90": len(vecs)}


def main(argv=None):
    return genio.vector_main("gdl90-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
