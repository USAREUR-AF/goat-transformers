#!/usr/bin/env python3
"""vectors.py: conversion vectors of the gmti pack, packed with struct.

This program states the GMTI layouts again, field by field as struct codes, from
AEDP-4607 Edition A Version 1. It does not read tools/gmti/*.tsv.txt and does not
import an engine, so a mistake in the tables shows as a failing vector. Expected
model values are computed here with the arithmetic the pack's transforms state
(engine-spec 0.5 ruling 1: v * num / den on decode, x * den / num rounded half
away from zero on encode).

Usage: python3 -I tools/gmti/vectors.py   (from the repository root)
"""
import json
import math
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "packs", "gmti", "vectors")
P32 = 4294967296


def sa(v, n):   # signed binary angle of n bits -> degrees
    return v * 180 / (1 << n)


def ba(v, n):   # binary angle of n bits -> degrees
    return v * 360 / (1 << n)


def smag(v, n):  # sign and magnitude of n bits: top bit 1 negative, the rest the magnitude
    mag = v & ((1 << (n - 1)) - 1)
    return -mag if v >> (n - 1) else mag


def rnd(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def num(x):
    """Canonical number text of the text wires: shortest round trip, integral without a fraction."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return repr(x)


def text(s, n):
    b = s.encode("ascii")
    return b + b" " * (n - len(b))


# Packet header: version (2 text), packet size (u32), nationality (2 text), classification (u8),
# classification system (2 text), handling codes (u16), exercise (u8), platform id (10 text),
# mission (u32), job (u32): 32 bytes.
def packet(segments, job=7, platform="N12345"):
    body = b"".join(segments)
    hdr = struct.pack(">2sI2sB2sHB10sII", b"41", 32 + len(body), b"XN", 5, b"XN", 0, 128,
                      text(platform, 10), 1001, job)
    return hdr + body


HDR_MODEL = {"gmti.version_id": "41", "gmti.nationality": "XN", "gmti.classification": "5",
             "gmti.class_system": "XN", "gmti.security_code": "0", "gmti.exercise": "128",
             "gmti.platform_id": "N12345    ", "gmti.mission_id": "1001", "gmti.job_id": "7"}


def segment(stype, body):
    return struct.pack(">BI", stype, 5 + len(body)) + body


def masked(nbytes, fields):
    """fields: (bit, struct code, value); bit 1 is the first bit sent of the mask."""
    mask, body = 0, b""
    for bit, code, value in sorted(fields):
        mask |= 1 << (nbytes * 8 - bit)
        body += struct.pack(">" + code, value)
    return mask.to_bytes(nbytes, "big") + body


VECTORS = []


def vec(name, frm, to, inp, exp, model=None, ref=""):
    v = {"name": "gmti-" + name, "from": frm, "to": to,
         "input": inp.hex() if isinstance(inp, bytes) else inp,
         "expect": exp.hex() if isinstance(exp, bytes) else exp}
    if model:
        v["model"] = model
    v["source"] = "synthetic"
    if ref:
        v["reference"] = ref
    VECTORS.append(v)


def mission():
    body = struct.pack(">12s12sB10sHBB", text("ATO-4471", 12), text("FP-22", 12), 34,
                       text("BLK40 SW7", 10), 2026, 11, 19)
    p = packet([segment(1, body)], job=0)
    m = dict(HDR_MODEL, **{"@kind": "mission", "gmti.job_id": "0", "gmti.mission_plan": "ATO-4471    ",
                           "gmti.flight_plan": "FP-22       ", "gmti.platform_type": "34",
                           "gmti.platform_config": "BLK40 SW7 ", "gmti.reference_year": "2026",
                           "gmti.reference_month": "11", "gmti.reference_day": "19"})
    vec("mission-roundtrip", "gmti", "gmti", p, p, m, "packet header and mission segment, every field")


# Dwell fields: bit, struct code, key, raw value, model text.
LAT1, LON1 = 1157627904, -119304647          # target: 48.515625 deg, about -10 deg
DWELL_TT = [
    (1, "H", "gmti.dwell_revisit_index", 3), (2, "H", "gmti.dwell_index", 12), (3, "B", "gmti.dwell_last_of_revisit", 0),
    (4, "H", "gmti.dwell_target_count", 1), (5, "I", "gmti.dwell_time_ms", 45135250),
    (6, "i", "gmti.sensor_lat", 1145044992), (7, "I", "gmti.sensor_lon", 4160749568), (8, "i", "gmti.sensor_alt_cm", 1066800),
    (14, "H", "gmti.sensor_track", 16384), (15, "I", "gmti.sensor_speed_mms", 180000), (16, "b", "gmti.sensor_vvel_dms", -3),
    (20, "H", "gmti.platform_heading", 16384), (21, "h", "gmti.platform_pitch", 512), (22, "h", "gmti.platform_roll", -1024),
    (23, "i", "gmti.dwell_center_lat", 1157627904), (24, "I", "gmti.dwell_center_lon", 4177526784),
    (25, "H", "gmti.dwell_range_half_km", 2560), (26, "H", "gmti.dwell_angle_half", 364),
    (27, "H", "gmti.sensor_heading", 49152), (28, "h", "gmti.sensor_pitch", -2048), (29, "h", "gmti.sensor_roll", 0),
    (31, "H", "gmti.mti_report_index", 0), (32, "i", "lat", LAT1), (33, "i", "lon", LON1), (36, "h", "hae", 152),
    (37, "h", "gmti.target_los_vel_cms", -1250), (38, "H", "gmti.target_wrap_vel_cms", 4000), (39, "b", "gmti.target_snr_db", 17),
    (40, "B", "gmti.target_class", 2), (41, "B", "gmti.target_class_prob", 80),
]
DWELL_REST = [   # the fields the targeting profile leaves out
    (9, "i", "gmti.lat_scale", 4096), (10, "I", "gmti.lon_scale", 8192), (11, "I", "gmti.sensor_unc_along_cm", 250),
    (12, "I", "gmti.sensor_unc_cross_cm", 300), (13, "H", "gmti.sensor_unc_alt_cm", 500), (17, "B", "gmti.sensor_track_unc_deg", 2),
    (18, "H", "gmti.sensor_speed_unc_mms", 150), (19, "H", "gmti.sensor_vvel_unc_cms", 40), (30, "B", "gmti.mdv_dms", 18),
    (34, "h", "gmti.target_delta_lat", -321), (35, "h", "gmti.target_delta_lon", 654),
    (42, "H", "gmti.target_unc_slant_cm", 1200), (43, "H", "gmti.target_unc_cross_dm", 95), (44, "B", "gmti.target_unc_height_m", 7),
    (45, "H", "gmti.target_unc_los_vel_cms", 30), (46, "B", "gmti.truth_tag_app", 9), (47, "I", "gmti.truth_tag_entity", 77001),
    (48, "b", "gmti.target_rcs_halfdb", -6),
]
SCALE = {"gmti.sensor_lat": lambda v: sa(v, 32), "gmti.sensor_lon": lambda v: ba(v, 32),
         "gmti.lat_scale": lambda v: sa(v, 32), "gmti.lon_scale": lambda v: ba(v, 32),
         "gmti.sensor_track": lambda v: ba(v, 16), "gmti.platform_heading": lambda v: ba(v, 16),
         "gmti.platform_pitch": lambda v: sa(v, 16), "gmti.platform_roll": lambda v: sa(v, 16),
         "gmti.dwell_center_lat": lambda v: sa(v, 32), "gmti.dwell_center_lon": lambda v: ba(v, 32),
         "gmti.dwell_range_half_km": lambda v: v / 128, "gmti.dwell_angle_half": lambda v: ba(v, 16),
         "gmti.sensor_heading": lambda v: ba(v, 16), "gmti.sensor_pitch": lambda v: sa(v, 16),
         "gmti.sensor_roll": lambda v: sa(v, 16), "lat": lambda v: sa(v, 32), "lon": lambda v: v * 360 / P32,
         "hae": float}


def model_of(fields):
    m = {}
    for _, _, k, v in fields:
        m[k] = repr(float(SCALE[k](v))) if k in SCALE else str(v)
    return m


def dwell_body(fields):
    return masked(8, [(b, c, v) for b, c, _, v in fields])


def dwell():
    p = packet([segment(2, dwell_body(DWELL_TT))])
    m = dict(HDR_MODEL, **model_of(DWELL_TT))
    m.update({"@kind": "dwell", "track.class": "vehicle", "track.simulated": "0"})
    vec("dwell-targeting-roundtrip", "gmti", "gmti", p, p, m,
        "dwell with the fields of the targeting class of the implementation guide and one target report; "
        "classification 2 (wheeled, live) reads as track.class vehicle, track.simulated 0")

    allf = sorted(DWELL_TT + DWELL_REST)
    p = packet([segment(2, dwell_body(allf))])
    m = dict(HDR_MODEL, **model_of(allf))
    m["@kind"] = "dwell"
    vec("dwell-every-field-roundtrip", "gmti", "gmti", p, p, m, "every field of the dwell and of its target report")

    # situation class: reduced-size target positions, two targets. Only the first is read; the
    # count stays 2 and the second report is not written.
    sa_hdr = [(1, "H", 3), (2, "H", 13), (3, "B", 1), (4, "H", 2), (5, "I", 45136000),
              (6, "i", 1145044992), (7, "I", 4160749568), (8, "i", 1066800), (9, "i", 4096), (10, "I", 8192),
              (14, "H", 16384), (15, "I", 180000), (16, "b", 0), (20, "H", 16384), (21, "h", 0), (22, "h", 0),
              (23, "i", 1157627904), (24, "I", 4177526784), (25, "H", 2560), (26, "H", 364)]
    t1 = [(31, "H", 0), (34, "h", -321), (35, "h", 654)]
    head = masked(8, sa_hdr + t1)
    second = struct.pack(">Hhh", 1, 100, -200)
    p_in = packet([segment(2, head + second)])
    p_out = packet([segment(2, head)])
    vec("dwell-two-targets-reads-first", "gmti", "gmti", p_in, p_out,
        {"@kind": "dwell", "gmti.dwell_target_count": "2", "gmti.mti_report_index": "0",
         "gmti.target_delta_lat": "-321", "gmti.target_delta_lon": "654"},
        "situation class (mask ff c7 1f c2 60 00 00 00): the second target report is skipped by the segment "
        "length and not written; the stated count is kept")

    # no target reports, target bits set: the target fields start at the end of the segment and read absent
    nohdr = [(b, c, v) for b, c, v in sa_hdr if b != 4] + [(4, "H", 0)]
    mask_in = masked(8, nohdr + [(31, "H", 0), (34, "h", 0), (35, "h", 0)])[:8]
    body_fields = masked(8, nohdr)[8:]
    p_in = packet([segment(2, mask_in + body_fields)])
    p_out = packet([segment(2, masked(8, nohdr))])
    vec("dwell-no-targets-mask-kept-constant", "gmti", "gmti", p_in, p_out,
        {"@kind": "dwell", "gmti.dwell_target_count": "0", "gmti.dwell_index": "13"},
        "a producer may leave the target bits of the mask set when the count is 0; decode reads no target "
        "and encode writes those bits 0")


def hrr():
    f = [(1, "H", 3), (2, "H", 12), (3, "B", 0), (4, "H", 0), (5, "H", 40), (6, "H", 64), (7, "H", 32),
         (8, "B", 115), (9, "B", 60), (10, "H", 6400), (11, "H", 3200), (12, "I", 0x00640000), (13, "I", 0x80320000),
         (14, "I", 0x05000000), (15, "B", 0), (16, "B", 1), (17, "B", 1), (18, "H", 0x8180), (19, "b", 21),
         (20, "h", -120), (21, "I", 0x00010000), (22, "B", 2), (23, "B", 0x80), (24, "B", 1), (25, "B", 0),
         (26, "B", 40), (27, "I", 150000), (28, "B", 16), (29, "I", 0x05400000), (30, "I", 0x00400000)]
    keys = ["hrr_revisit_index", "hrr_dwell_index", "hrr_last_of_revisit", "hrr_mti_report_index",
            "hrr_target_scatterers", "hrr_range_samples", "hrr_doppler_samples", "hrr_clutter_power_qdb",
            "hrr_threshold_qdb", "hrr_range_resolution_cm", "hrr_range_bin_spacing_cm", "hrr_doppler_resolution_hz",
            "hrr_doppler_spacing_hz", "hrr_center_freq_ghz", "hrr_compression", "hrr_range_weighting",
            "hrr_doppler_weighting", "hrr_max_pixel_power_db", "hrr_max_rcs_halfdb", "hrr_range_origin_m",
            "hrr_doppler_origin_hz", "hrr_type", "hrr_processing_mask", "hrr_magnitude_bytes", "hrr_phase_bytes",
            "hrr_range_extent_px", "hrr_range_to_edge_cm", "hrr_zero_velocity_bin", "hrr_electrical_length_m",
            "hrr_electrical_length_unc_m"]
    m = {"@kind": "hrr"}
    for (bit, _, v), k in zip(f, keys):
        if k in ("hrr_range_resolution_cm", "hrr_range_bin_spacing_cm"):
            m["gmti." + k] = repr(v / 128)
        elif k in ("hrr_doppler_resolution_hz", "hrr_doppler_spacing_hz", "hrr_doppler_origin_hz"):
            m["gmti." + k] = repr(smag(v, 32) / 65536)
        elif k == "hrr_max_pixel_power_db":
            m["gmti." + k] = repr(smag(v, 16) / 128)
        elif k in ("hrr_center_freq_ghz", "hrr_electrical_length_m", "hrr_electrical_length_unc_m"):
            m["gmti." + k] = repr(v / 8388608)
        else:
            m["gmti." + k] = str(v)
    body = masked(5, f)
    p = packet([segment(3, body)])
    vec("hrr-roundtrip", "gmti", "gmti", p, p, dict(HDR_MODEL, **m), "every field of the HRR segment before its scatterer records")
    # one-byte magnitude, no phase: the scatterer bit (31) is set and two records of one byte follow
    mask = int.from_bytes(body[:5], "big") | (1 << (40 - 31))
    p_in = packet([segment(3, mask.to_bytes(5, "big") + body[5:] + bytes([200, 180]))])
    vec("hrr-scatterers-not-read", "gmti", "gmti", p_in, p, {"@kind": "hrr", "gmti.hrr_magnitude_bytes": "1"},
        "scatterer records are skipped by the segment length; encode writes the scatterer bit 0")


def corners():
    vals = [(1157627904, 4177526784), (1161527296, 4177526784), (1161527296, 4194304000), (1157627904, 4194304000)]
    b, m = b"", {}
    for c, (la, lo) in zip("abcd", vals):
        b += struct.pack(">iI", la, lo)
        m["gmti.area_%s_lat" % c] = repr(sa(la, 32))
        m["gmti.area_%s_lon" % c] = repr(ba(lo, 32))
    return b, m


def jobdef():
    area, am = corners()
    body = (struct.pack(">IB6sBB", 7, 13, text("V2.1", 6), 1, 20) + area +
            struct.pack(">BHHHHBHHHHBBBBB", 95, 120, 30, 30, 50, 2, 100, 400, 182, 25, 18, 90, 40, 1, 1))
    p = packet([segment(5, body)])
    m = dict(HDR_MODEL, **am)
    m.update({"@kind": "jobdef", "gmti.jobdef_job_id": "7", "gmti.sensor_type": "13", "gmti.sensor_model": "V2.1  ",
              "gmti.target_filtering": "1", "gmti.radar_priority": "20", "gmti.radar_mode": "95",
              "gmti.revisit_interval_ds": "120", "gmti.nom_unc_along_dm": "30", "gmti.nom_unc_cross_dm": "30",
              "gmti.nom_unc_alt_dm": "50", "gmti.nom_unc_heading_deg": "2", "gmti.nom_unc_speed_mms": "100",
              "gmti.nom_slant_range_sd_cm": "400", "gmti.nom_cross_range_sd": repr(ba(182, 16)),
              "gmti.nom_los_vel_sd_cms": "25", "gmti.nom_mdv_dms": "18", "gmti.nom_detection_prob": "90",
              "gmti.nom_false_alarm_db": "40", "gmti.terrain_model": "1", "gmti.geoid_model": "1"})
    vec("jobdef-roundtrip", "gmti", "gmti", p, p, m, "job definition segment, every field")


def freetext():
    ids = struct.pack(">10s10s", text("GS-NORTH", 10), text("ALL", 10))
    p_in = packet([segment(6, ids + b"CHECK GRID 32U")], job=0)
    p_out = packet([segment(6, ids)], job=0)
    vec("freetext-text-not-read", "gmti", "gmti", p_in, p_out,
        {"@kind": "freetext", "gmti.originator_id": "GS-NORTH  ", "gmti.recipient_id": "ALL       "},
        "the text runs to the end of the segment and is not read")


def teststatus():
    p = packet([segment(10, struct.pack(">IHHIBB", 7, 3, 12, 45135250, 0x10, 0x80))])
    vec("teststatus-roundtrip", "gmti", "gmti", p, p,
        dict(HDR_MODEL, **{"@kind": "teststatus", "gmti.ts_job_id": "7", "gmti.ts_revisit_index": "3",
                           "gmti.ts_dwell_index": "12", "gmti.ts_dwell_time_ms": "45135250",
                           "gmti.hardware_status": "16", "gmti.mode_status": "128"}),
        "test and status segment, every field")


def prochist():
    head = struct.pack(">B2s10sII", 2, b"XN", text("N12345", 10), 1001, 7)
    r1 = struct.pack(">B2s10sIIH", 1, b"DE", text("GS-NORTH", 10), 5, 70, 0x0081)
    r2 = struct.pack(">B2s10sIIH", 2, b"NL", text("GS-WEST", 10), 6, 71, 0x0008)
    vec("prochist-reads-first-record", "gmti", "gmti", packet([segment(12, head + r1 + r2)], job=0),
        packet([segment(12, head + r1)], job=0),
        {"@kind": "prochist", "gmti.history_count": "2", "gmti.based_on_platform_id": "N12345    ",
         "gmti.based_on_job_id": "7", "gmti.record_sequence": "1", "gmti.record_nationality": "DE",
         "gmti.record_platform_id": "GS-NORTH  ", "gmti.record_mission_id": "5", "gmti.record_job_id": "70",
         "gmti.processing_performed": "129"},
        "two processing records; the second is skipped by the segment length")


LOC = struct.pack(">IiiiHIb", 45000000, 1157627904, -119304647, 1066800, 16384, 180000, -3)
LOC_MODEL = {"gmti.location_time_ms": "45000000", "lat": repr(sa(1157627904, 32)),
             "lon": repr(-119304647 * 360 / P32), "hae": repr(1066800 / 100), "course": "90.0",
             "speed_ms": "180.0", "track.vel_up_ms": repr(-3 / 10)}


def location():
    p = packet([segment(13, LOC)], job=0)
    vec("location-roundtrip", "gmti", "gmti", p, p,
        dict(HDR_MODEL, **dict(LOC_MODEL, **{"@kind": "location", "gmti.job_id": "0"})),
        "platform location segment: position, track, speed and vertical velocity are shared keys")
    # a second segment in the packet is not read
    mis = segment(1, struct.pack(">12s12sB10sHBB", text("ATO-4471", 12), text("FP-22", 12), 34,
                                 text("BLK40 SW7", 10), 2026, 11, 19))
    vec("two-segments-reads-first", "gmti", "gmti", packet([segment(13, LOC), mis], job=0), p,
        {"@kind": "location", "lat": LOC_MODEL["lat"]},
        "a packet of a location and a mission segment: the mission segment after the first is not read")
    lat, lon, hae = sa(1157627904, 32), -119304647 * 360 / P32, 1066800 / 100
    cot = ('<event version="2.0" uid="N12345    " type="a-u-X"><point lat="%s" lon="%s" hae="%s" ce="9999999" '
           'le="9999999"/><detail><track course="90" speed="180"/></detail></event>' % (num(lat), num(lon), num(hae)))
    vec("location-to-cot", "gmti", "cot-xml", p, cot,
        {"uid": "N12345    ", "lat": repr(lat), "lon": repr(lon), "hae": repr(hae), "course": "90.0", "speed_ms": "180.0", "@complete": True},
        "platform location to a CoT event; uid is the platform id of the packet header (space padded as sent)")


def from_geojson():
    lat, lon, hae, course, speed = 48.515625, -10.25, 10668.5, 135.0, 61.75
    inp = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,%s]},'
           '"properties":{"course":%s,"speed_ms":%s},"id":"trk-9"}' % (num(lon), num(lat), num(hae), num(course), num(speed)))
    body = struct.pack(">IiiiHIb", 0, rnd(lat * P32 / 180), rnd(lon * P32 / 360), rnd(hae * 100),
                       rnd(course * 65536 / 360), rnd(speed * 1000), 0)
    seg = segment(13, body)
    hdr = struct.pack(">2sI2sB2sHB10sII", b"41", 32 + len(seg), b"\0\0", 0, b"\0\0", 0, 0, b"\0" * 10, 0, 0)
    vec("geojson-to-location", "geojson", "gmti", inp, hdr + seg,
        {"lat": repr(lat), "lon": repr(lon), "hae": repr(hae), "course": "135.0", "speed_ms": "61.75"},
        "an entity from another format encodes as a platform location; the version defaults to 41, the "
        "other header fields are zero")


def dwell_to_geojson():
    p = packet([segment(2, dwell_body(DWELL_TT))])
    lat, lon = sa(LAT1, 32), LON1 * 360 / P32
    exp = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,152]},"properties":{},'
           '"id":"N12345    /1001/7/3/12/0"}' % (num(lon), num(lat)))
    vec("dwell-to-geojson", "gmti", "geojson", p, exp,
        {"uid": "N12345    /1001/7/3/12/0", "lat": repr(lat), "lon": repr(lon), "hae": "152.0", "@complete": True},
        "the first target report of a dwell as a Feature; uid is platform/mission/job/revisit/dwell/target index")


def jobreq():
    area, am = corners()
    body = (struct.pack(">10s10sB", text("JSTARS-CC", 10), text("RSR-0042", 10), 5) + area +
            struct.pack(">BHHHBBBBBHHHB6sB", 1, 300, 50, 2026, 11, 19, 14, 30, 0, 600, 3600, 100, 13, text("V2.1", 6), 0))
    p = packet([segment(101, body)], job=0)
    m = dict(am, **{"@kind": "jobreq", "gmti.requestor_id": "JSTARS-CC ", "gmti.requestor_task_id": "RSR-0042  ",
                    "gmti.requestor_priority": "5", "gmti.radar_mode": "1", "gmti.range_resolution_cm": "300",
                    "gmti.cross_range_resolution_dm": "50", "gmti.start_year": "2026", "gmti.start_month": "11",
                    "gmti.start_day": "19", "gmti.start_hour": "14", "gmti.start_minute": "30",
                    "gmti.start_second": "0", "gmti.allowed_delay_s": "600", "gmti.duration_s": "3600",
                    "gmti.revisit_interval_ds": "100", "gmti.sensor_type": "13", "gmti.sensor_model": "V2.1  ",
                    "gmti.request_type": "0"})
    vec("jobreq-roundtrip", "gmti", "gmti", p, p, m, "job request segment, every field")


def joback():
    area, am = corners()
    body = (struct.pack(">I10s10sB6sB", 8, text("JSTARS-CC", 10), text("RSR-0042", 10), 13, text("V2.1", 6), 20) + area +
            struct.pack(">BHHBHBBBBB2s", 1, 3600, 100, 2, 2026, 11, 19, 14, 35, 10, b"US"))
    p = packet([segment(102, body)], job=0)
    m = dict(am, **{"@kind": "joback", "gmti.ack_job_id": "8", "gmti.requestor_id": "JSTARS-CC ",
                    "gmti.requestor_task_id": "RSR-0042  ", "gmti.sensor_type": "13", "gmti.sensor_model": "V2.1  ",
                    "gmti.radar_priority": "20", "gmti.radar_mode": "1", "gmti.duration_s": "3600",
                    "gmti.revisit_interval_ds": "100", "gmti.request_status": "2", "gmti.job_start_year": "2026",
                    "gmti.job_start_month": "11", "gmti.job_start_day": "19", "gmti.job_start_hour": "14",
                    "gmti.job_start_minute": "35", "gmti.job_start_second": "10", "gmti.requestor_nationality": "US"})
    vec("joback-roundtrip", "gmti", "gmti", p, p, m, "job acknowledge segment, every field")


HDR_KEYS = set(HDR_MODEL)


def segment_vectors():
    """gmti-segment: every same-format gmti vector of one segment, without the packet header."""
    out = []
    for v in VECTORS:
        if v["from"] != "gmti" or v["to"] != "gmti" or "two-segments" in v["name"]:
            continue
        m = {k: x for k, x in v.get("model", {}).items() if k not in HDR_KEYS}
        out.append(dict(v, name="gmti-segment-" + v["name"][5:], **{"from": "gmti-segment", "to": "gmti-segment"},
                        input=v["input"][64:], expect=v["expect"][64:], model=m))
    # a packet of three segments, cut at the segment sizes
    mis = segment(1, struct.pack(">12s12sB10sHBB", text("ATO-4471", 12), text("FP-22", 12), 34,
                                 text("BLK40 SW7", 10), 2026, 11, 19))
    dw = segment(2, dwell_body(DWELL_TT))
    loc = segment(13, LOC)
    pk = packet([mis, dw, loc])
    out.append({"name": "gmti-split-0-packet", "from": "gmti", "to": "gmti", "input": pk.hex(),
                "expect": packet([mis]).hex(), "model": {"@kind": "mission", "gmti.mission_plan": "ATO-4471    "},
                "source": "synthetic",
                "reference": "a packet of a mission, a dwell and a location segment: gmti reads the header and the first segment"})
    off = 32
    for n, (seg, kind, m) in enumerate(((mis, "mission", {"gmti.reference_year": "2026"}),
                                        (dw, "dwell", {"gmti.dwell_index": "12", "lat": repr(sa(LAT1, 32))}),
                                        (loc, "location", {"lat": LOC_MODEL["lat"]})), 1):
        size = struct.unpack(">I", pk[off + 1:off + 5])[0]
        part = pk[off:off + size]
        assert part == seg
        off += size
        v = {"name": "gmti-split-%d-%s" % (n, kind), "from": "gmti-segment", "to": "gmti-segment",
             "input": part.hex(), "expect": part.hex(), "model": dict(m, **{"@kind": kind}), "source": "synthetic",
             "reference": "segment %d of the packet of split-0, cut at its stated size" % n}
        if kind == "dwell":
            v["context"] = {"gmti.platform_id": "N12345    ", "gmti.mission_id": "1001", "gmti.job_id": "7"}
            v["model"] = dict(v["model"], **{"uid": "N12345    /1001/7/3/12/0", "@complete": True})
            v["reference"] += "; the packet header's platform, mission and job given as context give the dwell its uid"
        out.append(v)
    assert off == len(pk)
    return out


# Value of every dwell field by mask bit: struct code, key, value (the two lists above).
DW = {b: (c, k, v) for b, c, k, v in DWELL_TT + DWELL_REST}
TGT2 = {31: 1, 32: 1157693440, 33: -119239111, 34: -300, 35: 700, 36: 160, 37: 900, 38: 4000, 39: 12, 40: 130, 41: 55}
TGT3 = {31: 2, 32: 1157758976, 33: -119173575, 34: 10, 35: -20, 36: 140, 37: 0, 38: 4000, 39: 9, 40: 4, 41: 70}


def ref_bits(refs, base):
    return [base[r] for r in refs]


DREF = {"D%d" % (n + 1): n for n in range(1, 31)}
DREF.update({"D32.%d" % n: 30 + n for n in range(1, 19)})


def records_vectors(hdr):
    pfx = "gmti-records-" if hdr else "gmti-segment-records-"
    fmt = "gmti-records" if hdr else "gmti-segment-records"
    out = []

    def wrap(seg):
        return packet([seg]) if hdr else seg

    def add(name, seg, model, ref):
        b = wrap(seg)
        m = dict(HDR_MODEL, **model) if hdr else model
        out.append({"name": pfx + name, "from": fmt, "to": fmt, "input": b.hex(), "expect": b.hex(), "model": m,
                    "source": "synthetic", "reference": ref})

    profiles = [("dwell-situation", "D2 D3 D4 D5 D6 D7 D8 D9 D10 D11 D15 D16 D17 D21 D22 D23 D24 D25 D26 D27", "D32.1 D32.4 D32.5"),
                ("dwell-targeting", "D2 D3 D4 D5 D6 D7 D8 D9 D15 D16 D17 D21 D22 D23 D24 D25 D26 D27 D28 D29 D30",
                 "D32.1 D32.2 D32.3 D32.6 D32.7 D32.8 D32.9 D32.10 D32.11"),
                ("dwell-targeting-as-masked", "D2 D3 D4 D5 D6 D7 D8 D9 D10 D11 D15 D16 D17 D21 D22 D23 D24 D25 D26 D27 D28 D29 D30",
                 "D32.1 D32.4 D32.5 D32.6 D32.7 D32.8 D32.9 D32.10 D32.11")]
    for kind, body, tgt in profiles:
        bb = [DREF[r] for r in body.split()]
        tb = [DREF[r] for r in tgt.split()]
        targets = [{b: DW[b][2] for b in tb}, {b: TGT2.get(b, DW[b][2]) for b in tb}, {b: TGT3.get(b, DW[b][2]) for b in tb}]
        mask = 0
        for b in bb + tb:
            mask |= 1 << (64 - b)
        vals = dict((b, DW[b][2]) for b in bb)
        vals[4] = len(targets)
        seg_body = mask.to_bytes(8, "big") + b"".join(struct.pack(">" + DW[b][0], vals[b]) for b in sorted(bb))
        for t in targets:
            seg_body += b"".join(struct.pack(">" + DW[b][0], t[b]) for b in sorted(tb))
        m = {"@kind": kind, "gmti.dwell_target_count": "3", "gmti.targets.#": "3", "gmti.dwell_index": "12"}
        for i, t in enumerate(targets):
            m["gmti.targets[%d].gmti.mti_report_index" % i] = str(t[31])
            if 32 in t:
                m["gmti.targets[%d].lat" % i] = repr(sa(t[32], 32))
                m["gmti.targets[%d].lon" % i] = repr(t[33] * 360 / P32)
            if 34 in t:
                m["gmti.targets[%d].gmti.target_delta_lat" % i] = str(t[34])
            if 40 in t:
                m["gmti.targets[%d].track.simulated" % i] = "1" if t[40] >= 128 else "0"
        m.setdefault("gmti.targets[0].track.class", "vehicle") if 40 in tb else None
        add(kind, segment(2, seg_body), m, "%s: a dwell of three target reports, mask %016x" % (kind, mask))

    hb = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 22, 23, 24, 25]
    HV = {1: ("H", 3), 2: ("H", 12), 3: ("B", 0), 4: ("H", 0), 5: ("H", 0), 7: ("H", 32), 8: ("B", 115), 9: ("B", 60),
          10: ("H", 6400), 11: ("H", 3200), 12: ("I", 0x00640000), 13: ("I", 0x80320000), 14: ("I", 0x05000000),
          15: ("B", 0), 16: ("B", 1), 17: ("B", 1), 18: ("H", 0x8180), 22: ("B", 2), 23: ("B", 0x80), 24: ("B", 1), 25: ("B", 0)}
    for mag in (1, 2):
        for ph in (0, 1, 2):
            recs = [(200, 10), (180, 250), (90, 3)] if mag == 1 else [(51200, 10), (46080, 64000), (23040, 3)]
            recs = [(a, b if ph == 2 else b & 0xFF) for a, b in recs]
            mask = 0
            for b in hb + [31] + ([32] if ph else []):
                mask |= 1 << (40 - b)
            vals = {b: HV[b][1] for b in hb}
            vals[5], vals[24], vals[25] = len(recs), mag, ph
            body = mask.to_bytes(5, "big") + b"".join(struct.pack(">" + HV[b][0], vals[b]) for b in hb)
            for a, b in recs:
                body += struct.pack(">" + "BH"[mag - 1], a) + (struct.pack(">" + "BH"[ph - 1], b) if ph else b"")
            m = {"@kind": "hrr-m%dp%d" % (mag, ph), "gmti.scatterers.#": "3", "gmti.hrr_target_scatterers": "3",
                 "gmti.scatterers[1].gmti.scatterer_magnitude": str(recs[1][0])}
            if ph:
                m["gmti.scatterers[1].gmti.scatterer_phase"] = str(recs[1][1])
            add("hrr-m%dp%d" % (mag, ph), segment(3, body), m,
                "HRR field set of the targeting-with-HRR class, %d-byte magnitude, %d-byte phase, three records" % (mag, ph))

    head = struct.pack(">B2s10sII", 3, b"XN", text("N12345", 10), 1001, 7)
    recs = [struct.pack(">B2s10sIIH", n, nat, text(pl, 10), mi, jo, pp) for n, nat, pl, mi, jo, pp in
            ((1, b"DE", "GS-NORTH", 5, 70, 0x0081), (2, b"NL", "GS-WEST", 6, 71, 0x0008), (3, b"XN", "CAOC", 9, 72, 0x2000))]
    add("prochist", segment(12, head + b"".join(recs)),
        {"@kind": "prochist", "gmti.records.#": "3", "gmti.records[2].gmti.record_platform_id": "CAOC      ",
         "gmti.records[1].gmti.processing_performed": "8", "gmti.history_count": "3"},
        "processing history of three records")
    return out


def write(pack, vectors):
    d = os.path.join(os.path.dirname(OUT), "..", pack, "vectors")
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):
        if old.endswith(".json"):
            os.remove(os.path.join(d, old))
    pfx = len(pack) + 1
    for i, v in enumerate(vectors, 1):
        with open(os.path.join(d, "%02d-%s.json" % (i, v["name"][pfx:] if v["name"].startswith(pack + "-") else v["name"][5:])),
                  "w", encoding="utf-8") as fh:
            json.dump(v, fh, indent=2)
            fh.write("\n")
    print("%s: %d vectors" % (pack, len(vectors)))


def main():
    for f in (mission, dwell, hrr, jobdef, freetext, teststatus, prochist, location, from_geojson,
              dwell_to_geojson, jobreq, joback):
        f()
    write("gmti", VECTORS)
    write("gmti-segment", segment_vectors())
    write("gmti-records", records_vectors(True))
    write("gmti-segment-records", records_vectors(False))


if __name__ == "__main__":
    main()
