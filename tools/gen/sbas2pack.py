#!/usr/bin/env python3
"""Write the sbas-l1 pack, its module and vectors from this program's own
statement of the SBAS L1 message layouts that RTKLIB decodes
(https://github.com/tomojitakasu/RTKLIB, src/sbas.c; BSD 2-Clause).

Python 3 standard library only; imports nothing from engines/. Each field
below is (key, bit offset in the message, bits, signed, factor): the offsets
are those sbas.c reads (its getbitu/getbits calls), and the vector writer
packs the fields one after another by their widths and asserts that every
field lands at the stated offset, so a width and an offset that disagree
fail here. RTCA DO-229, the standard, is a paid document and is not used.

A message is the 250-bit SBAS L1 message (an 8-bit preamble, a 6-bit message
type, 212 bits of data and the 24-bit CRC), followed by 6 zero bits to make
32 bytes; most significant bit first.

Usage:
  python3 -I tools/gen/sbas2pack.py <checkout>           write
  python3 -I tools/gen/sbas2pack.py <checkout> --check   exit 1 when a file differs
"""
import json
import os
import sys
from fractions import Fraction as Fr

FMT = "sbas-l1"
MODULE = "sbas"
SRC = ('RTKLIB, https://github.com/tomojitakasu/RTKLIB commit 71db0ffa0d9735697c6adfd06fdf766d0e5ce807, '
       'src/sbas.c (sha256 73eeed8538cc78112d0addc2ca9c86a381ce497a9657cf220ff2362f9cfa64e2); '
       'BSD 2-Clause License, Copyright (c) 2007-2013 T. Takasu (readme.txt)')
P8, P11, P31, P40 = Fr(1, 8), Fr(1, 2 ** 11), Fr(1, 2 ** 31), Fr(1, 2 ** 40)

