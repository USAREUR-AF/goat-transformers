#!/usr/bin/env python3
"""Write the vectors of the mf-json pack.

The pack reads one OGC Moving Features JSON (MF-JSON 1.0, OGC 19-045r3) moving
feature: a GeoJSON Feature whose temporalGeometry is a MovingPoint (Prism
encoding, clause 7.2), or a Trajectory (clause 7.1: a LineString geometry with
properties.datetimes). This script holds its own copy of the pack's lines,
builds every message from values written for these vectors (none is taken from
the standard's examples or from the MF-JSON schema files, whose notice reserves
all rights), and works out the canonical output, the decoded values and the
GeoJSON form by the rules of spec/engine-spec.md and of the geojson pack. It
reads no pack.def and calls no goat-transformers engine.

Rules applied (spec/engine-spec.md):
  0.5 json wire: mapped and `when` members in line order (common lines first),
      a nested object at the position of the first line that addresses into it;
      then residue scalars of each object in input order; arrays no group maps
      are not carried; null is absent.
  0.6 several lines for one key: decode takes the first line whose transform
      succeeds; on one locator encode writes the earliest line's form.
  0.7 groups: items carry no residue.
  0.18 iso8601_short: no fraction when the milliseconds are 0, `Z`.

Usage: python3 -I tools/gen/mf-json-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

FMT = "mf-json"
REF = "OGC Moving Features Encoding Extension - JSON (MF-JSON) 1.0, OGC 19-045r3"
SOURCE = ("derived by tools/gen/mf-json-vectors.py from the text of OGC 19-045r3 and spec/engine-spec.md; "
          "no engine run")

# (kind, `when` path and value of the kind, then the lines after it in pack order):
# ("g", path, list, item kind) where item kind is "dt" (datetime_ms), "s" (instant) or "f" (bound);
# ("f", path, transform, key)
KINDS = [
    ("MovingPoint", ("temporalGeometry.type", "MovingPoint"), [
        ("g", "temporalGeometry.datetimes", "mfjson.datetimes", "dt"),
        ("f", "temporalGeometry.interpolation", "s", "mfjson.interpolation"),
        ("g", "time", "mfjson.life_span", "s"),
        ("g", "bbox", "mfjson.bbox", "f"),
        ("f", "id", "s", "uid")]),
    ("Trajectory", ("geometry.type", "LineString"), [
        ("g", "properties.datetimes", "mfjson.trajectory_datetimes", "dt"),
        ("g", "bbox", "mfjson.bbox", "f"),
        ("f", "id", "s", "uid")]),
]
ITEM_KEY = {"dt": "mfjson.datetime_ms", "s": "mfjson.instant", "f": "mfjson.bound"}


def num(x):
    if isinstance(x, int) and not isinstance(x, bool):
        return str(x)
    x = float(x)
    if x == 0:
        return "0"
    r = repr(x)
    return r[:-2] if r.endswith(".0") else r


def iso_ms(text):
    t = text
    off = datetime.timedelta(0)
    if t[-1] in "Zz":
        t = t[:-1]
    else:
        sign = 1 if t[-6] == "+" else -1
        off = sign * datetime.timedelta(hours=int(t[-5:-3]), minutes=int(t[-2:]))
        t = t[:-6]
    ms = 0
    if "." in t:
        t, frac = t.split(".")
        ms = int((frac + "000")[:3])
    d = datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc) - off
    return int(d.timestamp()) * 1000 + ms


def ms_short(ms):
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    s = d.strftime("%Y-%m-%dT%H:%M:%S")
    if ms % 1000:
        s += "." + ("%03d" % (ms % 1000)).rstrip("0")
    return s + "Z"


def dt_ms(v):
    """The two lines of datetime_ms: iso8601_short on a string, else int on a number."""
    return iso_ms(v) if isinstance(v, str) else int(v)


def get(obj, path):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class Obj:
    def __init__(self):
        self.members = []

    def child(self, name):
        for n, v in self.members:
            if n == name:
                return v
        o = Obj()
        self.members.append((name, o))
        return o

    def put(self, name, text):
        self.members.append((name, text))

    def empty(self):
        return all(isinstance(v, Obj) and v.empty() for _, v in self.members)

    def text(self):
        parts = []
        for n, v in self.members:
            if isinstance(v, Obj):
                if v.empty():
                    continue
                v = v.text()
            parts.append("%s:%s" % (json.dumps(n), v))
        return "{" + ",".join(parts) + "}"


def place(root, path):
    parts = path.split(".")
    cur = root
    for p in parts[:-1]:
        cur = cur.child(p)
    return cur, parts[-1]


def item_text(v, ik):
    if ik == "dt":
        return json.dumps(ms_short(dt_ms(v)))
    if ik == "s":
        return json.dumps(v)
    return num(v)


def residue(src, out, mapped, prefix=""):
    for name, v in src.items():
        if "." in name or v is None or isinstance(v, list):
            continue
        path = prefix + name
        if isinstance(v, dict):
            residue(v, out.child(name), mapped, path + ".")
        elif path not in mapped:
            out.put(name, json.dumps(v, ensure_ascii=False))


def select(obj):
    if obj.get("type") != "Feature":
        return None
    for kind, (wp, wv), lines in KINDS:
        if get(obj, wp) == wv:
            return kind, (wp, wv), lines
    return None


def encode(obj):
    kind, (wp, wv), lines = select(obj)
    root = Obj()
    root.put("type", json.dumps("Feature"))
    mapped = {"type", wp}
    parent, last = place(root, wp)
    parent.put(last, json.dumps(wv))
    for line in lines:
        if line[0] == "g":
            _, path, _, ik = line
            v = get(obj, path)
            mapped.add(path)
            if isinstance(v, list):
                parent, last = place(root, path)
                parent.put(last, "[" + ",".join(item_text(x, ik) for x in v) + "]")
        else:
            _, path, _, _ = line
            mapped.add(path)
            v = get(obj, path)
            if v is not None:
                parent, last = place(root, path)
                parent.put(last, json.dumps(v))
    residue(obj, root, mapped)
    return root.text()


def model(obj):
    kind, _, lines = select(obj)
    m = {"@kind": kind}
    for line in lines:
        if line[0] == "g":
            _, path, key, ik = line
            v = get(obj, path)
            if isinstance(v, list):
                m[key + ".#"] = str(len(v))
                for i, x in enumerate(v):
                    m["%s[%d].%s" % (key, i, ITEM_KEY[ik])] = (str(dt_ms(x)) if ik == "dt" else
                                                                x if ik == "s" else num(x))
        else:
            _, path, _, key = line
            v = get(obj, path)
            if v is not None:
                m[key] = v
    return m


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def vec(name, frm, to, inp, expect=None, mdl=None, error=None, note=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if mdl:
        v["model"] = mdl
    v["source"] = SOURCE
    v["reference"] = REF + ("; " + note if note else "")
    return v


def rt(name, obj, note):
    return vec(name, FMT, FMT, js(obj), encode(obj), model(obj), note=note)


# -- the messages, written for these vectors -----------------------------------------

def moving_point():
    return {
        "type": "Feature",
        "id": "bus-17",
        "temporalGeometry": {
            "type": "MovingPoint",
            "datetimes": ["2026-05-01T08:00:00Z", "2026-05-01T08:00:30Z", "2026-05-01T08:01:00.5Z"],
            "coordinates": [[13.4049, 52.52], [13.4061, 52.5207], [13.4075, 52.5213]],
            "interpolation": "Linear",
            "crs": {"type": "Name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "trs": {"type": "Link", "properties": {"type": "OGCDEF",
                                                   "href": "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian"}}},
        "time": ["2026-05-01T08:00:00Z", "2026-05-01T08:01:00.5Z"],
        "bbox": [13.4049, 52.52, 13.4075, 52.5213],
        "properties": {"line": "M10", "operator": "Transit authority", "doors": 3},
    }


def build_vectors():
    V = {}
    mp = moving_point()
    V["01-moving-point-roundtrip"] = rt(
        "moving-point-roundtrip", mp,
        "type, then the temporal geometry (its type, datetimes, interpolation, then its crs and trs as residue), "
        "time, bbox, id, then properties as residue; the coordinates are an array of arrays and are not carried "
        "(pack.md, not mapped)")

    mp2 = {"type": "Feature",
           "temporalGeometry": {"type": "MovingPoint", "datetimes": [1777622400000, 1777622430250],
                                "coordinates": [[2.35, 48.85], [2.36, 48.86]]},
           "id": "walker-2"}
    V["02-moving-point-epoch-datetimes"] = rt(
        "moving-point-epoch-datetimes", mp2,
        "datetimes given as epoch milliseconds (clause 7.2.1.1 allows them) are read by the int line and written "
        "as RFC 3339 instants by the first line (iso8601_short); no interpolation member is written when absent")

    tr = {"type": "Feature",
          "geometry": {"type": "LineString", "coordinates": [[-3.7038, 40.4168], [-3.7, 40.42]]},
          "properties": {"datetimes": ["2026-05-02T10:00:00Z", "2026-05-02T10:05:00Z"], "name": "ferry"},
          "id": "ferry-4"}
    V["03-trajectory-roundtrip"] = rt(
        "trajectory-roundtrip", tr,
        "clause 7.1: a LineString geometry with properties.datetimes; the geometry's type is the kind's when, "
        "its coordinates are not carried")

    mp4 = {"type": "Feature",
           "temporalGeometry": {"type": "MovingPoint", "datetimes": ["2026-05-01T08:00:00Z"],
                                "coordinates": [[0, 0]], "base": {"type": "glTF", "href": "https://models.example.org/bus.glb"}},
           "temporalProperties": [{"datetimes": ["2026-05-01T08:00:00Z"],
                                   "speed": {"type": "Measure", "form": "KMH", "values": [32.5]}}],
           "id": "bus-18"}
    V["04-moving-point-temporal-properties-not-carried"] = rt(
        "moving-point-temporal-properties-not-carried", mp4,
        "temporalProperties is an array of objects whose member names are the property names: not carried; "
        "the base object's members are residue")

    V["05-moving-point-to-geojson"] = vec(
        "moving-point-to-geojson", FMT, "geojson", js(mp),
        '{"type":"Feature","geometry":null,"properties":{},"id":"bus-17"}',
        {"@kind": "MovingPoint", "uid": "bus-17"},
        note="only the id carries; no position is bound, so the geometry is null")

    V["06-numeric-id-is-transform-decode"] = vec(
        "numeric-id-is-transform-decode", FMT, FMT,
        js({"type": "Feature", "temporalGeometry": {"type": "MovingPoint", "datetimes": ["2026-05-01T08:00:00Z"],
                                                     "coordinates": [[0, 0]]}, "id": 17}),
        error="transform-decode", note="the standard allows a number as id; uid is read with string only")
    V["07-moving-polygon-is-no-kind"] = vec(
        "moving-polygon-is-no-kind", FMT, FMT,
        js({"type": "Feature", "temporalGeometry": {"type": "MovingPolygon", "datetimes": ["2026-05-01T08:00:00Z"],
                                                     "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]}}),
        error="no-kind", note="only MovingPoint and the Trajectory encoding are kinds of this pack")
    V["08-feature-collection-is-no-kind"] = vec(
        "feature-collection-is-no-kind", FMT, FMT,
        js({"type": "FeatureCollection", "features": [mp]}), error="no-kind",
        note="the common when holds type Feature; a collection is not one message of this pack")
    V["09-reduced-precision-datetime-is-transform-decode"] = vec(
        "reduced-precision-datetime-is-transform-decode", FMT, FMT,
        js({"type": "Feature", "temporalGeometry": {"type": "MovingPoint", "datetimes": ["2026-05-01T08:00Z"],
                                                     "coordinates": [[0, 0]]}}),
        error="transform-decode",
        note="an instant without seconds, which the standard lists among ISO 8601 forms, is refused by iso8601_short "
             "and is not a number for the int line")
    return V


def geojson_vectors():
    gin = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[13.4049,52.52]},'
           '"properties":{"time_ms":1777622400000,"callsign":"bus"},"id":"bus-17"}')
    return {"to-mf-json-is-no-kind": vec(
        "to-mf-json-is-no-kind", "geojson", FMT, gin, error="no-kind",
        note="each kind requires its list of instants, which a GeoJSON point does not have")}


def build(out):
    written = {}
    for fn, v in build_vectors().items():
        out.write("packs/mf-json/vectors/%s.json" % fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written[FMT] = written.get(FMT, 0) + 1
    for fn, v in geojson_vectors().items():
        out.write("packs/geojson/vectors/%s.json" % fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written["geojson"] = 1
    return written


def main(argv=None):
    return genio.vector_main("mf-json-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
