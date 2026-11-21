#!/usr/bin/env python3
"""Write the vectors of the ea-flood-station, ea-flood-readings and ea-flood-warnings packs.

Every response is built here from values written for these vectors (no live response and no
example of the API reference is used). This script holds its own copy of the members each pack
maps, in line order, and works out the canonical output by the rules of spec/engine-spec.md: 0.5
(json wire: mapped members in line order, a nested object at the position of the first line that
addresses into it, then scalar residue in input order at any depth of nested objects; arrays and
null are not carried; ruling 16: two lines on one locator write the earliest present key), 0.7
(groups: items carry no residue) and ruling 3 of 0.1.1 (number text). It reads no pack.def and
calls no goat-transformers engine.

Usage: python3 -I tools/gen/hydro-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/hydro-vectors.py from responses written for it and spec/engine-spec.md; no engine run"
REF = "Environment Agency real-time flood-monitoring API reference (environment.data.gov.uk/flood-monitoring/doc/reference)"


def F(path, key, tr):
    return ("f", tuple(path.split(".")) if path != "." else (), key, tr)


def G(path, lst, body):
    return ("g", tuple(path.split(".")), lst, body)


STATION = [F("@context", "eaflood.context", "string"), F("items.@id", "eaflood.station_uri", "string"),
           F("items.lat", "lat", "float"), F("items.lat", "eaflood.station_lat", "float"),
           F("items.long", "lon", "float"), F("items.long", "eaflood.station_long", "float")] + [
    F("items." + m, "eaflood." + k, t) for m, k, t in (
        ("notation", "notation", "string"), ("label", "label", "string"), ("RLOIid", "rloi_id", "string"),
        ("catchmentName", "catchment_name", "string"), ("dateOpened", "date_opened", "string"),
        ("datumOffset", "datum_offset", "float"), ("eaAreaName", "ea_area_name", "string"),
        ("eaRegionName", "ea_region_name", "string"), ("easting", "easting", "int"), ("northing", "northing", "int"),
        ("riverName", "river_name", "string"), ("stationReference", "station_reference", "string"),
        ("town", "town", "string"), ("wiskiID", "wiski_id", "string"))] + [
    G("items.measures", "eaflood.measures", [F(m, "eaflood." + k, t) for m, k, t in (
        ("@id", "measure_uri", "string"), ("label", "measure_label", "string"), ("parameter", "parameter", "string"),
        ("parameterName", "parameter_name", "string"), ("period", "period", "float"), ("qualifier", "qualifier", "string"),
        ("unitName", "unit_name", "string"), ("datumType", "datum_type", "string"),
        ("latestReading.dateTime", "latest_reading_time", "string"), ("latestReading.value", "latest_reading_value", "float"))])]

READINGS = [F("@context", "eaflood.context", "string"),
            G("items", "eaflood.readings", [F("@id", "eaflood.reading_uri", "string"), F("dateTime", "eaflood.reading_time", "string"),
                                             F("measure", "eaflood.reading_measure", "string"), F("value", "eaflood.reading_value", "float")])]

WARNINGS = [F("@context", "eaflood.context", "string"),
            G("items", "eaflood.floods", [F(m, "eaflood." + k, t) for m, k, t in (
                ("@id", "flood_uri", "string"), ("description", "flood_description", "string"),
                ("eaAreaName", "ea_area_name", "string"), ("eaRegionName", "ea_region_name", "string"),
                ("floodAreaID", "flood_area_id", "string"), ("message", "flood_message", "string"),
                ("severity", "severity", "string"), ("severityLevel", "severity_level", "int"),
                ("timeMessageChanged", "time_message_changed", "string"), ("timeRaised", "time_raised", "string"),
                ("timeSeverityChanged", "time_severity_changed", "string"), ("floodArea.county", "flood_area_county", "string"),
                ("floodArea.notation", "flood_area_notation", "string"), ("floodArea.polygon", "flood_area_polygon", "string"),
                ("floodArea.riverOrSea", "flood_area_river_or_sea", "string"))])]


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


ROOT = "http://environment.data.gov.uk/flood-monitoring"
META = {"publisher": "Environment Agency", "licence": "http://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "documentation": ROOT + "/doc/reference", "version": "0.9", "hasFormat": [ROOT + "/id/stations/E1234.csv"]}


def station():
    return {"@context": ROOT + "/meta/context.jsonld", "meta": META,
            "items": {"@id": ROOT + "/id/stations/E1234", "RLOIid": "9001", "catchmentName": "Example Catchment",
                      "dateOpened": "1994-04-01", "datumOffset": 52.5, "eaAreaName": "Example Area", "eaRegionName": "Example Region",
                      "easting": 452000, "label": "Example Mill", "lat": 51.7562, "long": -1.2387,
                      "measures": [{"@id": ROOT + "/id/measures/E1234-level-stage-i-15_min-mASD",
                                    "datumType": ROOT + "/def/core/datumASD", "label": "Example Mill - level-stage-i-15_min-mASD",
                                    "latestReading": {"@id": ROOT + "/data/readings/E1234-level-stage-i-15_min-mASD/2026-11-21T06-00-00Z",
                                                      "date": "2026-11-21", "dateTime": "2026-11-21T06:00:00Z",
                                                      "measure": ROOT + "/id/measures/E1234-level-stage-i-15_min-mASD", "value": 1.234},
                                    "notation": "E1234-level-stage-i-15_min-mASD", "parameter": "level", "parameterName": "Water Level",
                                    "period": 900, "qualifier": "Stage", "station": ROOT + "/id/stations/E1234",
                                    "stationReference": "E1234", "type": ["http://environment.data.gov.uk/flood-monitoring/def/core/Measure"],
                                    "unit": "http://qudt.org/1.1/vocab/unit#Meter", "unitName": "mASD", "valueType": "instantaneous"}],
                      "northing": 207000, "notation": "E1234", "riverName": "River Example",
                      "stageScale": {"@id": ROOT + "/id/stations/E1234/stageScale", "scaleMax": 4, "typicalRangeHigh": 1.605,
                                     "typicalRangeLow": 0.727, "maxOnRecord": {"dateTime": "2024-11-27T01:30:00", "value": 2.756}},
                      "stationReference": "E1234", "town": "Example Town", "wiskiID": "2200E1234"}}


def station_vectors():
    V = {}
    F_ = "ea-flood-station"
    s = station()
    V["01-station-roundtrip"] = vec(F_, "station-roundtrip", STATION, s, [
        "lat", "lon", "eaflood.station_lat", "eaflood.notation", "eaflood.easting", "eaflood.datum_offset",
        "eaflood.measures.#", "eaflood.measures[0].eaflood.unit_name", "eaflood.measures[0].eaflood.latest_reading_value",
        "eaflood.measures[0].eaflood.period"],
        note="one station: the mapped members in line order, then the residue (meta's scalars, the stage scale with "
             "its record, nested); arrays (hasFormat) are not carried, and inside a measure only the mapped members come back")
    gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{}}' % (num(-1.2387), num(51.7562))
    V["02-station-to-geojson"] = vec(F_, "station-to-geojson", STATION, s, [], to="geojson", expect=gj,
                                     note="the station's position reaches a GeoJSON Feature")
    bad = station()
    bad["items"]["lat"] = "51.7562"
    V["03-latitude-as-text"] = vec(F_, "latitude-as-text", STATION, bad, [], error="transform-decode",
                                   note="lat is a JSON number; text there is a transform failure")
    return V


def readings_vectors():
    V = {}
    F_ = "ea-flood-readings"
    r = {"@context": ROOT + "/meta/context.jsonld", "meta": dict(META, limit=2),
         "items": [{"@id": ROOT + "/data/readings/E1234-level-stage-i-15_min-mASD/2026-11-21T06-00-00Z",
                    "dateTime": "2026-11-21T06:00:00Z", "measure": ROOT + "/id/measures/E1234-level-stage-i-15_min-mASD",
                    "value": 1.234},
                   {"@id": ROOT + "/data/readings/E1234-level-stage-i-15_min-mASD/2026-11-21T05-45-00Z",
                    "dateTime": "2026-11-21T05:45:00Z", "measure": ROOT + "/id/measures/E1234-level-stage-i-15_min-mASD"}]}
    V["01-readings-roundtrip"] = vec(F_, "readings-roundtrip", READINGS, r, [
        "eaflood.readings.#", "eaflood.readings[0].eaflood.reading_time", "eaflood.readings[0].eaflood.reading_value"],
        note="two readings, the second without a value (a reading that is not a number omits it)")
    return V


def warnings_vectors():
    V = {}
    F_ = "ea-flood-warnings"
    w = {"@context": ROOT + "/meta/context.jsonld", "meta": META,
         "items": [{"@id": ROOT + "/id/floods/061WAF10Example", "description": "River Example at Example Town",
                    "eaAreaName": "Example Area", "eaRegionName": "No longer used",
                    "floodArea": {"@id": ROOT + "/id/floodAreas/061WAF10Example", "county": "Exampleshire",
                                  "notation": "061WAF10Example", "polygon": ROOT + "/id/floodAreas/061WAF10Example/polygon",
                                  "riverOrSea": "River Example"},
                    "floodAreaID": "061WAF10Example", "isTidal": False, "message": "River levels are rising.",
                    "severity": "Flood Alert", "severityLevel": 3, "timeMessageChanged": "2026-11-21T05:12:00",
                    "timeRaised": "2026-11-21T05:12:31", "timeSeverityChanged": "2026-11-20T18:00:00"}]}
    V["01-warnings-roundtrip"] = vec(F_, "warnings-roundtrip", WARNINGS, w, [
        "eaflood.floods.#", "eaflood.floods[0].eaflood.severity_level", "eaflood.floods[0].eaflood.flood_area_county",
        "eaflood.floods[0].eaflood.time_raised"],
        note="one flood alert; the area's @id and isTidal, unmapped inside an item, are dropped")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("ea-flood-station", station_vectors()), ("ea-flood-readings", readings_vectors()),
                    ("ea-flood-warnings", warnings_vectors())):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("hydro-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