KEYS = {   # key: (type, unit, meaning)
    "preamble": ("int", "-", "the 8-bit preamble: 0x53, 0x9A and 0xC6 in turn, one per message"),
    "crc": ("int", "-", "the 24-bit CRC-24Q of the 226 bits before it; carried, not computed"),
    "iodp": ("int", "-", "issue of data of the PRN mask the message refers to"),
    "iodf": ("int", "-", "issue of data of the fast corrections"),
    "mask_bit": ("int", "-", "item of prn_mask: 1 when the slot (item index + 1) is monitored: 1-37 GPS, 38-61 GLONASS, 120-138 SBAS, 183-202 QZSS as RTKLIB reads them"),
    "prc_m": ("float", "m", "fast correction (pseudorange correction) of a monitored satellite, 0.125 m steps"),
    "udrei": ("int", "-", "user differential range error indicator, a code 0 to 15 (14 not monitored, 15 do not use)"),
    "iodf_2": ("int", "-", "type 6: issue of data of the fast corrections of type 2"),
    "iodf_3": ("int", "-", "type 6: issue of data of the fast corrections of type 3"),
    "iodf_4": ("int", "-", "type 6: issue of data of the fast corrections of type 4"),
    "iodf_5": ("int", "-", "type 6: issue of data of the fast corrections of type 5"),
    "latency_s": ("int", "s", "type 7: system latency t_lat, seconds"),
    "spare": ("int", "-", "spare bits, as sent"),
    "ai": ("int", "-", "item of degradation_factors: fast correction degradation factor indicator, a code 0 to 15"),
    "geo_reserved": ("int", "-", "type 9: the 8 bits before t0, which RTKLIB does not read"),
    "geo_t0_s": ("int", "s", "type 9: time of applicability, seconds of the GPS day (16 s steps)"),
    "geo_ura": ("int", "-", "type 9: user range accuracy index (15: do not use)"),
    "geo_x_m": ("float", "m", "type 9: GEO position X, earth-centred earth-fixed, 0.08 m steps"),
    "geo_y_m": ("float", "m", "type 9: GEO position Y, 0.08 m steps"),
    "geo_z_m": ("float", "m", "type 9: GEO position Z, 0.4 m steps"),
    "geo_vx_ms": ("float", "m/s", "type 9: GEO velocity X, 0.000625 m/s steps"),
    "geo_vy_ms": ("float", "m/s", "type 9: GEO velocity Y, 0.000625 m/s steps"),
    "geo_vz_ms": ("float", "m/s", "type 9: GEO velocity Z, 0.004 m/s steps"),
    "geo_ax_mss": ("float", "m/s^2", "type 9: GEO acceleration X, 0.0000125 m/s^2 steps"),
    "geo_ay_mss": ("float", "m/s^2", "type 9: GEO acceleration Y, 0.0000125 m/s^2 steps"),
    "geo_az_mss": ("float", "m/s^2", "type 9: GEO acceleration Z, 0.0000625 m/s^2 steps"),
    "geo_af0_s": ("float", "s", "type 9: GEO clock offset, 2^-31 s steps"),
    "geo_af1_ss": ("float", "s/s", "type 9: GEO clock drift, 2^-40 s/s steps"),
    "band_count": ("int", "-", "type 18: number of IGP bands being broadcast"),
    "band": ("int", "-", "types 18 and 26: IGP band number, 0 to 10"),
    "iodi": ("int", "-", "types 18 and 26: issue of data of the ionospheric grid point mask"),
    "igp_bit": ("int", "-", "item of igp_mask: 1 when the ionospheric grid point (item index + 1) of the band is monitored"),
    "block": ("int", "-", "type 24: block of 13 satellites the fast corrections are for; type 26: block of 15 grid points"),
    "vel_code": ("int", "-", "long-term correction half: velocity code, 0 position only for two satellites, 1 position and velocity for one"),
    "sat1_slot": ("int", "-", "velocity code 0, first satellite: PRN mask number (1-51), 0 none"),
    "sat1_iode": ("int", "-", "velocity code 0, first satellite: issue of data of the ephemeris"),
    "sat1_dx_m": ("float", "m", "velocity code 0, first satellite: delta X, 0.125 m steps"),
    "sat1_dy_m": ("float", "m", "velocity code 0, first satellite: delta Y, 0.125 m steps"),
    "sat1_dz_m": ("float", "m", "velocity code 0, first satellite: delta Z, 0.125 m steps"),
    "sat1_daf0_s": ("float", "s", "velocity code 0, first satellite: clock offset correction, 2^-31 s steps"),
    "sat2_slot": ("int", "-", "velocity code 0, second satellite: PRN mask number"),
    "sat2_iode": ("int", "-", "velocity code 0, second satellite: issue of data of the ephemeris"),
    "sat2_dx_m": ("float", "m", "velocity code 0, second satellite: delta X"),
    "sat2_dy_m": ("float", "m", "velocity code 0, second satellite: delta Y"),
    "sat2_dz_m": ("float", "m", "velocity code 0, second satellite: delta Z"),
    "sat2_daf0_s": ("float", "s", "velocity code 0, second satellite: clock offset correction"),
    "lt_slot": ("int", "-", "velocity code 1: PRN mask number of the satellite"),
    "lt_iode": ("int", "-", "velocity code 1: issue of data of the ephemeris"),
    "lt_dx_m": ("float", "m", "velocity code 1: delta X, 0.125 m steps"),
    "lt_dy_m": ("float", "m", "velocity code 1: delta Y"),
    "lt_dz_m": ("float", "m", "velocity code 1: delta Z"),
    "lt_daf0_s": ("float", "s", "velocity code 1: clock offset correction, 2^-31 s steps"),
    "lt_ddx_ms": ("float", "m/s", "velocity code 1: delta X rate, 2^-11 m/s steps"),
    "lt_ddy_ms": ("float", "m/s", "velocity code 1: delta Y rate"),
    "lt_ddz_ms": ("float", "m/s", "velocity code 1: delta Z rate"),
    "lt_daf1_ss": ("float", "s/s", "velocity code 1: clock drift correction, 2^-39 s/s steps"),
    "lt_t0_s": ("int", "s", "velocity code 1: time of applicability, seconds of the GPS day (16 s steps)"),
    "giv_delay_m": ("float", "m", "item of grid_points: vertical delay estimate at the grid point, 0.125 m steps; 511 (not monitored) is absent"),
    "givei": ("int", "-", "item of grid_points: grid ionospheric vertical error indicator, a code 0 to 15"),
}
LISTS = {"prn_mask": "type 1: the 210 slots of the PRN mask, one item each",
         "fast_corrections": "fast corrections of the satellites of the message, in PRN mask order",
         "udreis": "UDREIs of the satellites of the message, in PRN mask order",
         "degradation_factors": "type 7: the 51 degradation factor indicators, in PRN mask order",
         "igp_mask": "type 18: the 201 grid points of the band, one item each",
         "long_term": "long-term correction halves of the message (106 bits each)",
         "grid_points": "type 26: the 15 grid points of the block"}

