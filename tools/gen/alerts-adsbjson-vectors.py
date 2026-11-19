#!/usr/bin/env python3
"""Derive the conversion vectors of the cap, readsb-aircraft and
readsb-aircraft-json packs without an engine.

Python 3 standard library only; imports nothing from engines/. Expected output
is built from a description of each message and the rules of
spec/engine-spec.md:

- xml: attributes in line order then residue; elements in line order, a group's
  items at the group's position; self-closing empty elements; no declaration
  (0.1 Canonicalisation; ruling 10 of 0.5; 0.7 Encode). Two lines on one
  locator: decode fills both, encode writes the earliest line whose key is
  present (ruling 16 of 0.5).
- json: mapped members in line order, then residue scalars in input order;
  arrays not carried outside groups; items carry no residue (0.5 json, 0.7).
- float: shortest round-trip decimal, plain, integer value without a point.
- derive scale:<num>/<den>: v * num / den in doubles (ruling 1 of 0.5, 0.6
  Derived keys); applied by convert when from != to.
- geojson and cot-xml: the lines and defaults of their pack.def files.
- iscale:1000 (0.15, text wires): the number's text as an exact decimal times
  1000, rounded half away from zero; encode writes ms / 1000 as an exact plain
  decimal (an integer without a point). Done with decimal.Decimal, not floats.

Usage: python3 -I tools/gen/alerts-adsbjson-vectors.py <goat-transformers checkout>
"""
import datetime
import json
import os
import sys

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
SOURCE = "derived by tools/gen/alerts-adsbjson-vectors.py from the format documentation and spec/engine-spec.md; no engine run"
REF_CAP = "OASIS CAP 1.2 (CAP-v1.2-os) 3.2.1-3.2.4, 3.3.2; CAP-v1.2.xsd"
REF_RSB = "readsb README-json.md (commit 88877b96), dump1090-fa README-json.md (commit 465e0633): aircraft.json keys"


def canon_float(x):
    x = float(x)
    if x == 0:
        return "0"
    r = repr(x)
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
    return r[:-2] if r.endswith(".0") else r


def iso_to_ms(t):
    sign = 1 if t[-6] == "+" else -1
    off = sign * datetime.timedelta(hours=int(t[-5:-3]), minutes=int(t[-2:]))
    d = datetime.datetime.strptime(t[:-6], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc) - off
    return int(d.timestamp()) * 1000


