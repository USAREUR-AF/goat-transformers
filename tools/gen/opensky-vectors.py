#!/usr/bin/env python3
"""Write the vectors of the opensky-states and opensky-track packs.

The packs read two responses of the OpenSky Network REST API, as its documentation
describes them (github.com/openskynetwork/opensky-api commit 98fecf74,
docs/free/states-response.rst and docs/free/track-response.rst). This script holds its
own copy of the member lists of each pack, in the order the pack lists them, builds every
message from values written for these vectors (none is taken from the documentation or
from the API), and works out the canonical output and the decoded values by the rules of
spec/engine-spec.md (0.5 json wire, 0.15 iscale) and of the geojson pack. It reads no
pack.def and calls no goat-transformers engine.

Canonical json (0.5): mapped members in line order, then residue scalars of objects in
input order; arrays, and anything inside them, are not carried. Numbers are written as
the shortest text that reads back (ruling 3 of 0.1.1); iscale:1000 decodes seconds to
milliseconds exactly and encodes milliseconds back to seconds as an exact decimal.

Usage: python3 -I tools/gen/opensky-vectors.py [--out DIR] [--check]
"""
import decimal
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = ("OpenSky Network REST API documentation, github.com/openskynetwork/opensky-api commit "
       "98fecf7438dfbd23c4a26c8a7286a25b805eb2d3, docs/free/%s")
SOURCE = "derived by tools/gen/opensky-vectors.py from the documentation's tables and spec/engine-spec.md; no engine run"

# (member, transform, model key), in pack line order. i int, s string, k iscale:1000
STATES = [("time", "k", "time_ms")]
TRACK = [("icao24", "s", "uid"), ("startTime", "i", "opensky.start_time"),
         ("endTime", "i", "opensky.end_time"), ("callsign", "s", "callsign")]