# A line: ("f", key, offset, bits, signed, factor[, extra])  or  ("g", list, offset, item_bits, count, lines)
#         or ("if", offset, bits, value, lines)
def f(key, off, bits, signed=False, factor=None, extra=""):
    return ("f", key, off, bits, signed, factor, extra)


FAST = lambda first, n: [("g", "fast_corrections", first, 12, n, [f("prc_m", 0, 12, True, P8)])]
HALF = [f("vel_code", 0, 1),
        ("if", 0, 1, 0, [f("sat1_slot", 1, 6), f("sat1_iode", 7, 8), f("sat1_dx_m", 15, 9, True, P8),
                         f("sat1_dy_m", 24, 9, True, P8), f("sat1_dz_m", 33, 9, True, P8),
                         f("sat1_daf0_s", 42, 10, True, P31),
                         f("sat2_slot", 52, 6), f("sat2_iode", 58, 8), f("sat2_dx_m", 66, 9, True, P8),
                         f("sat2_dy_m", 75, 9, True, P8), f("sat2_dz_m", 84, 9, True, P8),
                         f("sat2_daf0_s", 93, 10, True, P31), f("iodp", 103, 2), f("spare", 105, 1)]),
        ("if", 0, 1, 1, [f("lt_slot", 1, 6), f("lt_iode", 7, 8), f("lt_dx_m", 15, 11, True, P8),
                         f("lt_dy_m", 26, 11, True, P8), f("lt_dz_m", 37, 11, True, P8),
                         f("lt_daf0_s", 48, 11, True, P31), f("lt_ddx_ms", 59, 8, True, P11),
                         f("lt_ddy_ms", 67, 8, True, P11), f("lt_ddz_ms", 75, 8, True, P11),
                         f("lt_daf1_ss", 83, 8, True, Fr(1, 2 ** 39)), f("lt_t0_s", 91, 13, False, Fr(16)),
                         f("iodp", 104, 2)])]
