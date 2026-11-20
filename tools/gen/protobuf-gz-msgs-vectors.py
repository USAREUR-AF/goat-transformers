#!/usr/bin/env python3
"""protobuf-gz-msgs-vectors: hand-written vectors of the gz-msgs-navsat pack
(tools/gen/gz-msgs-run.sh), and one vector from geojson into it.

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines; the values are made up. The
expected output is worked out from spec/engine-spec.md: protobuf output is canonical (0.3),
only mapped fields in ascending field-number order; geojson output (Canonicalisation) has
`coordinates` as [lon, lat], members in the order of packs/geojson's `field` lines, numbers in
shortest form; model/track.def derives `course` 0 and `speed_ms` 5 exactly from a velocity of
0 east and 5 north, and the other way east 0 and north 5 from course 0 and speed 5.

Usage: python3 -I tools/gen/protobuf-gz-msgs-vectors.py [--out DIR] [--check]

With --check nothing is written and the exit status is 1 when a committed vector is not what
this script writes.
"""
import json
import os
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


def varint(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def key(num, wt):
    return varint(num << 3 | wt)


def V(num, n):
    return key(num, 0) + varint(n)


def D(num, x):
    return key(num, 1) + struct.pack("<d", x)


def L(num, *parts):
    body = b"".join(p.encode("utf-8") if isinstance(p, str) else p for p in parts)
    return key(num, 2) + varint(len(body)) + body


def S(num, text):
    return L(num, text.encode("utf-8"))


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}

    def write(pack, name, frm, to, inp, expect, model=None):
        v = {"name": name, "from": frm, "to": to, "input": inp, "expect": expect}
        if model:
            v["model"] = model
        sink.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1

    # NavSat: header 1 { stamp 1 { sec 1, nsec 2 } }, latitude_deg 2, longitude_deg 3, altitude 4,
    # velocity_east 5, velocity_north 6, velocity_up 7, frame_id 8.
    fix = (L(1, L(1, V(1, 1700000000), V(2, 250000000))) + D(2, 47.375) + D(3, 8.5625) + D(4, 408.5)
           + D(5, 0.0) + D(6, 5.0) + D(7, -0.25) + S(8, "gps_link"))
    write("gz-msgs-navsat", "01-fix-roundtrip", "gz-msgs-navsat", "gz-msgs-navsat", fix.hex(), fix.hex(),
          {"lat": "47.375", "lon": "8.5625", "track.vel_north_ms": "5", "track.vel_up_ms": "-0.25",
           "gzmsgsnavsat.nav_sat_altitude": "408.5", "gzmsgsnavsat.header_stamp_sec": "1700000000"})
    # The altitude has no stated reference: it does not reach geojson.
    write("gz-msgs-navsat", "02-fix-to-geojson", "gz-msgs-navsat", "geojson", fix.hex(),
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.5625,47.375]},'
          '"properties":{"course":0,"speed_ms":5}}',
          {"@complete": True, "course": "0", "speed_ms": "5"})
    write("geojson", "132-to-gz-msgs-navsat-position-and-velocity", "geojson", "gz-msgs-navsat",
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.5625,47.375,410]},'
          '"properties":{"course":0,"speed_ms":5}}',
          (D(2, 47.375) + D(3, 8.5625) + D(5, 0.0) + D(6, 5.0)).hex(),
          {"@complete": True, "track.vel_east_ms": "0", "track.vel_north_ms": "5"})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-gz-msgs-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
