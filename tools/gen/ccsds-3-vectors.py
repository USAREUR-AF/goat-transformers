#!/usr/bin/env python3
"""ccsds-3-vectors: write the conversion vectors of the CCSDS time code (CUC, CDS,
CCS) and Encapsulation Packet bits packs.

Python 3 standard library only; imports no engine and does not read any pack.def.
The layouts below are written from the CCSDS Blue Books (section numbers in each
table), in this program's own terms: (model key, bits) in wire order, bit 0 the
first transmitted bit, most significant bit first. A message is packed from
those tables by `pack()` and the expected hex of every vector is that result.

  packs/ccsds-cuc-time/vectors/*.json      CCSDS 301.0-B-4, 3.1 and 3.2
  packs/ccsds-cds-time/vectors/*.json      CCSDS 301.0-B-4, 3.1 and 3.3
  packs/ccsds-ccs-time/vectors/*.json      CCSDS 301.0-B-4, 3.1 and 3.4
  packs/ccsds-encap-packet/vectors/*.json  CCSDS 133.1-B-3, 4.1.2
  packs/geojson/vectors/ccsds-cds-time-*.json  GeoJSON to ccsds-cds-time

Inputs are codes and headers built here from values chosen here; no example of a
Blue Book is used. A CDS level 1 code to GeoJSON gives time_ms as
(day - 4383) x 86400000 + milliseconds of day: 4383 days separate 1958-01-01 and
1970-01-01 (12 years, 3 of them leap years). Calendar values are checked against
Python's calendar.timegm.

Usage: python3 -I tools/gen/ccsds-3-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.
"""
import calendar
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

DAYS_1958_1970 = 4383
assert calendar.timegm((1970, 1, 1, 0, 0, 0)) - calendar.timegm((1958, 1, 1, 0, 0, 0)) == DAYS_1958_1970 * 86400