KINDS = [
    ("type-1", 1, "PRN mask", [("g", "prn_mask", 14, 1, 210, [f("mask_bit", 0, 1)]), f("iodp", 224, 2)]),
] + [
    ("type-%d" % t, t, "fast corrections" + (" (type 0: test message, read as type 2)" if t == 0 else ""),
     [f("iodf", 14, 2), f("iodp", 16, 2)] + FAST(18, 13) +
     [("g", "udreis", 174, 4, 13, [f("udrei", 0, 4)])]) for t in (2, 3, 4, 5, 0)
] + [
    ("type-6", 6, "integrity information", [f("iodf_2", 14, 2), f("iodf_3", 16, 2), f("iodf_4", 18, 2), f("iodf_5", 20, 2),
                                            ("g", "udreis", 22, 4, 51, [f("udrei", 0, 4)])]),
    ("type-7", 7, "fast correction degradation factors", [f("latency_s", 14, 4), f("iodp", 18, 2), f("spare", 20, 2),
                                                           ("g", "degradation_factors", 22, 4, 51, [f("ai", 0, 4)])]),
    ("type-9", 9, "GEO navigation message", [
        f("geo_reserved", 14, 8), f("geo_t0_s", 22, 13, False, Fr(16)), f("geo_ura", 35, 4),
        f("geo_x_m", 39, 30, True, Fr(2, 25)), f("geo_y_m", 69, 30, True, Fr(2, 25)), f("geo_z_m", 99, 25, True, Fr(2, 5)),
        f("geo_vx_ms", 124, 17, True, Fr(1, 1600)), f("geo_vy_ms", 141, 17, True, Fr(1, 1600)),
        f("geo_vz_ms", 158, 18, True, Fr(1, 250)), f("geo_ax_mss", 176, 10, True, Fr(1, 80000)),
        f("geo_ay_mss", 186, 10, True, Fr(1, 80000)), f("geo_az_mss", 196, 10, True, Fr(1, 16000)),
        f("geo_af0_s", 206, 12, True, P31), f("geo_af1_ss", 218, 8, True, P40)]),
    ("type-18", 18, "ionospheric grid point mask", [
        f("band_count", 14, 4), f("band", 18, 4), f("iodi", 22, 2),
        ("g", "igp_mask", 24, 1, 201, [f("igp_bit", 0, 1)]), f("spare", 225, 1)]),
    ("type-24", 24, "mixed fast and long-term corrections", FAST(14, 6) + [
        ("g", "udreis", 86, 4, 6, [f("udrei", 0, 4)]), f("iodp", 110, 2), f("block", 112, 2), f("iodf", 114, 2),
        f("spare", 116, 4), ("g", "long_term", 120, 106, 1, HALF)]),
    ("type-25", 25, "long-term satellite error corrections", [("g", "long_term", 14, 106, 2, HALF)]),
    ("type-26", 26, "ionospheric delay corrections", [
        f("band", 14, 4), f("block", 18, 4),
        ("g", "grid_points", 22, 13, 15, [f("giv_delay_m", 0, 9, False, P8, "absent 511"), f("givei", 9, 4)]),
        f("iodi", 217, 2), f("spare", 219, 7)]),
]


def tr(signed, factor, key=None):
    if factor is None:
        return "twos" if signed else "uint"
    if key and KEYS[key][0] == "int":           # an integer key: an exact integer scale (engine-spec 0.15)
        return ("siscale:" if signed else "uiscale:") + str(factor)
    return ("sscale:" if signed else "uscale:") + ("%d/%d" % (factor.numerator, factor.denominator)
                                                     if factor.denominator != 1 else str(factor.numerator))


def emit(lines, ind, o):
    for l in lines:
        if l[0] == "f":
            _, key, off, bits, signed, factor, extra = l
            o.append(("%sfield  %s.%s  0:%d:%d  %s  %s" % (ind, MODULE, key, off, bits, tr(signed, factor, key), extra)).rstrip())
        elif l[0] == "g":
            _, lst, off, ib, n, body = l
            o.append("%sgroup  %s.%s  0:%d  item %d  count %d" % (ind, MODULE, lst, off, ib, n))
            emit(body, ind + "  ", o)
            o.append("%send" % ind)
        else:
            _, off, bits, val, body = l
            o.append("%sif 0:%d:%d %d" % (ind, off, bits, val))
            emit(body, ind + "  ", o)
            o.append("%send" % ind)


