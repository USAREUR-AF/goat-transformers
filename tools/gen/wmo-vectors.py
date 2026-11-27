#!/usr/bin/env python3
"""Write the vectors of the grib2 and bufr4 packs.

Every message is built here, with an encoder of its own, from values written for these vectors
(no example message of WMO, ECMWF or another source is used). GRIB2: section 0 (GRIB, reserved,
discipline, edition 2, total length in 8 octets), sections of a 4-octet length that counts
itself and a section number, section 8 (7777); templates 3.0, 4.0 and 5.0 as the wmo-im/GRIB2
templates list them, negative values in sign and magnitude (regulation 92.1.5, as the WMO
template notes cite it). BUFR edition 4: section 0 (BUFR, total length in 3 octets, edition 4),
sections 1 to 4 of a 3-octet length that counts itself, section 5 (7777), as the ecCodes BUFR
section definitions lay them out. The decoded values are stated from the same inputs, and a round
trip expects its input, which is written in the packs' canonical form (spec/engine-spec.md 0.8,
0.20, 0.21). It reads no pack.def and calls no goat-transformers engine.

Usage: python3 -I tools/gen/wmo-vectors.py [--out DIR] [--check]
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/wmo-vectors.py from messages written for it and spec/engine-spec.md; no engine run"
REF_GRIB = "WMO GRIB2 templates 3.0, 4.0, 5.0 (wmo-im/GRIB2) and the ecCodes GRIB2 section layouts"
REF_BUFR = "ecCodes BUFR edition 4 section layouts; WMO BUFR edition 4 tables (wmo-im/BUFR4)"


def vec(name, frm, inp, expect=None, model=None, error=None, ref="", note=None):
    v = {"name": name, "from": frm, "to": frm, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = {k: str(x) for k, x in model.items()}
    v["source"] = SOURCE
    v["reference"] = ref + ("; " + note if note else "")
    return v


def u(v, n):
    return v.to_bytes(n, "big")


def sm(v, n):
    """Sign and magnitude in n octets: the most significant bit is the sign."""
    mag = abs(v)
    if mag >= 1 << (8 * n - 1):
        raise ValueError(v)
    return u(mag | ((1 << (8 * n - 1)) if v < 0 else 0), n)


def f32(x):
    return struct.pack(">f", x)


# -- GRIB2 ---------------------------------------------------------------------------------------

def gsec(number, body):
    return u(5 + len(body), 4) + u(number, 1) + body


def grib(discipline, sections, edition=2):
    body = b"".join(sections) + b"7777"
    return b"GRIB" + u(0xFFFF, 2) + u(discipline, 1) + u(edition, 1) + u(16 + len(body), 8) + body


def sec1(year=2026, month=11, day=20, hour=6, minute=0, second=0):
    return gsec(1, u(98, 2) + u(0, 2) + u(33, 1) + u(0, 1) + u(1, 1) + u(year, 2) + bytes([month, day, hour, minute, second]) +
                u(0, 1) + u(1, 1))


def sec3_latlon(ni, nj, la1, lo1, la2, lo2, di, dj, scan=0):
    t = (u(6, 1) + u(0xFF, 1) + u(0xFFFFFFFF, 4) + u(0xFF, 1) + u(0xFFFFFFFF, 4) + u(0xFF, 1) + u(0xFFFFFFFF, 4) +
         u(ni, 4) + u(nj, 4) + u(0, 4) + u(0xFFFFFFFF, 4) + sm(la1, 4) + sm(lo1, 4) + u(0x30, 1) + sm(la2, 4) +
         sm(lo2, 4) + u(di, 4) + u(dj, 4) + u(scan, 1))
    return gsec(3, u(0, 1) + u(ni * nj, 4) + u(0, 1) + u(0, 1) + u(0, 2) + t)


def sec4_t0(category, number, surface, scale, value, forecast):
    t = (u(category, 1) + u(number, 1) + u(2, 1) + u(0, 1) + u(148, 1) + u(0, 2) + u(0, 1) + u(1, 1) + sm(forecast, 4) +
         u(surface, 1) + sm(scale, 1) + u(value, 4) + u(255, 1) + sm(0, 1) + u(0, 4))
    return gsec(4, u(0, 2) + u(0, 2) + t)


def sec5_t0(n, ref, e, d, bits):
    return gsec(5, u(n, 4) + u(0, 2) + f32(ref) + sm(e, 2) + sm(d, 2) + u(bits, 1) + u(0, 1))


def grib2_vectors():
    V = {}
    F = "grib2"
    data = bytes([0x12, 0x34, 0x56, 0x78])
    msg = grib(0, [sec1(), sec3_latlon(2, 2, 50000000, 10000000, 49750000, 10250000, 250000, 250000, 0),
                   sec4_t0(0, 0, 103, 0, 2, 6), sec5_t0(4, 273.5, 0, 1, 8), gsec(6, u(255, 1)), gsec(7, data)])
    x = msg.hex()
    S = "grib2.sections"
    V["01-temperature-field-roundtrip"] = vec("temperature-field-roundtrip", F, x, x, {
        "@kind": "grib2", "grib2.discipline": 0, "grib2.reserved": 0xFFFF, S + ".#": 7,
        S + "[6].@kind": "end", S + "[6].grib2.end_marker": 926365495,
        S + "[0].grib2.section_number": 1, S + "[0].grib2.centre": 98, S + "[0].grib2.year": 2026, S + "[0].grib2.hour": 6,
        S + "[1].grib2.grid_template": 0, S + "[1].grib2.ni": 2, S + "[1].grib2.la1": 50000000, S + "[1].grib2.lo2": 10250000,
        S + "[1].grib2.di": 250000, S + "[1].grib2.section_octets.#": 0,
        S + "[2].grib2.parameter_category": 0, S + "[2].grib2.forecast_time": 6, S + "[2].grib2.type_of_first_surface": 103,
        S + "[2].grib2.scaled_value_of_first_surface": 2,
        S + "[3].grib2.reference_value": "273.5", S + "[3].grib2.decimal_scale_factor": 1, S + "[3].grib2.bits_per_value": 8,
        S + "[4].grib2.bitmap_indicator": 255, S + "[5].grib2.section_number": 7, S + "[5].grib2.section_octets.#": 4,
        S + "[6].@kind": "end"}, ref=REF_GRIB,
        note="a 2 x 2 latitude/longitude grid of 2 m temperature (category 0, number 0, 2 m above ground) at a 6-hour "
             "forecast, simple packing with reference 273.5 and decimal scale factor 1; the four packed values are octets")
    msg = grib(10, [sec1(2026, 1, 2, 18, 30, 0), sec3_latlon(3, 1, -33500000, -70750000, -33500000, -70250000, 250000, 0, 0x40),
                    sec4_t0(1, 3, 160, -1, 25, -3), sec5_t0(3, -1.5, -2, -3, 12), gsec(6, u(255, 1)), gsec(7, bytes(5))])
    x = msg.hex()
    V["02-negative-values-roundtrip"] = vec("negative-values-roundtrip", F, x, x, {
        "grib2.discipline": 10, S + "[1].grib2.la1": -33500000, S + "[1].grib2.lo1": -70750000, S + "[1].grib2.scanning_mode": 0x40,
        S + "[2].grib2.forecast_time": -3, S + "[2].grib2.scale_factor_of_first_surface": -1,
        S + "[3].grib2.reference_value": "-1.5", S + "[3].grib2.binary_scale_factor": -2, S + "[3].grib2.decimal_scale_factor": -3},
        ref=REF_GRIB, note="a southern and western grid and negative forecast time, scale factors and reference value: the "
                           "signed fields are sign and magnitude (the most significant bit is the sign)")
    other3 = gsec(3, u(0, 1) + u(4, 4) + u(0, 1) + u(0, 1) + u(30, 2) + bytes(range(1, 11)))
    other4 = gsec(4, u(0, 2) + u(8, 2) + bytes(range(20, 26)))
    other5 = gsec(5, u(4, 4) + u(40, 2) + bytes([7, 7]))
    msg = grib(0, [sec1(), gsec(2, bytes([0xAA, 0xBB])), other3, other4, other5, gsec(6, u(0, 1) + bytes([0xF0])), gsec(7, bytes([1]))])
    x = msg.hex()
    V["03-other-templates-as-octets-roundtrip"] = vec("other-templates-as-octets-roundtrip", F, x, x, {
        S + "[1].grib2.section_number": 2, S + "[1].grib2.section_octets.#": 2, S + "[2].grib2.grid_template": 30,
        S + "[2].grib2.section_octets.#": 10, S + "[3].grib2.product_template": 8, S + "[3].grib2.section_octets.#": 6,
        S + "[4].grib2.data_template": 40, S + "[4].grib2.section_octets.#": 2, S + "[5].grib2.bitmap_indicator": 0,
        S + "[5].grib2.section_octets.#": 1}, ref=REF_GRIB,
        note="a local use section, and grid template 30, product template 8 and data template 40, which the pack keeps as "
             "octets, and a bitmap")
    two = grib(0, [sec1(), sec3_latlon(1, 1, 0, 0, 0, 0, 0, 0), sec4_t0(0, 0, 1, 0, 0, 0), sec5_t0(1, 1.0, 0, 0, 0),
                   gsec(6, u(255, 1)), gsec(7, b""), sec4_t0(0, 2, 1, 0, 0, 0), sec5_t0(1, 2.0, 0, 0, 0), gsec(6, u(255, 1)),
                   gsec(7, b"")])
    x = two.hex()
    V["04-two-fields-roundtrip"] = vec("two-fields-roundtrip", F, x, x, {
        S + ".#": 11, S + "[6].grib2.section_number": 4, S + "[6].grib2.parameter_number": 2, S + "[7].grib2.reference_value": "2",
        S + "[10].@kind": "end"}, ref=REF_GRIB,
        note="one message with two fields sharing the grid: sections 4 to 7 repeat, each a list item")
    x = grib(0, [sec1()], edition=1).hex()
    V["05-edition-1-is-no-kind"] = vec("edition-1-is-no-kind", F, x, error="no-kind", ref=REF_GRIB,
                                       note="octet 8 states edition 1: the common when does not hold")
    msg = grib(0, [sec1()])
    V["06-input-shorter-than-total-length"] = vec("input-shorter-than-total-length", F, msg[:-4].hex(), error="malformed-wire",
                                                  ref=REF_GRIB, note="the total length states four octets more than the input holds")
    return V


# -- BUFR edition 4 ------------------------------------------------------------------------------

def bsec(body):
    return u(3 + len(body), 3) + body


def bufr(sec1_flag, s2, descriptors, data, subsets=1, observed=1, compressed=0, edition=4, local=b""):
    s1 = bsec(u(0, 1) + u(98, 2) + u(0, 2) + u(0, 1) + u(0x80 if sec1_flag else 0, 1) + u(0, 1) + u(2, 1) + u(255, 1) +
              u(38, 1) + u(0, 1) + u(2026, 2) + bytes([11, 20, 12, 0, 0]) + local)
    secs = s1 + (bsec(u(0, 1) + s2) if sec1_flag else b"")
    d = b"".join(u((f << 14) | (x << 8) | y, 2) for f, x, y in descriptors)
    secs += bsec(u(0, 1) + u(subsets, 2) + u((observed << 7) | (compressed << 6), 1) + d)
    secs += bsec(u(0, 1) + data) + b"7777"
    total = 8 + len(secs)
    return b"BUFR" + u(total, 3) + u(edition, 1) + secs


def bufr_vectors():
    V = {}
    F = "bufr4"
    m = bufr(False, b"", [(3, 7, 80), (0, 12, 101)], bytes([0x5A, 0xA5, 0x0F]))
    x = m.hex()
    V["01-message-roundtrip"] = vec("message-roundtrip", F, x, x, {
        "@kind": "bufr4", "bufr4.centre": 98, "bufr4.optional_section": 0, "bufr4.data_category": 0,
        "bufr4.international_sub_category": 2, "bufr4.master_table_version": 38, "bufr4.year": 2026, "bufr4.hour": 12,
        "bufr4.section1_local.#": 0, "bufr4.number_of_subsets": 1, "bufr4.observed_data": 1, "bufr4.compressed_data": 0,
        "bufr4.descriptors.#": 2, "bufr4.descriptors[0].bufr4.descriptor_f": 3, "bufr4.descriptors[0].bufr4.descriptor_x": 7,
        "bufr4.descriptors[0].bufr4.descriptor_y": 80, "bufr4.descriptors[1].bufr4.descriptor_y": 101,
        "bufr4.data.#": 3}, ref=REF_BUFR,
        note="a message without section 2: two descriptors (a sequence 3 07 080 and an element 0 12 101) and three octets "
             "of data, which the pack does not expand")
    m = bufr(True, bytes([1, 2, 3, 4]), [(0, 1, 1)], bytes([0xFF]), subsets=2, observed=0, compressed=1, local=bytes([9, 9]))
    x = m.hex()
    V["02-optional-section-roundtrip"] = vec("optional-section-roundtrip", F, x, x, {
        "bufr4.optional_section": 1, "bufr4.section1_local.#": 2, "bufr4.section2_data.#": 4,
        "bufr4.section2_data[3].bufr4.section2_octet": 4, "bufr4.number_of_subsets": 2, "bufr4.compressed_data": 1},
        ref=REF_BUFR, note="the flag of section 1 set and section 2 present; two local octets at the end of section 1; "
                           "compressed data of two subsets")
    m = bufr(False, b"", [(0, 1, 1)], b"\x00", edition=3)
    V["03-edition-3-is-no-kind"] = vec("edition-3-is-no-kind", F, m.hex(), error="no-kind", ref=REF_BUFR,
                                       note="edition 3 lays out section 1 differently; the common when on the edition does not hold")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("grib2", grib2_vectors()), ("bufr4", bufr_vectors())):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("wmo-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
