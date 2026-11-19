#!/usr/bin/env python3
"""Derive the conversion vectors of the gpx and kml packs without an engine.

Python 3 standard library only; imports nothing from engines/. Each vector is
written from a description of the message (element, attributes, children) and
the canonical rules of spec/engine-spec.md:

- xml: attributes in field-line order, then residue in input order; mapped
  elements in line order; self-closing empty elements; no XML declaration
  (0.1 Canonicalisation, ruling 6 of 0.1.1, ruling 10 of 0.5, ruling 26 of 0.5).
- A child element no line maps is dropped; only the first sibling of a name is
  read (rulings 6 and 7 of 0.1.1).
- float: shortest round-trip decimal, plain notation, no point for an
  integer value, negative zero as 0 (ruling 3 of 0.1.1).
- iso8601_ms: offsets converted to UTC, digits past milliseconds truncated,
  written YYYY-MM-DDTHH:MM:SS.fffZ (0.1, ruling 8 of 0.1.1 as corrected in 0.6).
- geojson: type, geometry, properties, then top-level members; geometry null
  when lat or lon is absent; properties in field-line order (ruling 4, 5).
- cot-xml: the lines and defaults of packs/cot-xml/pack.def.

Usage: python3 -I tools/gen/aviation-xml-vectors.py <goat-transformers checkout>
Writes packs/gpx/vectors/*.json, packs/kml/vectors/*.json and one vector each
under packs/geojson/vectors and packs/cot-xml/vectors.
"""
import datetime
import json
import os
import sys

GPX_NS = "http://www.topografix.com/GPX/1/1"
KML_NS = "http://www.opengis.net/kml/2.2"
REF_GPX = "GPX 1.1 schema, https://www.topografix.com/GPX/1/1/gpx.xsd, wptType, rteType, trkType, trksegType, gpxType"
REF_KML = "OGC 07-147r2 (KML 2.2.0) 9.1 AbstractFeatureGroup, 10.3 Point, 16.9 coordinatesType; ogckml22.xsd"
SOURCE = "derived by tools/gen/aviation-xml-vectors.py from the schema and spec/engine-spec.md; no engine run"


# -- values -----------------------------------------------------------------

def canon_float(text):
    x = float(text)
    if x == 0:
        return "0"
    r = repr(x)
    if "e" in r or "E" in r:
        # plain notation of the shortest round-trip digits
        from decimal import Decimal
        r = format(Decimal(r), "f")
    if r.endswith(".0"):
        r = r[:-2]
    return r


def iso_to_ms(text):
    t = text
    if t[-1] in "Zz":
        off = datetime.timedelta(0)
        t = t[:-1]
    else:
        sign = 1 if t[-6] == "+" else -1
        off = sign * datetime.timedelta(hours=int(t[-5:-3]), minutes=int(t[-2:]))
        t = t[:-6]
    frac_ms = 0
    if "." in t:
        t, frac = t.split(".")
        frac_ms = int((frac + "000")[:3])        # truncate past milliseconds
    d = datetime.datetime.strptime(t.replace("t", "T"), "%Y-%m-%dT%H:%M:%S")
    d = d.replace(tzinfo=datetime.timezone.utc) - off
    return int(d.timestamp()) * 1000 + frac_ms


def ms_to_iso(ms):
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


# -- a tiny canonical XML writer (values here hold no character to escape) ---

def el(name, attrs=(), children=(), text=None):
    return (name, list(attrs), list(children), text)


def xml(node):
    name, attrs, children, text = node
    for _, v in attrs:
        assert not set(v) & set('<&"'), v
    a = "".join(' %s="%s"' % (k, v) for k, v in attrs)
    if text is not None:
        assert not set(text) & set("<&"), text
        return "<%s%s>%s</%s>" % (name, a, text, name)
    if not children:
        return "<%s%s/>" % (name, a)
    return "<%s%s>%s</%s>" % (name, a, "".join(xml(c) for c in children), name)


