#!/usr/bin/env python3
"""Write the vectors of the covjson-domain, covjson-coverage and covjson-coverage-collection packs.

The packs read OGC CoverageJSON documents (OGC 21-069r2, CoverageJSON Community Standard 1.0)
on the `json` wire. This script holds its own copy of the members the packs map, in the order
the packs list them, builds every document from values written for these vectors (none is taken
from the standard's examples), and works out the kind, the decoded values and the canonical
output by the rules of spec/engine-spec.md: 0.5 (`json` wire, kinds, residue, canonical output
and its rulings), 0.7 (groups: items carry no residue, `.` items) and ruling 3 of 0.1.1 (number
text). It reads no pack.def and calls no goat-transformers engine.

Usage: python3 -I tools/gen/covjson-vectors.py [--out DIR] [--check]
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/covjson-vectors.py from the members of the standard and spec/engine-spec.md; no engine run"
REF = ("OGC CoverageJSON Community Standard 1.0 (OGC 21-069r2), clauses on domain, axis, reference system "
       "connection, coverage and coverage collection objects")

# -- the lines of the packs, as this script reads the standard -------------------------------
# A line is ("w", path, value) for a `when`, ("f", path, key, transform) for a `field`, and
# ("g", path, list, body) for a `group`; a path is a tuple of member names, () for `.`.


def F(path, key, tr):
    return ("f", tuple(path.split(".")) if path != "." else (), "covjson." + key, tr)


def G(path, lst, body):
    return ("g", tuple(path.split(".")), "covjson." + lst, body)


def domain_lines(p):
    out = []
    for a, vt in (("x", "float"), ("y", "float"), ("z", "float"), ("t", "string")):
        out += [G(p + "axes.%s.values" % a, "axis_%s_values" % a, [F(".", "axis_%s_value" % a, vt)]),
                F(p + "axes.%s.start" % a, "axis_%s_start" % a, "float"),
                F(p + "axes.%s.stop" % a, "axis_%s_stop" % a, "float"),
                F(p + "axes.%s.num" % a, "axis_%s_num" % a, "int"),
                G(p + "axes.%s.bounds" % a, "axis_%s_bounds" % a, [F(".", "axis_%s_bound" % a, vt)])]
    out += [F(p + "axes.composite.dataType", "axis_composite_data_type", "string"),
            G(p + "axes.composite.coordinates", "axis_composite_coordinates", [F(".", "axis_composite_coordinate", "string")])]
    return out + referencing_lines(p)


def referencing_lines(p):
    return [G(p + "referencing", "referencing", [
        G("coordinates", "ref_coordinates", [F(".", "ref_coordinate", "string")]),
        F("system.type", "ref_system_type", "string"), F("system.id", "ref_system_id", "string"),
        F("system.calendar", "ref_system_calendar", "string"), F("system.timeScale", "ref_system_time_scale", "string")])]


PGROUPS = [G("parameterGroups", "parameter_groups", [
    F("type", "parameter_group_type", "string"), F("id", "parameter_group_id", "string"),
    G("members", "parameter_group_members", [F(".", "parameter_group_member", "string")])])]

PACKS = {
    "covjson-domain": [
        ("domain", [("w", ("type",), "Domain"), F("domainType", "domain_type", "string")] + domain_lines(""))],
    "covjson-coverage": [
        ("inline-domain", [("w", ("type",), "Coverage"), ("w", ("domain", "type"), "Domain"),
                           F("id", "id", "string"), F("domainType", "coverage_domain_type", "string"),
                           F("domain.type", "domain_object", "string"), F("domain.domainType", "domain_type", "string")]
         + domain_lines("domain.") + PGROUPS),
        ("domain-url", [("w", ("type",), "Coverage"),
                        F("id", "id", "string"), F("domainType", "coverage_domain_type", "string"),
                        F("domain", "domain_url", "string")] + PGROUPS)],
    "covjson-coverage-collection": [
        ("collection", [("w", ("type",), "CoverageCollection"),
                        F("domainType", "collection_domain_type", "string")] + PGROUPS + referencing_lines("")
         + [G("coverages", "coverages", [F("type", "coverage_type", "string"), F("id", "id", "string"),
                                         F("domainType", "coverage_domain_type", "string"),
                                         F("domain.type", "domain_object", "string"),
                                         F("domain.domainType", "domain_type", "string")]
              + domain_lines("domain.") + PGROUPS)])],
}


class Fail(Exception):
    def __init__(self, kind):
        Exception.__init__(self, kind)
        self.kind = kind


# -- reading a document ---------------------------------------------------------------------

def at(obj, path):
    """The value at a member path, or None when a member on the way is missing or not an object."""
    for name in path:
        if not isinstance(obj, dict) or name not in obj:
            return None
        obj = obj[name]
    return obj


def when_holds(doc, path, value):
    v = at(doc, path)
    if value == "present":
        return v is not None
    return isinstance(v, str) and v == value


def select(fmt, doc):
    for name, lines in PACKS[fmt]:
        if all(when_holds(doc, ln[1], ln[2]) for ln in lines if ln[0] == "w"):
            return name, lines
    raise Fail("no-kind")


def value_of(v, tr):
    """The model value of a JSON value under a transform (0.5 json transforms)."""
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


def decode(lines, obj, ent, prefix=""):
    """Keys and lists of the lines, as a vector's `model` member names them."""
    for ln in lines:
        if ln[0] == "f":
            v = at(obj, ln[1]) if ln[1] else obj
            if v is not None:
                ent[prefix + ln[2]] = value_of(v, ln[3])
        elif ln[0] == "g":
            arr = at(obj, ln[1])
            if arr is None:
                continue
            ent[prefix + ln[2] + ".#"] = len(arr)
            for i, item in enumerate(arr):
                decode(ln[3], item, ent, "%s%s[%d]." % (prefix, ln[2], i))