def secs_to_ms(text):
    """iscale:1000 decode of a JSON number's text."""
    from decimal import Decimal, ROUND_HALF_UP
    return int((Decimal(text) * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def ms_to_secs(ms):
    """iscale:1000 encode: ms / 1000 as exact plain decimal text."""
    from decimal import Decimal
    s = format(Decimal(ms) / 1000, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def ms_to_iso(ms):
    d = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def scale(v, num, den):
    return float(v) * num / den


def el(name, children=(), text=None, attrs=()):
    return (name, list(attrs), list(children), text)


def xml(n):
    name, attrs, kids, text = n
    a = "".join(' %s="%s"' % kv for kv in attrs)
    if text is not None:
        assert not set(text) & set("<&")
        return "<%s%s>%s</%s>" % (name, a, text, name)
    if not kids:
        return "<%s%s/>" % (name, a)
    return "<%s%s>%s</%s>" % (name, a, "".join(xml(k) for k in kids), name)


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def vec(name, frm, to, inp, expect=None, model=None, ref=None, note=None, error=None, context=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    if context is not None:
        v["context"] = context
    v["source"] = SOURCE
    v["reference"] = "; ".join(x for x in (ref, note) if x)
    return v


# -- CAP ------------------------------------------------------------------------

def t(name, value):
    return el(name, text=value)


def vn(name, a, b):
    return el(name, [t("valueName", a), t("value", b)])


def cap_vectors():
    out = {}
    area = el("area", [t("areaDesc", "river valley north of the bridge"),
                       t("polygon", "38.47,-120.14 38.34,-119.95 38.52,-119.74 38.62,-119.89 38.47,-120.14"),
                       t("polygon", "38.10,-120.00 38.20,-120.00 38.20,-119.90 38.10,-120.00"),
                       t("circle", "38.5,-120.0 12.5"),
                       vn("geocode", "SAME", "006109"), vn("geocode", "FIPS6", "006003"),
                       t("altitude", "1500.0"), t("ceiling", "12000")])
    area_c = el("area", area[2][:6] + [t("altitude", "1500"), t("ceiling", "12000")])
    def info(lang, event, headline, with_area, canonical):
        k = [t("language", lang), t("category", "Met"), t("category", "Safety"), t("event", event),
             t("responseType", "Prepare"), t("responseType", "Monitor"),
             t("urgency", "Expected"), t("severity", "Severe"), t("certainty", "Likely"),
             t("audience", "residents"), vn("eventCode", "SAME", "FFW"),
             t("effective", "2024-05-01T12:00:00-00:00"), t("onset", "2024-05-01T13:00:00-00:00"),
             t("expires", "2024-05-01T18:00:00-00:00"), t("senderName", "Regional Weather Office"),
             t("headline", headline), t("description", "heavy rain is expected upstream"),
             t("instruction", "move to higher ground if water rises"),
             t("web", "https://example.org/alerts/1"), t("contact", "duty officer"),
             vn("parameter", "WMOHEADER", "WWUS00"), vn("parameter", "LEVEL", "2"),
             el("resource", [t("resourceDesc", "map"), t("mimeType", "image/png"), t("size", "20480"),
                             t("uri", "https://example.org/alerts/1/map.png"),
                             t("digest", "0123456789abcdef0123456789abcdef01234567")])]
        if with_area:
            k.append(area_c if canonical else area)
        return el("info", k)
    head = [t("identifier", "ALERT-2024-0001"), t("sender", "warnings.example.org"),
            t("sent", "2024-05-01T11:45:00-00:00"), t("status", "Exercise"), t("msgType", "Alert"),
            t("source", "duty forecaster"), t("scope", "Public"),
            t("code", "IPAWSv1.0"), t("code", "EXERCISE"), t("note", "exercise message"),
            t("references", "warnings.example.org,ALERT-2024-0000,2024-05-01T10:00:00-00:00"),
            t("incidents", "FLOOD-7")]
    def alert(canonical):
        return el("alert", head + [info("en-GB", "Flood warning", "flood warning for the valley", True, canonical),
                                   info("de-DE", "Hochwasserwarnung", "Hochwasserwarnung fuer das Tal", False, canonical)],
                  attrs=[("xmlns", CAP_NS)])
    out["01-full-alert-roundtrip"] = vec("full-alert-roundtrip", "cap", "cap", xml(alert(False)), xml(alert(True)),
        {"@kind": "alert", "cap.identifier": "ALERT-2024-0001", "cap.sent": "2024-05-01T11:45:00-00:00",
         "time_ms": str(iso_to_ms("2024-05-01T11:45:00-00:00")), "cap.codes.#": "2",
         "cap.infos.#": "2", "cap.infos[0].cap.categories.#": "2",
         "cap.infos[0].cap.areas[0].cap.polygons.#": "2",
         "cap.infos[0].cap.areas[0].cap.circles[0].cap.circle": "38.5,-120.0 12.5",
         "cap.infos[0].cap.areas[0].cap.geocodes[1].cap.value": "006003",
         "cap.infos[0].cap.areas[0].cap.altitude": "1500",
         "cap.infos[0].cap.resources[0].cap.size": "20480",
         "cap.infos[1].cap.language": "de-DE", "cap.infos[1].cap.areas.#": "absent"},
        REF_CAP, "every element of alert, info, resource and area, two info blocks; sent is written back as written (the -00:00 form), not as iso8601_ms writes it; altitude 1500.0 is written 1500")

    minimal = el("alert", [t("identifier", "A2"), t("sender", "sender.example.org"),
                           t("sent", "2024-05-01T14:30:00+02:00"), t("status", "Actual"),
                           t("msgType", "Cancel"), t("scope", "Public")], attrs=[("xmlns", CAP_NS)])
    out["02-minimal-alert-roundtrip"] = vec("minimal-alert-roundtrip", "cap", "cap", xml(minimal), xml(minimal),
        {"cap.infos.#": "absent", "time_ms": str(iso_to_ms("2024-05-01T14:30:00+02:00"))},
        REF_CAP, "only the six required elements of alert; no info")

    exp = js({"type": "Feature", "geometry": None,
              "properties": {"time_ms": iso_to_ms("2024-05-01T14:30:00+02:00")}})
    out["03-alert-to-geojson"] = vec("alert-to-geojson", "cap", "geojson", xml(minimal), exp,
        {"time_ms": str(iso_to_ms("2024-05-01T14:30:00+02:00"))},
        REF_CAP, "sent carries as time_ms, the offset converted to UTC; the area geometry is text and does not carry, so geometry is null")

    old = el("alert", minimal[2], attrs=[("xmlns", "urn:oasis:names:tc:emergency:cap:1.1")])
    out["04-cap-1-1-namespace-is-no-kind"] = vec("cap-1-1-namespace-is-no-kind", "cap", "cap", xml(old),
        error="no-kind", ref=REF_CAP, note="a CAP 1.1 document; the common when on the 1.2 namespace does not hold")

    bad = el("alert", minimal[2] + [el("info", [t("category", "Met"), t("event", "x"), t("urgency", "Past"),
             t("severity", "Minor"), t("certainty", "Observed"),
             el("resource", [t("resourceDesc", "d"), t("mimeType", "text/plain"), t("size", "large")])])],
             attrs=[("xmlns", CAP_NS)])
    out["05-resource-size-not-integer"] = vec("resource-size-not-integer", "cap", "cap", xml(bad),
        error="transform-decode", ref=REF_CAP, note="size is xs:integer; an item whose field fails its transform fails the decode (0.7 Decode)")

    nozone = el("alert", [t("identifier", "A3"), t("sender", "s"), t("sent", "2024-05-01T12:00:00"),
                          t("status", "Actual"), t("msgType", "Alert"), t("scope", "Public")], attrs=[("xmlns", CAP_NS)])
    out["06-sent-without-offset"] = vec("sent-without-offset", "cap", "cap", xml(nozone), error="transform-decode",
        ref=REF_CAP, note="CAP requires a numeric offset; a sent with no designator fails iso8601_ms (ruling 9 of 0.1.1)")
    return out


def geojson_to_cap():
    ms = iso_to_ms("2024-05-01T11:45:00-00:00")
    inp = js({"type": "Feature", "geometry": {"type": "Point", "coordinates": [8.5, 47.4]},
              "properties": {"time_ms": ms, "callsign": "X"}})
    a = vec("to-cap-without-required-elements-is-no-kind", "geojson", "cap", inp, error="no-kind",
            ref=REF_CAP + "; packs/cap/pack.def",
            note="the alert kind requires identifier, sender, sent, status, msgType and scope, which no geojson line yields")
    ctx = {"cap.identifier": "A9", "cap.sender": "sender.example.org", "cap.sent": "2024-05-01T11:45:00-00:00",
           "cap.status": "Test", "cap.msg_type": "Alert", "cap.scope": "Public"}
    exp = xml(el("alert", [t("identifier", "A9"), t("sender", "sender.example.org"), t("sent", "2024-05-01T11:45:00-00:00"),
                           t("status", "Test"), t("msgType", "Alert"), t("scope", "Public")], attrs=[("xmlns", CAP_NS)]))
    b = vec("to-cap-with-context", "geojson", "cap", inp, exp, ref=REF_CAP + "; packs/cap/pack.def",
            note="the caller supplies the required elements; sent is written from cap.sent, the earlier line, so the CAP form with -00:00 is kept and time_ms is not written as Z",
            context=ctx)
    return a, b


# -- readsb -------------------------------------------------------------------

# Members in pack line order (readsb-aircraft, after now), with their kind.
RSB = [("hex", "s"), ("type", "s"), ("flight", "s"), ("alt_geom", "f"), ("gs", "f"), ("ias", "f"),
       ("tas", "f"), ("mach", "f"), ("track", "f"), ("track_rate", "f"), ("roll", "f"),
       ("mag_heading", "f"), ("true_heading", "f"), ("baro_rate", "f"), ("geom_rate", "f"),
       ("squawk", "s"), ("emergency", "s"), ("category", "s"), ("nav_qnh", "f"),
       ("nav_altitude_mcp", "f"), ("nav_altitude_fms", "f"), ("nav_heading", "f"), ("lat", "f"),
       ("lon", "f"), ("nic", "i"), ("rc", "f"), ("seen_pos", "f"), ("version", "i"), ("nic_baro", "i"),
       ("nac_p", "i"), ("nac_v", "i"), ("sil", "i"), ("sil_type", "s"), ("gva", "i"), ("sda", "i"),
       ("messages", "i"), ("seen", "f"), ("rssi", "f")]
MAPPED = {k for k, _ in RSB} | {"now"}


def num_text(x, kind):
    """JSON number text the encoder writes (ruling 3 of 0.1.1)."""
    return canon_float(x) if kind == "f" else str(int(x))


def rsb_canon(obj, with_now=True, residue=True):
    """Canonical text of one aircraft object: mapped members in line order,
    then residue scalars (and nested objects of scalars) in input order."""
    parts = []
    order = ([("now", "f")] if with_now else []) + RSB
    for k, kind in order:
        if k in obj:
            v = obj[k]
            if k == "now":
                # two lines on now: time_ms (iscale:1000) is first, so encode writes it (ruling 16 of 0.5)
                parts.append('"now":%s' % ms_to_secs(secs_to_ms(js(v))))
                continue
            parts.append('"%s":%s' % (k, json.dumps(v, ensure_ascii=False) if kind == "s" else num_text(v, kind)))
    if residue:
        for k, v in obj.items():
            if k in MAPPED or isinstance(v, list) or v is None:
                continue
            if isinstance(v, dict):
                inner = ",".join('"%s":%s' % (a, js(b)) for a, b in v.items() if not isinstance(b, (list, dict)) and b is not None)
                if inner:
                    parts.append('"%s":{%s}' % (k, inner))
            else:
                parts.append('"%s":%s' % (k, js(v)))
    return "{" + ",".join(parts) + "}"


FULL = {"now": 1714566600.5, "hex": "3c6586", "type": "adsb_icao", "flight": "DLH4AB  ",
        "alt_baro": 37000, "alt_geom": 37950, "gs": 450.0, "ias": 270, "tas": 462, "mach": 0.788,
        "track": 92.25, "track_rate": -0.03, "roll": -0.5, "mag_heading": 89.65, "true_heading": 92.1,
        "baro_rate": -64, "geom_rate": 0, "squawk": "1000", "emergency": "none", "category": "A3",
        "nav_qnh": 1013.6, "nav_altitude_mcp": 36992, "nav_heading": 90.0,
        "lat": 50.12345, "lon": 8.54321, "nic": 8, "rc": 186, "seen_pos": 0.2, "version": 2,
        "nic_baro": 1, "nac_p": 9, "nac_v": 1, "sil": 3, "sil_type": "perhour", "gva": 2, "sda": 2,
        "alert": 0, "spi": 0, "mlat": [], "tisb": [], "nav_modes": ["autopilot", "vnav"],
        "messages": 5123, "seen": 0.1, "rssi": -12.4, "wd": 271, "ws": 45, "oat": -55, "tat": -26,
        "lastPosition": {"lat": 50.1, "lon": 8.5, "nic": 8, "rc": 186, "seen_pos": 61.5}}


def rsb_vectors():
    out = {}
    inp = js(FULL)
    out["01-aircraft-roundtrip"] = vec("aircraft-roundtrip", "readsb-aircraft", "readsb-aircraft", inp, rsb_canon(FULL),
        {"uid": "3c6586", "callsign": "DLH4AB  ", "lat": "50.12345", "lon": "8.54321", "course": "92.25",
         "readsb.alt_geom": "37950", "readsb.gs": "450", "readsb.now": "1714566600.5",
         "time_ms": str(secs_to_ms("1714566600.5"))},
        REF_RSB, "every documented member the pack maps; alt_baro, alert, spi, wd, ws, oat, tat and the scalars of lastPosition are residue and come back after the mapped members; the arrays mlat, tisb and nav_modes are not carried; 450.0 is written 450, 90.0 is written 90; the trailing spaces of flight are kept")

    a = {"now": 1714566600.5, "hex": "a1b2c3", "flight": "TEST01", "alt_geom": 1000, "gs": 360,
         "track": 45.5, "lat": 47.25, "lon": -122.5}
    hae = scale(1000, 3048, 10000)
    spd = scale(360, 1852, 3600)
    ms = secs_to_ms(js(a["now"]))
    exp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.5,47.25,%s]},"properties":{"time_ms":%d,"callsign":"TEST01","course":45.5,"speed_ms":%s},"id":"a1b2c3"}' % (canon_float(hae), ms, canon_float(spd))
    out["02-aircraft-to-geojson"] = vec("aircraft-to-geojson", "readsb-aircraft", "geojson", js(a), exp,
        {"@complete": True, "hae": canon_float(hae), "speed_ms": canon_float(spd), "uid": "a1b2c3", "time_ms": str(ms)},
        REF_RSB, "alt_geom (feet above the WGS 84 ellipsoid) gives hae = 1000 * 3048 / 10000 = 304.8 m; gs (knots) gives speed_ms = 360 * 1852 / 3600 = 185.2 m/s; track is course; now 1714566600.5 s gives time_ms 1714566600500 (iscale:1000)")

    exp = ('<event version="2.0" uid="a1b2c3" type="a-u-X" time="%s" start="%s"><point lat="47.25" lon="-122.5" hae="%s" ce="9999999" le="9999999"/>'
           '<detail><contact callsign="TEST01"/><track course="45.5" speed="%s"/></detail></event>') % (
        ms_to_iso(ms), ms_to_iso(ms), canon_float(hae), canon_float(spd))
    out["03-aircraft-to-cot-xml"] = vec("aircraft-to-cot-xml", "readsb-aircraft", "cot-xml", js(a), exp,
        ref=REF_RSB + "; packs/cot-xml/pack.def", note="now 1714566600.5 s is time_ms 1714566600500 (iscale:1000), which cot-xml writes as time and start (iso8601_ms); no stale is derived; cot-xml writes its defaults for type, ce and le")

    ground = {"now": 1714566601, "hex": "~1a2b3c", "type": "tisb_other", "alt_baro": "ground", "gs": 12.5,
              "lat": 50.0, "lon": 8.5}
    out["04-ground-and-non-icao"] = vec("ground-and-non-icao", "readsb-aircraft", "readsb-aircraft", js(ground),
        rsb_canon(ground), {"uid": "~1a2b3c", "lat": "50", "time_ms": "1714566601000"},
        REF_RSB, "alt_baro is the text ground here, so no line maps it and residue keeps it; a non-ICAO address keeps its ~; now 1714566601 is written as an integer value")

    out["05-latitude-as-text"] = vec("latitude-as-text", "readsb-aircraft", "readsb-aircraft",
        js({"hex": "a1b2c3", "lat": "47.25", "lon": -122.5}), error="transform-decode",
        ref=REF_RSB, note="lat is a JSON number in the format; a string under float is a transform failure (0.5 json transforms)")
    return out


def geojson_to_rsb():
    inp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.5,47.25,304.8]},"properties":{"callsign":"TEST01","course":45.5,"speed_ms":185.2},"id":"a1b2c3"}'
    alt = scale(304.8, 10000, 3048)
    gs = scale(185.2, 3600, 1852)
    exp = '{"hex":"a1b2c3","flight":"TEST01","alt_geom":%s,"gs":%s,"track":45.5,"lat":47.25,"lon":-122.5}' % (canon_float(alt), canon_float(gs))
    return vec("to-readsb-aircraft", "geojson", "readsb-aircraft", inp, exp,
               {"@complete": True, "readsb.alt_geom": canon_float(alt), "readsb.gs": canon_float(gs)},
               REF_RSB + "; model/readsb.def", "hae 304.8 m gives alt_geom 304.8 * 10000 / 3048 = 1000 ft; speed_ms 185.2 gives gs 185.2 * 3600 / 1852 = 360 kt")