# -- GPX ----------------------------------------------------------------------

# (element, model key, transform) in wptType order, as in packs/gpx/pack.def.
GPX_POINT = [("ele", "gpx.ele", "float"), ("time", "time_ms", "iso"),
             ("magvar", "gpx.magvar", "float"), ("geoidheight", "gpx.geoidheight", "float"),
             ("name", "callsign", "string"), ("cmt", "gpx.cmt", "string"),
             ("desc", "gpx.desc", "string"), ("src", "gpx.src", "string"),
             ("sym", "gpx.sym", "string"), ("type", "gpx.type", "string"),
             ("fix", "gpx.fix", "string"), ("sat", "gpx.sat", "int"),
             ("hdop", "gpx.hdop", "float"), ("vdop", "gpx.vdop", "float"),
             ("pdop", "gpx.pdop", "float"), ("ageofdgpsdata", "gpx.ageofdgpsdata", "float"),
             ("dgpsid", "gpx.dgpsid", "int")]


def canon(value, tr):
    if tr == "float":
        return canon_float(value)
    if tr == "iso":
        return ms_to_iso(iso_to_ms(value))
    if tr == "int":
        return str(int(value))
    return value


def model_text(value, tr):
    if tr == "iso":
        return str(iso_to_ms(value))
    if tr == "float":
        return canon_float(value)
    return value


def gpx_point(tag, lat, lon, children, canonical):
    """children: dict element -> text. Writes them in wptType order."""
    kids = []
    for name, _, tr in GPX_POINT:
        if name in children:
            kids.append(el(name, text=canon(children[name], tr) if canonical else children[name]))
    la, lo = (canon_float(lat), canon_float(lon)) if canonical else (lat, lon)
    return el(tag, [("lat", la), ("lon", lo)], kids)


def gpx_model(lat, lon, children):
    m = {"lat": canon_float(lat), "lon": canon_float(lon)}
    for name, key, tr in GPX_POINT:
        if name in children:
            m[key] = model_text(children[name], tr)
    return m


def gpx_doc(creator, body, residue=(), canonical=True, order_input=None):
    if canonical:
        attrs = [("xmlns", GPX_NS), ("version", "1.1"), ("creator", creator)] + list(residue)
    else:
        attrs = order_input
    return el("gpx", attrs, body)