# -- the canonical output -------------------------------------------------------------------

def put(out, path, value):
    for name in path[:-1]:
        out = out.setdefault(name, {})
    out[path[-1]] = value


def encode_lines(lines, obj):
    """The members the lines write, in line order (an item: no residue)."""
    out = {}
    for ln in lines:
        if ln[0] == "w":
            if ln[2] != "present":
                put(out, ln[1], ln[2])
            else:
                # ruling 26 of 0.5: a member a `when` and a `field` both name is written at the
                # position of the first of them
                fl = next((x for x in lines if x[0] == "f" and x[1] == ln[1]), None)
                if fl is not None and at(obj, ln[1]) is not None:
                    put(out, ln[1], value_of(at(obj, ln[1]), fl[3]))
        elif ln[0] == "f":
            v = at(obj, ln[1]) if ln[1] else obj
            if v is not None:
                value = value_of(v, ln[3])
                if not ln[1]:
                    return value
                put(out, ln[1], value)
        else:
            arr = at(obj, ln[1])
            if arr is not None:
                put(out, ln[1], [encode_lines(ln[3], item) for item in arr])
    return out


def mapped_paths(lines):
    return {ln[1] for ln in lines if ln[1]}


def add_residue(out, obj, mapped, path=()):
    """Scalar members no line maps, at any depth of nested objects, after the mapped ones, in
    input order; arrays and null are not carried (0.5 json residue)."""
    for name, v in obj.items():
        p = path + (name,)
        if p in mapped or v is None or isinstance(v, list):
            continue
        if isinstance(v, dict):
            sub = out.get(name) if isinstance(out.get(name), dict) else {}
            add_residue(sub, v, mapped, p)
            if sub and name not in out:
                out[name] = sub
        else:
            out[name] = v


def prune(o):
    """A nested object with no members is not written."""
    if isinstance(o, dict):
        return {k: prune(v) for k, v in o.items() if not (isinstance(v, dict) and not prune(v))}
    if isinstance(o, list):
        return [prune(v) for v in o]
    return o


def num(x):
    """Number text of ruling 3 of 0.1.1: shortest round trip, plain notation, no `.0`."""
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0"
    r = repr(float(x))
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
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
    if isinstance(o, float) and not math.isfinite(o):
        raise ValueError(o)
    return num(o)


def canonical(fmt, doc):
    kind, lines = select(fmt, doc)
    out = encode_lines(lines, doc)
    add_residue(out, doc, mapped_paths(lines))
    return kind, text(prune(out))


# -- vectors ---------------------------------------------------------------------------------

def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def model_text(ent, keys):
    m = {}
    for k in keys:
        v = ent[k]
        m[k] = num(v) if isinstance(v, (int, float)) else v
    return m


def roundtrip(fmt, name, doc, keys, note):
    kind, out = canonical(fmt, doc)
    ent = {}
    decode(dict(PACKS[fmt])[kind], doc, ent)
    model = {"@kind": kind}
    model.update(model_text(ent, keys))
    return vec(name, fmt, fmt, js(doc), expect=out, model=model, note=note)


def refused(fmt, name, doc, note):
    try:
        kind, lines = select(fmt, doc)
        ent = {}
        decode(lines, doc, ent)
    except Fail as x:
        return vec(name, fmt, fmt, js(doc), error=x.kind, note=note)
    raise SystemExit("%s/%s: the document decodes" % (fmt, name))


