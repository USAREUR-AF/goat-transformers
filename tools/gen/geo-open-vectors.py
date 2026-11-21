#!/usr/bin/env python3
"""geo-open-vectors: write the vectors of the overpass-json pack.

Python 3 standard library only; imports no engine and reads no pack.def. The response layout is
this program's own restatement of the OSM JSON page of the OpenStreetMap Wiki (revision 2907469)
and of the JSON section of the Overpass API output formats page.

Inputs: responses built here from values chosen here, with element ids, users and coordinates of
this program's own; no response is taken from a document.

`expect` is worked out from the rules of spec/engine-spec.md for the `json` wire: members are
written in the order of the pack's lines, a nested object at the place of its first line; a list
item has no residue (engine-spec 0.7), so an element's `tags` object, which no line maps, is not
written back; numbers in the shortest form that reads back to the same value; no whitespace. The
conversion to geojson follows the geojson pack: a Feature with a null geometry and `time_ms` in
`properties`. `model` holds the values decoded.

Usage: python3 -I tools/gen/geo-open-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import calendar
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/geo-open-vectors.py from values chosen there; layout restated from the "
          "OpenStreetMap Wiki page OSM JSON and the Overpass API output formats page; expect derived "
          "there, no engine run")
COPY = "The data included in this document is from www.openstreetmap.org. The data is made available under ODbL."


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def ms(text):
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")) * 1000


def vec(name, inp, expect=None, to="overpass-json", model=None, error=None, what=""):
    v = {"name": name, "from": "overpass-json", "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE + "; " + what
    return v


def vectors():
    out = []
    base = "2026-11-20T08:15:02Z"
    head = {"version": 0.6, "generator": "Overpass API 0.7.62.7", "osm3s": {"timestamp_osm_base": base, "copyright": COPY}}
    nodes = dict(head, elements=[
        {"type": "node", "id": 900001, "lat": 50.2106234, "lon": 8.5856189, "timestamp": "2024-05-01T10:00:00Z",
         "version": 3, "changeset": 150001, "user": "mapper-a", "uid": 4401},
        {"type": "node", "id": 900002, "lat": 50.2121617, "lon": 8.5867523, "timestamp": "2025-02-11T07:30:15Z",
         "version": 1, "changeset": 160002, "user": "mapper-b", "uid": 4402,
         "tags": {"highway": "bus_stop", "name": "Example Street"}}])
    inp = dumps(nodes)
    # 01-03 (round trips of two nodes with metadata, of a way and a relation with out geom, and of a
    # response with the area timestamp and a remark) were dropped: their expectations wrote the
    # timestamp_osm_base text as the input had it, where ruling 16 of engine-spec 0.5 writes the value
    # of the earliest line that maps it, the time_ms line; an engine found the error, so rule 16 of the
    # brief drops the vectors rather than refit them
    out.append(("04-overpass-json-to-geojson.json", vec(
        "overpass-json-to-geojson", inp, dumps({"type": "Feature", "geometry": None, "properties": {"time_ms": ms(base)}}),
        to="geojson", what="the first response to geojson: the time of the data carries; the elements are a list "
                           "geojson does not map")))
    api = {"version": "0.6", "generator": "CGImap 0.9.3", "copyright": "OpenStreetMap and contributors",
           "elements": [{"type": "node", "id": 900001, "lat": 50.2106234, "lon": 8.5856189}]}
    out.append(("05-osm-api-string-version-is-transform-decode.json", vec(
        "osm-api-string-version-is-transform-decode", dumps(api), error="transform-decode",
        what="an OSM API JSON response, whose version is a string where Overpass writes a number")))
    return out


def build_files(out):
    for fname, v in vectors():
        out.write("packs/overpass-json/vectors/%s" % fname, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    return {"overpass-json": len(vectors())}


def main(argv=None):
    return genio.vector_main("geo-open-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
