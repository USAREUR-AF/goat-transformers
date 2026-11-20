#!/usr/bin/env python3
"""Write the vectors of the nhc-storm and nhc-current-storms packs.

The packs read the NHC Tropical Cyclone Status JSON file (CurrentStorms.json), described
by the NHC file reference (www.nhc.noaa.gov/productexamples/
NHC_Tropical_Cyclone_Status_JSON_File_Reference.pdf; US Government work). This script holds
its own copy of the member paths in the order the packs list them, builds every storm from
values written for these vectors (none is taken from the reference's or the site's example
files), and works out the canonical output, the decoded values and the GeoJSON and CoT forms
by the rules of spec/engine-spec.md (0.5 json: mapped members in line order, nested objects
at their first line, then residue scalars in input order, null not carried; 0.6 derive; 0.7
groups, items without residue) and of the geojson and cot-xml packs. It reads no pack.def
and calls no goat-transformers engine.

Usage: python3 -I tools/gen/nhc-vectors.py [--out DIR] [--check]
"""
import collections
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/nhc-vectors.py from the NHC JSON file reference and spec/engine-spec.md; no engine run"
REF = "NHC Tropical Cyclone Status JSON File Reference (2019-04-08), www.nhc.noaa.gov/productexamples/ (read 2026-11-20)"

# (member path, transform) in pack line order: s string, f float, t iso8601_ms
ADV = ["publicAdvisory", "forecastAdvisory", "windSpeedProbabilities", "forecastDiscussion", "forecastGraphics"]
GIS = ["forecastTrack", "windWatchesWarnings", "trackCone", "initialWindExtent", "forecastWindRadiiGIS"]
TOA = ["earliestArrivalTimeTSWindsGIS", "mostLikelyTimeTSWindsGIS"]
LINES = ([("id", "s"), ("binNumber", "s"), ("name", "s"), ("classification", "s"), ("latitude", "s"),
          ("longitude", "s"), ("latitudeNumeric", "f"), ("longitudeNumeric", "f"), ("movementDir", "f"),
          ("movementSpeed", "f"), ("lastUpdate", "t")]
         + [(o + "." + m, "s") for o in ADV for m in ("advNum", "issuance", "url")]
         + [(o + "." + m, "s") for o in GIS for m in ("advNum", "issuance", "zipFile", "kmzFile")]
         + [("bestTrackGIS.zipFile", "s"), ("bestTrackGIS.kmzFile", "s")]
         + [(o + "." + m, "s") for o in TOA for m in ("advNum", "issuance", "kmzFile")]
         + [("windSpeedProbabilitiesGIS." + m, "s") for m in ("issuance", "zipFile5km", "zipFile0p5deg",
                                                              "kmzFile34kt", "kmzFile50kt", "kmzFile64kt")])


def num(x):
    x = float(x)
    if x == 0:
        return 0
    r = repr(x)
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
    return r[:-2] if r.endswith(".0") else r


def iso_ms(t):
    t2 = t[:-1]
    ms = 0
    if "." in t2:
        t2, frac = t2.split(".")
        ms = int((frac + "000")[:3])
    d = datetime.datetime.strptime(t2, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp()) * 1000 + ms


def ms_iso(ms):
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


class Raw(str):
    """Number text written as it is (not quoted)."""


def get(obj, path):
    for p in path.split("."):
        if not isinstance(obj, dict) or p not in obj:
            return None
        obj = obj[p]
    return obj


def canon_tree(obj, residue):
    """The output tree: mapped members in line order, then (with residue) the residue
    scalars of each object in input order; null members are not carried."""
    tree = collections.OrderedDict()
    for path, tr in LINES:
        v = get(obj, path)
        if v is None:
            continue
        if tr == "f":
            v = Raw(str(num(v)))
        elif tr == "t":
            v = ms_iso(iso_ms(v))
        node = tree
        parts = path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, collections.OrderedDict())
        node[parts[-1]] = v

    def add(src, dst):
        for k, v in src.items():
            if v is None or isinstance(v, list):
                continue
            if isinstance(v, dict):
                sub = dst.get(k)
                fresh = sub is None
                sub = sub if sub is not None else collections.OrderedDict()
                add(v, sub)
                if fresh and sub:
                    dst[k] = sub
            elif k not in dst:
                dst[k] = Raw(json.dumps(v)) if not isinstance(v, str) else v
    if residue:
        add(obj, tree)
    return tree


def dumps(tree):
    if isinstance(tree, dict):
        return "{" + ",".join("%s:%s" % (json.dumps(k), dumps(v)) for k, v in tree.items()) + "}"
    if isinstance(tree, Raw):
        return str(tree)
    return json.dumps(tree, ensure_ascii=False)


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


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


def adv(n, kind, issued, base="https://www.hurricanes.example/archive/2026/al99/"):
    return {"advNum": n, "issuance": issued, "url": base + "al992026.%s.%s.shtml" % (kind, n)}