def vec(name, frm, to, inp, expect=None, model=None, error=None, note=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = REF + ("; " + note if note else "")
    return v


CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


def geo_ref(coords=("x", "y")):
    return {"coordinates": list(coords), "system": {"type": "GeographicCRS", "id": CRS84}}


def time_ref():
    return {"coordinates": ["t"], "system": {"type": "TemporalRS", "calendar": "Gregorian"}}


def point_domain(x=-3.5, y=50.25):
    return {"type": "Domain", "domainType": "Point",
            "axes": {"x": {"values": [x]}, "y": {"values": [y]}, "z": {"values": [5]},
                     "t": {"values": ["2026-11-20T06:00:00Z"]}},
            "referencing": [geo_ref(), {"coordinates": ["z"], "system": {"type": "VerticalCRS", "id": "http://www.opengis.net/def/crs/EPSG/0/5703"}},
                            time_ref()]}


def domain_vectors():
    fmt = "covjson-domain"
    V = {}
    V["01-point-domain-roundtrip"] = roundtrip(fmt, "point-domain-roundtrip", point_domain(), [
        "covjson.domain_type", "covjson.axis_x_values.#", "covjson.axis_x_values[0].covjson.axis_x_value",
        "covjson.axis_y_values[0].covjson.axis_y_value", "covjson.axis_t_values[0].covjson.axis_t_value",
        "covjson.referencing.#", "covjson.referencing[0].covjson.ref_system_id",
        "covjson.referencing[0].covjson.ref_coordinates[1].covjson.ref_coordinate",
        "covjson.referencing[2].covjson.ref_system_calendar"],
        note="a Point domain under a longitude-latitude CRS, a vertical CRS and the Gregorian calendar; z is written 5")
    grid = {"type": "Domain", "domainType": "Grid",
            "axes": {"x": {"start": -10.0, "stop": 10.0, "num": 81}, "y": {"start": 60.0, "stop": 40.0, "num": 81},
                     "t": {"values": ["2026-11-20T00:00:00Z", "2026-11-20T06:00:00Z"],
                           "bounds": ["2026-11-19T21:00:00Z", "2026-11-20T03:00:00Z", "2026-11-20T03:00:00Z", "2026-11-20T09:00:00Z"]}},
            "referencing": [geo_ref(), time_ref()]}
    V["02-grid-regular-axes-roundtrip"] = roundtrip(fmt, "grid-regular-axes-roundtrip", grid, [
        "covjson.axis_x_start", "covjson.axis_x_stop", "covjson.axis_x_num", "covjson.axis_y_start",
        "covjson.axis_t_values.#", "covjson.axis_t_bounds.#", "covjson.axis_t_bounds[3].covjson.axis_t_bound"],
        note="regularly spaced x and y (start, stop, num; y descends), two time steps with bounds; -10.0 is written -10")
    traj = {"type": "Domain", "domainType": "Trajectory", "dct:license": "https://creativecommons.org/licenses/by/4.0/",
            "axes": {"composite": {"dataType": "tuple", "coordinates": ["t", "x", "y"],
                                   "values": [["2026-11-20T00:00:00Z", 1.5, 50.0], ["2026-11-20T00:10:00Z", 1.75, 50.125]]},
                     "z": {"values": [100]}},
            "referencing": [{"coordinates": ["x", "y"], "system": {"type": "GeographicCRS", "id": CRS84,
                                                                  "description": {"en": "longitude and latitude"}}},
                            time_ref()]}
    V["03-trajectory-tuples-are-not-carried"] = roundtrip(fmt, "trajectory-tuples-are-not-carried", traj, [
        "covjson.axis_composite_data_type", "covjson.axis_composite_coordinates.#",
        "covjson.axis_composite_coordinates[0].covjson.axis_composite_coordinate"],
        note="the composite axis keeps dataType and coordinates; its tuple values (an array of arrays) are not "
             "carried, and the i18n description of a reference system, inside a list item, is dropped; the custom "
             "member dct:license is residue and comes back after the mapped members")
    V["04-not-a-domain"] = refused(fmt, "not-a-domain", {"type": "Coverage", "domain": point_domain(), "ranges": {}},
                                   note="a Coverage document is not a Domain: no kind holds")
    bad = point_domain()
    bad["axes"]["x"]["values"] = ["east"]
    V["05-text-on-a-numeric-axis"] = refused(fmt, "text-on-a-numeric-axis", bad,
                                             note="x values are read as numbers; a string there is a transform failure")
    return V


def parameters():
    return {"temperature": {"type": "Parameter", "unit": {"symbol": {"value": "K", "type": "http://www.opengis.net/def/uom/UCUM/"}},
                            "observedProperty": {"id": "http://vocab.nerc.ac.uk/standard_name/air_temperature/",
                                                 "label": {"en": "Air temperature"}}}}


def coverage_vectors():
    fmt = "covjson-coverage"
    V = {}
    cov = {"type": "Coverage", "id": "station-0042", "domain": point_domain(),
           "parameters": parameters(),
           "parameterGroups": [{"type": "ParameterGroup", "id": "air", "label": {"en": "Air"}, "members": ["temperature"]}],
           "ranges": {"temperature": {"type": "NdArray", "dataType": "float", "values": [281.25]}}}
    V["01-point-coverage-roundtrip"] = roundtrip(fmt, "point-coverage-roundtrip", cov, [
        "covjson.id", "covjson.domain_object", "covjson.domain_type", "covjson.axis_x_values[0].covjson.axis_x_value",
        "covjson.referencing[0].covjson.ref_system_type", "covjson.parameter_groups[0].covjson.parameter_group_id",
        "covjson.parameter_groups[0].covjson.parameter_group_members[0].covjson.parameter_group_member"],
        note="the domain inline; parameters and ranges are named by the producer, so their scalar members come back as "
             "residue and the range values (an array) are not carried; the label of the parameter group, inside a list "
             "item, is dropped")
    url = {"type": "Coverage", "domainType": "Grid", "domain": "https://example.org/coverages/run-7/domain",
           "parameters": parameters(),
           "ranges": {"temperature": "https://example.org/coverages/run-7/temperature"}}
    V["02-domain-url-roundtrip"] = roundtrip(fmt, "domain-url-roundtrip", url, [
        "covjson.domain_url", "covjson.coverage_domain_type"],
        note="the domain named by a URL, with domainType at the coverage; the range is a URL too, a scalar, residue")
    V["03-not-a-coverage"] = refused(fmt, "not-a-coverage", point_domain(), note="a Domain document is not a Coverage: no kind holds")
    bad = dict(cov)
    bad["domain"] = {"type": "Domain", "axes": {"x": {"start": 0, "stop": 1, "num": 2.5}}, "referencing": []}
    V["04-num-that-is-not-an-integer"] = refused(fmt, "num-that-is-not-an-integer", bad,
                                                 note="num is an integer; 2.5 is a transform failure")
    return V


def collection_vectors():
    fmt = "covjson-coverage-collection"
    V = {}

    def member(cid, x, y, value):
        d = point_domain(x, y)
        del d["referencing"]
        return {"type": "Coverage", "id": cid, "domain": d,
                "ranges": {"temperature": {"type": "NdArray", "dataType": "float", "values": [value]}}}
    col = {"type": "CoverageCollection", "domainType": "Point", "parameters": parameters(),
           "referencing": [geo_ref(), time_ref()],
           "coverages": [member("station-0042", -3.5, 50.25, 281.25), member("station-0043", -3.25, 50.5, 280.5)]}
    V["01-point-collection-roundtrip"] = roundtrip(fmt, "point-collection-roundtrip", col, [
        "covjson.collection_domain_type", "covjson.referencing.#", "covjson.coverages.#",
        "covjson.coverages[1].covjson.id", "covjson.coverages[1].covjson.axis_y_values[0].covjson.axis_y_value"],
        note="two Point coverages sharing the collection's parameters and referencing; each coverage is a list item, "
             "which carries no residue, so its ranges are dropped")
    urlcol = {"type": "CoverageCollection", "coverages": [{"type": "Coverage", "domain": "https://example.org/d/1",
                                                           "parameters": parameters(), "ranges": {}}]}
    V["02-domain-url-in-an-item-is-dropped"] = roundtrip(fmt, "domain-url-in-an-item-is-dropped", urlcol, [
        "covjson.coverages.#", "covjson.coverages[0].covjson.coverage_type"],
        note="a coverage of a collection whose domain is a URL: an item has no kinds, so only the inline form is "
             "mapped and the URL is dropped")
    V["03-not-a-collection"] = refused(fmt, "not-a-collection", {"type": "Coverage", "domain": point_domain(), "ranges": {}},
                                       note="a Coverage document is not a CoverageCollection: no kind holds")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("covjson-domain", domain_vectors()), ("covjson-coverage", coverage_vectors()),
                    ("covjson-coverage-collection", collection_vectors())):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("covjson-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