def pack(layout, values):
    nbits = sum(it[1] for it in layout)
    assert nbits % 8 == 0, nbits
    acc = 0
    for it in layout:
        key, width = it[0], it[1]
        v = it[2] if key is None else values.get(key, 0)
        if not 0 <= v < (1 << width):
            raise ValueError("%s=%d does not fit %d bits" % (key, v, width))
        acc = (acc << width) | v
    return acc.to_bytes(nbits // 8, "big")


def model_of(values, keys, kind, prefix):
    m = {"@kind": kind} if kind else {}
    for k in keys:
        m[prefix + k] = str(values.get(k, 0))
    return m


def vec(name, fmt, inp, expect=None, error=None, model=None, ref="", to=None):
    v = {"name": name, "from": fmt, "to": to or fmt, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = ref
    return v


def bcd(n, digits):
    s = "%0*d" % (digits, n)
    assert len(s) == digits
    return int(s, 16)


T = "ccsdstime."


def geojson_time(ms):
    return json.dumps({"type": "Feature", "geometry": None, "properties": {"time_ms": ms}}, separators=(",", ":"))


# ---- CUC, 301.0-B-4 3.2 -----------------------------------------------------------

def cuc(level, c, f, coarse, fine=0):
    lay = [(None, 1, 0), (None, 3, level), ("cuc_coarse_octets", 2), ("cuc_fine_octets", 2),
           ("cuc_coarse", 8 * (c + 1))] + ([("cuc_fine", 8 * f)] if f else [])
    v = {"cuc_coarse_octets": c, "cuc_fine_octets": f, "cuc_coarse": coarse, "cuc_fine": fine}
    keys = ["cuc_coarse_octets", "cuc_fine_octets", "cuc_coarse"] + (["cuc_fine"] if f else [])
    return pack(lay, v), model_of(v, keys, "level-1" if level == 1 else "level-2", T)


def cuc_time():
    F = "ccsds-cuc-time"
    out = []
    h, m = cuc(1, 3, 2, 2155766400, 0x8000)
    out.append(vec("level-1-four-and-two-octets", F, h.hex(), h.hex(), model=m,
                   ref="level 1 (1958 TAI epoch), 4 octets of seconds (2155766400) and 2 of fraction (0x8000, a "
                       "half second): P-field 0x2e and 6 octets"))
    h2, m2 = cuc(2, 0, 0, 200)
    out.append(vec("level-2-one-octet-no-fraction", F, (h2 + bytes(3)).hex(), h2.hex(), model=m2,
                   ref="level 2 (agency epoch), one octet of time units, no fraction; the 3 octets after the code are "
                       "read over"))
    he, me = cuc(1, 3, 3, 0xFFFFFFFF, 0xFFFFFF)
    out.append(vec("largest-four-and-three-octets", F, he.hex(), he.hex(), model=me,
                   ref="the largest code with a one-octet P-field: 4 coarse and 3 fine octets, all ones"))
    h3, m3 = cuc(2, 1, 1, 0x1234, 0x56)
    out.append(vec("level-2-two-and-one-octets", F, h3.hex(), h3.hex(), model=m3,
                   ref="level 2, 2 coarse octets and 1 fine octet"))
    ext = bytes([0x80 | 0x10 | 0x0C, 0x20]) + bytes(5)
    out.append(vec("extended-p-field-is-no-kind", F, ext.hex(), error="no-kind",
                   ref="a P-field with the extension bit set (a second P-field octet follows), which the pack does "
                       "not map"))
    cds_like = bytes([0x40]) + bytes(6)
    out.append(vec("cds-code-id-is-no-kind", F, cds_like.hex(), error="no-kind",
                   ref="a P-field with time code ID 100 (CDS)"))
    out.append(vec("cut-inside-fraction-is-malformed", F, h[:6].hex(), error="malformed-wire",
                   ref="the first code cut to 6 octets, inside its fraction"))
    return F, out


# ---- CDS, 301.0-B-4 3.3 -----------------------------------------------------------

def cds(level, day24, sub, day, ms, subv=0):
    p = [(None, 1, 0), (None, 3, 4), (None, 1, 0 if level == 1 else 1), ("cds_day_segment_24", 1),
         ("cds_submillisecond_length", 2)]
    lay = p + [("cds_day", 24 if day24 else 16), ("cds_ms_of_day", 32)]
    if sub in (1, 2):
        lay.append(("cds_submillisecond", 16 * sub))
    v = {"cds_day_segment_24": day24, "cds_submillisecond_length": sub, "cds_day": day, "cds_ms_of_day": ms,
         "cds_submillisecond": subv}
    keys = ["cds_day_segment_24", "cds_submillisecond_length", "cds_day", "cds_ms_of_day"] + \
        (["cds_submillisecond"] if sub in (1, 2) else [])
    m = model_of(v, keys, "level-1" if level == 1 else "level-2", T)
    if level == 1:
        m[T + "cds_day_unix_ms"] = str((day - DAYS_1958_1970) * 86400000)
    return pack(lay, v), m


DAY_20261119 = (calendar.timegm((2026, 11, 19, 0, 0, 0)) // 86400) + DAYS_1958_1970
MS_TIME = ((1 * 60 + 2) * 60 + 3) * 1000 + 456


def cds_time():
    F = "ccsds-cds-time"
    out = []
    h, m = cds(1, 0, 0, DAY_20261119, MS_TIME)
    out.append(vec("level-1-day-16-ms", F, h.hex(), h.hex(), model=m,
                   ref="level 1, 16-bit day %d (2026-11-19, counted from 1958-01-01 as day 0), %d ms of day "
                       "(01:02:03.456), no submillisecond segment: 7 octets" % (DAY_20261119, MS_TIME)))
    t = (DAY_20261119 - DAYS_1958_1970) * 86400000 + MS_TIME
    assert t == calendar.timegm((2026, 11, 19, 1, 2, 3)) * 1000 + 456
    out.append(vec("level-1-to-geojson-time", F, h.hex(), geojson_time(t), model=m, to="geojson",
                   ref="the first code to GeoJSON: the day count gives the day's start, %d ms since 1970, and the "
                       "derivation adds the milliseconds of day: time_ms %d, 2026-11-19 01:02:03.456 UTC"
                       % ((DAY_20261119 - DAYS_1958_1970) * 86400000, t)))
    h2, m2 = cds(1, 1, 1, DAY_20261119, 86399999, 999)
    out.append(vec("level-1-day-24-microseconds", F, h2.hex(), h2.hex(), model=m2,
                   ref="level 1, 24-bit day segment, the last millisecond of the day and 999 microseconds: 10 octets"))
    hl, ml = cds(1, 0, 0, DAY_20261119, 86400500)
    tl = (DAY_20261119 - DAYS_1958_1970) * 86400000 + 86400500
    out.append(vec("leap-second-to-geojson-time", F, hl.hex(), geojson_time(tl), model=ml, to="geojson",
                   ref="500 ms into a positive leap second (ms of day 86400500): time_ms %d, which is also the "
                       "time_ms of 00:00:00.500 of the next day; milliseconds since 1970 have no leap second" % tl))
    h3, m3 = cds(2, 1, 2, 0xFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
    out.append(vec("level-2-largest-picoseconds", F, h3.hex(), h3.hex(), model=m3,
                   ref="level 2 (agency epoch), every segment at its largest value with a 32-bit picosecond segment: "
                       "12 octets; no day start, no time_ms"))
    h4, m4 = cds(2, 0, 0, 5, 1000)
    out.append(vec("level-2-to-geojson-carries-no-time", F, h4.hex(),
                   json.dumps({"type": "Feature", "geometry": None, "properties": {}}, separators=(",", ":")),
                   model=m4, to="geojson",
                   ref="a level 2 code to GeoJSON: the epoch is the agency's, so no time_ms"))
    h5, m5 = cds(1, 0, 3, DAY_20261119, MS_TIME)
    out.append(vec("reserved-resolution-has-no-submillisecond", F, (h5 + bytes(2)).hex(), h5.hex(), model=m5,
                   ref="submillisecond length code 3 (reserved): no segment is read, the 2 octets after the "
                       "milliseconds are read over"))
    out.append(vec("cut-inside-ms-is-malformed", F, h[:5].hex(), error="malformed-wire",
                   ref="the first code cut to 5 octets, inside its milliseconds of day"))
    out.append(vec("cuc-code-id-is-no-kind", F, bytes([0x1C]).hex() + "00" * 4, error="no-kind",
                   ref="a P-field with time code ID 001 (CUC)"))
    return F, out


def geojson_to_cds():
    return [vec("time-only-is-no-kind", "geojson", geojson_time(1795568400000), error="no-kind", to="ccsds-cds-time",
                ref="a GeoJSON Feature with time_ms only: both CDS kinds require the day count, which no derivation "
                    "gives from time_ms (there is no integer division by 86400000), so no kind is chosen")]


# ---- CCS, 301.0-B-4 3.4 -----------------------------------------------------------

def ccs(doy_var, year, md, h, mi, s, subs):
    lay = [(None, 1, 0), (None, 3, 5), (None, 1, doy_var), ("ccs_resolution", 3), ("ccs_year", 16)]
    v = {"ccs_resolution": len(subs), "ccs_year": bcd(year, 4), "ccs_hour": bcd(h, 2), "ccs_minute": bcd(mi, 2),
         "ccs_second": bcd(s, 2)}
    if doy_var:
        lay.append(("ccs_day_of_year", 16))
        v["ccs_day_of_year"] = bcd(md, 4)
        kk, kind = ["ccs_day_of_year"], "day-of-year"
    else:
        lay += [("ccs_month", 8), ("ccs_day_of_month", 8)]
        v["ccs_month"], v["ccs_day_of_month"] = bcd(md[0], 2), bcd(md[1], 2)
        kk, kind = ["ccs_month", "ccs_day_of_month"], "month-day"
    lay += [("ccs_hour", 8), ("ccs_minute", 8), ("ccs_second", 8)]
    b = pack(lay, v) + bytes(bcd(x, 2) for x in subs)
    m = model_of(v, ["ccs_resolution", "ccs_year", "ccs_hour", "ccs_minute", "ccs_second"] + kk, kind, T)
    m[T + "ccs_subseconds.#"] = str(len(subs))
    for i, x in enumerate(subs):
        m[T + "ccs_subseconds[%d]." % i + T + "ccs_subsecond_digits"] = str(bcd(x, 2))
    return b, m


def ccs_time():
    F = "ccsds-ccs-time"
    out = []
    h, m = ccs(0, 2026, (11, 19), 12, 34, 56, [78, 90, 12])
    out.append(vec("month-day-microseconds", F, h.hex(), h.hex(), model=m,
                   ref="month/day variation, resolution 3: 2026-11-19 12:34:56.789012 in BCD (year 0x2026), 11 "
                       "octets"))
    h2, m2 = ccs(1, 2026, 323, 0, 0, 0, [])
    assert calendar.timegm((2026, 11, 19, 0, 0, 0)) - calendar.timegm((2026, 1, 1, 0, 0, 0)) == 322 * 86400
    out.append(vec("day-of-year-seconds", F, h2.hex(), h2.hex(), model=m2,
                   ref="day-of-year variation, resolution 0: 2026 day 323 (19 November) 00:00:00, 8 octets"))
    h3, m3 = ccs(0, 2016, (12, 31), 23, 59, 60, [50])
    out.append(vec("leap-second", F, h3.hex(), h3.hex(), model=m3,
                   ref="2016-12-31 23:59:60.50, the positive leap second at the end of 2016, with one subsecond "
                       "octet: second 0x60 is carried"))
    h4, m4 = ccs(1, 9999, 366, 23, 59, 59, [99] * 6)
    out.append(vec("largest-picoseconds", F, (h4 + bytes(4)).hex(), h4.hex(), model=m4,
                   ref="day-of-year variation at its largest digits, resolution 6 (10^-12 s): 14 octets; 4 octets "
                       "after it read over"))
    out.append(vec("cut-inside-subseconds-is-malformed", F, h[:10].hex(), error="malformed-wire",
                   ref="the first code cut to 10 octets, inside its subsecond octets"))
    out.append(vec("cds-code-id-is-no-kind", F, (bytes([0x40]) + bytes(7)).hex(), error="no-kind",
                   ref="a P-field with time code ID 100 (CDS)"))
    return F, out


# ---- Encapsulation Packet, 133.1-B-3 4.1.2 ---------------------------------------

E = "ccsdsep."


def encap(lol, v):
    lay = [(None, 3, 7), ("protocol_id", 3), (None, 2, lol)]
    keys = ["protocol_id"]
    if lol == 1:
        lay += [("packet_length", 8)]
        keys += ["packet_length"]
        kind = "length-1-octet"
    elif lol == 2:
        lay += [("user_defined", 4), ("protocol_id_extension", 4), ("packet_length", 16)]
        keys += ["user_defined", "protocol_id_extension", "packet_length"]
        kind = "length-2-octets"
    elif lol == 3:
        lay += [("user_defined", 4), ("protocol_id_extension", 4), ("ccsds_defined", 16), ("packet_length", 32)]
        keys += ["user_defined", "protocol_id_extension", "ccsds_defined", "packet_length"]
        kind = "length-4-octets"
    else:
        kind = "idle"
    return pack(lay, v), model_of(v, keys, kind, E)


def encap_packet():
    F = "ccsds-encap-packet"
    out = []
    hi, mi = encap(0, {})
    out.append(vec("idle-one-octet", F, hi.hex(), hi.hex(), model=mi,
                   ref="the 1-octet idle packet: protocol ID 0, length of length 0"))
    h1, m1 = encap(1, {"protocol_id": 2, "packet_length": 12})
    out.append(vec("one-octet-length-data-not-written", F, (h1 + bytes(10)).hex(), h1.hex(), model=m1,
                   ref="a 2-octet header, protocol ID 2, packet length 12 (header included); the 10 data octets are "
                       "read over"))
    h2, m2 = encap(2, {"protocol_id": 6, "user_defined": 5, "protocol_id_extension": 1, "packet_length": 1500})
    out.append(vec("two-octet-length-extended-protocol", F, h2.hex(), h2.hex(), model=m2,
                   ref="a 4-octet header, protocol ID 6 with extension 1, user defined bits 5, packet length 1500"))
    h4, m4 = encap(3, {"protocol_id": 7, "user_defined": 15, "protocol_id_extension": 15, "ccsds_defined": 0xFFFF,
                       "packet_length": 0xFFFFFFFF})
    out.append(vec("four-octet-length-largest", F, h4.hex(), h4.hex(), model=m4,
                   ref="an 8-octet header with every field at its largest value, the CCSDS defined field included "
                       "(the pack does not check it)"))
    out.append(vec("eight-octet-header-cut-is-malformed", F, h4[:6].hex(), error="malformed-wire",
                   ref="the 8-octet header cut to 6 octets"))
    sp = bytes([0x08, 0x01, 0xC0, 0x00, 0x00, 0x03])
    out.append(vec("space-packet-version-is-no-kind", F, sp.hex(), error="no-kind",
                   ref="a header whose version bits are 000, a Space Packet's"))
    return F, out


def build(out):
    written = {}
    for make in (cuc_time, cds_time, ccs_time, encap_packet):
        fmt, vecs = make()
        vdir = "packs/%s/vectors" % fmt
        assert len({v["name"] for v in vecs}) == len(vecs), fmt
        names = set()
        for i, v in enumerate(vecs, 1):
            rel = "%s/%02d-%s.json" % (vdir, i, v["name"])
            names.add(rel.rsplit("/", 1)[1])
            out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        for old in out.listdir(vdir):
            if old.endswith(".json") and old not in names:
                out.remove(vdir + "/" + old)
        written[fmt] = len(vecs)
    vdir, prefix = "packs/geojson/vectors", "ccsds-cds-time-"
    vecs = geojson_to_cds()
    names = set()
    for i, v in enumerate(vecs, 1):
        name = "%s%02d-%s.json" % (prefix, i, v["name"])
        names.add(name)
        out.write(vdir + "/" + name, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    for old in out.listdir(vdir):
        if old.startswith(prefix) and old.endswith(".json") and old not in names:
            out.remove(vdir + "/" + old)
    written["geojson/" + prefix.rstrip("-")] = len(vecs)
    return written


def main(argv=None):
    return genio.vector_main("ccsds-3-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