def vec(name, frm, to, inp, expect=None, model=None, error=None, note=None, ref=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = "; ".join(x for x in (ref, note) if x)
    return v


def gpx_vectors():
    out = {}
    xsi = [("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance"),
           ("xsi:schemaLocation", GPX_NS + " http://www.topografix.com/GPX/1/1/gpx.xsd")]

    # 01 waypoint, every mapped element, root residue
    kids = {"ele": "519.50", "time": "2024-05-01T12:30:00Z", "magvar": "2.5",
            "geoidheight": "47.3", "name": "POINT A", "cmt": "north gate",
            "desc": "meeting point at the north gate", "src": "survey 2024",
            "sym": "Flag, Blue", "type": "rally", "fix": "3d", "sat": "8",
            "hdop": "1.2", "vdop": "1.8", "pdop": "2.1", "ageofdgpsdata": "3.0",
            "dgpsid": "17"}
    inp = xml(el("gpx", [("version", "1.1"), ("creator", "survey-tool"), ("xmlns", GPX_NS)] + xsi,
                 [gpx_point("wpt", "48.137154", "11.576124", kids, False)]))
    exp = xml(gpx_doc("survey-tool", [gpx_point("wpt", "48.137154", "11.576124", kids, True)], xsi))
    m = gpx_model("48.137154", "11.576124", kids)
    m.update({"@kind": "waypoint", "gpx.creator": "survey-tool"})
    out["01-waypoint-roundtrip"] = vec("waypoint-roundtrip", "gpx", "gpx", inp, exp, m,
        note="every element of wptType that the pack maps; root attributes the pack does not map are residue and are written back after the mapped ones; decimals are written in shortest form (519.50 is 519.5, 3.0 is 3); the time gains milliseconds",
        ref=REF_GPX)

    # 02 route point
    kids = {"ele": "100.0", "name": "TURN 1"}
    inp = xml(gpx_doc("planner", [el("rte", [], [el("name", text="ROUTE NORTH"),
                       gpx_point("rtept", "50.5", "8.25", kids, False)])]))
    exp = xml(gpx_doc("planner", [el("rte", [], [el("name", text="ROUTE NORTH"),
                       gpx_point("rtept", "50.5", "8.25", kids, True)])]))
    m = gpx_model("50.5", "8.25", kids)
    m.update({"@kind": "route-point", "gpx.route_name": "ROUTE NORTH"})
    out["02-route-point-roundtrip"] = vec("route-point-roundtrip", "gpx", "gpx", inp, exp, m,
        note="a document with only a route: the first point of the route; rte/name before rtept as rteType orders them", ref=REF_GPX)

    # 03 track point, sub-millisecond time; the second point is not carried
    k1 = {"ele": "312.25", "time": "2024-05-01T12:30:00.123456Z"}
    k2 = {"ele": "313", "time": "2024-05-01T12:30:01Z"}
    inp = xml(gpx_doc("logger", [el("trk", [], [el("name", text="MORNING"), el("trkseg", [], [
        gpx_point("trkpt", "47.0", "9.0", k1, False), gpx_point("trkpt", "47.0001", "9.0001", k2, False)])])]))
    exp = xml(gpx_doc("logger", [el("trk", [], [el("name", text="MORNING"), el("trkseg", [], [
        gpx_point("trkpt", "47.0", "9.0", k1, True)])])]))
    m = gpx_model("47.0", "9.0", k1)
    m.update({"@kind": "track-point", "gpx.track_name": "MORNING"})
    out["03-track-point-roundtrip"] = vec("track-point-roundtrip", "gpx", "gpx", inp, exp, m,
        note="the first point of the first segment is read; the second trkpt is a later sibling of the same name and is not carried (ruling 7 of 0.1.1); fraction digits past milliseconds are truncated", ref=REF_GPX)

    # 04 waypoint to geojson
    kids = {"ele": "519.5", "time": "2024-05-01T12:30:00Z", "name": "POINT A", "sym": "Flag, Blue"}
    inp = xml(gpx_doc("survey-tool", [gpx_point("wpt", "48.137154", "11.576124", kids, True)]))
    ms = iso_to_ms(kids["time"])
    exp = json.dumps({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [11.576124, 48.137154]},
                      "properties": {"time_ms": ms, "callsign": "POINT A"}}, separators=(",", ":"))
    out["04-waypoint-to-geojson"] = vec("waypoint-to-geojson", "gpx", "geojson", inp, exp,
        {"lat": "48.137154", "lon": "11.576124", "time_ms": str(ms), "callsign": "POINT A", "gpx.ele": "519.5"},
        note="ele has no stated height reference and is not hae, so the Point has two coordinates", ref=REF_GPX)

    # 05 track point to cot-xml
    k1 = {"ele": "312.25", "time": "2024-05-01T12:30:00.500Z", "name": "TP1"}
    inp = xml(gpx_doc("logger", [el("trk", [], [el("trkseg", [], [gpx_point("trkpt", "47.5", "-122.25", k1, True)])])]))
    t = ms_to_iso(iso_to_ms(k1["time"]))
    exp = xml(el("event", [("version", "2.0"), ("type", "a-u-X"), ("time", t), ("start", t)], [
        el("point", [("lat", "47.5"), ("lon", "-122.25"), ("hae", "9999999"), ("ce", "9999999"), ("le", "9999999")]),
        el("detail", [], [el("contact", [("callsign", "TP1")])])]))
    out["05-track-point-to-cot-xml"] = vec("track-point-to-cot-xml", "gpx", "cot-xml", inp, exp,
        {"@kind": "track-point", "lat": "47.5", "lon": "-122.25", "time_ms": str(iso_to_ms(k1["time"]))},
        note="cot-xml writes its defaults for type, hae, ce and le; ele is not carried", ref=REF_GPX + "; packs/cot-xml/pack.def")

    # 06 time with an offset
    kids = {"time": "2024-05-01T14:30:00+02:00"}
    inp = xml(gpx_doc("x", [gpx_point("wpt", "1", "2", kids, False)]))
    exp = xml(gpx_doc("x", [gpx_point("wpt", "1", "2", kids, True)]))
    out["06-time-offset-to-utc"] = vec("time-offset-to-utc", "gpx", "gpx", inp, exp,
        {"time_ms": str(iso_to_ms(kids["time"]))},
        note="xsd:dateTime may carry an offset; the instant is converted to UTC (0.6 correction to ruling 8)", ref=REF_GPX)

    # 07 edge values of the latitude and longitude ranges
    kids = {"ele": "-0.0"}
    inp = xml(gpx_doc("x", [gpx_point("wpt", "-90.0", "-180", kids, False)]))
    exp = xml(gpx_doc("x", [gpx_point("wpt", "-90.0", "-180", kids, True)]))
    out["07-range-edges"] = vec("range-edges", "gpx", "gpx", inp, exp,
        {"lat": "-90", "lon": "-180", "gpx.ele": "0"},
        note="latitudeType is -90 to 90 inclusive, longitudeType -180 inclusive to 180 exclusive; negative zero is written 0", ref=REF_GPX)
    inp = xml(gpx_doc("x", [gpx_point("wpt", "90", "179.999999999", {}, False)]))
    exp = xml(gpx_doc("x", [gpx_point("wpt", "90", "179.999999999", {}, True)]))
    out["08-range-upper-edges"] = vec("range-upper-edges", "gpx", "gpx", inp, exp,
        {"lat": "90", "lon": "179.999999999"}, ref=REF_GPX)

    # 09 the GPX 1.0 namespace is not this pack
    inp = xml(el("gpx", [("xmlns", "http://www.topografix.com/GPX/1/0"), ("version", "1.0"), ("creator", "x")],
                 [gpx_point("wpt", "1", "2", {}, False)]))
    out["09-gpx-1-0-is-no-kind"] = vec("gpx-1-0-is-no-kind", "gpx", "gpx", inp, error="no-kind",
        note="a GPX 1.0 document has another namespace and version; the common when lines do not hold", ref=REF_GPX)

    # 10 no point at all
    inp = xml(gpx_doc("x", [el("metadata", [], [el("name", text="EMPTY")])]))
    out["10-no-point-is-no-kind"] = vec("no-point-is-no-kind", "gpx", "gpx", inp, error="no-kind",
        note="no wpt, rtept or trkpt: no kind holds", ref=REF_GPX)

    # 11 a prefixed root
    inp = '<g:gpx xmlns:g="%s" version="1.1" creator="x"><g:wpt lat="1" lon="2"/></g:gpx>' % GPX_NS
    out["11-prefixed-root-is-no-kind"] = vec("prefixed-root-is-no-kind", "gpx", "gpx", inp,
        error="no-kind",
        note="the same GPX document written with a namespace prefix; the xml wire compares element names as written (no namespace processing), so the root g:gpx is not gpx, and a root that matches no kind is no-kind in a pack with kinds (ruling 11 of 0.6)", ref=REF_GPX)

    # 12 latitude that is not a decimal
    inp = xml(gpx_doc("x", [gpx_point("wpt", "north", "2", {}, False)]))
    out["12-latitude-not-decimal"] = vec("latitude-not-decimal", "gpx", "gpx", inp, error="transform-decode",
        note="lat is xsd:decimal; text that is not a number fails the float transform (ruling 9 of 0.1.1)", ref=REF_GPX)

    # 13 waypoint and track: the waypoint is read, the track dropped
    kids = {"name": "WP"}
    inp = xml(gpx_doc("x", [gpx_point("wpt", "10", "20", kids, False),
                            el("trk", [], [el("trkseg", [], [gpx_point("trkpt", "11", "21", {}, False)])])]))
    exp = xml(gpx_doc("x", [gpx_point("wpt", "10", "20", kids, True)]))
    out["13-waypoint-before-track"] = vec("waypoint-before-track", "gpx", "gpx", inp, exp,
        {"@kind": "waypoint", "lat": "10", "lon": "20"},
        note="kinds are tried in pack order; the waypoint kind holds and the track, which it does not map, is dropped", ref=REF_GPX)
    return out


