#!/usr/bin/env python3
"""protobuf-3-vectors: the hand-written vectors of the Apollo, KUKSA.val and Tesla Fleet
Telemetry record packs (tools/gen/protobuf-3-run.sh), and three vectors from geojson into
the Apollo packs that carry a position.

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines. The expected output of each vector
is worked out from the rules of spec/engine-spec.md, not by running a conversion:

- protobuf output is canonical (0.3): only mapped fields, ascending field numbers inside every
  message and every item; a field no line maps is left out; a `const` line writes its value on
  every encode (0.6);
- the derivations of model/track.def (0.6) on values that derive exactly: sigma east 3 and north
  4 give `ce` 5, sigma up 1.5 gives `le` 1.5, velocity east 0 and north 5 give `course` 0 and
  `speed_ms` 5, and the other way course 0 and speed 5 give east 0 and north 5;
- geojson output (Canonicalisation, 0.5 "Canonical output"): members in the order of
  packs/geojson's `field` lines, `coordinates` as [lon, lat, alt], numbers in shortest form.

Usage: python3 -I tools/gen/protobuf-3-vectors.py [--out DIR] [--check]

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


def Z(num, n):                  # zig-zag varint (sint32, sint64)
    return key(num, 0) + varint((n << 1) ^ (n >> 63))


def D(num, x):
    return key(num, 1) + struct.pack("<d", x)


def F(num, x):
    return key(num, 5) + struct.pack("<f", x)


def L(num, *parts):
    body = b"".join(p.encode("utf-8") if isinstance(p, str) else p for p in parts)
    return key(num, 2) + varint(len(body)) + body


def S(num, text):
    return L(num, text.encode("utf-8"))


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

    # ---- apollo-gnss: position 4 (lon 1, lat 2, height 3), position_std_dev 5, linear_velocity 6
    gnss = (D(2, 1400000000.5) + L(4, D(1, 13.375), D(2, 52.5), D(3, 41.25))
            + L(5, D(1, 3.0), D(2, 4.0), D(3, 1.5)) + L(6, D(1, 0.0), D(2, 5.0), D(3, 0.0)) + V(8, 12))
    write("apollo-gnss", "01-fix-to-geojson", "apollo-gnss", "geojson", gnss.hex(),
          expect='{"type":"Feature","geometry":{"type":"Point","coordinates":[13.375,52.5,41.25]},'
                 '"properties":{"ce":5,"le":1.5,"course":0,"speed_ms":5}}',
          model={"@complete": True, "lat": "52.5", "lon": "13.375", "hae": "41.25", "ce": "5", "le": "1.5",
                 "course": "0", "speed_ms": "5"})
    write("apollo-gnss", "02-fix-roundtrip", "apollo-gnss", "apollo-gnss", gnss.hex(), expect=gnss.hex(),
          model={"track.sigma_north_m": "4", "track.vel_north_ms": "5", "apollognss.gnss_measurement_time": "1400000000.5",
                 "apollognss.gnss_num_sats": "12"})

    # ---- apollo-gnss-best-pose: latitude 5, longitude 6, height_msl 7, undulation 8, datum_id 9,
    # std devs 10 to 12, base_station_id 13 (bytes, no line)
    bp_in = (D(5, 52.5) + D(6, 13.375) + D(7, 34.0) + F(8, 47.25) + V(9, 61)
             + F(10, 4.0) + F(11, 3.0) + F(12, 1.5) + L(13, b"\x01\x02"))
    bp_out = D(5, 52.5) + D(6, 13.375) + D(7, 34.0) + F(8, 47.25) + V(9, 61) + F(10, 4.0) + F(11, 3.0) + F(12, 1.5)
    write("apollo-gnss-best-pose", "01-base-station-id-dropped", "apollo-gnss-best-pose", "apollo-gnss-best-pose",
          bp_in.hex(), expect=bp_out.hex(),
          model={"lat": "52.5", "lon": "13.375", "track.sigma_north_m": "4", "track.sigma_east_m": "3",
                 "apollognssbestpose.gnss_best_pose_height_msl": "34"})
    write("apollo-gnss-best-pose", "02-to-geojson-no-hae", "apollo-gnss-best-pose", "geojson", bp_in.hex(),
          expect='{"type":"Feature","geometry":{"type":"Point","coordinates":[13.375,52.5]},'
                 '"properties":{"ce":5,"le":1.5}}',
          model={"@complete": True, "ce": "5", "le": "1.5"})
    # The way in: latitude and longitude, and the datum the const line writes. The altitude of
    # the point has no line (height_msl is not hae).
    write("geojson", "97-to-apollo-gnss-best-pose-datum-written", "geojson", "apollo-gnss-best-pose",
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[13.375,52.5,41.25]},"properties":{}}',
          expect=(D(5, 52.5) + D(6, 13.375) + V(9, 61)).hex(),
          model={"lat": "52.5", "lon": "13.375", "hae": "41.25"})

    # ---- apollo-ins: from geojson; course 0 and speed 5 become the east and north velocity.
    write("geojson", "98-to-apollo-ins-position-and-velocity", "geojson", "apollo-ins",
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[13.375,52.5,41.25]},'
          '"properties":{"course":0,"speed_ms":5}}',
          expect=(L(4, D(1, 13.375), D(2, 52.5), D(3, 41.25)) + L(6, D(1, 0.0), D(2, 5.0))).hex(),
          model={"@complete": True, "track.vel_east_ms": "0", "track.vel_north_ms": "5"})

    # ---- kuksa-val-v2-get-value-response: data_point 1 (timestamp 1, value 2: double 18)
    gv = L(1, L(1, V(1, 1700000000), V(2, 5)), L(2, D(18, 12.5)))
    write("kuksa-val-v2-get-value-response", "01-double-value-roundtrip", "kuksa-val-v2-get-value-response",
          "kuksa-val-v2-get-value-response", gv.hex(), expect=gv.hex(),
          model={"kuksavalv2getvalueresponse.data_point_value_double": "12.5",
                 "kuksavalv2getvalueresponse.data_point_timestamp_seconds": "1700000000"})
    gi = L(1, L(2, Z(13, -40)))     # sint32 int32 13: -40 zig-zags to 79
    write("kuksa-val-v2-get-value-response", "02-negative-int32-zigzag", "kuksa-val-v2-get-value-response",
          "kuksa-val-v2-get-value-response", gi.hex(), expect=gi.hex(),
          model={"kuksavalv2getvalueresponse.data_point_value_int32": "-40"})

    # ---- tesla-fleet-alerts: alerts 1 (name 1, audiences 2 packed, started_at 3), created_at 2, vin 3
    al = (L(1, S(1, "ChargePortFault"), L(2, varint(1)), L(3, V(1, 1700000000)))
          + L(2, V(1, 1700000001)) + S(3, "TESTVIN0000000001"))
    write("tesla-fleet-alerts", "01-one-alert-roundtrip", "tesla-fleet-alerts", "tesla-fleet-alerts",
          al.hex(), expect=al.hex(),
          model={"teslafleetalerts.vehicle_alerts_vin": "TESTVIN0000000001",
                 "teslafleetalerts.vehicle_alerts_alerts.#": "1",
                 "teslafleetalerts.vehicle_alerts_alerts[0].teslafleetalerts.vehicle_alert_name": "ChargePortFault"})
    return written


def main(argv=None):
    return genio.vector_main("protobuf-3-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
