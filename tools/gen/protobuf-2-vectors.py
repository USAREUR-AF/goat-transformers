#!/usr/bin/env python3
"""The hand-written vectors of packs foxglove-location-fix, osm-pbf-blob-header, osm-pbf-header,
osm-pbf-primitive, mvt and tesla-fleet-telemetry, and one vector from geojson into
foxglove-location-fix.

Python standard library only; it imports no engine and no generator. Each message is written
here field by field with a protobuf encoder of a few lines. The expected output of each vector
is worked out from the rules of spec/engine-spec.md, not by running a conversion:

- protobuf output is canonical (0.3): only mapped fields, ascending field numbers inside every
  message and every item, a repeated number packed (0.7); so an input written that way with
  mapped fields only is its own expected output, and a field no line maps is left out;
- the derivations of model/track.def (0.6) on the velocity north 5, east 0: `speed_ms` = 5 and
  `course` = 0 exactly; and the other way, speed 5 and course 0 give east 5 * sin 0 = 0 and
  north 5 * cos 0 = 5 exactly;
- geojson output (Canonicalisation, 0.5 "Canonical output"): `geometry` null with no position,
  members in the order of packs/geojson's `field` lines, numbers in shortest form.

Run after tools/gen/protobuf-2-run.sh:

  python3 -I tools/gen/protobuf-2-vectors.py [--out DIR] [--check]

With --check nothing is written and the exit status is 1 when a committed vector
is not what this script writes.
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


def zz(n):                       # zig-zag of a 64-bit signed value
    return (n << 1) ^ (n >> 63)


def key(num, wt):
    return varint(num << 3 | wt)


def V(num, n):
    return key(num, 0) + varint(n)


def Z(num, n):
    return key(num, 0) + varint(zz(n))


def D(num, x):
    return key(num, 1) + struct.pack("<d", x)


def L(num, *parts):
    body = b"".join(p.encode("utf-8") if isinstance(p, str) else p for p in parts)
    return key(num, 2) + varint(len(body)) + body


def S(num, text):
    return L(num, text.encode("utf-8"))


def PACKED(num, values, signed=False):
    return L(num, b"".join(varint(zz(v) if signed else v) for v in values))


def write(pack, name, frm, to, inp, expect=None, error=None, model=None, context=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if context is not None:
        v["context"] = context
    if error is None:
        v["expect"] = expect
    else:
        v["expect_error"] = error
    if model:
        v["model"] = model
    SINK.write("packs/%s/vectors/%s.json" % (pack, name), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    WRITTEN[pack] = WRITTEN.get(pack, 0) + 1


SINK = None
WRITTEN = {}


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    global SINK
    SINK = sink
    WRITTEN.clear()
    # --- foxglove-location-fix -------------------------------------------------------
    # Fields in ascending order: latitude 1, longitude 2, altitude 3, timestamp 6, frame_id 7,
    # velocity 11.
    fix = (D(1, 52.5) + D(2, 13.375) + D(3, 34.5) + L(6, V(1, 1700000000), V(2, 500)) + S(7, "gnss")
           + L(11, D(1, 0.0), D(2, 5.0), D(3, 1.0)))
    write("foxglove-location-fix", "01-fix-roundtrip", "foxglove-location-fix", "foxglove-location-fix",
          fix.hex(), expect=fix.hex(),
          model={"lat": "52.5", "lon": "13.375", "track.vel_east_ms": "0", "track.vel_north_ms": "5",
                 "track.vel_up_ms": "1", "foxglove.location_fix_latitude": "52.5",
                 "foxglove.location_fix_altitude": "34.5", "foxglove.location_fix_frame_id": "gnss"})
    # The position reaches geojson as [lon, lat]; altitude is a raw key and does not. The velocity
    # arrives as the course and speed it derives.
    write("foxglove-location-fix", "02-fix-to-geojson", "foxglove-location-fix", "geojson",
          fix.hex(), expect='{"type":"Feature","geometry":{"type":"Point","coordinates":[13.375,52.5]},'
                            '"properties":{"course":0,"speed_ms":5}}',
          model={"@complete": True, "lat": "52.5", "lon": "13.375", "course": "0", "speed_ms": "5"})
    # The way in: the point's position becomes latitude and longitude; course and speed become the
    # east and north velocity; the id has no line.
    write("geojson", "93-to-foxglove-location-fix", "geojson", "foxglove-location-fix",
          '{"type":"Feature","geometry":{"type":"Point","coordinates":[13.375,52.5]},'
          '"properties":{"course":0,"speed_ms":5},"id":"fix-1"}',
          expect=(D(1, 52.5) + D(2, 13.375) + L(11, D(1, 0.0), D(2, 5.0))).hex(),
          model={"@complete": True, "track.vel_east_ms": "0", "track.vel_north_ms": "5"})

    # --- osm-pbf ------------------------------------------------------------------------
    # BlobHeader: type 1, indexdata 2 (bytes, no line), datasize 3.
    write("osm-pbf-blob-header", "01-indexdata-dropped", "osm-pbf-blob-header", "osm-pbf-blob-header",
          (S(1, "OSMData") + L(2, b"\x00\x01") + V(3, 1234)).hex(), expect=(S(1, "OSMData") + V(3, 1234)).hex(),
          model={"osmpbf.blob_header_type": "OSMData", "osmpbf.blob_header_datasize": "1234"})

    # HeaderBlock: bbox 1 (sint64 nanodegrees), required_features 4, writingprogram 16.
    hdr = (L(1, Z(1, 13000000000), Z(2, 13500000000), Z(3, 52750000000), Z(4, 52250000000))
           + S(4, "OsmSchema-V0.6") + S(4, "DenseNodes") + S(16, "example-writer"))
    write("osm-pbf-header", "01-header-roundtrip", "osm-pbf-header", "osm-pbf-header", hdr.hex(), expect=hdr.hex(),
          model={"osmpbf.bbox_left": "13000000000", "osmpbf.bbox_top": "52750000000",
                 "osmpbf.header_block_required_features.#": "2",
                 "osmpbf.header_block_required_features[1].osmpbf.header_block_required_features_item": "DenseNodes"})

    # PrimitiveBlock: stringtable 1 (bytes entries, no line), one group 2 with DenseNodes 2
    # (id 1, lat 8, lon 9: sint64, packed, each the difference from the node before), granularity 17.
    dense = L(2, PACKED(1, [100, 1], True), PACKED(8, [525000000, 10], True), PACKED(9, [133750000, -20], True))
    blk_in = L(1, L(1, b""), L(1, b"highway")) + L(2, dense) + V(17, 100)
    blk_out = L(2, dense) + V(17, 100)
    write("osm-pbf-primitive", "01-dense-nodes-stringtable-dropped", "osm-pbf-primitive", "osm-pbf-primitive",
          blk_in.hex(), expect=blk_out.hex(),
          model={"osmpbf.primitive_block_granularity": "100", "osmpbf.primitive_block_primitivegroup.#": "1"})

    # --- mvt -------------------------------------------------------------------------------
    # Layer: name 1, features 2, keys 3, values 4, extent 5, version 15. Feature: id 1, tags 2
    # (packed), type 3 (2 = LINESTRING), geometry 4 (packed: MoveTo 1 (9), 25, 17 zig-zagged;
    # LineTo 1 (10), 1, 2 zig-zagged).
    feature = L(2, V(1, 1), PACKED(2, [0, 0]), V(3, 2), PACKED(4, [9, 50, 34, 10, 2, 4]))
    layer = L(3, S(1, "roads"), feature, S(3, "class"), L(4, S(1, "primary")), V(5, 4096), V(15, 2))
    write("mvt", "01-one-line-feature-roundtrip", "mvt", "mvt", layer.hex(), expect=layer.hex(),
          model={"mvt.tile_layers.#": "1", "mvt.tile_layers[0].mvt.layer_name": "roads",
                 "mvt.tile_layers[0].mvt.layer_features[0].mvt.feature_geometry.#": "6"})

    # --- tesla-fleet-telemetry ---------------------------------------------------------------
    # Payload: data 1 (Datum: key 1, value 2), created_at 2, vin 3. Field 21 is Location, 64
    # VehicleName; Value.location_value 7 (latitude 1, longitude 2), string_value 1.
    pay = (L(1, V(1, 21), L(2, L(7, D(1, 37.5), D(2, -122.25))))
           + L(1, V(1, 64), L(2, S(1, "Test car")))
           + L(2, V(1, 1700000000), V(2, 250000000)) + S(3, "TESTVIN0000000001"))
    write("tesla-fleet-telemetry", "01-location-and-name-roundtrip", "tesla-fleet-telemetry", "tesla-fleet-telemetry",
          pay.hex(), expect=pay.hex(),
          model={"teslafleet.payload_vin": "TESTVIN0000000001", "teslafleet.payload_data.#": "2",
                 "teslafleet.payload_data[0].teslafleet.datum_key": "21",
                 "teslafleet.payload_data[0].teslafleet.datum_value_location_value_latitude": "37.5",
                 "teslafleet.payload_data[1].teslafleet.datum_value_string_value": "Test car"})
    return dict(WRITTEN)


def main(argv=None):
    return genio.vector_main("protobuf-2-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
