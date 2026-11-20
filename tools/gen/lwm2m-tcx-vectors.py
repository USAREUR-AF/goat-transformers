#!/usr/bin/env python3
"""Write the vectors of the lwm2m-json and tcx packs.

lwm2m-json reads an OMA LwM2M JSON payload (content format 11543, LwM2M 1.0.2 section 6.4.4);
tcx reads a Garmin Training Center Database v2 document. This script holds its own copy of the
members each pack maps, in the order the packs list them, builds every message from values
written for these vectors (no example of either specification is used), and works out the
canonical output and the decoded values by the rules of spec/engine-spec.md: 0.5 (`json`
wire, residue, canonical output), 0.7 (groups: items carry no residue), 0.1 (xml canonical
form: attributes in line order, then elements in line order) and ruling 3 of 0.1.1 (number
text). It reads no pack.def and calls no goat-transformers engine.

Usage: python3 -I tools/gen/lwm2m-tcx-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/lwm2m-tcx-vectors.py from the members the pack maps and spec/engine-spec.md; no engine run"
REF_LWM2M = "OMA LwM2M 1.0.2 technical specification, section 6.4.4 JSON; resource IDs from the OMA LwM2M registry"
REF_TCX = "Garmin Training Center Database XML schema v2 (TrainingCenterDatabasev2.xsd)"


def num(x):
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


def vec(name, frm, inp, expect=None, model=None, error=None, ref=None, note=None):
    v = {"name": name, "from": frm, "to": frm, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = SOURCE
    v["reference"] = ref + ("; " + note if note else "")
    return v


# -- lwm2m-json ----------------------------------------------------------------------------------
# top members in line order, then the members of an entry in line order: (member, transform)
TOP = [("bn", "string"), ("bt", "float")]
ENTRY = [("n", "string"), ("t", "float"), ("v", "float"), ("bv", "bool"), ("ov", "string"), ("sv", "string")]
KEY = {"bn": "lwm2m.base_name", "bt": "lwm2m.base_time", "n": "lwm2m.name", "t": "lwm2m.time",
       "v": "lwm2m.value", "bv": "lwm2m.boolean_value", "ov": "lwm2m.objlnk_value", "sv": "lwm2m.string_value"}


def jtext(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return num(v)


def lwm2m_canonical(doc):
    """Mapped members in line order (e at its group line, after bn and bt), each entry with its
    mapped members in line order and nothing else (0.7), then top-level scalar residue in input
    order (0.5); arrays and null are not carried."""
    parts = ['"%s":%s' % (m, jtext(doc[m])) for m, _ in TOP if doc.get(m) is not None]
    if "e" in doc:
        items = ["{" + ",".join('"%s":%s' % (m, jtext(it[m])) for m, _ in ENTRY if it.get(m) is not None) + "}"
                 for it in doc["e"]]
        parts.append('"e":[%s]' % ",".join(items))
    known = {m for m, _ in TOP} | {"e"}
    parts += ['"%s":%s' % (k, jtext(v)) for k, v in doc.items()
              if k not in known and v is not None and not isinstance(v, (list, dict))]
    return "{" + ",".join(parts) + "}"


def lwm2m_model(doc, picks):
    ent = {}
    for m, _ in TOP:
        if doc.get(m) is not None:
            ent[KEY[m]] = doc[m]
    ent["lwm2m.entries.#"] = len(doc["e"])
    for i, it in enumerate(doc["e"]):
        for m, tr in ENTRY:
            if it.get(m) is not None:
                v = it[m]
                ent["lwm2m.entries[%d].%s" % (i, KEY[m])] = (1 if v else 0) if tr == "bool" else v
    return {k: (num(ent[k]) if not isinstance(ent[k], str) else ent[k]) for k in picks}


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def lwm2m_vectors():
    V = {}
    F = "lwm2m-json"
    device = {"bn": "/3/0/", "e": [
        {"n": "0", "sv": "Example Systems"}, {"n": "1", "sv": "EX-200"}, {"n": "2", "sv": "SN-000417"},
        {"n": "3", "sv": "2.4.1"}, {"n": "6/0", "v": 1}, {"n": "7/0", "v": 3700}, {"n": "9", "v": 87},
        {"n": "11/0", "v": 0}, {"n": "13", "v": 1763640000}, {"n": "14", "sv": "+01:00"},
        {"n": "16", "sv": "U"}, {"n": "17", "sv": "tracker"}]}
    V["01-device-instance-roundtrip"] = vec("device-instance-roundtrip", F, js(device), lwm2m_canonical(device),
        lwm2m_model(device, ["lwm2m.base_name", "lwm2m.entries.#", "lwm2m.entries[0].lwm2m.string_value",
                             "lwm2m.entries[6].lwm2m.name", "lwm2m.entries[6].lwm2m.value", "lwm2m.entries[8].lwm2m.value"]),
        ref=REF_LWM2M, note="instance 0 of the Device object (3): manufacturer, model, serial, firmware, power source, "
                            "voltage, battery level, error code, current time, UTC offset, binding, device type")
    loc = {"bn": "/6/0/", "e": [{"n": "0", "v": 47.6205, "t": -10}, {"n": "1", "v": -122.3493, "t": -10},
                                {"n": "2", "v": 56.5, "t": -10}, {"n": "5", "v": 1763639990, "t": -10},
                                {"n": "6", "v": 1.25, "t": -10}], "bt": 1763640000}
    V["02-location-notification-reordered"] = vec("location-notification-reordered", F, js(loc), lwm2m_canonical(loc),
        lwm2m_model(loc, ["lwm2m.base_time", "lwm2m.entries[0].lwm2m.value", "lwm2m.entries[1].lwm2m.value",
                          "lwm2m.entries[0].lwm2m.time"]),
        ref=REF_LWM2M, note="a notification of the Location object (6): latitude, longitude, altitude, timestamp and "
                            "speed, ten seconds before the base time; bt is written before e, and t before v")
    full = {"e": [{"n": "/3303/0/5700", "v": 21.5}, {"n": "/3303/0/5701", "sv": "Cel"},
                  {"n": "/3311/0/5850", "bv": True}, {"n": "/3311/1/5850", "bv": False}]}
    V["03-full-names-and-booleans-roundtrip"] = vec("full-names-and-booleans-roundtrip", F, js(full), lwm2m_canonical(full),
        lwm2m_model(full, ["lwm2m.entries[0].lwm2m.name", "lwm2m.entries[2].lwm2m.boolean_value",
                           "lwm2m.entries[3].lwm2m.boolean_value"]),
        ref=REF_LWM2M, note="no base name, so each name is the full path: a Temperature (3303) value and its unit, "
                            "and the on/off state of two Light Control (3311) instances; a boolean is held as 1 or 0")
    link = {"bn": "/", "e": [{"n": "65/0/0/0", "ov": "66:0"}, {"n": "65/0/0/1", "ov": "66:1"}, {"n": "66/0/0", "sv": "a"}]}
    V["04-object-links-roundtrip"] = vec("object-links-roundtrip", F, js(link), lwm2m_canonical(link),
        lwm2m_model(link, ["lwm2m.entries[1].lwm2m.objlnk_value"]), ref=REF_LWM2M,
        note="a base name of / and object link values, written object:instance")
    extra = {"bn": "/3303/0/", "ver": 1, "e": [{"n": "5700", "v": 19.75, "x": 2}, {"n": "5701", "sv": "Cel"}]}
    V["05-members-not-in-the-format"] = vec("members-not-in-the-format", F, js(extra), lwm2m_canonical(extra),
        lwm2m_model(extra, ["lwm2m.entries[0].lwm2m.value"]), ref=REF_LWM2M,
        note="a top-level member the format does not define is residue and comes back after e; one inside an entry "
             "is dropped, as an item carries no residue")
    bad = {"bn": "/6/0/", "e": [{"n": "0", "v": "47.6205"}]}
    V["06-value-as-text"] = vec("value-as-text", F, js(bad), error="transform-decode", ref=REF_LWM2M,
                                note="v is a JSON number; a string there is a transform failure")
    return V


# -- tcx -----------------------------------------------------------------------------------------
NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
# element order of each item, as the pack's lines write it (attributes are written first)
LAP_ORDER = ["TotalTimeSeconds", "DistanceMeters", "MaximumSpeed", "Calories", "AverageHeartRateBpm",
             "MaximumHeartRateBpm", "Intensity", "Cadence", "TriggerMethod", "Track", "Notes"]
POINT_ORDER = ["Time", "Position", "AltitudeMeters", "DistanceMeters", "HeartRateBpm", "Cadence", "SensorState"]


def el(name, body, attrs=""):
    return "<%s%s>%s</%s>" % (name, attrs, body, name) if body != "" else "<%s%s/>" % (name, attrs)


def point_xml(p, keep_extensions=False):
    out = ""
    for m in POINT_ORDER:
        if m not in p:
            continue
        v = p[m]
        if m == "Position":
            out += el("Position", el("LatitudeDegrees", num(v[0])) + el("LongitudeDegrees", num(v[1])))
        elif m == "HeartRateBpm":
            out += el("HeartRateBpm", el("Value", num(v)))
        else:
            out += el(m, v if isinstance(v, str) else num(v))
    if keep_extensions and "Extensions" in p:
        out += p["Extensions"]
    return el("Trackpoint", out)


def lap_xml(lap, keep_extensions=False):
    out = ""
    for m in LAP_ORDER:
        if m not in lap:
            continue
        v = lap[m]
        if m in ("AverageHeartRateBpm", "MaximumHeartRateBpm"):
            out += el(m, el("Value", num(v)))
        elif m == "Track":
            for track in v:
                out += el("Track", "".join(point_xml(p, keep_extensions) for p in track))
        else:
            out += el(m, v if isinstance(v, str) else num(v))
    return el("Lap", out, ' StartTime="%s"' % lap["StartTime"])


def tcx_xml(activities, keep_extensions=False, ns=NS):
    acts = ""
    for a in activities:
        body = el("Id", a["Id"]) + "".join(lap_xml(l, keep_extensions) for l in a["Laps"])
        if "Notes" in a:
            body += el("Notes", a["Notes"])
        acts += el("Activity", body, ' Sport="%s"' % a["Sport"])
    return el("TrainingCenterDatabase", el("Activities", acts), ' xmlns="%s"' % ns)


def run_activity():
    pts = [{"Time": "2026-11-15T07:30:00Z", "Position": (47.6205, -122.3493), "AltitudeMeters": 56.5,
            "DistanceMeters": 0.5, "HeartRateBpm": 98, "Cadence": 80, "SensorState": "Present"},
           {"Time": "2026-11-15T07:30:05Z", "Position": (47.62065, -122.34915), "AltitudeMeters": 56.75,
            "DistanceMeters": 18.25, "HeartRateBpm": 104, "Cadence": 82, "SensorState": "Present"},
           {"Time": "2026-11-15T07:30:10Z", "Position": (47.6208, -122.349), "AltitudeMeters": 57.25,
            "DistanceMeters": 36.5, "HeartRateBpm": 109}]
    lap = {"StartTime": "2026-11-15T07:30:00Z", "TotalTimeSeconds": 10.5, "DistanceMeters": 36.5,
           "MaximumSpeed": 3.75, "Calories": 3, "AverageHeartRateBpm": 104, "MaximumHeartRateBpm": 109,
           "Intensity": "Active", "Cadence": 81, "TriggerMethod": "Manual", "Track": [pts], "Notes": "warm-up"}
    return [{"Sport": "Running", "Id": "2026-11-15T07:30:00Z", "Laps": [lap], "Notes": "test run"}]


def tcx_vectors():
    V = {}
    F = "tcx"
    acts = run_activity()
    x = tcx_xml(acts)
    V["01-run-roundtrip"] = vec("run-roundtrip", F, x, x, {
        "@kind": "database", "tcx.activities.#": "1", "tcx.activities[0].tcx.activity_sport": "Running",
        "tcx.activities[0].tcx.laps[0].tcx.lap_calories": "3",
        "tcx.activities[0].tcx.laps[0].tcx.tracks[0].tcx.trackpoints.#": "3",
        "tcx.activities[0].tcx.laps[0].tcx.tracks[0].tcx.trackpoints[1].tcx.point_latitude": num(47.62065),
        "tcx.activities[0].tcx.laps[0].tcx.tracks[0].tcx.trackpoints[2].tcx.point_heart_rate": "109"},
        ref=REF_TCX, note="one run: an activity with one lap, one track and three trackpoints; the last point has no "
                          "cadence or sensor state")
    two = [{"Sport": "Biking", "Id": "2026-11-16T16:00:00Z", "Laps": [
        {"StartTime": "2026-11-16T16:00:00Z", "TotalTimeSeconds": 600.5, "DistanceMeters": 4200.25, "Calories": 95,
         "Intensity": "Active", "TriggerMethod": "Distance",
         "Track": [[{"Time": "2026-11-16T16:00:00Z", "Position": (51.5007, -0.1246)}],
                   [{"Time": "2026-11-16T16:05:00Z", "Position": (51.5101, -0.1342)}]]},
        {"StartTime": "2026-11-16T16:10:00.5Z", "TotalTimeSeconds": 300.25, "DistanceMeters": 1800.5, "Calories": 40,
         "Intensity": "Resting", "TriggerMethod": "Manual"}]},
           {"Sport": "Other", "Id": "2026-11-16T18:00:00Z", "Laps": [
               {"StartTime": "2026-11-16T18:00:00Z", "TotalTimeSeconds": 60.5, "DistanceMeters": 0.25, "Calories": 2,
                "Intensity": "Resting", "TriggerMethod": "Time"}]}]
    x = tcx_xml(two)
    V["02-two-activities-roundtrip"] = vec("two-activities-roundtrip", F, x, x, {
        "@kind": "database", "tcx.activities.#": "2", "tcx.activities[0].tcx.laps.#": "2",
        "tcx.activities[0].tcx.laps[0].tcx.tracks.#": "2",
        "tcx.activities[0].tcx.laps[1].tcx.lap_start_time": "2026-11-16T16:10:00.5Z",
        "tcx.activities[1].tcx.activity_sport": "Other"},
        ref=REF_TCX, note="a ride whose first lap has two tracks and whose second lap has none, then a second activity; "
                          "date-times are kept as text, fractions of a second included")
    ext = run_activity()
    ext[0]["Laps"][0]["Track"][0][0]["Extensions"] = (
        '<Extensions><TPX xmlns="http://www.garmin.com/xmlschemas/ActivityExtension/v2"><Speed>3.25</Speed></TPX></Extensions>')
    V["03-trackpoint-extensions-are-dropped"] = vec("trackpoint-extensions-are-dropped", F, tcx_xml(ext, True), tcx_xml(ext, False),
        {"tcx.activities[0].tcx.laps[0].tcx.tracks[0].tcx.trackpoints.#": "3"}, ref=REF_TCX,
        note="an Extensions element inside a trackpoint (written with a default namespace, no prefix) is not mapped "
             "and an item carries no residue, so it is dropped")
    V["04-version-1-namespace"] = vec("version-1-namespace", F,
        tcx_xml(run_activity(), ns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v1"),
        error="no-kind", ref=REF_TCX, note="a document in the namespace of TCX version 1: the pack's when does not hold")
    bad = run_activity()
    bad[0]["Laps"][0]["Calories"] = "3.5"
    V["05-calories-not-an-integer"] = vec("calories-not-an-integer", F, tcx_xml(bad), error="transform-decode",
                                          ref=REF_TCX, note="Calories is an unsigned short; 3.5 is a transform failure")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("lwm2m-json", lwm2m_vectors()), ("tcx", tcx_vectors())):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("lwm2m-tcx-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
