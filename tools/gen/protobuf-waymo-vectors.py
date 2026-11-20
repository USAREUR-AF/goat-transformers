#!/usr/bin/env python3
"""protobuf-waymo-vectors: hand-written vectors of the waymo-box3d and waymo-velocity packs
(tools/gen/waymo-run.sh).

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines; the values are made up and no
value of the Waymo Open Dataset is used. The expected output is worked out from
spec/engine-spec.md: protobuf output is canonical (0.3), only mapped fields in ascending
field-number order inside every message, so an input written that way with mapped fields only
is its own expected output; a `float` field holds the single nearest to its value (0.3).

Usage: python3 -I tools/gen/protobuf-waymo-vectors.py [--out DIR] [--check]

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


def D(num, x):
    return key(num, 1) + struct.pack("<d", x)


def F(num, x):
    return key(num, 5) + struct.pack("<f", x)


def L(num, *parts):
    body = b"".join(parts)
    return key(num, 2) + varint(len(body)) + body


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}

    def write(pack, name, inp, model):
        v = {"name": name, "from": pack, "to": pack, "input": inp, "expect": inp, "model": model}
        sink.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1

    # Box3d: center 1 { x 1, y 2, z 3 }, size 2 { x 1, y 2, z 3 }, heading 3; metres and radians in
    # the frame of the box's owner.
    box = L(1, D(1, 12.5), D(2, -3.25), D(3, 0.875)) + L(2, D(1, 4.5), D(2, 1.875), D(3, 1.5)) + D(3, 1.5625)
    write("waymo-box3d", "01-box-roundtrip", box.hex(),
          {"waymobox3d.center_x": "12.5", "waymobox3d.size_y": "1.875", "waymobox3d.box3d_heading": "1.5625"})

    # Velocity: v_x 1, v_y 2, v_z 3 (float), w_x 4, w_y 5, w_z 6 (double).
    vel = F(1, 7.25) + F(2, -0.5) + F(3, 0.125) + D(4, 0.0) + D(5, 0.0) + D(6, 0.0625)
    write("waymo-velocity", "01-velocity-roundtrip", vel.hex(),
          {"waymovelocity.velocity_v_x": "7.25", "waymovelocity.velocity_v_y": "-0.5",
           "waymovelocity.velocity_w_z": "0.0625"})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-waymo-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
