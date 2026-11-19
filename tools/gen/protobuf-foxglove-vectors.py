#!/usr/bin/env python3
"""protobuf-foxglove-vectors: hand-written vectors of four foxglove-proto-* packs
(tools/gen/foxglove-run.sh): pose-in-frame, raw-image, log and geojson.

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines; the values are made up. The expected
output is worked out from spec/engine-spec.md: protobuf output is canonical (0.3), only mapped
fields in ascending field-number order inside every message, so an input written that way with
mapped fields only is its own expected output, and a field no line maps (here `fixed32` and
`bytes`) is left out.

Usage: python3 -I tools/gen/protobuf-foxglove-vectors.py [--out DIR] [--check]

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


def U32(num, n):
    return key(num, 5) + struct.pack("<I", n)


def L(num, *parts):
    body = b"".join(p.encode("utf-8") if isinstance(p, str) else p for p in parts)
    return key(num, 2) + varint(len(body)) + body


def S(num, text):
    return L(num, text.encode("utf-8"))


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}

    def write(pack, name, inp, expect, model):
        v = {"name": name, "from": pack, "to": pack, "input": inp, "expect": expect, "model": model}
        sink.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1

    stamp = L(1, V(1, 1700000000), V(2, 250000000))

    # PoseInFrame: timestamp 1, frame_id 2, pose 3 { position 1 { x 1, y 2, z 3 },
    # orientation 2 { x 1, y 2, z 3, w 4 } }
    pif = stamp + S(2, "map") + L(3, L(1, D(1, 1.5), D(2, -2.25), D(3, 0.5)),
                                  L(2, D(1, 0.0), D(2, 0.0), D(3, 0.0), D(4, 1.0)))
    write("foxglove-proto-pose-in-frame", "01-pose-roundtrip", pif.hex(), pif.hex(),
          {"foxgloveprotoposeinframe.pose_in_frame_frame_id": "map",
           "foxgloveprotoposeinframe.pose_position_y": "-2.25",
           "foxgloveprotoposeinframe.pose_orientation_w": "1",
           "foxgloveprotoposeinframe.timestamp_nanos": "250000000"})

    # RawImage: timestamp 1, width 2 and height 3 (fixed32), encoding 4, step 5 (fixed32),
    # data 6 (bytes), frame_id 7: only timestamp, encoding and frame_id are written back.
    img_in = stamp + U32(2, 2) + U32(3, 1) + S(4, "mono8") + U32(5, 2) + L(6, b"\x10\x20") + S(7, "camera")
    img_out = stamp + S(4, "mono8") + S(7, "camera")
    write("foxglove-proto-raw-image", "01-dimensions-and-data-dropped", img_in.hex(), img_out.hex(),
          {"foxgloveprotorawimage.raw_image_encoding": "mono8",
           "foxgloveprotorawimage.raw_image_frame_id": "camera"})

    # Log: timestamp 1, level 2 (enum), message 3, name 4, file 5, line 6 (fixed32).
    log_in = stamp + V(2, 3) + S(3, "battery low") + S(4, "power") + S(5, "power.cpp") + U32(6, 42)
    log_out = stamp + V(2, 3) + S(3, "battery low") + S(4, "power") + S(5, "power.cpp")
    write("foxglove-proto-log", "01-line-number-dropped", log_in.hex(), log_out.hex(),
          {"foxgloveprotolog.log_level": "3", "foxgloveprotolog.log_message": "battery low"})

    # GeoJSON: geojson 1, a string the pack carries as it is.
    doc = '{"type":"Point","coordinates":[13.375,52.5]}'
    gj = S(1, doc)
    write("foxglove-proto-geojson", "01-document-carried-as-text", gj.hex(), gj.hex(),
          {"foxgloveprotogeojson.geo_json_geojson": doc})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-foxglove-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
