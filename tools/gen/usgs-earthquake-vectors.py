#!/usr/bin/env python3
"""Write the vectors of the usgs-earthquake and usgs-earthquake-feed packs.

The packs read the USGS Earthquake Hazards Program GeoJSON summary feed
(earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php; US Government work, public
domain): one event as a GeoJSON Feature (geojson wire), and the whole feed as a JSON
object (json wire). This script holds its own copy of the documented member list, in
the order the packs list it, builds every event from values written for these vectors
(none is taken from a live feed), and works out the canonical output, the decoded values
and the GeoJSON and CoT forms by the rules of spec/engine-spec.md (0.1 geojson and its
rulings, 0.5 json, 0.6 const and default, 0.7 groups) and of the geojson and cot-xml
packs. It reads no pack.def and calls no goat-transformers engine.

Usage: python3 -I tools/gen/usgs-earthquake-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = ("USGS GeoJSON Summary Format (earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php, read 2026-11-20); "
       "ComCat event terms (data/comcat/index.php, archived 2026-04-14)")
SOURCE = "derived by tools/gen/usgs-earthquake-vectors.py from the documented member list and spec/engine-spec.md; no engine run"

# properties members in pack line order: (member, transform, model key); f float, i int, s string
PROPS = [("mag", "f", "usgsquake.mag"), ("place", "s", "usgsquake.place"), ("time", "i", "time_ms"),
         ("updated", "i", "usgsquake.updated"), ("tz", "i", "usgsquake.tz"), ("url", "s", "usgsquake.url"),
         ("detail", "s", "usgsquake.detail"), ("felt", "i", "usgsquake.felt"), ("cdi", "f", "usgsquake.cdi"),
         ("mmi", "f", "usgsquake.mmi"), ("alert", "s", "usgsquake.alert"), ("status", "s", "usgsquake.status"),
         ("tsunami", "i", "usgsquake.tsunami"), ("sig", "i", "usgsquake.sig"), ("net", "s", "usgsquake.net"),
         ("code", "s", "usgsquake.code"), ("ids", "s", "usgsquake.ids"), ("sources", "s", "usgsquake.sources"),
         ("types", "s", "usgsquake.types"), ("nst", "i", "usgsquake.nst"), ("dmin", "f", "usgsquake.dmin"),
         ("rms", "f", "usgsquake.rms"), ("gap", "f", "usgsquake.gap"), ("magType", "s", "usgsquake.mag_type"),
         ("type", "s", "usgsquake.event_type")]
# the members the feed sends as null for most events (tz always, felt, cdi, mmi and alert for
# events without felt reports or PAGER, dmin now and then) are not lines of the geojson pack: on
# that wire a null under a field fails its transform. They are residue there (null dropped, a
# number back as a string: ruling 13 of 0.6); the json feed pack maps them.
NULLABLE = {"tz", "felt", "cdi", "mmi", "alert", "dmin"}
GEO_PROPS = [x for x in PROPS if x[0] not in NULLABLE]
META = [("generated", "i", "time_ms"), ("url", "s", "usgsquake.feed_url"), ("title", "s", "usgsquake.feed_title"),
        ("api", "s", "usgsquake.feed_api"), ("count", "i", "usgsquake.feed_count"),
        ("status", "i", "usgsquake.feed_status")]


def num(x):
    """Number text the encoders write (ruling 3 of 0.1.1)."""
    x = float(x)
    if x == 0:
        return "0"
    r = repr(x)
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
    return r[:-2] if r.endswith(".0") else r


def ms_iso(ms):
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def jstr(s):
    return json.dumps(s, ensure_ascii=False)


def val(v, tr):
    if tr == "s":
        return jstr(v)
    if tr == "i":
        return str(int(v))
    return num(v)


def mtext(v, tr):
    return v if tr == "s" else (str(int(v)) if tr == "i" else num(v))


def props_text(p, members, residue):
    """`properties` in line order; then, on the geojson wire, residue members in input order:
    a string as it was, a number as a string of its text as written, null dropped (ruling 13
    of 0.6)."""
    parts = ['"%s":%s' % (m, val(p[m], tr)) for m, tr, _ in members if p.get(m) is not None]
    if residue:
        known = {m for m, _, _ in members}
        for k, v in p.items():
            if k in known or v is None or isinstance(v, (list, dict)):
                continue
            parts.append('"%s":%s' % (k, jstr(v) if isinstance(v, str) else jstr(json.dumps(v))))
    return "{" + ",".join(parts) + "}"


def feature_canon(f):
    """geojson wire (0.1, ruling 4 of 0.1.1): type, geometry, properties, then id."""
    lon, lat, depth = f["geometry"]["coordinates"]
    return '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,%s]},"properties":%s,"id":%s}' % (
        num(lon), num(lat), num(depth), props_text(f["properties"], GEO_PROPS, True), jstr(f["id"]))


def item_canon(f):
    """json wire item (0.7): const type, properties (no residue), geometry, id."""
    c = ",".join(num(x) for x in f["geometry"]["coordinates"])
    return '{"type":"Feature","properties":%s,"geometry":{"type":"Point","coordinates":[%s]},"id":%s}' % (
        props_text(f["properties"], PROPS, False), c, jstr(f["id"]))


def feed_canon(d):
    m = d["metadata"]
    meta = ",".join('"%s":%s' % (k, val(m[k], tr)) for k, tr, _ in META if k in m)
    return '{"type":"FeatureCollection","metadata":{%s},"bbox":[%s],"features":[%s]}' % (
        meta, ",".join(num(x) for x in d["bbox"]), ",".join(item_canon(f) for f in d["features"]))


def model_of(f, members=None):
    lon, lat, depth = f["geometry"]["coordinates"]
    m = {"uid": f["id"], "lon": num(lon), "lat": num(lat), "usgsquake.depth_km": num(depth)}
    for k, tr, key in members or GEO_PROPS:
        if f["properties"].get(k) is not None:
            m[key] = mtext(f["properties"][k], tr)
    return m


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


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


# -- events written for these vectors --------------------------------------------------------

def event_a():
    return {"type": "Feature", "properties": {
        "mag": 4.25, "place": "12 km SSW of Example Town, Region", "time": 1772600767250, "updated": 1772601888125,
        "tz": None, "url": "https://earthquake.usgs.gov/earthquakes/eventpage/zz00000001",
        "detail": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/zz00000001.geojson",
        "felt": 37, "cdi": 3.8, "mmi": 4.125, "alert": "green", "status": "reviewed", "tsunami": 0, "sig": 301,
        "net": "zz", "code": "00000001", "ids": ",zz00000001,yy00000042,", "sources": ",zz,yy,",
        "types": ",dyfi,origin,phase-data,shakemap,", "nst": 42, "dmin": 0.0675, "rms": 0.21, "gap": 37.5,
        "magType": "ml", "type": "earthquake"},
        "geometry": {"type": "Point", "coordinates": [-121.6125, 36.7875, 8.25]}, "id": "zz00000001"}


def event_b():
    # many members null, as the feed sends them for a small automatic event
    return {"type": "Feature", "properties": {
        "mag": 1.2, "place": "3 km E of Example Ridge", "time": 1772600000000, "updated": 1772600090000,
        "tz": None, "url": "https://earthquake.usgs.gov/earthquakes/eventpage/zz00000002",
        "detail": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/zz00000002.geojson",
        "felt": None, "cdi": None, "mmi": None, "alert": None, "status": "automatic", "tsunami": 0, "sig": 22,
        "net": "zz", "code": "00000002", "ids": ",zz00000002,", "sources": ",zz,", "types": ",origin,",
        "nst": 9, "dmin": 0.01, "rms": 0.05, "gap": 120, "magType": "md", "type": "earthquake"},
        "geometry": {"type": "Point", "coordinates": [-117.5, 33.875, -0.75]}, "id": "zz00000002"}


def single_vectors():
    V = {}
    a = event_a()
    shuffled = dict(a)
    shuffled["properties"] = dict(sorted(a["properties"].items(), key=lambda kv: kv[0][::-1]))
    shuffled["properties"]["title"] = "M 4.3 - 12 km SSW of Example Town, Region"
    inp = js({"type": "Feature", "id": a["id"], "properties": shuffled["properties"], "geometry": a["geometry"]})
    exp = feature_canon(shuffled)
    m = model_of(a)
    V["01-event-roundtrip"] = vec("event-roundtrip", "usgs-earthquake", "usgs-earthquake", inp, exp, m,
        note="every documented member, in an order of its own; title (sent, but not in the member list) and the members often null (felt, cdi, mmi, alert, dmin) are residue: a number among them comes back as a string; the null tz is dropped; the depth is the third coordinate")
    b = event_b()
    exp = feature_canon(b)
    m = model_of(b)
    V["02-event-nulls-roundtrip"] = vec("event-nulls-roundtrip", "usgs-earthquake", "usgs-earthquake", js(b), exp, m,
        note="the members the feed sends as null are residue on this wire and dropped; a negative depth (above the reference) is kept")
    gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"time_ms":%d},"id":%s}' % (
        num(a["geometry"]["coordinates"][0]), num(a["geometry"]["coordinates"][1]), a["properties"]["time"], jstr(a["id"]))
    V["03-event-to-geojson"] = vec("event-to-geojson", "usgs-earthquake", "geojson", js(a), gj,
        {"lat": num(36.7875), "lon": num(-121.6125), "time_ms": str(a["properties"]["time"]), "uid": a["id"]},
        note="the depth is not hae: the shared GeoJSON Point has two coordinates")
    t = ms_iso(a["properties"]["time"])
    cot = ('<event version="2.0" uid=%s type="a-u-X" time="%s" start="%s"><point lat="%s" lon="%s" hae="9999999" '
           'ce="9999999" le="9999999"/></event>') % (jstr(a["id"]), t, t, num(36.7875), num(-121.6125))
    V["04-event-to-cot-xml"] = vec("event-to-cot-xml", "usgs-earthquake", "cot-xml", js(a), cot,
        note="cot-xml writes its defaults for type, hae, ce and le; the origin time is time and start")
    V["05-time-not-integer"] = vec("time-not-integer", "usgs-earthquake", "usgs-earthquake",
        js({"type": "Feature", "properties": {"time": "soon"}, "geometry": {"type": "Point", "coordinates": [1, 2, 3]}, "id": "x"}),
        error="transform-decode", note="time is a long integer; text that is not an integer fails the int transform")
    return V


def geojson_to_event():
    inp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-121.6125,36.7875,120.5]},"properties":{"time_ms":1772600767250,"callsign":"X"},"id":"zz00000001"}'
    exp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-121.6125,36.7875]},"properties":{"time":1772600767250},"id":"zz00000001"}'
    return vec("to-usgs-earthquake", "geojson", "usgs-earthquake", inp, exp,
               note="hae has no usgs line (depth is not hae), so the Point has two coordinates; callsign has no usgs line")


def feed_vectors():
    V = {}
    d = {"type": "FeatureCollection",
         "metadata": {"generated": 1772602000000, "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
                      "title": "USGS All Earthquakes, Past Hour", "status": 200, "api": "1.10.3", "count": 2},
         "bbox": [-121.6125, 33.875, -0.75, -117.5, 36.7875, 8.25],
         "features": [event_a(), event_b()]}
    m = {"time_ms": "1772602000000", "usgsquake.feed_count": "2", "usgsquake.bbox.#": "6", "usgsquake.events.#": "2",
         "usgsquake.events[0].uid": "zz00000001", "usgsquake.events[0].time_ms": "1772600767250",
         "usgsquake.events[0].usgsquake.coordinates.#": "3", "usgsquake.events[1].usgsquake.status": "automatic"}
    V["01-feed-roundtrip"] = vec("feed-roundtrip", "usgs-earthquake-feed", "usgs-earthquake-feed", js(d), feed_canon(d), m,
        note="metadata members in the document's order; the bbox and each event's coordinates are lists of numbers; null members of an event are absent")
    e = {"type": "FeatureCollection", "metadata": {"generated": 1772602000000, "count": 0, "status": 200},
         "bbox": [], "features": []}
    V["02-empty-feed"] = vec("empty-feed", "usgs-earthquake-feed", "usgs-earthquake-feed", js(e),
        '{"type":"FeatureCollection","metadata":{"generated":1772602000000,"count":0,"status":200},"bbox":[],"features":[]}',
        {"usgsquake.events.#": "0"}, note="a feed with no events: present, empty lists are written as []")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fn, v in single_vectors().items():
        out.write("packs/usgs-earthquake/vectors/%s.json" % fn, dump(v))
        w["usgs-earthquake"] = w.get("usgs-earthquake", 0) + 1
    for fn, v in feed_vectors().items():
        out.write("packs/usgs-earthquake-feed/vectors/%s.json" % fn, dump(v))
        w["usgs-earthquake-feed"] = w.get("usgs-earthquake-feed", 0) + 1
    out.write("packs/geojson/vectors/97-to-usgs-earthquake.json", dump(geojson_to_event()))
    w["geojson"] = 1
    return w


def main(argv=None):
    return genio.vector_main("usgs-earthquake-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