def pack_text():
    o = ["# SBAS L1 messages (WAAS, EGNOS, MSAS, GAGAN and others): the message types RTKLIB decodes.",
         "# Generated by tools/gen/sbas2pack.py; do not edit by hand. One message is the 250-bit message",
         "# (preamble, type, data, CRC-24Q) and 6 zero bits: 32 bytes, most significant bit first.",
         "# Licence: Apache-2.0 (a restatement; its source, RTKLIB sbas.c, is BSD-2-Clause).",
         "format        %s" % FMT, "version       0.1.0", "distribution  public",
         'source        "%s"' % SRC, "uses          %s" % MODULE, "wire          bits", "word_bytes    1",
         "bit_order     msb",
         "field  %s.preamble  0:0:8  uint" % MODULE,
         "field  %s.crc  0:226:24  uint" % MODULE]
    for name, t, what, lines in KINDS:
        o += ["", "# %s" % what, "kind  %s" % name, "when  0:8:6  %d" % t]
        emit(lines, "", o)
    return "\n".join(o) + "\n"


def module_text():
    o = ["# The sbas module: the fields of SBAS L1 messages as RTKLIB decodes them. Generated by",
         "# tools/gen/sbas2pack.py.", "module        %s" % MODULE, "version       0.1.0", "distribution  public",
         'source        "%s"' % SRC]
    for k, (ty, unit, meaning) in KEYS.items():
        o.append('key  %s  %s  %s  "%s"' % (k, ty, unit, meaning))
    for k, meaning in LISTS.items():
        o.append('list %s  "%s"' % (k, meaning))
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------- vectors ---

class Writer:
    def __init__(self):
        self.v, self.n = 0, 0

    def put(self, value, bits, at):
        assert self.n == at, ("field at bit", self.n, "stated", at)
        self.v = (self.v << bits) | (value & ((1 << bits) - 1))
        self.n += bits

    def pad_to(self, at):
        self.put(0, at - self.n, self.n)


def value_for(key, bits, signed, i):
    top = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
    v = (29 * (i + 3) + 7 * bits) % (top + 1)
    if key == "giv_delay_m":
        v = v % 511          # 511 is the not-monitored sentinel
    return -v if signed and i % 3 == 1 else v


def text(v, signed, factor, key=None):
    if factor is None:
        return str(v)
    if key and KEYS[key][0] == "int":
        return str(int(v * factor))
    return repr(float(v * factor))


def write_lines(lines, w, base, m, prefix, i0, choose):
    """Write lines at base (item-relative offsets) and fill the model; choose(off) gives a gate value."""
    for l in lines:
        if l[0] == "f":
            _, key, off, bits, signed, factor, _ = l
            if w.n < base + off:
                w.pad_to(base + off)
            v = choose.get((base, key), value_for(key, bits, signed, i0 + off))
            w.put(v, bits, base + off)
            m["%s%s.%s" % (prefix, MODULE, key)] = text(v, signed, factor, key)
        elif l[0] == "g":
            _, lst, off, ib, n, body = l
            m["%s%s.%s.#" % (prefix, MODULE, lst)] = str(n)
            for j in range(n):
                write_lines(body, w, base + off + j * ib, m, "%s%s.%s[%d]." % (prefix, MODULE, lst, j), i0 + j, choose)
                if w.n < base + off + (j + 1) * ib:
                    w.pad_to(base + off + (j + 1) * ib)
        else:
            _, off, bits, val, body = l
            if choose.get((base, "vel_code")) == val:
                write_lines(body, w, base, m, prefix, i0, choose)


