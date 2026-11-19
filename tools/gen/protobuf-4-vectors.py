#!/usr/bin/env python3
"""protobuf-4-vectors: the hand-written vectors of the Meshtastic payload, OTLP, gNMI, OpenXC,
geobuf and Waymo Open Dataset packs (tools/gen/protobuf-4-run.sh), and one vector from geojson
into meshtastic-user.

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines; no message or value is taken from a
dataset, a capture or a schema file's comments. The expected output of each vector is worked out
from the rules of spec/engine-spec.md, not by running a conversion:

- protobuf output is canonical (0.3): only mapped fields, ascending field numbers inside every
  message and every item; a field no line maps (here `bytes`, `fixed32`, `fixed64`, `sfixed32` and
  map entries) is left out; a repeated number is written packed (0.7);
- geojson output (Canonicalisation, 0.5 "Canonical output"): `geometry` null with no position,
  members in the order of packs/geojson's `field` lines inside the layout `type`, `geometry`,
  `properties`, `id`.

Usage: python3 -I tools/gen/protobuf-4-vectors.py [--out DIR] [--check]

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


def zz(n):
    return (n << 1) ^ (n >> 63)


def key(num, wt):
    return varint(num << 3 | wt)


def V(num, n):
    return key(num, 0) + varint(n)


def Z(num, n):
    return key(num, 0) + varint(zz(n))


def D(num, x):
    return key(num, 1) + struct.pack("<d", x)


def F(num, x):
    return key(num, 5) + struct.pack("<f", x)


def X32(num, n, signed=False):     # fixed32 / sfixed32
    return key(num, 5) + struct.pack("<i" if signed else "<I", n)


def X64(num, n):                   # fixed64
    return key(num, 1) + struct.pack("<Q", n)


def L(num, *parts):
    body = b"".join(p.encode("utf-8") if isinstance(p, str) else p for p in parts)
    return key(num, 2) + varint(len(body)) + body


def S(num, text):
    return L(num, text.encode("utf-8"))


def PACKED(num, values, signed=False, double=False):
    if double:
        return L(num, b"".join(struct.pack("<d", v) for v in values))
    return L(num, b"".join(varint(zz(v) if signed else v) for v in values))


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written = {}

    def write(pack, name, frm, to, inp, expect=None, error=None, model=None):
        v = {"name": name, "from": frm, "to": to, "input": inp}
        if error is None:
            v["expect"] = expect
        else:
            v["expect_error"] = error
        if model:
            v["model"] = model
        sink.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[pack] = written.get(pack, 0) + 1

    # ---- meshtastic-user: id 1, long_name 2, short_name 3, macaddr 4 (bytes, no line), hw_model 5
    user_in = S(1, "!a1b2c3d4") + S(2, "Base Camp") + S(3, "BC") + L(4, b"\x01\x02\x03\x04\x05\x06") + V(5, 43)
    user_out = S(1, "!a1b2c3d4") + S(2, "Base Camp") + S(3, "BC") + V(5, 43)
    write("meshtastic-user", "01-macaddr-dropped", "meshtastic-user", "meshtastic-user", user_in.hex(),
          expect=user_out.hex(), model={"uid": "!a1b2c3d4", "callsign": "Base Camp", "meshtasticuser.user_short_name": "BC"})
    write("meshtastic-user", "02-to-geojson-no-geometry", "meshtastic-user", "geojson", user_in.hex(),
          expect='{"type":"Feature","geometry":null,"properties":{"callsign":"Base Camp"},"id":"!a1b2c3d4"}')
    write("geojson", "130-to-meshtastic-user", "geojson", "meshtastic-user",
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[13.375,52.5]},'
          '"properties":{"callsign":"Base Camp"},"id":"!a1b2c3d4"}',
          expect=(S(1, "!a1b2c3d4") + S(2, "Base Camp")).hex())

    # ---- meshtastic-position: latitude_i 1 and longitude_i 2 (sfixed32), altitude 3, time 4
    # (fixed32), altitude_hae 9 (sint32), ground_speed 15: the fixed-width fields are not written.
    pos_in = (X32(1, 525000000, True) + X32(2, 133750000, True) + V(3, 34) + X32(4, 1700000000)
              + Z(9, 81) + V(15, 5))
    pos_out = V(3, 34) + Z(9, 81) + V(15, 5)
    write("meshtastic-position", "01-fixed-width-fields-dropped", "meshtastic-position", "meshtastic-position",
          pos_in.hex(), expect=pos_out.hex(),
          model={"meshtasticposition.position_altitude": "34", "meshtasticposition.position_altitude_hae": "81"})

    # ---- meshtastic-routing: one layout; error_reason 3 (enum).
    rt = V(3, 8)
    write("meshtastic-routing", "01-error-reason-roundtrip", "meshtastic-routing", "meshtastic-routing",
          rt.hex(), expect=rt.hex(), model={"meshtasticrouting.routing_error_reason": "8"})

    # ---- otlp-export-logs-request: resource_logs 1 { scope_logs 2 { log_records 2 {
    # time_unix_nano 1 (fixed64, no line), severity_number 2, body 5 { string_value 1 } } } }
    rec_in = L(2, X64(1, 1700000000000000000), V(2, 9), L(5, S(1, "service started")))
    rec_out = L(2, V(2, 9), L(5, S(1, "service started")))
    logs_in = L(1, L(2, rec_in))
    logs_out = L(1, L(2, rec_out))
    write("otlp-export-logs-request", "01-time-unix-nano-dropped", "otlp-export-logs-request",
          "otlp-export-logs-request", logs_in.hex(), expect=logs_out.hex(),
          model={"otlpexportlogsrequest.export_logs_service_request_resource_logs.#": "1"})

    # ---- gnmi-get-request: prefix 1 { origin 2 }, path 2 { elem 3 { name 1, key 2 (map, no line) } },
    # type 3, encoding 5.
    elem_in = L(3, S(1, "interfaces"), L(2, S(1, "name"), S(2, "eth0")))
    elem_out = L(3, S(1, "interfaces"))
    get_in = L(1, S(2, "openconfig")) + L(2, elem_in) + V(3, 2) + V(5, 4)
    get_out = L(1, S(2, "openconfig")) + L(2, elem_out) + V(3, 2) + V(5, 4)
    write("gnmi-get-request", "01-path-key-map-dropped", "gnmi-get-request", "gnmi-get-request",
          get_in.hex(), expect=get_out.hex(),
          model={"gnmigetrequest.prefix_origin": "openconfig", "gnmigetrequest.get_request_type": "2",
                 "gnmigetrequest.get_request_path.#": "1"})

    # ---- openxc-vehicle-message: type 1 (2 = SIMPLE), simple_message 3 { name 1, value 2
    # { type 1 (2 = NUM), numeric_value 3 } }, timestamp 7.
    ox = V(1, 2) + L(3, S(1, "vehicle_speed"), L(2, V(1, 2), D(3, 42.5))) + V(7, 1700000000000)
    write("openxc-vehicle-message", "01-simple-numeric-roundtrip", "openxc-vehicle-message",
          "openxc-vehicle-message", ox.hex(), expect=ox.hex(),
          model={"openxc.simple_message_name": "vehicle_speed", "openxc.simple_message_value_numeric_value": "42.5"})

    # ---- geobuf: keys 1, dimensions 2, precision 3, geometry 6 { type 1 (0 = POINT), coords 3
    # (packed sint64) }: kind geometry.
    gb = S(1, "name") + V(2, 2) + V(3, 6) + L(6, V(1, 0), PACKED(3, [13375000, 52500000], signed=True))
    write("geobuf", "01-point-geometry-roundtrip", "geobuf", "geobuf", gb.hex(), expect=gb.hex(),
          model={"@kind": "geometry", "geobuf.precision": "6", "geobuf.geometry_coords.#": "2",
                 "geobuf.geometry_coords[1].geobuf.geometry_coords_item": "52500000"})

    # ---- waymo-scenario: timestamps_seconds 1 (packed double), tracks 2 { id 1, object_type 2,
    # states 3 { center_x 2, center_y 3, valid 11 } }, scenario_id 5, current_time_index 10.
    track = L(2, V(1, 7), V(2, 1), L(3, D(2, 1.5), D(3, -2.25), V(11, 1)), L(3, D(2, 2.5), D(3, -2.0), V(11, 1)))
    sc = PACKED(1, [0.0, 0.1], double=True) + track + S(5, "made-up-scenario") + V(10, 1)
    write("waymo-scenario", "01-one-track-two-states-roundtrip", "waymo-scenario", "waymo-scenario",
          sc.hex(), expect=sc.hex(),
          model={"waymoscenario.scenario_scenario_id": "made-up-scenario", "waymoscenario.scenario_tracks.#": "1",
                 "waymoscenario.scenario_tracks[0].waymoscenario.track_states.#": "2"})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-4-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
