#!/usr/bin/env python3
"""Write the hand-derived conversion vectors of the vda5050-connection pack.

VDA 5050 (github.com/VDA5050/VDA5050, MIT) carries no geodetic position: its positions
are metres on a project map. What converts to other formats is the header: `timestamp`
(ISO 8601 UTC, bound to time_ms) and `serialNumber` (bound to uid). This script writes
one connection message to geojson and one GeoJSON Feature to a connection message, and
works out the expected output and the decoded values by the rules of spec/engine-spec.md
(0.1 geojson and its rulings, 0.5 json, iso8601_ms) and of the geojson pack. It reads no
pack.def and calls no goat-transformers engine. The generated round trips of the eight
packs are written by tools/gen/vda5050-run.sh.

Usage: python3 -I tools/gen/vda5050-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "VDA 5050 version 3.0.0, VDA5050_EN.md and json_schemas/connection.schema (commit f480c4020c91)"
SOURCE = "derived by tools/gen/vda5050-vectors.py from the schema and spec/engine-spec.md; no engine run"
DIR = "packs/vda5050-connection/vectors"


def iso_ms(text):
    """Epoch milliseconds UTC of YYYY-MM-DDTHH:MM:SS.fffZ."""
    d = datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp()) * 1000 + int(text[20:23])


def compact(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def vectors():
    out = []
    # a connection message, members in the schema's order (the pack's line order)
    ts = "2026-03-14T09:26:53.589Z"
    msg = {"headerId": 412, "timestamp": ts, "version": "3.0.0", "manufacturer": "ExampleRobotics",
           "serialNumber": "AMR-0042", "connectionState": "ONLINE"}
    ms = iso_ms(ts)
    model = {"time_ms": str(ms), "uid": "AMR-0042",
             "vda5050connection.header_id": "412", "vda5050connection.timestamp": ts,
             "vda5050connection.version": "3.0.0", "vda5050connection.manufacturer": "ExampleRobotics",
             "vda5050connection.serial_number": "AMR-0042", "vda5050connection.connection_state": "ONLINE"}
    # geojson (0.1): a Feature; no lat/lon, so geometry null; time_ms is properties.time_ms
    # (an int); uid is id. The raw keys of the vda5050connection module have no line there.
    expect = '{"type":"Feature","geometry":null,"properties":{"time_ms":%d},"id":"AMR-0042"}' % ms
    out.append(("01-to-geojson.json", {
        "name": "vda5050-connection-to-geojson",
        "from": "vda5050-connection", "to": "geojson",
        "input": compact(msg), "expect": expect, "model": model,
        "source": SOURCE, "reference": REF}))
    # from geojson: a Point Feature with time_ms and an id. The connection pack has no line for
    # lat and lon, so they are dropped; timestamp is written from time_ms by iso8601_ms, and
    # serialNumber from uid, in line order. No other member has a value.
    ms2 = iso_ms("2026-03-14T09:30:00.250Z")
    feat = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[8.6821,50.1109]},'
            '"properties":{"time_ms":%d},"id":"AMR-0042"}' % ms2)
    out.append(("02-point-feature.json", {
        "name": "geojson-to-vda5050-connection",
        "from": "geojson", "to": "vda5050-connection",
        "input": feat,
        "expect": '{"timestamp":"2026-03-14T09:30:00.250Z","serialNumber":"AMR-0042"}',
        "model": {"uid": "AMR-0042", "time_ms": str(ms2), "lat": "50.1109", "lon": "8.6821"},
        "source": SOURCE, "reference": REF}))
    return out


def dump(v):
    return json.dumps(v, indent=1, ensure_ascii=False) + "\n"


PACK = "vda5050-connection"
# Files of earlier runs that this script no longer writes (it removes only these).
STALE = ["%s/02-from-geojson.json" % DIR]


def build(out):
    """A vector lives under the pack that owns its input (`from`): one whose `from` is
    another pack goes to packs/<from>/vectors as to-<this pack>-<name>.json."""
    written = {}
    for rel in STALE:
        out.remove(rel)
    for fn, v in vectors():
        if v["from"] == PACK:
            rel = "%s/%s" % (DIR, fn)
        else:
            rel = "packs/%s/vectors/to-%s-%s" % (v["from"], PACK, fn)
        out.write(rel, dump(v))
        written[v["from"]] = written.get(v["from"], 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("vda5050-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
