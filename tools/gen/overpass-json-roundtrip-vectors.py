#!/usr/bin/env python3
"""Write the three round-trip vectors 01-03 of packs/overpass-json, derived by hand.

Usage: python3 -I tools/gen/overpass-json-roundtrip-vectors.py [--check] <checkout>

Standard library only; no engine is imported or run. Each vector is written from values
chosen here. The expected output is laid out by hand from spec/engine-spec.md and
packs/overpass-json/pack.def:

- members are written in field-line order (0.5, "Canonical output"); a nested object
  (`osm3s`, `bounds`) stands at the position of the first line that addresses into it;
- `osm3s.timestamp_osm_base` is bound to `time_ms` (iso8601_s) and then to the raw key
  `overpass.timestamp_osm_base` (string). Decode fills both (ruling 16 of 0.5); encode
  writes the value of the earliest line whose key is present, the `time_ms` line, in the
  text of iso8601_s, `YYYY-MM-DDTHH:MM:SSZ` (engine-spec 0.26), the form the Output
  Formats page says osm_base always has;
- items of a group carry no residue (0.7, Decode), so an element's `tags` object is
  dropped; a `.` item of `nodes` is the array element itself;
- numbers are written as ruling 2f/2g of 0.11 states (shortest round-trip digits, plain
  notation); Python's float repr gives the same digits for the values used, checked below.

The epoch milliseconds of `time_ms` are computed with datetime (proleptic Gregorian, UTC),
which is ruling 3d of 0.11. With --check nothing is written; the exit status is 1 when a
file differs.
"""
import datetime
import json
import os
import sys

SOURCE = ("derived by hand in tools/gen/overpass-json-roundtrip-vectors.py from values chosen "
          "there, from spec/engine-spec.md (0.5 json wire and ruling 16, 0.7 groups, 0.11 "
          "rulings 2 and 3) and packs/overpass-json/pack.def; no engine run before the expect "
          "was written; ")

COPY = "Data: OpenStreetMap contributors, ODbL."
GEN = "Overpass API 0.7.62.7"


def epoch_ms(text):
    d = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp()) * 1000


def iso_s(ms):
    """iso8601_s encode (engine-spec 0.26): whole seconds, `Z`."""
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def num(x):
    """Ruling 2f text of a float, checked against Python's shortest repr."""
    r = repr(float(x))
    assert "e" not in r and "inf" not in r and "nan" not in r, r
    if r.endswith(".0"):
        r = r[:-2]
    return r


# --- 01: one node with lat/lon, metadata and tags ------------------------------------
T1 = "2026-11-20T08:15:02Z"
node = {"type": "node", "id": 900002, "lat": 50.2121617, "lon": 8.5867523,
        "timestamp": "2025-02-11T07:30:15Z", "version": 1, "changeset": 160002,
        "user": "mapper-b", "uid": 4402,
        "tags": {"highway": "bus_stop", "name": "Example Street"}}
in1 = {"version": 0.6, "generator": GEN,
       "osm3s": {"timestamp_osm_base": T1, "copyright": COPY},
       "elements": [node]}
node_out = {k: v for k, v in node.items() if k != "tags"}
out1 = {"version": 0.6, "generator": GEN,
        "osm3s": {"timestamp_osm_base": iso_s(epoch_ms(T1)), "copyright": COPY},
        "elements": [node_out]}
v1 = {
    "name": "node-with-tags-roundtrip",
    "from": "overpass-json", "to": "overpass-json",
    "input": dump(in1), "expect": dump(out1),
    "model": {
        "overpass.version": num(0.6),
        "overpass.generator": GEN,
        "time_ms": str(epoch_ms(T1)),
        "overpass.timestamp_osm_base": T1,
        "overpass.osm3s_copyright": COPY,
        "overpass.elements.#": "1",
        "overpass.elements[0].overpass.type": "node",
        "overpass.elements[0].overpass.id": "900002",
        "overpass.elements[0].overpass.lat": num(50.2121617),
        "overpass.elements[0].overpass.lon": num(8.5867523),
        "overpass.elements[0].overpass.timestamp": "2025-02-11T07:30:15Z",
        "overpass.elements[0].overpass.element_version": "1",
        "overpass.elements[0].overpass.changeset": "160002",
        "overpass.elements[0].overpass.user": "mapper-b",
        "overpass.elements[0].overpass.uid": "4402",
        "overpass.elements[0].overpass.nodes.#": "absent",
        "@absent": ["overpass.timestamp_areas_base", "overpass.remark", "lat", "lon"],
    },
    "source": SOURCE + "one node: the time of the data is written back as iso8601_s writes it "
              "(the time_ms line comes first on that locator); the tags object of an item is "
              "dropped (items carry no residue)",
}

# --- 02: one way with nodes, bounds and out-geom geometry; osm3s members out of order ----
T2 = "2026-11-19T23:59:58Z"
TA = "2026-11-19T23:40:01Z"
b = {"minlat": 50.2106234, "minlon": 8.5856189, "maxlat": 50.2121617, "maxlon": 8.5867523}
geom = [{"lat": 50.2106234, "lon": 8.5856189}, {"lat": 50.2121617, "lon": 8.5867523}]
way_in = {"type": "way", "id": 800001, "timestamp": "2024-09-03T12:00:00Z", "version": 4,
          "changeset": 155555, "user": "mapper-c", "uid": 4403,
          "bounds": b, "nodes": [900001, 900002], "geometry": geom,
          "tags": {"highway": "residential"}}
# input: copyright first, then the areas time, then the data time (not line order)
in2 = {"version": 0.6, "generator": GEN,
       "osm3s": {"copyright": COPY, "timestamp_areas_base": TA, "timestamp_osm_base": T2},
       "elements": [way_in]}