def gis(n, issued, tag):
    return {"advNum": n, "issuance": issued, "fileUpdateTime": issued,
            "zipFile": "https://www.hurricanes.example/gis/al992026_%s_%s.zip" % (tag, n),
            "kmzFile": "https://www.hurricanes.example/gis/AL992026_%sadv_%s.kmz" % (n, tag)}


def storm(name="Example", sid="al992026", lat=24.5, lon=-71.25, mdir=315, mph=12, last="2026-09-14T21:00:00.000Z"):
    iss = "2026-09-14T21:00:00.000Z"
    s = collections.OrderedDict([
        ("id", sid), ("binNumber", "AT4"), ("name", name), ("classification", "HU"),
        ("intensity", "85"), ("pressure", "972"), ("latitude", "24.5N"), ("longitude", "71.3W"),
        ("latitudeNumeric", lat), ("longitudeNumeric", lon), ("movementDir", mdir), ("movementSpeed", mph),
        ("lastUpdate", last),
        ("publicAdvisory", adv("023", "public", iss)), ("forecastAdvisory", adv("023", "fstadv", iss)),
        ("windSpeedProbabilities", adv("023", "wndprb", iss)), ("forecastDiscussion", adv("023", "discus", iss)),
        ("forecastGraphics", {"advNum": "023", "issuance": iss, "url": "https://www.hurricanes.example/graphics_at4.shtml"}),
        ("forecastTrack", gis("023", iss, "TRACK")), ("windWatchesWarnings", gis("023", iss, "WW")),
        ("trackCone", gis("023", iss, "CONE")), ("initialWindExtent", gis("023", iss, "initialradii")),
        ("forecastWindRadiiGIS", gis("023", iss, "forecastradii")),
        ("bestTrackGIS", {"zipFile": "https://www.hurricanes.example/gis/al992026_best_track.zip",
                          "kmzFile": "https://www.hurricanes.example/gis/al992026_best_track.kmz"}),
        ("earliestArrivalTimeTSWindsGIS", {"advNum": "023", "issuance": iss, "kmzFile": "https://www.hurricanes.example/gis/AL992026_023adv_earliest_toa_34.kmz"}),
        ("mostLikelyTimeTSWindsGIS", {"advNum": "023", "issuance": iss, "kmzFile": "https://www.hurricanes.example/gis/AL992026_023adv_most_likely_toa_34.kmz"}),
        ("windSpeedProbabilitiesGIS", {"issuance": "2026-09-14T18:00:00.000Z",
                                       "zipFile5km": "https://www.hurricanes.example/gis/2026091418_wsp_120hr5km.zip",
                                       "zipFile0p5deg": "https://www.hurricanes.example/gis/2026091418_wsp_120hrhalfDeg.zip",
                                       "kmzFile34kt": "https://www.hurricanes.example/gis/2026091418_wsp34knt120hr_5km.kmz",
                                       "kmzFile50kt": "https://www.hurricanes.example/gis/2026091418_wsp50knt120hr_5km.kmz",
                                       "kmzFile64kt": "https://www.hurricanes.example/gis/2026091418_wsp64knt120hr_5km.kmz"}),
        ("stormSurgeWatchWarningGIS", None),
        ("potentialStormSurgeFloodingGIS", {"advNum": "023", "issuance": iss,
                                            "zipFile": "https://www.hurricanes.example/gis/al992026_psurge_023.zip"})])
    return s


def model_of(s):
    return {"uid": s["id"], "callsign": s["name"], "lat": str(num(s["latitudeNumeric"])),
            "lon": str(num(s["longitudeNumeric"])), "course": str(num(s["movementDir"])),
            "nhc.movement_speed_mph": str(num(s["movementSpeed"])), "time_ms": str(iso_ms(s["lastUpdate"]))}