def js(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def iscale_dec(n, factor):
    """iscale decode: the number's text as an exact decimal, times factor, rounded."""
    r = decimal.Decimal(json.dumps(n)) * factor
    return int(r.to_integral_value(rounding=decimal.ROUND_HALF_EVEN))


def iscale_enc(x, factor):
    """iscale encode: x / factor exactly, as a JSON number."""
    q = decimal.Decimal(x) / decimal.Decimal(factor)
    return int(q) if q == q.to_integral_value() else float(q)


def model_text(v):
    return str(v)


def decode(obj, lines):
    """model of a json object under lines; None for a wrong JSON type."""
    m = {}
    for member, tr, key in lines:
        if member not in obj or obj[member] is None:
            continue
        v = obj[member]
        if tr == "s":
            if not isinstance(v, str):
                return None
            m[key] = v
        elif tr == "i":
            if isinstance(v, bool) or not isinstance(v, int):
                return None
            m[key] = model_text(v)
        elif tr == "k":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return None
            m[key] = model_text(iscale_dec(v, 1000))
    return m


def canon(obj, lines):
    """mapped members in line order, then scalar residue in input order (no arrays)."""
    mapped = [member for member, _, _ in lines]
    out = {}
    for member in mapped:
        if member in obj and obj[member] is not None:
            out[member] = obj[member]
    for k, v in obj.items():
        if k in mapped or v is None or isinstance(v, (list, dict)):
            continue
        out[k] = v
    return js(out)


def vec(name, frm, to, inp, expect=None, model=None, error=None, note="", doc="states-response.rst"):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
        if model is not None:
            v["model"] = model
    v["source"] = SOURCE
    v["reference"] = (REF % doc) + ("; " + note if note else "")
    return v


def build_vectors():
    S, T, X = {}, {}, {}
    # states: time and two state vectors; the vectors are arrays, so they are not carried
    states = {"time": 1700000010, "states": [
        ["a1b2c3", "TEST123 ", "Testland", 1700000009, 1700000010, 8.25, 47.5, 10972.8, False,
         231.5, 87.25, -2.5, None, 11010.9, "7421", False, 0, 3],
        ["0f0e0d", None, "Testland", None, 1700000004, None, None, None, True,
         0, None, None, None, None, None, False, 0]]}
    S["01-states-roundtrip"] = vec("states-roundtrip", "opensky-states", "opensky-states", js(states),
        canon(states, STATES), decode(states, STATES),
        note="time, seconds, is time_ms through iscale:1000; the state vectors are arrays of arrays and are not carried (0.5 json residue)")
    only = {"time": 1700000020}
    S["02-time-only-roundtrip"] = vec("time-only-roundtrip", "opensky-states", "opensky-states", js(only),
        canon(only, STATES), decode(only, STATES), note="a response with no state vectors (states null in the API) reads as time alone")
    nulls = {"time": 1700000030, "states": None}
    S["03-states-null-roundtrip"] = vec("states-null-roundtrip", "opensky-states", "opensky-states", js(nulls),
        canon(nulls, STATES), decode(nulls, STATES), note="a null member is absent (0.5 json)")
    bad = {"time": "1700000010", "states": []}
    S["04-time-as-text"] = vec("time-as-text", "opensky-states", "opensky-states", js(bad),
        error="transform-decode", note="time is an integer; a JSON string under iscale is a transform failure (0.15)")
    # geojson to states: the geojson pack's time_ms is milliseconds; iscale encode divides by 1000
    feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [8.25, 47.5]},
            "properties": {"time_ms": 1700000040000}, "id": "a1b2c3"}
    X["to-opensky-states-from-geojson"] = vec("geojson-to-opensky-states", "geojson", "opensky-states", js(feat),
        js({"time": iscale_enc(1700000040000, 1000)}),
        note="geojson properties.time_ms is time_ms (int, ms); opensky-states writes it as whole seconds; the position has no place in the pack")

    # track: identifier, times, callsign; path (array of arrays) is not carried
    trk = {"icao24": "a1b2c3", "callsign": "TEST123 ", "startTime": 1700000000, "endTime": 1700003600,
           "path": [[1700000000, 47.5, 8.25, 10972.8, 87.25, False],
                    [1700003600, 48.125, 11.5, None, 90.0, False]]}
    T["01-track-roundtrip"] = vec("track-roundtrip", "opensky-track", "opensky-track", js(trk),
        canon(trk, TRACK), decode(trk, TRACK), doc="track-response.rst",
        note="members in the pack's line order; path is an array of arrays and is not carried")
    extra = {"endTime": 1700000600, "startTime": 1700000000, "icao24": "0f0e0d", "callsign": None,
             "note": "kept"}
    T["02-track-residue"] = vec("track-residue", "opensky-track", "opensky-track", js(extra),
        canon(extra, TRACK), decode(extra, TRACK), doc="track-response.rst",
        note="callsign null is absent; a scalar member no line maps is residue, written after the mapped members")
    badt = {"icao24": 11259375, "startTime": 1700000000, "endTime": 1700000600}
    T["03-icao24-as-number"] = vec("icao24-as-number", "opensky-track", "opensky-track", js(badt),
        error="transform-decode", doc="track-response.rst",
        note="icao24 is a hex string; a JSON number under string is a transform failure (ruling 9 of 0.1.1)")
    feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [8.25, 47.5]},
            "properties": {"callsign": "TEST123"}, "id": "a1b2c3"}
    X["to-opensky-track-from-geojson"] = vec("geojson-to-opensky-track", "geojson", "opensky-track", js(feat),
        js({"icao24": "a1b2c3", "callsign": "TEST123"}), doc="track-response.rst",
        note="geojson id is uid, written as icao24; properties.callsign is callsign; the position has no place in the pack")
    return S, T, X


def build(out):
    S, T, X = build_vectors()
    for fn, v in S.items():
        out.write("packs/opensky-states/vectors/%s.json" % fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    for fn, v in T.items():
        out.write("packs/opensky-track/vectors/%s.json" % fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    # a vector lives under the pack its input comes from (`from`)
    for fn, v in X.items():
        out.write("packs/%s/vectors/%s.json" % (v["from"], fn), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    return {"opensky-states": len(S), "opensky-track": len(T), "geojson": len(X)}


def main(argv=None):
    return genio.vector_main("opensky-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
