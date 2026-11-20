#!/usr/bin/env python3
"""Write the vectors of the mf-csv pack and the KML 2.3 Track vectors of the kml pack.

mf-csv reads one line of an OGC Moving Features Simple CSV file (OGC 14-084r2,
sections 7 to 9); kml reads a KML Placemark, here with a kml:Track or a
kml:MultiTrack (OGC 12-007r2, 10.15 and 10.16). Every message below is written
for these vectors; none is copied from a standard. The expected bytes follow
from the rules of spec/engine-spec.md, applied by hand in this file:

- text (0.10): the record is the fields joined by ","; a field whose key is
  absent is empty; trailing fields whose every line is `optional` and that are
  empty are removed; a `const` writes its text; a group writes its items back
  to back from its index, an item with no value as an empty field; residue is
  written back at its index (same format only).
- text input: characters 0x20 to 0x7E only (step 2 of "Reading a record").
- xml: root attributes in line order then residue in input order; elements in
  the order of the first line that addresses them; a group writes one element
  per item at its position, all items of one group before the next group's;
  an element with no content is written `<e/>`; no XML declaration (0.1,
  rulings 6 and 7 of 0.1.1, ruling 10 of 0.5, 0.7 Encode, ruling 1 of 0.11).
- geojson: type, geometry (null without lat and lon), properties, then
  top-level members (ruling 4 of 0.1.1).

It reads no pack.def and imports no goat-transformers engine. Python 3
standard library only. With --check nothing is written and the exit status is
1 when a committed file differs from what this script writes.

Usage: python3 -I tools/gen/ogc-mf-kml-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/ogc-mf-kml-vectors.py from the standard and spec/engine-spec.md; no engine run"
REF_MF = "OGC 14-084r2 (Moving Features Simple CSV 1.0)"
REF_KML = "OGC 12-007r2 (KML 2.3) 10.15 kml:Track, 10.16 kml:MultiTrack; ogckml23.xsd TrackType, MultiTrackType"
KML_NS = "http://www.opengis.net/kml/2.2"


def vec(name, frm, to, inp, expect=None, model=None, error=None, ref="", note=""):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error is not None:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model is not None:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = ref + ("; " + note if note else "")
    return v


# -- text records -------------------------------------------------------------

def record(fields, optional_tail=0):
    """Join fields; drop up to `optional_tail` trailing empty fields (step 5)."""
    fields = list(fields)
    while optional_tail and fields and fields[-1] == "":
        fields.pop()
        optional_tail -= 1
    return ",".join(fields)


def mf_vectors():
    out = []
    # 01: an @stboundedby line with every column (8.2.1)
    sb = ["@stboundedby", "urn:ogc:def:crs:EPSG::4326", "2D", "48.10 11.50", "48.20 11.60",
          "2024-05-01T08:00:00Z", "2024-05-01T09:00:00Z", "sec"]
    line = ",".join(sb)
    out.append(vec("stboundedby-roundtrip", "mf-csv", "mf-csv", line, record(sb, 1),
        {"@kind": "stboundedby", "mfcsv.srid": sb[1], "mfcsv.dim": "2D", "mfcsv.upper_left": "48.10 11.50",
         "mfcsv.lower_right": "48.20 11.60", "mfcsv.period_start": sb[5], "mfcsv.period_end": sb[6],
         "mfcsv.time_encode": "sec"},
        ref=REF_MF + " 8.2.1 @stboundedby",
        note="every column of the header line, carried as written; the corners keep their space and their digits"))

    # 02: dim left empty and time encode omitted (7.2: an omitted column is empty)
    sb2 = sb[:2] + [""] + sb[3:7]
    line = ",".join(sb2)
    out.append(vec("stboundedby-omitted-columns-roundtrip", "mf-csv", "mf-csv", line, record(sb2 + [""], 1),
        {"@kind": "stboundedby", "mfcsv.srid": sb[1], "@absent": ["mfcsv.dim", "mfcsv.time_encode"]},
        ref=REF_MF + " 7.2 omissible columns, 8.2.1",
        note="an empty field is absent and is written back empty; the last column, time encode, is optional and is not written when absent"))

    # 03: @columns with two attribute definitions (8.2.2)
    co = ["@columns", "mfidref", "trajectory", "state", "xsd:token", "speed", "xsd:decimal"]
    line = ",".join(co)
    out.append(vec("columns-roundtrip", "mf-csv", "mf-csv", line, line,
        {"@kind": "columns", "mfcsv.attribute_defs.#": "2",
         "mfcsv.attribute_defs[0].mfcsv.attribute_name": "state",
         "mfcsv.attribute_defs[0].mfcsv.attribute_type": "xsd:token",
         "mfcsv.attribute_defs[1].mfcsv.attribute_name": "speed",
         "mfcsv.attribute_defs[1].mfcsv.attribute_type": "xsd:decimal"},
        ref=REF_MF + " 8.2.2 @columns",
        note="columns 1 and 2 are the fixed names, written by const lines; the definitions are items of two fields from column 3"))

    # 04: @columns with no attribute definitions
    line = "@columns,mfidref,trajectory"
    out.append(vec("columns-without-attributes-roundtrip", "mf-csv", "mf-csv", line, line,
        {"@kind": "columns", "mfcsv.attribute_defs.#": "absent"},
        ref=REF_MF + " 8.2.2 @columns",
        note="no varying attribute: the list is absent and the line ends at the fixed names"))

    # 05: @foliation (8.2.3)
    line = "@foliation,Sequential"
    out.append(vec("foliation-roundtrip", "mf-csv", "mf-csv", line, line,
        {"@kind": "foliation", "mfcsv.order": "Sequential"}, ref=REF_MF + " 8.2.3 @foliation"))

    # 06: a header line the pack has no kind for (8.1: any line starting with @)
    line = "@note,first,second"
    out.append(vec("other-header-roundtrip", "mf-csv", "mf-csv", line, line,
        {"@kind": "header", "mfcsv.header_name": "@note"},
        ref=REF_MF + " 8.1 header line structure",
        note="a header line other than the three the standard defines selects kind header by its first character; its value columns are residue and are written back"))

    # 07: a trajectory line with two attribute values (9)
    tr = ["veh-7", "0", "60", "11.5 48.1 11.52 48.11", "moving", "12.5"]
    line = ",".join(tr)
    out.append(vec("trajectory-roundtrip", "mf-csv", "mf-csv", line, line,
        {"@kind": "trajectory", "uid": "veh-7", "mfcsv.start_time": "0", "mfcsv.end_time": "60",
         "mfcsv.points": "11.5 48.1 11.52 48.11", "mfcsv.attributes.#": "2",
         "mfcsv.attributes[0].mfcsv.value": "moving", "mfcsv.attributes[1].mfcsv.value": "12.5"},
        ref=REF_MF + " 9 trajectory lines",
        note="mfidref is uid; times are offsets in the unit of the header and are carried as text; the points are one column"))

    # 08: an attribute value left empty (9.2: equal to the previous value)
    tr = ["veh-7", "60", "120", "11.52 48.11 11.53 48.12", "", "13"]
    line = ",".join(tr)
    out.append(vec("trajectory-omitted-attribute-roundtrip", "mf-csv", "mf-csv", line, line,
        {"@kind": "trajectory", "mfcsv.attributes.#": "2", "mfcsv.attributes[1].mfcsv.value": "13"},
        ref=REF_MF + " 9.2 attr",
        note="an empty attribute column is an item with no value and is written back as an empty field"))

    # 09: absolute times and 3D points, no attributes
    tr = ["p1", "2024-05-01T08:00:00Z", "2024-05-01T08:01:00Z", "11.5 48.1 0 11.6 48.2 5"]
    line = ",".join(tr)
    out.append(vec("trajectory-absolute-3d-roundtrip", "mf-csv", "mf-csv", line, line,
        {"@kind": "trajectory", "uid": "p1", "mfcsv.start_time": tr[1], "mfcsv.end_time": tr[2],
         "mfcsv.points": tr[3], "mfcsv.attributes.#": "absent"},
        ref=REF_MF + " 8.2.1 time encode absolute, 9.2",
        note="times are carried as text whatever the time encode of the header; no attribute columns, so the list is absent"))

    # 10: trajectory to geojson
    line = "veh-7,0,60,11.5 48.1 11.52 48.11,moving"
    exp = json.dumps({"type": "Feature", "geometry": None, "properties": {}, "id": "veh-7"},
                     separators=(",", ":"))
    out.append(vec("trajectory-to-geojson", "mf-csv", "geojson", line, exp,
        {"uid": "veh-7", "mfcsv.points": "11.5 48.1 11.52 48.11"},
        ref=REF_MF + " 9.2 mfidref; packs/geojson/pack.def",
        note="mfidref carries as the Feature id; the points are one text value that no transform splits, so geometry is null"))

    # 11: a character outside 0x20..0x7E
    line = "bus-é,0,60,11.5 48.1 11.52 48.11"
    out.append(vec("non-ascii-is-malformed-wire", "mf-csv", "mf-csv", line, error="malformed-wire",
        ref=REF_MF + " 7.1 (UTF-8); spec/engine-spec.md 0.10 Reading a record step 2",
        note="the standard allows UTF-8 text; the text wire accepts 0x20 to 0x7E only"))

    # 12: geojson to mf-csv
    inp = json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
                      "properties": {}, "id": "veh-7"}, separators=(",", ":"))
    to_mf = vec("geojson-to-trajectory-without-points-is-no-kind", "geojson", "mf-csv", inp, error="no-kind",
        ref=REF_MF + " 9.2; packs/mf-csv/pack.def",
        note="the trajectory kind requires the points text, which no geojson line yields; the header kinds require their own keys")
    return out, to_mf


# -- xml ----------------------------------------------------------------------

def esc_text(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\r", "&#13;")


def esc_attr(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\t", "&#9;").replace("\n", "&#10;").replace("\r", "&#13;"))


def el(name, attrs=(), kids=(), text=None, empty_open_close=False):
    return {"name": name, "attrs": list(attrs), "kids": list(kids), "text": text, "oc": empty_open_close}


def ser(e, canonical=True):
    a = "".join(' %s="%s"' % (k, esc_attr(v)) for k, v in e["attrs"])
    inner = (esc_text(e["text"]) if e["text"] is not None else "") + "".join(ser(k, canonical) for k in e["kids"])
    if inner == "" and (canonical or not e["oc"]):
        return "<%s%s/>" % (e["name"], a)
    return "<%s%s>%s</%s>" % (e["name"], a, inner, e["name"])


def T(name, text):
    return el(name, text=text)


def kml(kids, extra=()):
    return el("kml", [("xmlns", KML_NS)] + list(extra), kids)


def track(whens, coords, angles=(), mode=None, extrude=None, order="grouped"):
    kids = []
    if extrude is not None:
        kids.append(T("extrude", extrude))
    if mode is not None:
        kids.append(T("altitudeMode", mode))
    w = [T("when", x) for x in whens]
    c = [el("coord", text=x, empty_open_close=True) for x in coords]
    g = [T("angles", x) for x in angles]
    if order == "grouped":
        kids += w + c + g
    else:
        for i in range(max(len(w), len(c))):
            kids += w[i:i + 1] + c[i:i + 1]
        kids += g
    return el("Track", [], kids)


def kml_vectors():
    out = {}
    w = ["2024-05-01T08:00:00Z", "2024-05-01T08:00:10Z"]
    c = ["11.5 48.1 520", "11.5001 48.1002 521.5"]
    g = ["90 0 0", "92.5 0 0"]
    pm = el("Placemark", [("id", "t1")], [T("name", "ROVER"), T("description", "survey run"), T("styleUrl", "#trk"),
                                          track(w, c, g, mode="absolute", extrude="1")])
    doc = ser(kml([pm], [("version", "2.3")]))
    out["07-track-roundtrip"] = vec("track-roundtrip", "kml", "kml", doc, doc,
        {"@kind": "track", "callsign": "ROVER", "kml.placemark_id": "t1", "kml.description": "survey run",
         "kml.style_url": "#trk", "kml.extrude": "1", "kml.altitude_mode": "absolute",
         "kml.track_whens.#": "2", "kml.track_whens[0].kml.track_when": w[0], "kml.track_whens[1].kml.track_when": w[1],
         "kml.track_coords.#": "2", "kml.track_coords[1].kml.coord": c[1],
         "kml.track_angles.#": "2", "kml.track_angles[0].kml.angles": g[0]},
        ref=REF_KML, note="a KML 2.3 Track as a Placemark's geometry; the root's version attribute is residue; when, coord and angles are three lists in document order; coord texts are carried whole")

    w3 = ["2024-05-01T08:00:00Z", "2024-05-01T08:00:10Z", "2024-05-01T08:00:20Z"]
    pm_in = el("Placemark", [], [T("name", "ROVER"), track(w3, ["11.5 48.1 520", "", "11.5002 48.1004 523"])])
    out["08-track-missing-coord"] = vec("track-missing-coord", "kml", "kml",
        ser(kml([pm_in]), canonical=False), ser(kml([pm_in])),
        {"@kind": "track", "kml.track_coords.#": "3", "kml.track_coords[2].kml.coord": "11.5002 48.1004 523"},
        ref=REF_KML, note="10.15.2 allows an empty coord for missing data: written <coord></coord> it is an item with no value, and is written back as <coord/>")

    pm_in = el("Placemark", [], [T("name", "ROVER"), track(w, c, order="interleaved")])
    pm_out = el("Placemark", [], [T("name", "ROVER"), track(w, c)])
    out["09-track-interleaved-is-regrouped"] = vec("track-interleaved-is-regrouped", "kml", "kml",
        ser(kml([pm_in])), ser(kml([pm_out])),
        {"@kind": "track", "kml.track_whens.#": "2", "kml.track_coords.#": "2", "kml.track_coords[0].kml.coord": c[0]},
        ref=REF_KML, note="10.15.2 lets when and coord appear in any order; the lists keep each array's order, and the encoder writes every when and then every coord")

    pm = el("Placemark", [], [T("name", "ROVER"), track(w, c, mode="clampToGround")])
    doc = ser(kml([el("Document", [], [T("name", "RUNS"), pm])]))
    out["10-document-track-roundtrip"] = vec("document-track-roundtrip", "kml", "kml", doc, doc,
        {"@kind": "document-track", "kml.document_name": "RUNS", "callsign": "ROVER",
         "kml.altitude_mode": "clampToGround", "kml.track_whens.#": "2"},
        ref=REF_KML, note="a Track Placemark inside a Document")

    t1 = track(w, c, mode="absolute")
    t2 = track(["2024-05-01T09:00:00Z"], ["11.6 48.2 530"])
    mt = el("MultiTrack", [], [T("altitudeMode", "absolute"), T("interpolate", "1"), t1, t2])
    doc = ser(kml([el("Placemark", [("id", "m1")], [T("name", "ROVER"), mt])]))
    out["11-multitrack-roundtrip"] = vec("multitrack-roundtrip", "kml", "kml", doc, doc,
        {"@kind": "multitrack", "kml.placemark_id": "m1", "callsign": "ROVER", "kml.altitude_mode": "absolute",
         "kml.interpolate": "1", "kml.tracks.#": "2",
         "kml.tracks[0].kml.altitude_mode": "absolute", "kml.tracks[0].kml.track_whens.#": "2",
         "kml.tracks[0].kml.track_coords[1].kml.coord": c[1],
         "kml.tracks[1].kml.track_whens[0].kml.track_when": "2024-05-01T09:00:00Z",
         "kml.tracks[1].kml.track_coords.#": "1"},
        ref=REF_KML, note="each Track of a MultiTrack is an item holding its own when and coord lists")

    doc = ser(kml([el("Placemark", [], [T("name", "ROVER"), track(w, c)])]))
    exp = json.dumps({"type": "Feature", "geometry": None, "properties": {"callsign": "ROVER"}},
                     separators=(",", ":"))
    out["12-track-to-geojson"] = vec("track-to-geojson", "kml", "geojson", doc, exp,
        {"callsign": "ROVER", "kml.track_coords.#": "2"},
        ref=REF_KML + "; packs/geojson/pack.def",
        note="the name carries; coord texts are not split into lat and lon, so geometry is null and the lists have no geojson line")

    doc = ('<kml xmlns="%s" xmlns:gx="http://www.google.com/kml/ext/2.2"><Placemark><name>ROVER</name>'
           '<gx:Track><when>%s</when><gx:coord>%s</gx:coord></gx:Track></Placemark></kml>') % (KML_NS, w[0], c[0])
    out["13-gx-track-is-no-kind"] = vec("gx-track-is-no-kind", "kml", "kml", doc, error="no-kind",
        ref=REF_KML + "; the gx extension namespace of KML 2.2 documents",
        note="the same track written as the KML 2.2 extension gx:Track: element names are compared as written, so the prefixed name matches no kind until the pack language has XML namespaces")
    return out


def build(out):
    written = {}
    mf, to_mf = mf_vectors()
    vdir = "packs/mf-csv/vectors"
    names = set()
    for i, v in enumerate(mf, 1):
        rel = "%s/%02d-%s.json" % (vdir, i, v["name"])
        names.add(rel.rsplit("/", 1)[1])
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    for old in out.listdir(vdir):
        if old not in names:
            out.remove(vdir + "/" + old)
    written["mf-csv"] = len(mf)
    out.write("packs/geojson/vectors/to-mf-csv-%s.json" % to_mf["name"],
              json.dumps(to_mf, indent=2, ensure_ascii=False) + "\n")
    written["geojson"] = 1
    kv = kml_vectors()
    for fn, v in kv.items():
        out.write("packs/kml/vectors/%s.json" % fn, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    written["kml"] = len(kv)
    return written


def main(argv=None):
    return genio.vector_main("ogc-mf-kml-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
