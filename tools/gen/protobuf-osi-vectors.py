#!/usr/bin/env python3
"""protobuf-osi-vectors: hand-written vectors of the osi-host-vehicle-data and osi-ground-truth
packs (tools/gen/osi-run.sh), and one vector from geojson into osi-host-vehicle-data.

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines; the values are made up, not taken
from a simulation or a trace. The expected output is worked out from spec/engine-spec.md:
protobuf output is canonical (0.3), only mapped fields in ascending field-number order inside
every message; geojson output (Canonicalisation) has `coordinates` as [lon, lat] and members in
the order of packs/geojson's `field` lines.

Usage: python3 -I tools/gen/protobuf-osi-vectors.py [--out DIR] [--check]

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

    # HostVehicleData: vehicle_localization 8 { geodetic_position 3 { longitude 1, latitude 2,
    # altitude 3 (EGM96, a raw key) } }, version 9 { major 1, minor 2, patch 3 }, timestamp 10
    # { seconds 1, nanos 2 }.
    geo = L(8, L(3, D(1, 11.5625), D(2, 48.1875), D(3, 519.25)))
    hvd = geo + L(9, V(1, 3), V(2, 8), V(3, 0)) + L(10, V(1, 1700000000), V(2, 500000000))
    write("osi-host-vehicle-data", "01-geodetic-position-roundtrip", "osi-host-vehicle-data",
          "osi-host-vehicle-data", hvd.hex(), hvd.hex(),
          {"lat": "48.1875", "lon": "11.5625",
           "osihostvehicledata.vehicle_localization_geodetic_position_altitude": "519.25",
           "osihostvehicledata.version_version_minor": "8",
           "osihostvehicledata.timestamp_nanos": "500000000"})
    # The altitude is above the EGM96 geoid, not the ellipsoid: it does not reach geojson.
    write("osi-host-vehicle-data", "02-geodetic-position-to-geojson", "osi-host-vehicle-data", "geojson",
          hvd.hex(), '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.5625,48.1875]},"properties":{}}')
    # The way in: the point's altitude has no line here (hae is not EGM96 height).
    write("geojson", "131-to-osi-host-vehicle-data-latitude-longitude", "geojson", "osi-host-vehicle-data",
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.5625,48.1875,520.5]},"properties":{}}',
          L(8, L(3, D(1, 11.5625), D(2, 48.1875))).hex(), {"lat": "48.1875", "lon": "11.5625", "hae": "520.5"})

    # GroundTruth: version 1, timestamp 2, proj_string 14 (text, carried as it is).
    proj = "+proj=utm +zone=32 +ellps=WGS84 +units=m +no_defs"
    gt = L(1, V(1, 3), V(2, 8), V(3, 0)) + L(2, V(1, 12), V(2, 250)) + S(14, proj)
    write("osi-ground-truth", "01-proj-string-carried-as-text", "osi-ground-truth", "osi-ground-truth",
          gt.hex(), gt.hex(), {"osigroundtruth.ground_truth_proj_string": proj, "osigroundtruth.timestamp_seconds": "12"})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-osi-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