def storm_vectors():
    V = {}
    s = storm()
    m = model_of(s)
    m["nhc.public_advisory_adv_num"] = "023"
    V["01-storm-roundtrip"] = vec("storm-roundtrip", "nhc-storm", "nhc-storm", js(s), dumps(canon_tree(s, True)), m,
        note="every documented member; intensity and pressure (text in the site's example file, numbers in the reference) are residue and come back as sent; fileUpdateTime, which the reference does not list, is residue inside its object; the null storm surge member is dropped; the unmapped storm surge flooding object is residue")
    n = storm()
    n["intensity"], n["pressure"] = 85, 972
    V["02-storm-numeric-intensity"] = vec("storm-numeric-intensity", "nhc-storm", "nhc-storm", js(n),
        dumps(canon_tree(n, True)), {"uid": "al992026"},
        note="intensity and pressure as numbers, as the reference shows them: residue keeps the type")
    sp = s["movementSpeed"] * 1609344 / 3600000
    ms = iso_ms(s["lastUpdate"])
    gj = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"time_ms":%d,'
          '"callsign":%s,"course":%s,"speed_ms":%s},"id":%s}') % (
        num(s["longitudeNumeric"]), num(s["latitudeNumeric"]), ms, json.dumps(s["name"]), num(s["movementDir"]),
        num(sp), json.dumps(s["id"]))
    V["03-storm-to-geojson"] = vec("storm-to-geojson", "nhc-storm", "geojson", js(s), gj,
        {"@complete": True, "speed_ms": str(num(sp))},
        note="movementSpeed 12 mph is speed_ms 12 * 1609344 / 3600000 = 5.36448 (model/nhc.def); movementDir is course")
    t = ms_iso(ms)
    cot = ('<event version="2.0" uid=%s type="a-u-X" time="%s" start="%s"><point lat="%s" lon="%s" hae="9999999" '
           'ce="9999999" le="9999999"/><detail><contact callsign=%s/><track course="%s" speed="%s"/></detail></event>') % (
        json.dumps(s["id"]), t, t, num(s["latitudeNumeric"]), num(s["longitudeNumeric"]), json.dumps(s["name"]),
        num(s["movementDir"]), num(sp))
    V["04-storm-to-cot-xml"] = vec("storm-to-cot-xml", "nhc-storm", "cot-xml", js(s), cot,
        note="cot-xml writes its defaults for type, hae, ce and le, and its detail element after the point")
    bad = storm(last="2026-09-14 21:00")
    V["05-last-update-not-iso"] = vec("last-update-not-iso", "nhc-storm", "nhc-storm", js(bad), error="transform-decode",
        note="lastUpdate is ISO 8601 UTC; other text fails iso8601_ms")
    return V


def geojson_to_storm():
    inp = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[-71.25,24.5,0]},"properties":'
           '{"time_ms":1789419600000,"callsign":"Example","course":315,"speed_ms":5.36448},"id":"al992026"}')
    exp = ('{"id":"al992026","name":"Example","latitudeNumeric":24.5,"longitudeNumeric":-71.25,"movementDir":315,'
           '"movementSpeed":12,"lastUpdate":"%s"}') % ms_iso(1789419600000)
    return vec("to-nhc-storm", "geojson", "nhc-storm", inp, exp,
               {"@complete": True, "nhc.movement_speed_mph": "12"},
               note="speed_ms 5.36448 is movementSpeed 5.36448 * 3600000 / 1609344 = 12 mph; hae has no nhc line")


def file_vectors():
    V = {}
    a, b = storm(), storm(name="Second", sid="ep992026", lat=15.75, lon=-110.5, mdir=290, mph=9)
    for s in (a, b):
        del s["potentialStormSurgeFloodingGIS"]
        for o in GIS:
            del s[o]["fileUpdateTime"]
        del s["intensity"], s["pressure"]
    doc = {"activeStorms": [a, b]}
    exp = '{"activeStorms":[%s,%s]}' % (dumps(canon_tree(a, False)), dumps(canon_tree(b, False)))
    V["01-file-roundtrip"] = vec("file-roundtrip", "nhc-current-storms", "nhc-current-storms", js(doc), exp,
        {"nhc.storms.#": "2", "nhc.storms[0].uid": "al992026", "nhc.storms[1].lat": "15.75",
         "nhc.storms[1].time_ms": str(iso_ms(b["lastUpdate"]))},
        note="two storms, every documented member mapped; the null storm surge member is absent")
    V["02-no-active-storms"] = vec("no-active-storms", "nhc-current-storms", "nhc-current-storms",
        '{"activeStorms":[]}', '{"activeStorms":[]}', {"nhc.storms.#": "0"},
        note="no active storm: the reference gives the file as an empty activeStorms array")
    c = storm()
    doc = {"activeStorms": [c]}
    exp = '{"activeStorms":[%s]}' % dumps(canon_tree(c, False))
    V["03-item-residue-dropped"] = vec("item-residue-dropped", "nhc-current-storms", "nhc-current-storms", js(doc), exp,
        {"nhc.storms.#": "1"}, note="an item carries no residue (0.7): intensity, pressure, fileUpdateTime and the storm surge flooding object are dropped")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fn, v in storm_vectors().items():
        out.write("packs/nhc-storm/vectors/%s.json" % fn, dump(v))
        w["nhc-storm"] = w.get("nhc-storm", 0) + 1
    for fn, v in file_vectors().items():
        out.write("packs/nhc-current-storms/vectors/%s.json" % fn, dump(v))
        w["nhc-current-storms"] = w.get("nhc-current-storms", 0) + 1
    out.write("packs/geojson/vectors/99-to-nhc-storm.json", dump(geojson_to_storm()))
    w["geojson"] = 1
    return w


def main(argv=None):
    return genio.vector_main("nhc-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
