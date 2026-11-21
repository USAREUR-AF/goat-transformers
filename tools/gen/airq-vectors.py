#!/usr/bin/env python3
"""Write the vectors of the defra-ukair-timeseries and defra-ukair-data packs.

Every response is built here from values written for these vectors in the shape of the UK-AIR SOS
REST API (52 North Timeseries API v1); no live response is copied. This script holds its own copy
of the members each pack maps, in line order, and works out the canonical output by the rules of
spec/engine-spec.md: 0.5 (json wire: mapped members in line order, a nested object at the position
of the first line that addresses into it, then scalar residue in input order at any depth of
nested objects; arrays and null are not carried), 0.7 (groups: items carry no residue; an empty
list writes []) and ruling 3 of 0.1.1 (number text). It reads no pack.def and calls no
goat-transformers engine.

Usage: python3 -I tools/gen/airq-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/airq-vectors.py from responses written for it and spec/engine-spec.md; no engine run"
REF = "UK-AIR SOS REST API (uk-air.defra.gov.uk/sos-ukair/api/v1), members as 52North/sensorweb-server-helgoland names them"


def F(path, key, tr):
    return ("f", tuple(path.split(".")) if path != "." else (), key, tr)


def G(path, lst, body):
    return ("g", tuple(path.split(".")), lst, body)


D = "defraukair."
SERIES = [F(m, D + k, t) for m, k, t in (
    ("id", "id", "string"), ("label", "label", "string"), ("uom", "uom", "string"),
    ("station.properties.id", "station_id", "int"), ("station.properties.label", "station_label", "string"),
    ("firstValue.timestamp", "first_time", "int"), ("firstValue.value", "first_value", "float"))] + [
    F("lastValue.timestamp", "time_ms", "int"), F("lastValue.value", D + "last_value", "float")] + [
    F("parameters." + m, D + k, "string") for m, k in (
        ("service.label", "service_label"), ("offering.id", "offering_id"), ("offering.label", "offering_label"),
        ("feature.id", "feature_id"), ("feature.label", "feature_label"), ("procedure.id", "procedure_id"),
        ("phenomenon.id", "phenomenon_id"), ("phenomenon.label", "phenomenon_label"), ("category.id", "category_id"))]

DATA = [G("values", D + "values", [F("timestamp", D + "value_time", "int"), F("value", D + "value", "float")])]


class Fail(Exception):
    def __init__(self, kind):
        Exception.__init__(self, kind)
        self.kind = kind


def at(obj, path):
    for name in path:
        if not isinstance(obj, dict) or name not in obj:
            return None
        obj = obj[name]
    return obj


def value_of(v, tr):
    if tr == "string":
        if not isinstance(v, str):
            raise Fail("transform-decode")
        return v
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Fail("transform-decode")
    if tr == "int":
        if float(v) != int(v):
            raise Fail("transform-decode")
        return int(v)
    return float(v)


def put(out, path, value):
    for name in path[:-1]:
        out = out.setdefault(name, {})
    out[path[-1]] = value


def encode(lines, obj):
    out = {}
    for ln in lines:
        if ln[0] == "f":
            v = at(obj, ln[1]) if ln[1] else obj
            if v is not None:
                x = value_of(v, ln[3])
                if not ln[1]:
                    return x
                if not (isinstance(out, dict) and at(out, ln[1]) is not None):     # ruling 16: the earliest line
                    put(out, ln[1], x)
        else:
            arr = at(obj, ln[1])
            if arr is not None:
                put(out, ln[1], [encode(ln[3], item) for item in arr])
    return out


def decode(lines, obj, ent, prefix=""):
    for ln in lines:
        if ln[0] == "f":
            v = at(obj, ln[1]) if ln[1] else obj
            if v is not None:
                ent[prefix + ln[2]] = value_of(v, ln[3])
        else:
            arr = at(obj, ln[1])
            if arr is None:
                continue
            ent[prefix + ln[2] + ".#"] = len(arr)
            for i, item in enumerate(arr):
                decode(ln[3], item, ent, "%s%s[%d]." % (prefix, ln[2], i))


def residue(out, obj, mapped, path=()):
    for name, v in obj.items():
        p = path + (name,)
        if p in mapped or v is None or isinstance(v, list):
            continue
        if isinstance(v, dict):
            sub = out.get(name) if isinstance(out.get(name), dict) else {}
            residue(sub, v, mapped, p)
            if sub and name not in out:
                out[name] = sub
        elif "." not in name:
            out[name] = v


def num(x):
    if isinstance(x, int) and not isinstance(x, bool):
        return str(x)
    r = repr(float(x))
    return r[:-2] if r.endswith(".0") else r


def text(o):
    if isinstance(o, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + text(v) for k, v in o.items()) + "}"
    if isinstance(o, list):
        return "[" + ",".join(text(v) for v in o) + "]"
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, bool):
        return "true" if o else "false"
    return num(o)


def canonical(lines, obj):
    out = encode(lines, obj)
    residue(out, obj, {ln[1] for ln in lines})
    return text(out)


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def vec(fmt, name, lines, obj, keys, note, to=None, expect=None, error=None):
    v = {"name": name, "from": fmt, "to": to or fmt, "input": js(obj)}
    if error:
        try:
            decode(lines, obj, {})
        except Fail as x:
            assert x.kind == error
            v["expect_error"] = error
        else:
            raise SystemExit("%s: decodes" % name)
    else:
        v["expect"] = expect if expect is not None else canonical(lines, obj)
        ent = {}
        decode(lines, obj, ent)
        v["model"] = {k: (num(ent[k]) if not isinstance(ent[k], str) else ent[k]) for k in keys}
    v["source"] = SOURCE
    v["reference"] = REF + "; " + note
    return v


VOC = "http://dd.eionet.europa.eu/vocabulary/aq/pollutant/"


def series():
    return {"id": "9001", "label": VOC + "5 7001 - Example Town Centre-Particulate matter < 10 \u00b5m (aerosol), "
                                   "Example Town Centre-Particulate matter < 10 \u00b5m (aerosol)",
            "extras": ["license"], "uom": "ug.m-3",
            "station": {"properties": {"id": 7001, "label": "Example Town Centre-Particulate matter < 10 \u00b5m (aerosol)"},
                        "geometry": {"coordinates": [52.5, -1.25, "NaN"], "type": "Point"}, "type": "Feature"},
            "referenceValues": [],
            "firstValue": {"timestamp": 1704067200000, "value": 21},
            "lastValue": {"timestamp": 1795233600000, "value": 17.5},
            "parameters": {"service": {"id": "1", "label": "Example service"},
                           "offering": {"id": "7001", "label": "7001 - Example Town Centre"},
                           "feature": {"id": "7001", "label": "Example Town Centre"},
                           "procedure": {"id": "7001", "label": "7001 - Example Town Centre"},
                           "phenomenon": {"id": "5", "label": VOC + "5"},
                           "category": {"id": "5", "label": VOC + "5"}}}


def series_vectors():
    V = {}
    F_ = "defra-ukair-timeseries"
    s = series()
    V["01-timeseries-roundtrip"] = vec(F_, "timeseries-roundtrip", SERIES, s, [
        "time_ms", D + "first_time", D + "first_value", D + "last_value", D + "station_id", D + "uom",
        D + "phenomenon_label"],
        note="one time series: the mapped members in line order, then the residue (the station's type and its "
             "geometry type, the ids and labels of parameters the pack does not name); arrays (extras, the "
             "coordinates, referenceValues) are not carried")
    e = series()
    del e["firstValue"], e["lastValue"]
    V["02-series-without-values"] = vec(F_, "series-without-values", SERIES, e, [D + "id"],
                                        note="a series that holds no value yet: no firstValue or lastValue, time_ms absent")
    bad = series()
    bad["lastValue"]["timestamp"] = "2026-11-21T06:00:00.000Z"
    V["03-time-as-text"] = vec(F_, "time-as-text", SERIES, bad, [], error="transform-decode",
                               note="the API writes times as epoch milliseconds; the ISO text form (not the "
                                    "service's default) is a transform failure for an int line")
    return V


def data_vectors():
    V = {}
    F_ = "defra-ukair-data"
    d = {"values": [{"timestamp": 1795226400000, "value": 18.25}, {"timestamp": 1795230000000, "value": 16},
                    {"timestamp": 1795233600000, "value": 17.5}]}
    V["01-data-roundtrip"] = vec(F_, "data-roundtrip", DATA, d, [
        D + "values.#", D + "values[0]." + D + "value_time", D + "values[0]." + D + "value",
        D + "values[1]." + D + "value"], note="three hourly values in time order")
    V["02-data-empty"] = vec(F_, "data-empty", DATA, {"values": []}, [D + "values.#"],
                             note="a period with no values: an empty list, written back as []")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("defra-ukair-timeseries", series_vectors()), ("defra-ukair-data", data_vectors())):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("airq-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
