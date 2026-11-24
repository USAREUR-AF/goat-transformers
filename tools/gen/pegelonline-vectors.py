#!/usr/bin/env python3
"""Write the vectors of the pegelonline-station, pegelonline-timeseries and pegelonline-current packs.

Every response is built here from values written for these vectors in the shape the PEGELONLINE
REST API v2 documentation describes; no live response is copied. This script holds its own copy
of the members each pack maps, in line order, and works out the canonical output by the rules of
spec/engine-spec.md: 0.5 (json wire: mapped members in line order, a nested object at the
position of the first line that addresses into it, then scalar residue in input order at any depth
of nested objects; arrays and null are not carried; ruling 16: two lines on one locator write the
earliest present key), 0.7 (groups: items carry no residue), ruling 3 of 0.1.1 (number text) and
the iso8601_ms grammar (ruling 3 of 0.11 and the offset correction of 0.6: an offset is converted
to UTC on decode; encode writes YYYY-MM-DDTHH:MM:SS.fffZ). It reads no pack.def and calls no
goat-transformers engine.

Usage: python3 -I tools/gen/pegelonline-vectors.py [--out DIR] [--check]
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/pegelonline-vectors.py from responses written for it and spec/engine-spec.md; no engine run"
REF = "PEGELONLINE REST API v2 documentation (pegelonline.wsv.de/webservice/dokuRestapi)"

ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:([Zz])|([+-])(\d{2}):(\d{2}))$")
EPOCH = datetime.datetime(1970, 1, 1)


def iso_ms(v):
    m = ISO.match(v) if isinstance(v, str) else None
    if not m:
        raise Fail("transform-decode")
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    try:
        t = datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        raise Fail("transform-decode")
    ms = int(((m.group(7) or "") + "000")[:3])
    off = 0
    if m.group(9):
        off = (int(m.group(10)) * 60 + int(m.group(11))) * (1 if m.group(9) == "+" else -1)
    delta = t - EPOCH - datetime.timedelta(minutes=off)
    return (delta.days * 86400 + delta.seconds) * 1000 + ms


def iso_text(ms):
    t = EPOCH + datetime.timedelta(milliseconds=ms)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def F(path, key, tr):
    return ("f", tuple(path.split(".")) if path != "." else (), key, tr)


def G(path, lst, body):
    return ("g", tuple(path.split(".")), lst, body)


P = "pegelonline."


def ts_lines(time_ms):
    L = [F("shortname", P + "ts_shortname", "string"), F("longname", P + "ts_longname", "string"),
         F("unit", P + "unit", "string"), F("equidistance", P + "equidistance", "int")]
    if time_ms:
        L.append(F("currentMeasurement.timestamp", "time_ms", "iso8601_ms"))
    L += [F("currentMeasurement.timestamp", P + "current_time", "string"),
          F("currentMeasurement.value", P + "current_value", "float"),
          F("currentMeasurement.stateMnwMhw", P + "state_mnw_mhw", "string"),
          F("currentMeasurement.stateNswHsw", P + "state_nsw_hsw", "string"),
          F("gaugeZero.unit", P + "gauge_zero_unit", "string"), F("gaugeZero.value", P + "gauge_zero_value", "float"),
          F("gaugeZero.validFrom", P + "gauge_zero_valid_from", "string")]
    return L


STATION = [F(m, P + k, t) for m, k, t in (
    ("uuid", "uuid", "string"), ("number", "number", "string"), ("shortname", "shortname", "string"),
    ("longname", "longname", "string"), ("km", "km", "float"), ("agency", "agency", "string"))] + [
    F("longitude", "lon", "float"), F("latitude", "lat", "float")] + [F(m, P + k, t) for m, k, t in (
        ("voiceServiceNumber", "voice_service_number", "string"), ("remark", "remark", "string"),
        ("water.shortname", "water_shortname", "string"), ("water.longname", "water_longname", "string"))] + [
    G("timeseries", P + "timeseries", ts_lines(False))]

TIMESERIES = ts_lines(True)

CURRENT = [F("timestamp", "time_ms", "iso8601_ms"), F("timestamp", P + "current_time", "string"),
           F("value", P + "current_value", "float"), F("stateMnwMhw", P + "state_mnw_mhw", "string"),
           F("stateNswHsw", P + "state_nsw_hsw", "string")]


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
    if tr == "iso8601_ms":
        return iso_ms(v)
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
                if ln[3] == "iso8601_ms":
                    x = iso_text(x)
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


def encode_model(lines, model):
    """The json a pack writes from a model alone (a conversion): flat lines in line order, ruling 16."""
    out = {}
    for ln in lines:
        k = ln[2]
        if k in model and at(out, ln[1]) is None:
            x = model[k]
            put(out, ln[1], iso_text(x) if ln[3] == "iso8601_ms" else x)
    return text(out)


UUID = "5f0c1e2d-0000-4000-8000-00000000a001"


def ts_w():
    return {"shortname": "W", "longname": "WASSERSTAND ROHDATEN", "unit": "cm", "equidistance": 15,
            "currentMeasurement": {"timestamp": "2026-11-21T12:15:00+01:00", "value": 157.0,
                                   "stateMnwMhw": "normal", "stateNswHsw": "normal"},
            "gaugeZero": {"unit": "m. ü. NHN", "value": 31.82, "validFrom": "1936-11-01"}}


def station():
    return {"uuid": UUID, "number": "48300999", "shortname": "MUSTERSTADT", "longname": "MUSTERSTADT AM FLUSS",
            "km": 12.5, "agency": "MUSTERAMT", "longitude": 10.25, "latitude": 52.5,
            "voiceServiceNumber": "+49 228 0000000 001", "water": {"shortname": "MUSTER", "longname": "MUSTERFLUSS"},
            "timeseries": [ts_w(), {"shortname": "WT", "longname": "WASSERTEMPERATUR ROHDATEN", "unit": "°C",
                                    "equidistance": 15, "currentMeasurement": {"timestamp": "2026-08-01T14:30:00+02:00",
                                                                               "value": 18.5}}]}


GEO = {}


def station_vectors():
    V = {}
    F_ = "pegelonline-station"
    s = station()
    V["01-station-roundtrip"] = vec(F_, "station-roundtrip", STATION, s, [
        "lat", "lon", P + "km", P + "water_longname", P + "timeseries.#",
        P + "timeseries[0]." + P + "current_time", P + "timeseries[0]." + P + "current_value",
        P + "timeseries[0]." + P + "gauge_zero_value", P + "timeseries[1]." + P + "unit"],
        note="one station with two time series (water level with its states and gauge zero, water temperature "
             "without them); the times inside the list stay as written")
    gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{}}' % (num(10.25), num(52.5))
    V["02-station-to-geojson"] = vec(F_, "station-to-geojson", STATION, s, [], to="geojson", expect=gj,
                                     note="longitude and latitude are WGS84 decimal degrees, as the reference states; "
                                          "the position reaches a GeoJSON Feature")
    v = {"name": "geojson-to-pegelonline-station", "from": "geojson", "to": F_,
         "input": '{"type":"Feature","geometry":{"type":"Point","coordinates":[10.25,52.5]},"properties":{}}',
         "expect": encode_model(STATION, {"lon": 10.25, "lat": 52.5}),
         "source": SOURCE, "reference": REF + "; a GeoJSON point written as a station: longitude, then latitude, in line order"}
    GEO["pegelonline-geojson-to-station"] = v
    bad = station()
    bad["latitude"] = "52.5"
    V["03-latitude-as-text"] = vec(F_, "latitude-as-text", STATION, bad, [], error="transform-decode",
                                   note="latitude is a JSON number; text there is a transform failure")
    return V


def timeseries_vectors():
    V = {}
    F_ = "pegelonline-timeseries"
    t = ts_w()
    V["01-timeseries-roundtrip"] = vec(F_, "timeseries-roundtrip", TIMESERIES, t, [
        "time_ms", P + "current_time", P + "current_value", P + "gauge_zero_value", P + "equidistance"],
        note="one water-level series; the time with its +01:00 offset is time_ms in UTC, and is written back "
             "in UTC with Z (the shared line comes first on the locator)")
    e = ts_w()
    del e["currentMeasurement"], e["gaugeZero"]
    V["02-timeseries-plain"] = vec(F_, "timeseries-plain", TIMESERIES, e, [P + "ts_shortname"],
                                   note="a series requested without its current measurement: time_ms absent")
    return V


def current_vectors():
    V = {}
    F_ = "pegelonline-current"
    c = {"timestamp": "2026-07-15T08:45:00+02:00", "value": 412.0, "stateMnwMhw": "high", "stateNswHsw": "normal"}
    V["01-current-roundtrip"] = vec(F_, "current-roundtrip", CURRENT, c, [
        "time_ms", P + "current_time", P + "current_value", P + "state_mnw_mhw"],
        note="a summer measurement (+02:00, CEST) above mean high water")
    ent = {}
    decode(CURRENT, c, ent)
    V["02-current-to-timeseries"] = vec(F_, "current-to-timeseries", CURRENT, c, [], to="pegelonline-timeseries",
                                        expect=encode_model(TIMESERIES, ent),
                                        note="a current measurement written as a time series: it lands under "
                                             "currentMeasurement, its time in UTC")
    bad = dict(c, value="412")
    V["03-value-as-text"] = vec(F_, "value-as-text", CURRENT, bad, [], error="transform-decode",
                                note="value is a decimal number; text there is a transform failure")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("pegelonline-station", station_vectors()), ("pegelonline-timeseries", timeseries_vectors()),
                    ("pegelonline-current", current_vectors()), ("geojson", GEO)):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("pegelonline-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
