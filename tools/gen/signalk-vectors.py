#!/usr/bin/env python3
"""Hand-derived vectors of the signalk-vessel and signalk-delta packs.

The messages follow the Signal K schemas (vessel.json, groups/navigation.json,
definitions.json, delta.json at SignalK/specification c6130b2a). Expected text is
built here to the canonical rules of the json wire (engine-spec 0.5, "Canonical
output": mapped members in field-line order, a nested object where its first line
is, then residue in input order; no whitespace; numbers as the shortest round-trip
decimal) and of geojson (0.1.1 rulings 3 and 4). Derived values are chosen so the
derivation is exact: courseOverGroundTrue 0.7853981633974483 rad gives 45 degrees
through `deg`, and 90 degrees gives 1.5707963267948966 rad through `rad`.
No engine is imported.

    python3 -I tools/gen/signalk-vectors.py [--check] [<checkout>]
"""
import calendar
import json
import math
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "Signal K specification c6130b2a; text by tools/gen/signalk-vectors.py"


def j(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def ms(text):
    """Epoch milliseconds of an RFC 3339 UTC text with three fraction digits."""
    date, frac = text[:-1].split(".")
    return calendar.timegm(tuple(map(int, date.replace("T", "-").replace(":", "-").split("-"))) + (0, 0, 0)) * 1000 + int(frac)


UUID = "urn:mrn:signalk:uuid:6b0e776f-811a-4b35-980e-b93405371bc5"
T1 = "2026-11-20T10:15:30.250Z"


def vessel():
    return {"uuid": UUID, "name": "Seabird", "mmsi": "230099999",
            "navigation": {
                "position": {"value": {"latitude": 52.0987654, "longitude": 4.98765245, "altitude": 12.5},
                             "timestamp": T1, "$source": "nmea0183.GP"},
                "courseOverGroundTrue": {"value": 0.7853981633974483, "timestamp": T1, "$source": "nmea0183.GP"},
                "speedOverGround": {"value": 3.5, "timestamp": T1, "$source": "nmea0183.GP"},
                "headingTrue": {"value": 0.5},
                "state": {"value": "motoring"}},
            "design": {"length": {"value": {"overall": 12.3}}}}


def vec(name, frm, to, inp, expect=None, model=None, error=None, note=""):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = REF + ("; " + note if note else "")
    return v


def build(out):
    files = []
    v = vessel()
    text = j(v)
    files.append(("packs/signalk-vessel/vectors/01-vessel-roundtrip.json",
                  vec("signalk-vessel-roundtrip", "signalk-vessel", "signalk-vessel", text, text,
                      {"lat": "52.0987654", "lon": "4.98765245", "time_ms": str(ms(T1)), "callsign": "Seabird",
                       "speed_ms": "3.5", "signalk.cog_true_rad": "0.7853981633974483",
                       "signalk.heading_true_rad": "0.5", "signalk.navigation_state": "motoring",
                       "signalk.position_altitude_m": "12.5", "signalk.vessel_mmsi": "230099999"},
                      note="the design group is residue and comes back after the mapped members")))
    loose = json.dumps({"name": "Seabird", "navigation": {"position": {"value": {"latitude": 52.5, "longitude": -3.25},
                                                                       "timestamp": "2026-11-20T10:15:30Z"}}}, indent=1)
    canon = j({"name": "Seabird", "navigation": {"position": {"value": {"latitude": 52.5, "longitude": -3.25},
                                                              "timestamp": "2026-11-20T10:15:30.000Z"}}})
    files.append(("packs/signalk-vessel/vectors/02-vessel-canonical-timestamp.json",
                  vec("signalk-vessel-canonical-timestamp", "signalk-vessel", "signalk-vessel", loose, canon,
                      note="the position timestamp is time_ms, written back with three fraction digits")))
    deg = 0.7853981633974483 * (180 / math.pi)
    assert deg == 45.0
    gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[4.98765245,52.0987654]},' \
         '"properties":{"time_ms":%d,"callsign":"Seabird","course":45,"speed_ms":3.5}}' % ms(T1)
    files.append(("packs/signalk-vessel/vectors/03-vessel-to-geojson.json",
                  vec("signalk-vessel-to-geojson", "signalk-vessel", "geojson", text, gj,
                      note="course 45 degrees derived from 0.7853981633974483 rad; altitude has no stated reference, not hae")))
    rad = 90 * (math.pi / 180)
    assert repr(rad) == "1.5707963267948966"
    gin = '{"type":"Feature","geometry":{"type":"Point","coordinates":[-3.25,52.5]},' \
          '"properties":{"time_ms":%d,"callsign":"Seabird","course":90,"speed_ms":2.5}}' % ms(T1)
    sk = j({"name": "Seabird", "navigation": {
        "position": {"value": {"latitude": 52.5, "longitude": -3.25}, "timestamp": T1},
        "courseOverGroundTrue": {"value": rad}, "speedOverGround": {"value": 2.5}}})
    files.append(("packs/geojson/vectors/to-signalk-vessel-position-course-speed.json",
                  vec("geojson-to-signalk-vessel", "geojson", "signalk-vessel", gin, sk,
                      note="course 90 degrees becomes 1.5707963267948966 rad through rad")))
    files.append(("packs/signalk-vessel/vectors/04-latitude-not-a-number.json",
                  vec("signalk-vessel-latitude-text", "signalk-vessel", "signalk-vessel",
                      j({"navigation": {"position": {"value": {"latitude": "52.5", "longitude": 4.0}}}}),
                      error="transform-decode", note="the schema's latitude is a number")))
    delta = {"context": "vessels." + UUID, "updates": [
        {"source": {"label": "N2K-1", "type": "NMEA2000", "src": "36", "pgn": 129025},
         "timestamp": T1,
         "values": [{"path": "navigation.position", "value": {"latitude": 52.0987654, "longitude": 4.98765245}}]},
        {"$source": "nmea0183.GP", "timestamp": T1,
         "values": [{"path": "navigation.speedOverGround", "value": 3.5},
                    {"path": "navigation.state", "value": "motoring"}],
         "meta": [{"path": "navigation.speedOverGround", "value": {"units": "m/s"}}]}]}
    dout = {"context": "vessels." + UUID, "updates": [
        {"source": {"label": "N2K-1", "type": "NMEA2000", "src": "36", "pgn": 129025},
         "timestamp": T1, "values": [{"path": "navigation.position"}]},
        {"$source": "nmea0183.GP", "timestamp": T1,
         "values": [{"path": "navigation.speedOverGround"}, {"path": "navigation.state"}],
         "meta": [{"path": "navigation.speedOverGround"}]}]}
    files.append(("packs/signalk-delta/vectors/01-delta-paths.json",
                  vec("signalk-delta-paths", "signalk-delta", "signalk-delta", j(delta), j(dout),
                      {"signalk.delta_context": "vessels." + UUID, "signalk.delta_updates.#": "2",
                       "signalk.delta_updates[0].signalk.delta_update_source_label": "N2K-1",
                       "signalk.delta_updates[0].signalk.delta_update_source_pgn": "129025",
                       "signalk.delta_updates[0].signalk.delta_values.#": "1",
                       "signalk.delta_updates[0].signalk.delta_values[0].signalk.delta_value_path": "navigation.position",
                       "signalk.delta_updates[1].signalk.delta_update_source_ref": "nmea0183.GP",
                       "signalk.delta_updates[1].signalk.delta_values.#": "2",
                       "signalk.delta_updates[1].signalk.delta_meta.#": "1"},
                      note="the value of each pair is not carried: items keep only mapped members (engine-spec 0.7)")))
    for rel, v in files:
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    return {"signalk": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("signalk-vectors", __doc__.split("\n")[0], build))