def geojson_time_to_rsb():
    inp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-122.5,47.25]},"properties":{"time_ms":1714566601250},"id":"a1b2c3"}'
    exp = '{"now":%s,"hex":"a1b2c3","lat":47.25,"lon":-122.5}' % ms_to_secs(1714566601250)
    return vec("to-readsb-aircraft-with-time", "geojson", "readsb-aircraft", inp, exp,
               {"@complete": True, "uid": "a1b2c3", "time_ms": "1714566601250", "lat": "47.25", "lon": "-122.5"},
               REF_RSB + "; spec/engine-spec.md 0.15 (iscale)",
               "time_ms 1714566601250 is written as now = 1714566601250 / 1000 = 1714566601.25 seconds, exactly; now is the first member of the object")


def file_vectors():
    out = {}
    a1 = {"hex": "3c6586", "type": "adsb_icao", "flight": "DLH4AB  ", "alt_geom": 37950, "gs": 450.5,
          "track": 92.25, "lat": 50.12345, "lon": 8.54321, "seen_pos": 0.2, "messages": 5123, "seen": 0.1, "rssi": -12.4}
    a2 = {"hex": "~1a2b3c", "type": "tisb_other", "gs": 12, "lat": 50.0, "lon": 8.5, "seen": 3.5}
    doc = {"now": 1714566600.5, "messages": 912345, "aircraft": [a1, a2]}
    exp = '{"now":1714566600.5,"messages":912345,"aircraft":[%s,%s]}' % (
        rsb_canon(a1, with_now=False, residue=False), rsb_canon(a2, with_now=False, residue=False))
    out["01-file-roundtrip"] = vec("file-roundtrip", "readsb-aircraft-json", "readsb-aircraft-json", js(doc), exp,
        {"readsb.now": "1714566600.5", "time_ms": "1714566600500", "readsb.messages": "912345", "readsb.aircraft.#": "2",
         "readsb.aircraft[0].uid": "3c6586", "readsb.aircraft[1].lat": "50", "readsb.aircraft[1].readsb.gs": "12"},
        REF_RSB, "two aircraft objects, every member mapped, so the round trip is exact; 50.0 is written 50")

    b = dict(a2)
    b["alt_baro"] = "ground"
    b["nav_modes"] = ["tcas"]
    doc = {"now": 1714566601, "messages": 7, "aircraft": [b]}
    exp = '{"now":1714566601,"messages":7,"aircraft":[%s]}' % rsb_canon(a2, with_now=False, residue=False)
    out["02-item-members-unmapped-are-dropped"] = vec("item-members-unmapped-are-dropped", "readsb-aircraft-json",
        "readsb-aircraft-json", js(doc), exp, {"readsb.aircraft.#": "1", "time_ms": "1714566601000"},
        REF_RSB, "items carry no residue (0.7 Decode): alt_baro and nav_modes of an aircraft object are dropped")

    doc = {"now": 1714566602, "messages": 0, "aircraft": []}
    out["03-no-aircraft"] = vec("no-aircraft", "readsb-aircraft-json", "readsb-aircraft-json", js(doc), js(doc),
        {"readsb.aircraft.#": "0", "time_ms": "1714566602000"}, REF_RSB, "an empty aircraft array is a present, empty list and is written as []")
    return out


def write(path, v):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(v, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    gt = sys.argv[1]
    P = lambda *a: os.path.join(gt, "packs", *a)
    for fn, v in cap_vectors().items():
        write(P("cap", "vectors", fn + ".json"), v)
    a, b = geojson_to_cap()
    write(P("geojson", "vectors", "93-to-cap-without-required-elements-is-no-kind.json"), a)
    write(P("geojson", "vectors", "94-to-cap-with-context.json"), b)
    rv = rsb_vectors()
    for fn, v in rv.items():
        write(P("readsb-aircraft", "vectors", fn + ".json"), v)
    write(P("geojson", "vectors", "95-to-readsb-aircraft.json"), geojson_to_rsb())
    write(P("geojson", "vectors", "96-to-readsb-aircraft-with-time.json"), geojson_time_to_rsb())
    for fn, v in file_vectors().items():
        write(P("readsb-aircraft-json", "vectors", fn + ".json"), v)


if __name__ == "__main__":
    main()
