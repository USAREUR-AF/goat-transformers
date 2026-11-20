#!/usr/bin/env python3
"""Write the vectors of the eonet-event and coops-data packs.

eonet-event reads one Feature of NASA EONET v3 events in GeoJSON form
(eonet.gsfc.nasa.gov/docs/v3); coops-data reads one NOAA CO-OPS Data Retrieval API
response in JSON form (api.tidesandcurrents.noaa.gov/api/prod/). Both are US Government
works. This script holds its own copy of the documented members, in the order the packs
list them, builds every message from values written for these vectors (none is taken from
a live feed), and works out the canonical output, the decoded values and the GeoJSON and
CoT forms by the rules of spec/engine-spec.md (0.1 geojson and its rulings, ruling 13 of
0.6 for geojson residue, 0.5 json and kinds, 0.7 groups) and of the geojson and cot-xml
packs. It reads no pack.def and calls no goat-transformers engine.

Usage: python3 -I tools/gen/usgov2-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/usgov2-vectors.py from the documented members and spec/engine-spec.md; no engine run"
REF_EONET = "NASA EONET API v3 documentation, Events (GeoJSON), eonet.gsfc.nasa.gov/docs/v3 (read 2026-11-20)"
REF_COOPS = ("NOAA CO-OPS Data Retrieval API and Response Help, api.tidesandcurrents.noaa.gov/api/prod/ "
             "(read 2026-11-20)")


def num(x):
    x = float(x)
    if x == 0:
        return "0"
    r = repr(x)
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
    return r[:-2] if r.endswith(".0") else r


def iso_ms(t):
    t2 = t[:-1] if t.endswith("Z") else t
    ms = 0
    if "." in t2:
        t2, frac = t2.split(".")
        ms = int((frac + "000")[:3])
    d = datetime.datetime.strptime(t2, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp()) * 1000 + ms


def ms_iso(ms):
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def jstr(s):
    return json.dumps(s, ensure_ascii=False)


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def vec(name, frm, to, inp, expect=None, model=None, error=None, ref=None, note=None):
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


# -- EONET -----------------------------------------------------------------------------------
# properties members in pack line order: (member, model key, transform)
EONET_PROPS = [("id", "uid", "s"), ("title", "callsign", "s"), ("link", "eonet.link", "s"), ("date", "time_ms", "t")]


def residue_text(v):
    """geojson residue (ruling 13 of 0.6): a string as it was, a number as a string of its
    text as written, an array or object as it was, null dropped."""
    if isinstance(v, str):
        return jstr(v)
    if isinstance(v, (list, dict)):
        return js(v)
    return jstr(json.dumps(v))


def eonet_canon(f):
    p = f["properties"]
    parts = []
    for m, _, tr in EONET_PROPS:
        if p.get(m) is None:
            continue
        parts.append('"%s":%s' % (m, jstr(ms_iso(iso_ms(p[m])) if tr == "t" else p[m])))
    known = {m for m, _, _ in EONET_PROPS}
    parts += ['"%s":%s' % (k, residue_text(v)) for k, v in p.items() if k not in known and v is not None]
    lon, lat = f["geometry"]["coordinates"]
    return '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{%s}}' % (
        num(lon), num(lat), ",".join(parts))


def eonet_event():
    return {"type": "Feature", "properties": {
        "id": "EONET_90001", "title": "Wildfire - Example Ridge, Example County",
        "description": None, "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_90001", "closed": None,
        "date": "2026-11-12T00:00:00Z", "magnitudeValue": 1250.5, "magnitudeUnit": "acres",
        "categories": [{"id": "wildfires", "title": "Wildfires"}],
        "sources": [{"id": "IRWIN", "url": "https://example.org/incident/90001"}]},
        "geometry": {"type": "Point", "coordinates": [-120.4375, 38.8125]}}


def eonet_vectors():
    V = {}
    e = eonet_event()
    p = e["properties"]
    ms = iso_ms(p["date"])
    m = {"uid": p["id"], "callsign": p["title"], "eonet.link": p["link"], "time_ms": str(ms),
         "lat": num(38.8125), "lon": num(-120.4375)}
    V["01-event-roundtrip"] = vec("event-roundtrip", "eonet-event", "eonet-event", js(e), eonet_canon(e), m, ref=REF_EONET,
        note="the date gains milliseconds; description and closed, null for an open event, are residue and dropped; magnitudeValue, residue, comes back as a string; the arrays categories and sources come back as they were")
    closed = eonet_event()
    closed["properties"]["closed"] = "2026-11-18T00:00:00Z"
    closed["properties"]["description"] = "contained"
    V["02-closed-event-roundtrip"] = vec("closed-event-roundtrip", "eonet-event", "eonet-event", js(closed),
        eonet_canon(closed), {"time_ms": str(ms)}, ref=REF_EONET,
        note="a closed event: closed and description, present, are residue and come back as text")
    gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{"time_ms":%d,"callsign":%s},"id":%s}' % (
        num(-120.4375), num(38.8125), ms, jstr(p["title"]), jstr(p["id"]))
    V["03-event-to-geojson"] = vec("event-to-geojson", "eonet-event", "geojson", js(e), gj, ref=REF_EONET)
    t = ms_iso(ms)
    cot = ('<event version="2.0" uid=%s type="a-u-X" time="%s" start="%s"><point lat="%s" lon="%s" hae="9999999" '
           'ce="9999999" le="9999999"/><detail><contact callsign=%s/></detail></event>') % (
        jstr(p["id"]), t, t, num(38.8125), num(-120.4375), jstr(p["title"]))
    V["04-event-to-cot-xml"] = vec("event-to-cot-xml", "eonet-event", "cot-xml", js(e), cot, ref=REF_EONET,
        note="cot-xml writes its defaults for type, hae, ce and le")
    bad = eonet_event()
    bad["properties"]["date"] = "12 November 2026"
    V["05-date-not-iso"] = vec("date-not-iso", "eonet-event", "eonet-event", js(bad), error="transform-decode",
        ref=REF_EONET, note="date is an ISO 8601 UTC date-time; other text fails iso8601_ms")
    return V


def geojson_to_eonet():
    inp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-120.4375,38.8125,350]},"properties":{"time_ms":1762905600000,"callsign":"Wildfire - Example"},"id":"EONET_90001"}'
    exp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-120.4375,38.8125]},"properties":{"id":"EONET_90001","title":"Wildfire - Example","date":"%s"}}' % ms_iso(1762905600000)
    return vec("to-eonet-event", "geojson", "eonet-event", inp, exp, ref=REF_EONET,
               note="hae has no eonet line; uid, callsign and time_ms become id, title and date")


# -- CO-OPS ----------------------------------------------------------------------------------
META = [("id", "coops.station_id"), ("name", "coops.station_name"), ("lat", "coops.station_lat"),
        ("lon", "coops.station_lon")]
DATA = ["t", "v", "s", "d", "dr", "g", "ty", "f", "q"]
PRED = ["t", "v"]


def row(r, cols):
    return "{" + ",".join('"%s":%s' % (c, jstr(r[c])) for c in cols if c in r) + "}"


def coops_vectors():
    V = {}
    meta = {"id": "9999001", "name": "Example Harbor, ST", "lat": "36.9461", "lon": "-122.0158"}
    wl = {"metadata": meta, "data": [
        {"t": "2026-11-19 23:54", "v": "1.234", "s": "0.012", "f": "0,0,0,0", "q": "p"},
        {"t": "2026-11-20 00:00", "v": "1.241", "s": "0.010", "f": "0,0,0,0", "q": "p"}]}
    exp = '{"metadata":{%s},"data":[%s]}' % (",".join('"%s":%s' % (k, jstr(meta[k])) for k, _ in META),
                                             ",".join(row(r, DATA) for r in wl["data"]))
    V["01-water-level-roundtrip"] = vec("water-level-roundtrip", "coops-data", "coops-data", js(wl), exp,
        {"@kind": "observations", "coops.station_id": "9999001", "coops.station_lat": "36.9461",
         "coops.data.#": "2", "coops.data[0].coops.v": "1.234"}, ref=REF_COOPS,
        note="every value is text, as the API sends it; the time is in the zone the request named")
    wind = {"metadata": meta, "data": [{"t": "2026-11-20 00:00", "s": "5.4", "d": "270.0", "dr": "W", "g": "7.1", "f": "0,0"}]}
    exp = '{"metadata":{%s},"data":[%s]}' % (",".join('"%s":%s' % (k, jstr(meta[k])) for k, _ in META), row(wind["data"][0], DATA))
    V["02-wind-roundtrip"] = vec("wind-roundtrip", "coops-data", "coops-data", js(wind), exp,
        {"@kind": "observations", "coops.data[0].coops.dr": "W"}, ref=REF_COOPS,
        note="wind columns: s is the speed, d and dr the direction, g the gust")
    pred = {"predictions": [{"t": "2026-11-20 03:12", "v": "1.507"}, {"t": "2026-11-20 09:30", "v": "-0.112"}]}
    V["03-predictions-roundtrip"] = vec("predictions-roundtrip", "coops-data", "coops-data", js(pred),
        '{"predictions":[%s]}' % ",".join(row(r, PRED) for r in pred["predictions"]),
        {"@kind": "predictions", "coops.predictions.#": "2"}, ref=REF_COOPS)
    err = {"error": {"message": "No data was found."}}
    V["04-error-roundtrip"] = vec("error-roundtrip", "coops-data", "coops-data", js(err), js(err),
        {"@kind": "error", "coops.error_message": "No data was found."}, ref=REF_COOPS)
    V["05-number-where-text-is-sent"] = vec("number-where-text-is-sent", "coops-data", "coops-data",
        js({"metadata": meta, "data": [{"t": "2026-11-20 00:00", "v": 1.234}]}), error="transform-decode",
        ref=REF_COOPS, note="the API sends every value as a JSON string; a number under string is a transform failure (0.5 json transforms)")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fn, v in eonet_vectors().items():
        out.write("packs/eonet-event/vectors/%s.json" % fn, dump(v))
        w["eonet-event"] = w.get("eonet-event", 0) + 1
    for fn, v in coops_vectors().items():
        out.write("packs/coops-data/vectors/%s.json" % fn, dump(v))
        w["coops-data"] = w.get("coops-data", 0) + 1
    out.write("packs/geojson/vectors/98-to-eonet-event.json", dump(geojson_to_eonet()))
    w["geojson"] = 1
    return w


def main(argv=None):
    return genio.vector_main("usgov2-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
