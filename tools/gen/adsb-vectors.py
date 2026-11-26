#!/usr/bin/env python3
"""Write the vectors of the pack `adsb-df18` and the added vectors 46-49 of the
pack `adsb` (the type code 28 subtype 2 kinds).

Both packs are maintained by hand. This script holds its own copy of their
layouts, restated from pyModeS (https://github.com/junzis/pyModeS, GPL-3.0,
commit 4bf083284c0d9878ca0c88f16b9b5f6514ca194a): decoder/adsb.py (DF17 and
DF18 share the frame and the ME layouts), decoder/bds/bds05.py, bds06.py,
bds08.py, bds09.py, bds30.py, bds61.py, bds62.py and bds65.py. It does not read
any pack.def and calls no goat-transformers engine: it packs each message from
these tables, computes the Mode S parity, decodes each published message with
the same tables and checks the values pyModeS's tests assert for it.

Vectors 01-45 of `adsb` were written by an earlier script and are kept by hand;
this script does not write them.

Inputs: none; every value is stated in this file. The same run always gives the
same bytes. With --check nothing is written and the exit status is 1 when a
committed file differs from what this script writes.

Usage: python3 -I tools/gen/adsb-vectors.py [--out DIR] [--check]
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

# ---------------------------------------------------------------- adsb layout

# (key, first ME bit numbered from 1 as in the source tables, length)
POSITION_TAIL = [("time_flag", 21, 1), ("cpr_odd", 22, 1), ("cpr_lat", 23, 17), ("cpr_lon", 40, 17)]
IDENT = [("category", 6, 3)] + [("cs_c%d" % (i + 1), 9 + 6 * i, 6) for i in range(8)]
SURFACE = [("movement_raw", 6, 7), ("track_valid", 13, 1), ("track_raw", 14, 7)] + POSITION_TAIL
AIR_BARO = [("ss", 6, 2), ("saf", 8, 1), ("alt_baro_raw", 9, 12)] + POSITION_TAIL
AIR_GNSS = [("ss", 6, 2), ("saf", 8, 1), ("gnss_height_m", 9, 12)] + POSITION_TAIL
VEL_HEAD = [("intent_change", 9, 1), ("ifr", 10, 1), ("nac_v", 11, 3)]
VEL_TAIL = [("vr_source", 36, 1), ("vr_sign", 37, 1), ("vr_raw", 38, 9), ("reserved", 47, 2),
            ("galt_diff_sign", 49, 1), ("galt_diff_raw", 50, 7)]
VEL_GROUND = VEL_HEAD + [("ew_sign", 14, 1), ("ew_raw", 15, 10), ("ns_sign", 25, 1), ("ns_raw", 26, 10)] + VEL_TAIL
VEL_AIR = VEL_HEAD + [("heading_valid", 14, 1), ("heading_raw", 15, 10), ("airspeed_true", 25, 1),
                      ("airspeed_raw", 26, 10)] + VEL_TAIL
STATUS = [("emergency_state", 9, 3), ("squawk_raw", 12, 13), ("reserved", 25, 32)]
TARGET = [("sil_supp", 8, 1), ("sel_alt_fms", 9, 1), ("sel_alt_raw", 10, 11), ("baro_setting_raw", 21, 9),
          ("sel_heading_valid", 30, 1), ("sel_heading_sign", 31, 1), ("sel_heading_raw", 32, 8),
          ("nac_p", 40, 4), ("nic_baro", 44, 1), ("sil", 45, 2), ("mode_valid", 47, 1),
          ("autopilot", 48, 1), ("vnav", 49, 1), ("alt_hold", 50, 1), ("reserved", 51, 1),
          ("approach", 52, 1), ("tcas_operational", 53, 1), ("lnav", 54, 1), ("reserved2", 55, 2)]
OPS_TAIL_A = [("operational_mode", 25, 16), ("version", 41, 3), ("nic_supp_a", 44, 1), ("nac_p", 45, 4)]
OPS_AIR = [("capability_class", 9, 16)] + OPS_TAIL_A + [
    ("gva", 49, 2), ("sil", 51, 2), ("nic_baro", 53, 1), ("hrd", 54, 1), ("sil_supp", 55, 1), ("reserved", 56, 1)]
OPS_SURF = [("surface_capability_class", 9, 12), ("length_width", 21, 4)] + OPS_TAIL_A + [
    ("reserved2", 49, 2), ("sil", 51, 2), ("track_heading", 53, 1), ("hrd", 54, 1), ("sil_supp", 55, 1),
    ("reserved", 56, 1)]

# (kind name, [(ME first bit, length, value) when lines], requires, fields, comment)
ADSB_KINDS = []
for tc in range(1, 5):
    ADSB_KINDS.append(("identification-tc%d" % tc, [(1, 5, tc)],
                       "icao category cs_c1 cs_c8", IDENT, "Aircraft identification, type code %d." % tc))
for tc in range(5, 9):
    ADSB_KINDS.append(("surface-position-tc%d" % tc, [(1, 5, tc)],
                       "icao movement_raw track_raw cpr_odd cpr_lat cpr_lon", SURFACE,
                       "Surface position, type code %d." % tc))
for tc in range(9, 19):
    ADSB_KINDS.append(("airborne-position-baro-tc%d" % tc, [(1, 5, tc)],
                       "icao alt_baro_raw cpr_odd cpr_lat cpr_lon", AIR_BARO,
                       "Airborne position with barometric altitude, type code %d." % tc))
for st in (1, 2):
    ADSB_KINDS.append(("airborne-velocity-ground-st%d" % st, [(1, 5, 19), (6, 3, st)],
                       "icao ew_raw ns_raw vr_raw", VEL_GROUND,
                       "Airborne velocity, type code 19, subtype %d: ground velocity components%s."
                       % (st, "" if st == 1 else ", supersonic scale")))
for st in (3, 4):
    ADSB_KINDS.append(("airborne-velocity-air-st%d" % st, [(1, 5, 19), (6, 3, st)],
                       "icao heading_raw airspeed_raw vr_raw", VEL_AIR,
                       "Airborne velocity, type code 19, subtype %d: airspeed and magnetic heading%s."
                       % (st, "" if st == 3 else ", supersonic scale")))
for tc in range(20, 23):
    ADSB_KINDS.append(("airborne-position-gnss-tc%d" % tc, [(1, 5, tc)],
                       "icao gnss_height_m cpr_odd cpr_lat cpr_lon", AIR_GNSS,
                       "Airborne position with GNSS height, type code %d." % tc))
ADSB_KINDS.append(("aircraft-status-emergency", [(1, 5, 28), (6, 3, 1)],
                   "icao emergency_state squawk_raw", STATUS,
                   "Aircraft status, type code 28, subtype 1: emergency / priority status and Mode A code."))
ADSB_KINDS.append(("target-state", [(1, 5, 29), (6, 2, 1)],
                   "icao sel_alt_raw baro_setting_raw sel_heading_raw", TARGET,
                   "Target state and status, type code 29, subtype 1 (ADS-B version 2)."))
ADSB_KINDS.append(("operational-status-airborne", [(1, 5, 31), (6, 3, 0)],
                   "icao capability_class operational_mode version", OPS_AIR,
                   "Aircraft operational status, type code 31, subtype 0 (airborne), version 2 field names."))
ADSB_KINDS.append(("operational-status-surface", [(1, 5, 31), (6, 3, 1)],
                   "icao surface_capability_class length_width operational_mode version", OPS_SURF,
                   "Aircraft operational status, type code 31, subtype 1 (surface), version 2 field names."))

# Type code 28 subtype 2, ACAS resolution advisory broadcast. Layout from pyModeS
# decoder/bds/bds61.py (subtype 2 carries the BDS 3,0 payload bits 8-55) and
# decoder/bds/bds30.py (the bit of each flag, the threat type indicator, and the
# threat identity by indicator); pyModeS bit b of the payload is ME bit b + 1 here.
ACAS_HEAD = [("ra_active", 9, 1), ("ra_corrective", 10, 1), ("ra_downward", 11, 1),
             ("ra_increased_rate", 12, 1), ("ra_sense_reversal", 13, 1), ("ra_altitude_crossing", 14, 1),
             ("ra_positive", 15, 1), ("ara_acas3", 16, 7), ("rac_no_below", 23, 1), ("rac_no_above", 24, 1),
             ("rac_no_left", 25, 1), ("rac_no_right", 26, 1), ("ra_terminated", 27, 1),
             ("multiple_threat", 28, 1), ("tti", 29, 2)]
ACAS_KINDS = [
    ("acas-ra-no-threat-identity", [(1, 5, 28), (6, 3, 2), (29, 2, 0)], "icao ra_active tid_raw",
     ACAS_HEAD + [("tid_raw", 31, 26)],
     "Aircraft status, type code 28, subtype 2: ACAS resolution advisory, threat type indicator 0 "
     "(no threat identity; the 26 identity bits are carried as they are)."),
    ("acas-ra-threat-address", [(1, 5, 28), (6, 3, 2), (29, 2, 1)], "icao ra_active threat_icao",
     ACAS_HEAD + [("threat_icao", 31, 24), ("reserved", 55, 2)],
     "Aircraft status, type code 28, subtype 2: ACAS resolution advisory, threat type indicator 1 "
     "(the threat's 24-bit address)."),
    ("acas-ra-threat-position", [(1, 5, 28), (6, 3, 2), (29, 2, 2)],
     "icao ra_active threat_alt_code threat_range_raw threat_bearing_raw",
     ACAS_HEAD + [("threat_alt_code", 31, 13), ("threat_range_raw", 44, 7), ("threat_bearing_raw", 51, 6)],
     "Aircraft status, type code 28, subtype 2: ACAS resolution advisory, threat type indicator 2 "
     "(the threat's altitude code, range and bearing)."),
]
ADSB_KINDS_V1 = len(ADSB_KINDS)        # the kinds of the first edition; their vectors keep their numbers
ADSB_KINDS += ACAS_KINDS

# Downlink format 18. pyModeS decoder/adsb.py dispatches DF17 and DF18 alike: the same
# 112-bit frame and the same ME layouts per type code. The kinds are those of DF17, but
# the surface operational status maps the 16-bit capability class as pyModeS reads it
# (decoder/bds/bds65.py, bits 8-23 raw), not split in two.
OPS_SURF_18 = [("capability_class", 9, 16)] + OPS_SURF[2:]
ADSB18_KINDS = [(n, w, (r.replace("surface_capability_class length_width", "capability_class")
                        if n == "operational-status-surface" else r),
                 (OPS_SURF_18 if n == "operational-status-surface" else f), c)
                for n, w, r, f, c in ADSB_KINDS]


# ---------------------------------------------------------------- fact checks
# Decoders for the published values only. They are not part of any pack: they
# exist so that a wrong bit offset in the layout table fails here.

def crc24(first88):
    """Mode S parity: remainder of the first 88 bits x 2^24 by 0x1FFF409."""
    v = first88 << 24
    for i in range(111, 23, -1):
        if v >> i & 1:
            v ^= 0x1FFF409 << (i - 24)
    return v & 0xFFFFFF


def callsign(e):
    table = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"
    return "".join(table[e["adsb.cs_c%d" % i]] for i in range(1, 9)).rstrip()



PUB_PMS = "pyModeS tests/%s at commit 4bf0832, https://github.com/junzis/pyModeS"

# published messages whose last 24 bits are not the remainder of the first 88
PARITY_NOT_VALID = {
    # pyModeS made it from a DF17 message by changing the downlink format only
    "df18-identification-ezy85mh"}


def acas_tti3(df_first_byte):
    """Type code 28 subtype 2 with threat type indicator 3, which pyModeS bds30.py names reserved."""
    me = (28 << 51) | (2 << 48) | (1 << 47) | (3 << 26)
    first = (df_first_byte << 80) | (0xABC0FF << 56) | me
    return "%022x%06x" % (first, crc24(first))




def surface_cpr_with_ref(odd, lat_raw, lon_raw, lat_ref, lon_ref):
    """Locally unambiguous surface position from one CPR frame and a reference within
    45 NM, as pyModeS position/_cpr.py states it (90-degree zones); NL by the closed form."""
    def nl(lat):
        if abs(lat) >= 87.0:
            return 2 if abs(lat) == 87.0 else 1
        a = 1 - math.cos(math.pi / 30) 
        b = math.cos(math.pi / 180 * abs(lat)) ** 2
        return int(math.floor(2 * math.pi / math.acos(1 - a / b)))
    d_lat = 90.0 / (59 if odd else 60)
    yl, xl = lat_raw / 131072.0, lon_raw / 131072.0
    lat = d_lat * (math.floor(0.5 + lat_ref / d_lat - yl) + yl)
    ni = nl(lat) - odd
    d_lon = 90.0 / ni if ni > 0 else 90.0
    lon = d_lon * (math.floor(0.5 + lon_ref / d_lon - xl) + xl)
    return lat, lon


PUB_PMS18 = PUB_PMS
PUBLISHED_18 = [
    ("df18-identification-ezy85mh", "90406B902015A678D4D220AA4BDA",
     PUB_PMS18 % "test_adsb.py" + " (test_df18_routes_to_same_dispatch: the DF17 message 8D406B90... "
     "with the downlink format changed to 18, decoded as type code 4)",
     "identification-tc4",
     lambda e: (e["adsb.df"] == 18, e["adsb.icao"] == 0x406B90, callsign(e) == "EZY85MH",
                e["adsb.category"] == 0),
     ["adsb.cf", "adsb.icao", "adsb.category", "adsb.cs_c1", "adsb.cs_c7", "adsb.cs_c8"]),
    ("df18-surface-position-even", "903a23ff426a38565950432ebf95",
     PUB_PMS18 % "test_cpr.py" + " (TestSurfacePositionPair, even frame of ICAO 3A23FF at LFBO)",
     "surface-position-tc8",
     lambda e: (e["adsb.df"] == 18, e["adsb.icao"] == 0x3A23FF, e["adsb.cpr_odd"] == 0),
     ["adsb.cf", "adsb.icao", "adsb.movement_raw", "adsb.track_valid", "adsb.track_raw", "adsb.cpr_odd",
      "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("df18-surface-position-odd", "903a23ff426a4e65f7487a775d17",
     PUB_PMS18 % "test_cpr.py" + " (TestSurfacePositionWithRef: odd frame resolved against 43.63, 1.37 to "
     "43.62646, 1.37476)",
     "surface-position-tc8",
     lambda e: (e["adsb.df"] == 18, e["adsb.icao"] == 0x3A23FF, e["adsb.cpr_odd"] == 1,
                all(abs(a - b) < 0.001 for a, b in zip(
                    surface_cpr_with_ref(1, e["adsb.cpr_lat"], e["adsb.cpr_lon"], 43.63, 1.37),
                    (43.62646, 1.37476)))),
     ["adsb.cf", "adsb.icao", "adsb.cpr_odd", "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("df18-surface-stopped", "903a33ff40100858d34ff3cce976",
     PUB_PMS18 % "test_bds06.py" + " (movement code 1: ground speed 0)",
     "surface-position-tc8",
     lambda e: (e["adsb.df"] == 18, e["adsb.movement_raw"] == 1),
     ["adsb.cf", "adsb.icao", "adsb.movement_raw"]),
]




# ---------------------------------------------------------------- messages from the tables

# The raw values pyModeS reads as "not available" (decoder/bds/bds06.py movement 0
# and above 124; bds09.py velocity, vertical rate and airspeed magnitude 0, the
# GNSS-baro difference 0 and 127; bds62.py selected altitude and barometric
# setting 0; bds30.py threat range and bearing 0). The packs name them with
# `absent` (engine-spec 0.9): decode gives no key, encode of a missing key writes
# the first of them.
SENTINELS = {"adsb.ew_raw": (0,), "adsb.ns_raw": (0,), "adsb.vr_raw": (0,), "adsb.airspeed_raw": (0,),
             "adsb.galt_diff_raw": (0, 127), "adsb.movement_raw": (0, 125, 126, 127),
             "adsb.sel_alt_raw": (0,), "adsb.baro_setting_raw": (0,),
             "adsb.threat_range_raw": (0,), "adsb.threat_bearing_raw": (0,)}


# `chars:icao6` (engine-spec 0.15) on the eight 6-bit characters of an identification message:
# code 1-26 A-Z, 32 space, 48-57 0-9 (pyModeS _callsign.py builds the same alphabet); any other
# code is transform-decode. Trailing spaces are removed on decode and written back on encode.
ICAO6 = {c: chr(0x40 | c) for c in range(1, 27)}
ICAO6.update({32: " "})
ICAO6.update({c: chr(c) for c in range(48, 58)})
ICAO6_CODE = {ch: c for c, ch in ICAO6.items()}
CS_KEYS = ["adsb.cs_c%d" % i for i in range(1, 9)]


class Icao6Error(Exception):
    pass


def icao6_text(codes):
    if any(c not in ICAO6 for c in codes):
        raise Icao6Error("a code outside the ICAO character set")
    return "".join(ICAO6[c] for c in codes).rstrip(" ")


def kind_lines(df, row):
    """(common fields, kind fields, whens) of a kind row, as (key, offset, length) and
    (offset, length, value): ME bit n (numbered from 1) is message offset 31 + n."""
    name, whens, _requires, fields, _comment = row
    common = [("adsb.df", 0, 5), ("adsb.ca" if df == 17 else "adsb.cf", 5, 3), ("adsb.icao", 8, 24),
              ("adsb.parity", 88, 24)]
    kind = [("adsb.tc", 32, 5)] + [("adsb." + k, 31 + first, length) for k, first, length in fields]
    return common, kind, [(31 + first, length, value) for first, length, value in whens]


def encode(df, row, values):
    common, kind, whens = kind_lines(df, row)
    if row[0].startswith("identification") and "callsign" in values:
        # the callsign line comes before the raw characters and wins on encode (ruling 5 of 0.5)
        values = dict(values, **{k: ICAO6_CODE[ch] for k, ch in zip(CS_KEYS, values["callsign"].ljust(8))})
    acc = 0
    for key, off, n in common + kind:
        v = values.get(key, SENTINELS.get(key, (0,))[0])
        assert 0 <= v < (1 << n), (key, v)
        acc = (acc & ~(((1 << n) - 1) << (112 - off - n))) | (v << (112 - off - n))
    for off, n, v in [(0, 5, df)] + whens:          # the when values are written over the fields
        acc = (acc & ~(((1 << n) - 1) << (112 - off - n))) | (v << (112 - off - n))
    return "%028x" % acc


def decode(df, rows, hexmsg):
    """The first kind whose when lines hold, and its values; None when none holds."""
    m = int(hexmsg, 16)
    get = lambda off, n: (m >> (112 - off - n)) & ((1 << n) - 1)
    if get(0, 5) != df:
        return None, None
    for row in rows:
        common, kind, whens = kind_lines(df, row)
        if all(get(off, n) == v for off, n, v in whens):
            got = {key: get(off, n) for key, off, n in common + kind}
            got = {k: v for k, v in got.items() if v not in SENTINELS.get(k, ())}
            if row[0].startswith("identification"):
                got["callsign"] = icao6_text([got[k] for k in CS_KEYS])
            return row[0], got
    return None, None


def pinned(kind, entity, keys):
    m = {"@kind": kind}
    for k in keys:
        m[k] = str(entity[k])
    return m


SCRIPT = "tools/gen/adsb-vectors.py"


def roundtrip_vectors(pack_name, df, frame, kind_rows, first_n):
    """One constructed, self-consistent message per kind, round-tripped. The values
    are those the earlier generator chose: (37 x (i + 1) x (n + 3) + 11) mod 2^len for
    the i-th line of the kind (adsb.tc first), 1 where that is 0, reserved fields 0."""
    out = []
    for n, row in enumerate(kind_rows, first_n):
        name, _w, requires, _f, _c = row
        _common, kind, whens = kind_lines(df, row)
        on_when = {(off, length): v for off, length, v in whens}
        values = dict(frame, **{"adsb.icao": 0xABC000 + n + 1, "adsb.parity": 0})
        for i, (key, off, length) in enumerate(kind):
            if (off, length) in on_when:              # adsb.tc, and adsb.tti in the ACAS kinds
                values[key] = on_when[(off, length)]
            elif key in CS_KEYS:                      # a character of the ICAO set, never a space
                letters = sorted(c for c in ICAO6 if c != 32)
                values[key] = letters[(37 * (i + 1) * (n + 3) + 11) % len(letters)]
            elif key in ("adsb.reserved", "adsb.reserved2"):
                values[key] = 0
            else:
                values[key] = (37 * (i + 1) * (n + 3) + 11) % (1 << length) or 1
        values["adsb.parity"] = crc24(int(encode(df, row, values), 16) >> 24)
        hexmsg = encode(df, row, values)
        if name.startswith("identification"):
            values["callsign"] = icao6_text([values[k] for k in CS_KEYS])
        got, entity = decode(df, [r for r in kind_rows], hexmsg)
        assert not any(values.get(k) in v for k, v in SENTINELS.items()), name
        assert got == name and entity == values, name
        pins = ["adsb.df", "adsb.tc"] + ["adsb." + k for k in requires.split() if k != "callsign"] + ["adsb.parity"]
        if "callsign" in entity:
            pins.append("callsign")
        out.append({"name": name + "-roundtrip", "from": pack_name, "to": pack_name, "input": hexmsg,
                    "expect": hexmsg, "model": pinned(name, entity, pins), "source": "constructed",
                    "reference": "field values chosen by %s; parity computed there with "
                                 "the Mode S generator 0x1FFF409 so the frame is self-consistent" % SCRIPT})
    return out


def published_vectors(pack_name, df, rows, table):
    out = []
    for name, msg, reference, kind_name, facts, pins in table:
        hexmsg = msg.lower()
        kind, entity = decode(df, rows, hexmsg)
        assert kind == kind_name, (name, kind)
        results = facts(entity)
        assert all(results), (name, results)
        parity_ok = crc24(int(hexmsg, 16) >> 24) == entity["adsb.parity"]
        assert parity_ok == (name not in PARITY_NOT_VALID), name + ": parity"
        if not parity_ok:
            reference += ("; one bit differs from the message above and the source leaves the parity "
                          "unchanged, so the parity field is not the frame's remainder")
        row = next(r for r in rows if r[0] == kind)
        assert encode(df, row, entity) == hexmsg, name
        out.append({"name": name, "from": pack_name, "to": pack_name, "input": hexmsg, "expect": hexmsg,
                    "model": pinned(kind, entity, ["adsb.df", "adsb.tc"] + pins
                                    + (["callsign"] if "callsign" in entity else [])), "source": "specification",
                    "reference": "published message " + msg + ": " + reference})
    return out


def acas_tti3_vector(pack_name, df_first_byte):
    return {"name": "acas-ra-threat-type-3-no-kind", "from": pack_name, "to": pack_name,
            "input": acas_tti3(df_first_byte), "expect_error": "no-kind", "source": "constructed",
            "reference": "type code 28 subtype 2 with threat type indicator 3, reserved in pyModeS "
                         "decoder/bds/bds30.py; parity computed by " + SCRIPT}


def sentinel_vector(pack_name, df, frame, row, values, model_keys, ref):
    """A message whose fields hold sentinels: decode gives no key for them, and the
    re-encoded message holds the first sentinel of each (engine-spec 0.9 ruling 7)."""
    values = dict(frame, **values)
    values["adsb.parity"] = 0
    values["adsb.parity"] = crc24(int(encode(df, row, values), 16) >> 24)
    hexmsg = encode(df, row, values)
    kind, entity = decode(df, ADSB_KINDS if df == 17 else ADSB18_KINDS, hexmsg)
    assert kind == row[0]
    again = dict(entity)
    expect = encode(df, row, again)
    missing = sorted(k for k in values if k not in entity)
    assert missing and all(k in SENTINELS for k in missing), missing
    return {"name": row[0] + "-sentinels-decode-absent", "from": pack_name, "to": pack_name, "input": hexmsg,
            "expect": expect, "model": pinned(kind, entity, ["adsb.df", "adsb.tc"] + model_keys),
            "source": "constructed",
            "reference": ref + "; keys left absent: %s; parity computed by %s for the input, carried as it is"
                         % (", ".join(missing), SCRIPT)}


CS_REF = ("pyModeS _callsign.py (the 6-bit alphabet: 1-26 A-Z, 32 space, 48-57 0-9) and engine-spec 0.15 "
          "`chars:icao6`; %s")


def callsign_vectors(pack_name, df, rows, published_hex, published_ref, invalid_hex, back_from, back_input,
                     back_context, back_ref):
    """The callsign bound by `chars:icao6`: a published identification to GeoJSON and CoT, a message
    whose characters fall outside the set, and an identification written from another format."""
    out = []
    kind, entity = decode(df, rows, published_hex)
    cs = entity["callsign"]
    out.append({"name": "identification-callsign-to-geojson", "from": pack_name, "to": "geojson",
                "input": published_hex,
                "expect": '{"type":"Feature","geometry":null,"properties":{"callsign":"%s"}}' % cs,
                "model": {"@kind": kind, "callsign": cs}, "source": "specification",
                "reference": CS_REF % ("published message %s (%s): the eight characters as the callsign; no "
                                       "position, so geometry null" % (published_hex.upper(), published_ref))})
    out.append({"name": "identification-callsign-to-cot-xml", "from": pack_name, "to": "cot-xml",
                "input": published_hex,
                "expect": '<event version="2.0" type="a-u-X"><point hae="9999999" ce="9999999" le="9999999"/>'
                          '<detail><contact callsign="%s"/></detail></event>' % cs,
                "source": "specification",
                "reference": CS_REF % ("the same message; cot-xml canonical form by hand from its pack, with its "
                                       "point defaults; the 24-bit address is an integer and is not uid")})
    try:
        decode(df, rows, invalid_hex)
        raise AssertionError("the invalid characters decoded")
    except Icao6Error:
        pass
    out.append({"name": "identification-character-outside-the-set", "from": pack_name, "to": pack_name,
                "input": invalid_hex, "expect_error": "transform-decode", "source": "constructed",
                "reference": CS_REF % "the round trip of version 0.2 of the pack, whose characters were "
                                      "chosen before the callsign was bound: codes such as 0, 27-31, 33-47 and "
                                      "58-63 are outside the set"})
    row = next(r for r in rows if r[0] == "identification-tc4")
    values = {"adsb.df": df, "adsb.icao": int(back_context["adsb.icao"]), "adsb.tc": 4, "callsign": cs}
    expect = encode(df, row, values)
    out.append({"name": "callsign-to-identification-%s" % back_from, "from": back_from, "to": pack_name,
                "input": back_input, "context": back_context, "expect": expect, "source": "constructed",
                "reference": CS_REF % (back_ref + "; the kind identification-tc4 requires adsb.icao and callsign, "
                                       "so the address comes from the context; the category is 0 and the parity "
                                       "field is written as 0: the pack does not compute the CRC")})
    return out


def adsb_added():
    """Vectors 46-50 of adsb: they follow the 45 of the first edition."""
    out = roundtrip_vectors("adsb", 17, {"adsb.df": 17, "adsb.ca": 5}, ADSB_KINDS[ADSB_KINDS_V1:], ADSB_KINDS_V1)
    out.append(acas_tti3_vector("adsb", 0x8D))
    assert decode(17, ADSB_KINDS, out[-1]["input"])[0] is None
    row = next(r for r in ADSB_KINDS if r[0] == "airborne-velocity-ground-st1")
    out.append(sentinel_vector(
        "adsb", 17, {"adsb.df": 17, "adsb.ca": 5, "adsb.icao": 0xABCDEF}, row,
        {"adsb.tc": 19, "adsb.intent_change": 0, "adsb.ifr": 1, "adsb.nac_v": 2, "adsb.ew_sign": 0,
         "adsb.ew_raw": 0, "adsb.ns_sign": 1, "adsb.ns_raw": 101, "adsb.vr_source": 1, "adsb.vr_sign": 0,
         "adsb.vr_raw": 0, "adsb.reserved": 0, "adsb.galt_diff_sign": 0, "adsb.galt_diff_raw": 127},
        ["adsb.icao", "adsb.ns_raw", "adsb.ns_sign", "adsb.nac_v"],
        "pyModeS decoder/bds/bds09.py: an east-west and a vertical-rate magnitude of 0 and a GNSS-baro "
        "difference of 127 are not available; the 127 is written back as 0, the first sentinel"))
    out += callsign_vectors(
        "adsb", 17, ADSB_KINDS, "8d4840d6202cc371c32ce0576098", "1090 Megahertz Riddle, chapter 2, as vector 30",
        V02_IDENT_TC1, "geojson",
        '{"type":"Feature","geometry":null,"properties":{"callsign":"KLM1023"}}', {"adsb.icao": "4735190"},
        "a GeoJSON Feature with the callsign KLM1023 and address 4840D6 (4735190) in the context")
    return out


# The input of the identification-tc1 round trip of version 0.2 (the same in adsb and, with DF 18
# and CF 0, in adsb-df18): its characters were chosen as any 6-bit numbers.
V02_IDENT_TC1 = "8dabc00109607da5503ca1a19695"
V02_IDENT_TC1_DF18 = "90abc00109607da5503ca1dc9a60"


def adsb_first_edition_identifications():
    """Vectors 01-04 of adsb, the identification round trips: since the callsign is bound their
    characters are letters and digits, so this script writes them."""
    return roundtrip_vectors("adsb", 17, {"adsb.df": 17, "adsb.ca": 5}, ADSB_KINDS[:4], 0)


def adsb18():
    out = roundtrip_vectors("adsb-df18", 18, {"adsb.df": 18, "adsb.cf": 0}, ADSB18_KINDS, 0)
    out += published_vectors("adsb-df18", 18, ADSB18_KINDS, PUBLISHED_18)
    out.append({"name": "df17-no-kind", "from": "adsb-df18", "to": "adsb-df18",
                "input": "8d406b902015a678d4d220aa4bda", "expect_error": "no-kind",
                "source": "specification",
                "reference": "published DF17 message 8D406B902015A678D4D220AA4BDA: " + PUB_PMS % "test_bds08.py"
                             + "; downlink format 17 is the pack adsb"})
    tc0 = int("90406b902015a678d4d220", 16) & ~(0x1F << 51)
    out.append({"name": "type-code-0-no-kind", "from": "adsb-df18", "to": "adsb-df18",
                "input": "%022x%06x" % (tc0, crc24(tc0)), "expect_error": "no-kind",
                "source": "constructed",
                "reference": "90406B902015A678D4D220AA4BDA with the type code set to 0 and parity recomputed; "
                             "pyModeS decoder/adsb.py has no layout for type code 0"})
    out.append(acas_tti3_vector("adsb-df18", 0x90))
    late = []
    late += callsign_vectors(
        "adsb-df18", 18, ADSB18_KINDS, "90406b902015a678d4d220aa4bda",
        "pyModeS tests/test_adsb.py, as vector 33", V02_IDENT_TC1_DF18, "cot-xml",
        '<event version="2.0" type="a-f-A" how="m-g"><point lat="0" lon="0" hae="0" ce="0" le="0"/>'
        '<detail><contact callsign="EZY85MH"/></detail></event>', {"adsb.icao": "4221840"},
        "a CoT event with the callsign EZY85MH and address 406B90 (4221840) in the context")
    row = next(r for r in ADSB18_KINDS if r[0] == "surface-position-tc7")
    out.append(sentinel_vector(
        "adsb-df18", 18, {"adsb.df": 18, "adsb.cf": 0, "adsb.icao": 0x3A23FF}, row,
        {"adsb.tc": 7, "adsb.movement_raw": 126, "adsb.track_valid": 1, "adsb.track_raw": 64,
         "adsb.time_flag": 0, "adsb.cpr_odd": 1, "adsb.cpr_lat": 12345, "adsb.cpr_lon": 54321},
        ["adsb.icao", "adsb.track_raw", "adsb.cpr_lat", "adsb.cpr_lon"],
        "pyModeS decoder/bds/bds06.py: a movement code above 124 is not available; 126 decodes to no "
        "key and is written back as 0, the first sentinel"))
    for v in out:
        if "expect_error" in v:
            assert decode(18, ADSB18_KINDS, v["input"])[0] is None, v["name"]
    return out + late


# DF 18 airborne velocity of subtypes 2 and 4 converted to the pack adsb: the
# subtype (ME bits 5 to 7) multiplies the speed by 4, so it must come through.
KEEPS_VELOCITY_REF = ('pyModeS decoder/bds/bds09.py: the subtype is ME bits 5 to 7 and subtypes 2 and 4 multiply the speed by 4, so it must come through; only the 5-bit downlink format differs (18 to 17)')


def adsb18_to_adsb():
    """The vectors from adsb-df18 to adsb: two that keep the velocity subtype, and a surface
    status that adsb has no kind for."""
    out = []
    for name, hexmsg in (("to-adsb-keeps-velocity-st2", '90abc0149adf1faf7c148f2cfccc'), ("to-adsb-keeps-velocity-st4", '90abc0169cdcdbf978cc9bd68485')):
        df17 = "88" + hexmsg[2:]   # only the 5-bit downlink format differs (18 to 17), CA 0 for CF 0
        out.append({"name": name, "from": "adsb-df18", "to": "adsb", "input": hexmsg, "expect": df17,
                    "source": "constructed", "reference": KEEPS_VELOCITY_REF})
    out.append({"name": "to-adsb-surface-status-is-no-kind", "from": "adsb-df18", "to": "adsb",
                "input": "90abc01df909010d7cfd3e2d6a59", "expect_error": "no-kind", "source": "constructed",
                "reference": "pyModeS bds65: subtype 1 is the surface status; adsb-df18 maps its capability "
                             "class as adsb.capability_class, which adsb's surface kind does not hold (it "
                             "requires the surface capability class and the length/width code), and the "
                             "subtype now requires its value, so the message is no-kind, not an airborne status"})
    return out


def text(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    written = {}
    vdir = "packs/adsb/vectors"
    numbered = list(enumerate(adsb_first_edition_identifications(), 1)) + list(enumerate(adsb_added(), 46))
    for i, v in numbered:
        if v["from"] == "adsb":
            rel = "%s/%02d-%s.json" % (vdir, i, v["name"])
        else:       # a vector lives in the pack that owns its input
            rel = "packs/%s/vectors/to-adsb-%s.json" % (v["from"], v["name"])
        out.write(rel, text(v))
        written["adsb"] = written.get("adsb", 0) + 1
    vdir = "packs/adsb-df18/vectors"
    names = set()
    for v in adsb18_to_adsb():
        rel = "%s/%s.json" % (vdir, v["name"])
        names.add(rel.split("/")[-1])
        out.write(rel, text(v))
    for i, v in enumerate(adsb18(), 1):
        if v["from"] != "adsb-df18":
            out.write("packs/%s/vectors/to-adsb-df18-%s.json" % (v["from"], v["name"]), text(v))
            continue
        rel = "%s/%02d-%s.json" % (vdir, i, v["name"])
        names.add(rel.split("/")[-1])
        out.write(rel, text(v))
    for old in out.listdir(vdir):
        if old not in names:
            out.remove(vdir + "/" + old)
    written["adsb-df18"] = len(names)
    return written


def main(argv=None):
    return genio.vector_main("adsb-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