def geojson_to_gpx():
    ms = iso_to_ms("2024-05-01T12:30:00Z")
    inp = json.dumps({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [11.576124, 48.137154, 519.5]},
                      "properties": {"callsign": "POINT A", "time_ms": ms}}, separators=(",", ":"))
    exp = xml(gpx_doc("goat-transformers", [gpx_point("wpt", "48.137154", "11.576124",
                                                       {"time": ms_to_iso(ms), "name": "POINT A"}, True)]))
    return vec("to-gpx-waypoint", "geojson", "gpx", inp, exp,
               note="encode picks the first kind whose requires hold (waypoint); the when values write the namespace and version, the default writes creator; the altitude is not carried (gpx binds no hae)",
               ref=REF_GPX + "; packs/gpx/pack.def")


def cot_to_gpx():
    inp = ('<event uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g">'
           '<point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/>'
           '<detail><contact callsign="GATOR"/></detail></event>')
    exp = xml(gpx_doc("goat-transformers", [gpx_point("wpt", "30.0090027", "-85.9578182",
                                                       {"time": "2021-02-27T20:00:00.000Z", "name": "GATOR"}, True)]))
    return vec("to-gpx-waypoint", "cot-xml", "gpx", inp, exp,
               note="the input is that of 02-cot-roundtrip; lat, lon, time and callsign carry; hae, ce, le, uid, type and how have no gpx line",
               ref=REF_GPX + "; packs/gpx/pack.def")


