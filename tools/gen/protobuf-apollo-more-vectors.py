#!/usr/bin/env python3
"""protobuf-apollo-more-vectors: hand-written vectors of three packs of the second Apollo sweep
(tools/gen/apollo-more-run.sh): apollo-gnss-status, apollo-conti-radar and apollo-zhongyun.

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines; the values are made up. The expected
output is worked out from spec/engine-spec.md: protobuf output is canonical (0.3), only mapped
fields in ascending field-number order inside every message and every item (0.7), so an input
written that way with mapped fields only is its own expected output, and a field no line maps is
left out.

Usage: python3 -I tools/gen/protobuf-apollo-more-vectors.py [--out DIR] [--check]

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

    def write(pack, name, inp, expect, model):
        v = {"name": name, "from": pack, "to": pack, "input": inp, "expect": expect, "model": model}
        sink.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1

    # apollo-gnss-status: header 1 { timestamp_sec 1, module_name 2 }, solution_completed 2,
    # solution_status 3, position_type 4, num_sats 5.
    gs = L(1, D(1, 1700000000.25), S(2, "gnss")) + V(2, 1) + V(3, 0) + V(4, 50) + V(5, 17)
    write("apollo-gnss-status", "01-status-roundtrip", gs.hex(), gs.hex(),
          {"apollognssstatus.header_module_name": "gnss", "apollognssstatus.gnss_status_num_sats": "17",
           "apollognssstatus.gnss_status_position_type": "50"})

    # apollo-conti-radar: header 1 { frame_id 9 }, contiobs 2 (two items, each with only its own
    # header 1 { sequence_num 3 }), radar_state 3 { max_distance 1 }.
    item1 = L(2, L(1, V(3, 1)))
    item2 = L(2, L(1, V(3, 2)))
    cr = L(1, S(9, "radar_front")) + item1 + item2 + L(3, V(1, 250))
    write("apollo-conti-radar", "01-two-obstacles-roundtrip", cr.hex(), cr.hex(),
          {"apollocontiradar.header_frame_id": "radar_front", "apollocontiradar.radar_state_max_distance": "250",
           "apollocontiradar.conti_radar_contiobs.#": "2",
           "apollocontiradar.conti_radar_contiobs[1].apollocontiradar.conti_radar_obs_header_sequence_num": "2"})

    # apollo-zhongyun: gear_control_a1 1 { gear_state_target 1, gear_enable_control 2 },
    # torque_control_a3 2 { driven_torque 1 }, steering_control_a2 3 { steering_target 1 }.
    zy = L(1, V(1, 4), V(2, 1)) + L(2, D(1, 12.5)) + L(3, D(1, -3.75))
    write("apollo-zhongyun", "01-controls-roundtrip", zy.hex(), zy.hex(),
          {"apollozhongyun.gear_control_a1_gear_state_target": "4",
           "apollozhongyun.torque_control_a3_driven_torque": "12.5",
           "apollozhongyun.steering_control_a2_steering_target": "-3.75"})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-apollo-more-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
