#!/usr/bin/env python3
"""Write the vectors of the sensorthings-1.0 and sensorthings-1.1 packs.

The packs read one entity of the OGC SensorThings API Part 1: Sensing (1.0, OGC
15-078r6; 1.1, OGC 18-088) as its JSON object, the kind chosen by a member only
that entity has. This script holds its own copy of the lines of every kind, in
the packs' order, builds every message from values written for these vectors
(none is taken from the standards' examples), and works out the canonical
output, the decoded values and the GeoJSON forms by the rules of
spec/engine-spec.md and of the geojson pack. It reads no pack.def and calls no
goat-transformers engine.

Rules applied (spec/engine-spec.md):
  0.5 json wire: mapped and `when` members in line order, a nested object at the
      position of the first line that addresses into it; then residue scalars of
      each object in input order. Arrays no group maps are not carried; `null`
      is absent; a member whose name holds `.` (the @iot annotations) is dropped.
      Ruling 27: `when <m> present` does not map the member.
  0.7 groups: an array of scalars is a list, one `.` line per item; items carry
      no residue.
  0.18 iso8601_short: an instant with no milliseconds is written without a
      fraction; an offset is converted to UTC and written `Z`.
  Ruling 3 of 0.1.1: numbers shortest round trip, an integer value without a point.

Usage: python3 -I tools/gen/sensorthings-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF11 = "OGC SensorThings API Part 1: Sensing 1.1 (OGC 18-088), clause 8.2"
REF10 = "OGC SensorThings API Part 1: Sensing 1.0 (OGC 15-078r6), clauses 8.2 and 12"
SOURCE = ("derived by tools/gen/sensorthings-vectors.py from the entity tables of the standard and "
          "spec/engine-spec.md; no engine run")
P = "sensorthings."


# -- the lines of each kind, in pack order ---------------------------------------------
# ("f", path, transform, key)    a field; transforms s string, f float, t iso8601_short
# ("g", path, key, [("f", ".", tr, key)] or [("f", member, tr, key), ...])   a group
# ("w", path, value)             a `when`; value None is `present`

def named(*more):
    return [("f", "name", "s", P + "name"), ("f", "description", "s", P + "description")] + list(more)


def point_kind(member, path, key):
    return named(("f", "encodingType", "s", P + "encoding_type"),
                 ("w", path.rsplit(".", 1)[0] + ".type", "Point"),
                 ("g", path, P + key, [("f", ".", "f", P + "coordinate")]))


KINDS = [
    ("Datastream", named(("f", "unitOfMeasurement.name", "s", P + "unit_name"),
                         ("f", "unitOfMeasurement.symbol", "s", P + "unit_symbol"),
                         ("f", "unitOfMeasurement.definition", "s", P + "unit_definition"),
                         ("f", "observationType", "s", P + "observation_type"),
                         ("f", "phenomenonTime", "s", P + "phenomenon_time"),
                         ("f", "resultTime", "s", P + "result_time_period"),
                         ("w", "unitOfMeasurement", None))),
    ("Observation", [("f", "phenomenonTime", "s", P + "phenomenon_time"),
                     ("f", "resultTime", "t", "time_ms"),
                     ("f", "validTime", "s", P + "valid_time"),
                     ("w", "result", None)]),
    ("LocationPoint", point_kind("location", "location.coordinates", "location_coordinates")),
    ("LocationFeaturePoint", point_kind("location", "location.geometry.coordinates",
                                        "location_feature_coordinates")),
    ("Location", named(("f", "encodingType", "s", P + "encoding_type"),
                       ("f", "location.type", "s", P + "location_type"),
                       ("w", "location", None))),
    ("FeatureOfInterestPoint", point_kind("feature", "feature.coordinates", "feature_coordinates")),
    ("FeatureOfInterestFeaturePoint", point_kind("feature", "feature.geometry.coordinates",
                                                 "feature_feature_coordinates")),
    ("FeatureOfInterest", named(("f", "encodingType", "s", P + "encoding_type"),
                                ("f", "feature.type", "s", P + "feature_type"),
                                ("w", "feature", None))),
    ("Sensor", named(("f", "encodingType", "s", P + "encoding_type"), ("w", "metadata", None))),
    ("HistoricalLocation", [("f", "time", "t", "time_ms"), ("w", "time", None)]),
    ("ObservedProperty", [("f", "name", "s", P + "name"), ("f", "definition", "s", P + "definition"),
                          ("f", "description", "s", P + "description"), ("w", "definition", None)]),
    ("Thing", [("f", "name", "s", "callsign"), ("f", "description", "s", P + "description"),
               ("w", "name", None)]),
]
MULTI = ("MultiDatastream", named(
    ("g", "unitOfMeasurements", P + "units", [("f", "name", "s", P + "unit_name"),
                                               ("f", "symbol", "s", P + "unit_symbol"),
                                               ("f", "definition", "s", P + "unit_definition")]),
    ("f", "observationType", "s", P + "observation_type"),
    ("g", "multiObservationDataTypes", P + "multi_observation_data_types",
     [("f", ".", "s", P + "observation_type")]),
    ("f", "phenomenonTime", "s", P + "phenomenon_time"),
    ("f", "resultTime", "s", P + "result_time_period"),
    ("w", "multiObservationDataTypes", None)))
PACK_KINDS = {"sensorthings-1.1": KINDS, "sensorthings-1.0": [MULTI] + KINDS}


# -- values ---------------------------------------------------------------------------

def num(x):
    """JSON number text the encoder writes (ruling 3 of 0.1.1)."""
    if isinstance(x, int) and not isinstance(x, bool):
        return str(x)
    x = float(x)
    if x == 0:
        return "0"
    r = repr(x)
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
    return r[:-2] if r.endswith(".0") else r


def iso_ms(text):
    """iso8601 decode (ruling 3 of 0.11): Z or an offset, fraction cut to milliseconds."""
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
    """iso8601_short encode (0.18)."""
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    s = d.strftime("%Y-%m-%dT%H:%M:%S")
    if ms % 1000:
        s += "." + ("%03d" % (ms % 1000)).rstrip("0")
    return s + "Z"


def get(obj, path):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def wire_value(v, tr):
    if tr == "s":
        assert isinstance(v, str), v
        return json.dumps(v, ensure_ascii=False)
    if tr == "f":
        return num(v)
    return json.dumps(ms_short(iso_ms(v)))


def model_value(v, tr):
    if tr == "t":
        return str(iso_ms(v))
    if tr == "f":
        return num(v)
    return v


# -- canonical output ----------------------------------------------------------------

class Obj:
    """An output object: members in the order they are first written."""

    def __init__(self):
        self.members = []          # (name, text or Obj)

    def child(self, name):
        for n, v in self.members:
            if n == name:
                return v
        o = Obj()
        self.members.append((name, o))
        return o

    def put(self, name, text):
        self.members.append((name, text))

    def has(self, name):
        return any(n == name for n, _ in self.members)

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


def item_text(item, lines):
    if lines[0][1] == ".":
        _, _, tr, _ = lines[0]
        return "null" if item is None else wire_value(item, tr)
    o = Obj()
    for _, member, tr, _ in lines:
        v = item.get(member) if isinstance(item, dict) else None
        if v is not None:
            o.put(member, wire_value(v, tr))
    return o.text()


def residue(src, out, mapped, prefix=""):
    """Scalars no line maps, at any depth of objects, in input order."""
    for name, v in src.items():
        if "." in name or v is None or isinstance(v, list):
            continue
        path = prefix + name
        if isinstance(v, dict):
            residue(v, out.child(name), mapped, path + ".")
        elif path not in mapped:
            out.put(name, json.dumps(v, ensure_ascii=False))


def encode(obj, lines):
    root = Obj()
    mapped = set()
    for line in lines:
        if line[0] == "f":
            _, path, tr, _ = line
            mapped.add(path)
            v = get(obj, path)
            if v is not None:
                parent, last = place(root, path)
                parent.put(last, wire_value(v, tr))
        elif line[0] == "g":
            _, path, _, item_lines = line
            v = get(obj, path)
            if isinstance(v, list):
                parent, last = place(root, path)
                parent.put(last, "[" + ",".join(item_text(it, item_lines) for it in v) + "]")
            mapped.add(path)
        else:
            _, path, value = line
            if value is not None:
                mapped.add(path)
                parent, last = place(root, path)
                if not parent.has(last):
                    parent.put(last, json.dumps(value))
    residue(obj, root, mapped)
    return root.text()


def decode_model(obj, lines, kind):
    m = {"@kind": kind}
    for line in lines:
        if line[0] == "f":
            _, path, tr, key = line
            v = get(obj, path)
            if v is not None:
                m[key] = model_value(v, tr)
        elif line[0] == "g":
            _, path, key, item_lines = line
            v = get(obj, path)
            if isinstance(v, list):
                m[key + ".#"] = str(len(v))
                for i, it in enumerate(v):
                    for _, member, tr, ikey in item_lines:
                        x = it if member == "." else (it or {}).get(member)
                        if x is not None:
                            m["%s[%d].%s" % (key, i, ikey)] = model_value(x, tr)
    return m


def kind_of(obj, kinds):
    for name, lines in kinds:
        ok = True
        for line in lines:
            if line[0] == "w":
                v = get(obj, line[1])
                if v is None or (line[2] is not None and v != line[2]):
                    ok = False
        if ok:
            return name, lines
    return None, None


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def vec(name, frm, to, inp, expect=None, model=None, error=None, ref=REF11, note=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = ref + ("; " + note if note else "")
    return v


def roundtrip(fmt, name, obj, ref, note=None, kinds=None):
    kinds = kinds or PACK_KINDS[fmt]
    kind, lines = kind_of(obj, kinds)
    assert kind, name
    return vec(name, fmt, fmt, js(obj), encode(obj, lines), decode_model(obj, lines, kind), ref=ref, note=note)


# -- the messages, written for these vectors -----------------------------------------

def ann(entity, n, links, v):
    """The identifier and self link a service adds to an entity it returns. The navigation
    links (a related set's name, then the annotation) are left out: their member names read
    as mail addresses to tools/boundary-gate, and they are dropped exactly as these two are."""
    return {"@iot.id": n, "@iot.selfLink": "https://sta.example.org/v%s/%s(%d)" % (v, entity, n)}


def messages(v):
    """One entity per kind; properties members only where version 1.1 has them."""
    new = v == "1.1"
    M = []

    thing = ann("Things", 3, ["Locations", "Datastreams", "HistoricalLocations"], v)
    thing.update({"name": "Weather mast 3", "description": "Ten-metre mast on the north field",
                  "properties": {"operator": "Field station", "serial": 4417, "heated": True}})
    M.append(("thing-roundtrip", thing,
              "the @iot annotations hold a dot in their names and are dropped (engine-spec 0.5 ruling 12); "
              "name is callsign; properties are residue and keep their JSON types"))

    loc = ann("Locations", 5, ["Things", "HistoricalLocations"], v)
    loc.update({"name": "North field", "description": "Mast foundation",
                "encodingType": "application/geo+json",
                "location": {"type": "Point", "coordinates": [8.6821, 50.1109, 112.5]}})
    if new:
        loc["properties"] = {"surveyed": "2025"}
    M.append(("location-point-roundtrip", loc,
              "location is a GeoJSON Point: its coordinates are a list of three numbers"))

    locf = {"name": "Roof", "description": "Roof of building B",
            "encodingType": "application/geo+json",
            "location": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-0.1276, 51.5072]},
                         "properties": {"floor": 4}}}
    M.append(("location-feature-point-roundtrip", locf,
              "location is a GeoJSON Feature whose geometry is a Point; the Feature's type and properties are residue"))

    locp = {"name": "Yard", "description": "Storage yard outline",
            "encodingType": "application/geo+json",
            "location": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
    M.append(("location-polygon-roundtrip", locp,
              "a geometry other than a Point: its type is kept, its coordinates (an array of arrays) are not carried"))

    hl = ann("HistoricalLocations", 9, ["Locations", "Thing"], v)
    hl.update({"time": "2026-04-05T06:07:08Z"})
    M.append(("historical-location-roundtrip", hl, "time is time_ms; a time with no milliseconds is written without a fraction"))

    ds = ann("Datastreams", 2, ["Thing", "Sensor", "ObservedProperty", "Observations"], v)
    ds.update({"name": "Air temperature", "description": "Two-metre air temperature, one-minute means",
               "unitOfMeasurement": {"name": "degree Celsius", "symbol": "Cel",
                                     "definition": "http://unitsofmeasure.org/ucum.html"},
               "observationType": "http://www.opengis.net/def/observationType/OGC-OM/2.0/OM_Measurement",
               "observedArea": {"type": "Polygon", "coordinates": [[[8.68, 50.11], [8.69, 50.11], [8.68, 50.11]]]},
               "phenomenonTime": "2026-01-01T00:00:00Z/2026-04-05T06:07:00Z",
               "resultTime": "2026-01-01T00:00:10Z/2026-04-05T06:07:10Z"})
    if new:
        ds["properties"] = {"aggregation": "mean"}
    M.append(("datastream-roundtrip", ds,
              "phenomenonTime and resultTime of a Datastream are intervals: raw text; observedArea keeps its type, "
              "its coordinates are not carried"))

    sen = ann("Sensors", 4, ["Datastreams"], v)
    sen.update({"name": "PT100 probe", "description": "Platinum resistance thermometer in a radiation shield",
                "encodingType": "application/pdf", "metadata": "https://sensors.example.org/pt100.pdf"})
    M.append(("sensor-roundtrip", sen, "metadata is any JSON value: not mapped, a string is residue"))

    op = ann("ObservedProperties", 6, ["Datastreams"], v)
    op.update({"name": "Air temperature", "definition": "https://vocab.example.org/air-temperature",
               "description": "Temperature of the air two metres above ground"})
    if new:
        op["properties"] = {"domain": "meteorology"}
    M.append(("observed-property-roundtrip", op, None))

    obs = ann("Observations", 1001, ["Datastream", "FeatureOfInterest"], v)
    obs.update({"phenomenonTime": "2026-04-05T06:06:00Z/2026-04-05T06:07:00Z", "result": 14.25,
                "resultTime": "2026-04-05T06:07:01.5Z",
                "validTime": "2026-04-05T06:07:00Z/2026-04-05T07:07:00Z",
                "parameters": {"samples": 60, "qc": "passed"}})
    M.append(("observation-roundtrip", obs,
              "resultTime is time_ms; result is residue (the when on result does not map it) and is written after the mapped members"))

    foi = ann("FeaturesOfInterest", 8, ["Observations"], v)
    foi.update({"name": "Mast 3 air", "description": "Air at the mast",
                "encodingType": "application/geo+json",
                "feature": {"type": "Point", "coordinates": [8.6821, 50.1109]}})
    M.append(("feature-of-interest-point-roundtrip", foi, None))

    foif = {"name": "Lake buoy", "description": "Surface water at the buoy",
            "encodingType": "application/geo+json",
            "feature": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [9.17, 47.65]}}}
    M.append(("feature-of-interest-feature-point-roundtrip", foif, None))

    foil = {"name": "River reach", "description": "Reach between two gauges",
            "encodingType": "application/geo+json",
            "feature": {"type": "LineString", "coordinates": [[9.1, 47.6], [9.2, 47.7]]}}
    M.append(("feature-of-interest-line-roundtrip", foil,
              "a geometry other than a Point: its type is kept, its coordinates are not carried"))
    return M


def multidatastream():
    md = ann("MultiDatastreams", 1, ["Thing", "Sensor", "ObservedProperties", "Observations"], "1.0")
    md.update({"name": "Wind", "description": "Wind speed and direction, ten-minute means",
               "unitOfMeasurements": [
                   {"name": "metre per second", "symbol": "m/s", "definition": "http://unitsofmeasure.org/ucum.html"},
                   {"name": "degree", "symbol": "deg", "definition": "http://unitsofmeasure.org/ucum.html"}],
               "observationType": "http://www.opengis.net/def/observationType/OGC-OM/2.0/OM_ComplexObservation",
               "multiObservationDataTypes": [
                   "http://www.opengis.net/def/observationType/OGC-OM/2.0/OM_Measurement",
                   "http://www.opengis.net/def/observationType/OGC-OM/2.0/OM_Measurement"],
               "phenomenonTime": "2026-01-01T00:00:00Z/2026-04-05T06:00:00Z"})
    return md


def build_vectors():
    out = {}
    for fmt, v, ref in (("sensorthings-1.1", "1.1", REF11), ("sensorthings-1.0", "1.0", REF10)):
        V = {}
        n = 1
        if v == "1.0":
            V["%02d-multidatastream-roundtrip" % n] = roundtrip(
                fmt, "multidatastream-roundtrip", multidatastream(), ref,
                "unitOfMeasurements is a group of objects, multiObservationDataTypes a group of strings")
            n += 1
        for name, obj, note in messages(v):
            V["%02d-%s" % (n, name)] = roundtrip(fmt, name, obj, ref, note)
            n += 1

        # an Observation with an offset time and a result that is an object
        o = {"phenomenonTime": "2026-04-05T08:07:00+02:00", "resultTime": "2026-04-05T08:07:01.250+02:00",
             "result": {"speed": 4.5, "direction": 270}}
        V["%02d-observation-offset-time-object-result" % n] = roundtrip(
            fmt, "observation-offset-time-object-result", o, ref,
            "resultTime is read with its offset and written in UTC with Z (iso8601_short); phenomenonTime is "
            "raw text and keeps its offset; an object result is carried member by member as residue")
        n += 1

        # a create body of an Observation (an MQTT publish body has the same form): the
        # link to the Datastream is an object holding only @iot.id, which is dropped
        o = {"phenomenonTime": "2026-04-05T06:07:00Z", "result": 14.5, "Datastream": {"@iot.id": 2}}
        V["%02d-observation-create-body" % n] = roundtrip(
            fmt, "observation-create-body", o, ref,
            "the Datastream link holds only @iot.id, which is not addressable; the object is then empty and not written")
        n += 1

        if v == "1.0":
            o = {"phenomenonTime": "2026-04-05T06:00:00Z", "resultTime": "2026-04-05T06:00:05Z",
                 "result": [3.5, 270]}
            V["%02d-multidatastream-observation-array-result-dropped" % n] = roundtrip(
                fmt, "multidatastream-observation-array-result-dropped", o, ref,
                "the result of a MultiDatastream's Observation is an array; arrays no group maps are not carried, "
                "so the output has no result (pack.md, not mapped)")
            n += 1

        # to geojson: a Thing (callsign), a HistoricalLocation (time_ms), an Observation (time_ms)
        t = {"name": "Weather mast 3", "description": "Ten-metre mast on the north field"}
        V["%02d-thing-to-geojson" % n] = vec(
            "thing-to-geojson", fmt, "geojson", js(t),
            '{"type":"Feature","geometry":null,"properties":{"callsign":"Weather mast 3"}}',
            {"@kind": "Thing", "callsign": t["name"]}, ref=ref,
            note="name is callsign; a Thing has no position the pack can bind, so geometry is null")
        n += 1
        h = {"time": "2026-04-05T06:07:08.25Z"}
        V["%02d-historical-location-to-geojson" % n] = vec(
            "historical-location-to-geojson", fmt, "geojson", js(h),
            '{"type":"Feature","geometry":null,"properties":{"time_ms":%d}}' % iso_ms(h["time"]),
            {"@kind": "HistoricalLocation", "time_ms": str(iso_ms(h["time"]))}, ref=ref)
        n += 1
        o = {"phenomenonTime": "2026-04-05T06:07:00Z", "result": 14.25, "resultTime": "2026-04-05T06:07:01Z"}
        V["%02d-observation-to-geojson" % n] = vec(
            "observation-to-geojson", fmt, "geojson", js(o),
            '{"type":"Feature","geometry":null,"properties":{"time_ms":%d}}' % iso_ms(o["resultTime"]),
            {"@kind": "Observation", "time_ms": str(iso_ms(o["resultTime"])),
             P + "phenomenon_time": o["phenomenonTime"]}, ref=ref,
            note="resultTime is time_ms; the result and phenomenonTime have no geojson line")
        n += 1

        # errors
        V["%02d-no-entity-member-is-no-kind" % n] = vec(
            "no-entity-member-is-no-kind", fmt, fmt, js({"@iot.id": 1, "value": 3}), error="no-kind", ref=ref,
            note="an object with none of the members that select a kind")
        n += 1
        V["%02d-result-time-not-an-instant" % n] = vec(
            "result-time-not-an-instant", fmt, fmt,
            js({"phenomenonTime": "2026-04-05T06:07:00Z", "result": 1, "resultTime": "2026-04-05"}),
            error="transform-decode", ref=ref,
            note="resultTime is an instant with a time of day; a date alone is refused by iso8601_short (ruling 3 of 0.11)")
        n += 1
        out[fmt] = V
    return out


def geojson_vectors():
    G = {}
    gin = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[8.6821,50.1109]},'
           '"properties":{"time_ms":1775369228000,"callsign":"Mast 3"},"id":"m3"}')
    for fmt in ("sensorthings-1.1", "sensorthings-1.0"):
        G["to-%s-historical-location" % fmt] = vec(
            "to-%s-historical-location" % fmt, "geojson", fmt, gin,
            '{"time":"%s"}' % ms_short(1775369228000), {"time_ms": "1775369228000", "callsign": "Mast 3"},
            ref=REF11 if fmt.endswith("1.1") else REF10,
            note="encode takes the first kind whose requires hold: HistoricalLocation (time_ms) comes before "
                 "Thing (callsign); the position and the id have no line in that kind")
        gin2 = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[8.6821,50.1109]},'
                '"properties":{"callsign":"Mast 3"}}')
        G["to-%s-thing" % fmt] = vec(
            "to-%s-thing" % fmt, "geojson", fmt, gin2, '{"name":"Mast 3"}', {"callsign": "Mast 3"},
            ref=REF11 if fmt.endswith("1.1") else REF10,
            note="with no time_ms the entity qualifies for Thing only (callsign)")
    return G


def build(out):
    written = {}
    for fmt, V in build_vectors().items():
        for fn, v in V.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), json.dumps(v, indent=2, ensure_ascii=False) + "\n")
            written[fmt] = written.get(fmt, 0) + 1
    for fn, v in geojson_vectors().items():
        out.write("packs/geojson/vectors/%s.json" % fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        written["geojson"] = written.get("geojson", 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("sensorthings-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