# -- KML ----------------------------------------------------------------------

def placemark(pid, name, desc, when, style, extrude, mode, coords):
    kids = []
    if name is not None:
        kids.append(el("name", text=name))
    if desc is not None:
        kids.append(el("description", text=desc))
    if when is not None:
        kids.append(el("TimeStamp", [], [el("when", text=when)]))
    if style is not None:
        kids.append(el("styleUrl", text=style))
    pk = []
    if extrude is not None:
        pk.append(el("extrude", text=extrude))
    if mode is not None:
        pk.append(el("altitudeMode", text=mode))
    if coords is not None:
        pk.append(el("coordinates", text=coords))
    kids.append(el("Point", [], pk))
    return el("Placemark", [("id", pid)] if pid else [], kids)


def kml_vectors():
    out = {}
    gx = [("xmlns:gx", "http://www.google.com/kml/ext/2.2")]
    pm = placemark("p1", "ALPHA", "observation post", "2024-05-01T12:30:00Z", "#red", "1",
                   "absolute", "11.576124,48.137154,519.5")
    doc = xml(el("kml", [("xmlns", KML_NS)] + gx, [pm]))
    out["01-placemark-roundtrip"] = vec("placemark-roundtrip", "kml", "kml", doc, doc,
        {"@kind": "placemark", "callsign": "ALPHA", "kml.placemark_id": "p1",
         "kml.description": "observation post", "kml.when": "2024-05-01T12:30:00Z",
         "kml.style_url": "#red", "kml.extrude": "1", "kml.altitude_mode": "absolute",
         "kml.coordinates": "11.576124,48.137154,519.5"},
        note="a Placemark as the root's feature; elements in the order of AbstractFeatureGroup and Point; the root attribute xmlns:gx is residue; the coordinates are carried as their text", ref=REF_KML)

    pm = placemark(None, "BRAVO", None, None, None, None, None, "-122.0822035425683,37.42228990140251,0")
    doc = xml(el("kml", [("xmlns", KML_NS)], [el("Document", [], [el("name", text="SITES"), pm])]))
    out["02-document-placemark-roundtrip"] = vec("document-placemark-roundtrip", "kml", "kml", doc, doc,
        {"@kind": "document-placemark", "callsign": "BRAVO", "kml.document_name": "SITES",
         "kml.coordinates": "-122.0822035425683,37.42228990140251,0"},
        note="a Placemark inside a Document; the coordinate text is kept exactly, digits and all", ref=REF_KML)

    pm = placemark(None, "ALPHA", None, None, None, None, None, "11.576124,48.137154")
    doc = xml(el("kml", [("xmlns", KML_NS)], [pm]))
    exp = json.dumps({"type": "Feature", "geometry": None, "properties": {"callsign": "ALPHA"}},
                     separators=(",", ":"))
    out["03-placemark-to-geojson"] = vec("placemark-to-geojson", "kml", "geojson", doc, exp,
        {"callsign": "ALPHA", "kml.coordinates": "11.576124,48.137154"},
        note="the coordinate tuple is one text value and no transform splits it, so lat and lon are absent and geometry is null (ruling 5 of 0.1.1)", ref=REF_KML)

    doc = xml(el("kml", [("xmlns", "http://earth.google.com/kml/2.1")], [placemark(None, "A", None, None, None, None, None, "1,2")]))
    out["04-kml-2-1-namespace-is-no-kind"] = vec("kml-2-1-namespace-is-no-kind", "kml", "kml", doc,
        error="no-kind", note="a document in another KML namespace; the common when does not hold", ref=REF_KML)

    doc = xml(el("kml", [("xmlns", KML_NS)], [el("Placemark", [], [el("name", text="A")])]))
    out["05-placemark-without-point-is-no-kind"] = vec("placemark-without-point-is-no-kind", "kml", "kml", doc,
        error="no-kind", note="the pack reads a Placemark with a Point; one without coordinates matches no kind", ref=REF_KML)

    doc = '<k:kml xmlns:k="%s"><k:Placemark><k:Point><k:coordinates>1,2</k:coordinates></k:Point></k:Placemark></k:kml>' % KML_NS
    out["06-prefixed-root-is-no-kind"] = vec("prefixed-root-is-no-kind", "kml", "kml", doc,
        error="no-kind", note="the same KML written with a namespace prefix; element names are compared as written, and a root that matches no kind is no-kind in a pack with kinds (ruling 11 of 0.6)", ref=REF_KML)
    return out


def geojson_to_kml():
    inp = json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
                      "properties": {"callsign": "ALPHA"}}, separators=(",", ":"))
    return vec("to-kml-without-coordinates-is-no-kind", "geojson", "kml", inp, error="no-kind",
               note="both kml kinds require kml.coordinates, which no geojson line yields: a position cannot be written into KML until the pack language can join numbers into the coordinate text, so encode fails rather than write a Placemark without its Point",
               ref=REF_KML + "; packs/kml/pack.def")


def write(path, v):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(v, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    gt = sys.argv[1]
    for d, vs in (("gpx", gpx_vectors()), ("kml", kml_vectors())):
        for fn, v in vs.items():
            write(os.path.join(gt, "packs", d, "vectors", fn + ".json"), v)
    write(os.path.join(gt, "packs", "geojson", "vectors", "91-to-gpx-waypoint.json"), geojson_to_gpx())
    write(os.path.join(gt, "packs", "geojson", "vectors", "92-to-kml-without-coordinates-is-no-kind.json"), geojson_to_kml())
    write(os.path.join(gt, "packs", "cot-xml", "vectors", "20-to-gpx-waypoint.json"), cot_to_gpx())


if __name__ == "__main__":
    main()