def vectors():
    out = {}
    for n, (name, t, what, lines) in enumerate(KINDS, 1):
        w = Writer()
        pre = [0x53, 0x9A, 0xC6][n % 3]
        w.put(pre, 8, 0)
        w.put(t, 6, 8)
        m = {"@kind": name, "sbas.preamble": str(pre)}
        choose = {}
        if name == "type-24":
            choose[(120, "vel_code")] = 1
        if name == "type-25":
            choose[(14, "vel_code")] = 0
            choose[(120, "vel_code")] = 1
        write_lines(lines, w, 0, m, "", t, choose)
        if w.n < 226:
            w.pad_to(226)
        crc = (0x5A5A5A + t) & 0xFFFFFF
        w.put(crc, 24, 226)
        m["sbas.crc"] = str(crc)
        w.put(0, 6, 250)
        data = w.v.to_bytes(32, "big").hex()
        out["%02d-%s-roundtrip" % (n, name)] = {
            "name": "%s-roundtrip" % name, "from": FMT, "to": FMT, "input": data, "expect": data, "model": m,
            "source": "derived by tools/gen/sbas2pack.py; no engine run",
            "reference": "RTKLIB src/sbas.c (BSD-2-Clause) decode of message type %d (%s): field offsets as it "
                         "reads them; values chosen here%s" % (
                             t, what, "; the long-term half has velocity code 1" if name == "type-24" else
                             "; the first half velocity code 0 (two satellites), the second 1" if name == "type-25" else "")}
    # type 26 with a grid point not monitored (delay 511): the item has no delay key
    w = Writer()
    w.put(0x53, 8, 0)
    w.put(26, 6, 8)
    w.put(3, 4, 14)
    w.put(1, 4, 18)
    for j in range(15):
        w.put(511 if j == 0 else 8 * j, 9, 22 + 13 * j)
        w.put(15 if j == 0 else 2, 4, 31 + 13 * j)
    w.put(2, 2, 217)
    w.put(0, 7, 219)
    w.put(0, 24, 226)
    w.put(0, 6, 250)
    data = w.v.to_bytes(32, "big").hex()
    out["%02d-type-26-not-monitored" % (len(KINDS) + 1)] = {
        "name": "type-26-not-monitored", "from": FMT, "to": FMT, "input": data, "expect": data,
        "model": {"@kind": "type-26", "sbas.grid_points.#": "15", "sbas.grid_points[0].sbas.givei": "15",
                  "sbas.grid_points[1].sbas.giv_delay_m": "1.0"},
        "source": "derived by tools/gen/sbas2pack.py; no engine run",
        "reference": "RTKLIB src/sbas.c reads a vertical delay of 0x1FF as not monitored: the first grid point has "
                     "no giv_delay_m (absent 511) and writes 511 back"}
    w = Writer()
    w.put(0x53, 8, 0)
    w.put(10, 6, 8)
    w.pad_to(250)
    w.put(0, 6, 250)
    out["%02d-type-10-is-no-kind" % (len(KINDS) + 2)] = {
        "name": "type-10-is-no-kind", "from": FMT, "to": FMT, "input": w.v.to_bytes(32, "big").hex(),
        "expect_error": "no-kind", "source": "derived by tools/gen/sbas2pack.py; no engine run",
        "reference": "message type 10 (degradation parameters) is not decoded by RTKLIB and has no kind here"}
    out["%02d-short-is-malformed" % (len(KINDS) + 3)] = {
        "name": "short-is-malformed", "from": FMT, "to": FMT, "input": out["01-type-1-roundtrip"]["input"][:56],
        "expect_error": "malformed-wire", "source": "derived by tools/gen/sbas2pack.py; no engine run",
        "reference": "a message is 32 bytes; 28 are too few for the CRC field"}
    return out


def main():
    gt = sys.argv[1]
    check = "--check" in sys.argv[2:]
    files = {os.path.join("packs", FMT, "pack.def"): pack_text(), os.path.join("model", MODULE + ".def"): module_text()}
    for name, v in vectors().items():
        files[os.path.join("packs", FMT, "vectors", name + ".json")] = json.dumps(v, indent=2) + "\n"
    bad = 0
    for rel, t in files.items():
        path = os.path.join(gt, rel)
        if check:
            cur = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            if cur != t:
                print("differs: " + rel)
                bad += 1
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(t)
    if check:
        print("sbas2pack: %s" % ("ok" if not bad else "%d differ" % bad))
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
