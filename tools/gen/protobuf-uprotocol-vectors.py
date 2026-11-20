#!/usr/bin/env python3
"""protobuf-uprotocol-vectors: hand-written vectors of the uprotocol-v1-umessage and
uprotocol-v1-uuri packs (tools/gen/uprotocol-run.sh).

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines; the values are made up. The
expected output is worked out from spec/engine-spec.md: protobuf output is canonical (0.3),
only mapped fields in ascending field-number order inside every message, so an input written
that way with mapped fields only is its own expected output, and a field no line maps (here the
`fixed64` halves of a `UUID` and the `bytes` payload) is left out.

Usage: python3 -I tools/gen/protobuf-uprotocol-vectors.py [--out DIR] [--check]

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


def X64(num, n):
    return key(num, 1) + struct.pack("<Q", n)


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

    # UUri: authority_name 1, ue_id 2, ue_version_major 3, resource_id 4.
    def uuri(num, authority, ue, major, resource):
        return L(num, S(1, authority), V(2, ue), V(3, major), V(4, resource))

    plain = S(1, "vehicle-1") + V(2, 0x10AB) + V(3, 1) + V(4, 0x8001)
    write("uprotocol-v1-uuri", "01-topic-uri-roundtrip", plain.hex(), plain.hex(),
          {"uprotocolv1uuri.uuri_authority_name": "vehicle-1", "uprotocolv1uuri.uuri_ue_id": "4267",
           "uprotocolv1uuri.uuri_resource_id": "32769"})

    # UMessage: attributes 1 { id 1 (UUID: msb 1, lsb 2, fixed64), type 2 (1 = publish),
    # source 3 (UUri), priority 5, ttl 6 }, payload 2 (bytes).
    uuid = L(1, X64(1, 0x0190A1B2C3D47000), X64(2, 0x8000000000000001))
    attrs_in = uuid + V(2, 1) + uuri(3, "vehicle-1", 0x10AB, 1, 0x8001) + V(5, 2) + V(6, 1000)
    attrs_out = V(2, 1) + uuri(3, "vehicle-1", 0x10AB, 1, 0x8001) + V(5, 2) + V(6, 1000)
    msg_in = L(1, attrs_in) + L(2, b"\x0a\x02hi")
    msg_out = L(1, attrs_out)
    write("uprotocol-v1-umessage", "01-uuid-and-payload-dropped", msg_in.hex(), msg_out.hex(),
          {"uprotocolv1umessage.attributes_type": "1",
           "uprotocolv1umessage.attributes_source_authority_name": "vehicle-1",
           "uprotocolv1umessage.attributes_ttl": "1000"})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-uprotocol-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