way_out = {k: v for k, v in way_in.items() if k != "tags"}
out2 = {"version": 0.6, "generator": GEN,
        "osm3s": {"timestamp_osm_base": iso_s(epoch_ms(T2)), "timestamp_areas_base": TA,
                  "copyright": COPY},
        "elements": [way_out]}
v2 = {
    "name": "way-out-geom-roundtrip",
    "from": "overpass-json", "to": "overpass-json",
    "input": dump(in2), "expect": dump(out2),
    "model": {
        "time_ms": str(epoch_ms(T2)),
        "overpass.timestamp_osm_base": T2,
        "overpass.timestamp_areas_base": TA,
        "overpass.elements.#": "1",
        "overpass.elements[0].overpass.type": "way",
        "overpass.elements[0].overpass.id": "800001",
        "overpass.elements[0].overpass.element_version": "4",
        "overpass.elements[0].overpass.bounds_minlat": num(b["minlat"]),
        "overpass.elements[0].overpass.bounds_minlon": num(b["minlon"]),
        "overpass.elements[0].overpass.bounds_maxlat": num(b["maxlat"]),
        "overpass.elements[0].overpass.bounds_maxlon": num(b["maxlon"]),
        "overpass.elements[0].overpass.nodes.#": "2",
        "overpass.elements[0].overpass.nodes[0].overpass.node_ref": "900001",
        "overpass.elements[0].overpass.nodes[1].overpass.node_ref": "900002",
        "overpass.elements[0].overpass.geometry.#": "2",
        "overpass.elements[0].overpass.geometry[0].overpass.lat": num(50.2106234),
        "overpass.elements[0].overpass.geometry[0].overpass.lon": num(8.5856189),
        "overpass.elements[0].overpass.geometry[1].overpass.lat": num(50.2121617),
        "overpass.elements[0].overpass.geometry[1].overpass.lon": num(8.5867523),
        "overpass.elements[0].overpass.members.#": "absent",
    },
    "source": SOURCE + "one way with out geom: bounds, the node ids and the geometry come "
              "back in line order; the osm3s members, given out of line order, are written in "
              "line order with the data time in iso8601_s form; tags dropped",
}

# --- 03: one relation with a node member and a way member (out geom), remark last ------
T3 = "2026-11-20T00:00:00Z"
REMARK = "runtime remark: example only"
rel_in = {"type": "relation", "id": 700001,
          "bounds": b,
          "members": [
              {"type": "node", "ref": 900001, "role": "stop", "lat": 50.2106234, "lon": 8.5856189},
              {"type": "way", "ref": 800001, "role": "", "geometry": geom}],
          "tags": {"type": "route", "route": "bus"}}
in3 = {"version": 0.6, "generator": GEN,
       "osm3s": {"timestamp_osm_base": T3, "copyright": COPY},
       "elements": [rel_in], "remark": REMARK}
rel_out = {k: v for k, v in rel_in.items() if k != "tags"}
out3 = {"version": 0.6, "generator": GEN,
        "osm3s": {"timestamp_osm_base": iso_s(epoch_ms(T3)), "copyright": COPY},
        "remark": REMARK, "elements": [rel_out]}
v3 = {
    "name": "relation-members-roundtrip",
    "from": "overpass-json", "to": "overpass-json",
    "input": dump(in3), "expect": dump(out3),
    "model": {
        "time_ms": str(epoch_ms(T3)),
        "overpass.timestamp_osm_base": T3,
        "overpass.remark": REMARK,
        "overpass.elements.#": "1",
        "overpass.elements[0].overpass.type": "relation",
        "overpass.elements[0].overpass.id": "700001",
        "overpass.elements[0].overpass.members.#": "2",
        "overpass.elements[0].overpass.members[0].overpass.type": "node",
        "overpass.elements[0].overpass.members[0].overpass.ref": "900001",
        "overpass.elements[0].overpass.members[0].overpass.role": "stop",
        "overpass.elements[0].overpass.members[0].overpass.lat": num(50.2106234),
        "overpass.elements[0].overpass.members[0].overpass.lon": num(8.5856189),
        "overpass.elements[0].overpass.members[0].overpass.geometry.#": "absent",
        "overpass.elements[0].overpass.members[1].overpass.type": "way",
        "overpass.elements[0].overpass.members[1].overpass.ref": "800001",
        "overpass.elements[0].overpass.members[1].overpass.role": "",
        "overpass.elements[0].overpass.members[1].overpass.geometry.#": "2",
        "overpass.elements[0].overpass.members[1].overpass.geometry[1].overpass.lat": num(50.2121617),
        "overpass.elements[0].overpass.members[1].overpass.geometry[1].overpass.lon": num(8.5867523),
    },
    "source": SOURCE + "one relation with out geom: a node member with its position and a way "
              "member with its geometry and an empty role (a string, so present); the remark, "
              "given after the elements, is written before them, in line order; a midnight "
              "time gets .000Z",
}

FILES = [("01-node-with-tags-roundtrip.json", v1),
         ("02-way-out-geom-roundtrip.json", v2),
         ("03-relation-members-roundtrip.json", v3)]


def main(argv):
    check = bool(argv) and argv[0] == "--check"
    if check:
        argv = argv[1:]
    if len(argv) != 1:
        sys.stderr.write("usage: overpass-json-roundtrip-vectors.py [--check] <checkout>\n")
        return 2
    d = os.path.join(argv[0], "packs", "overpass-json", "vectors")
    differs = 0
    for fn, v in FILES:
        text = json.dumps(v, indent=2, ensure_ascii=False) + "\n"
        path = os.path.join(d, fn)
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if old == text:
            continue
        if check:
            sys.stderr.write("differs: %s\n" % path)
            differs = 1
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
    return differs


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
