#!/usr/bin/env python3
"""Hand-derived vectors of the homeassistant-state and homeassistant-ws-state-changed packs.

The messages have the shape Home Assistant core writes (State._as_dict, Event._as_dict and the
websocket event_message of tag 2026.11.2): a device_tracker state with latitude, longitude,
gps_accuracy and friendly_name attributes, and the state_changed event that carries it. Times
are what Python's datetime.isoformat() writes for an aware UTC time (microseconds, +00:00).

Expected text follows the canonical rules of the json wire (engine-spec 0.5): mapped members in
field-line order, a nested object where its first line is, residue members after the mapped ones
in input order, `null` members not written, no whitespace. `last_updated` is `time_ms` and comes
back as ISO 8601 with milliseconds and `Z` (the microseconds beyond the millisecond are
truncated, 0.6). GeoJSON text follows 0.1.1 rulings 3 and 4. No engine is imported.

    python3 -I tools/gen/homeassistant-vectors.py [--check] [<checkout>]
"""
import calendar
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "Home Assistant core 2026.11.2 State/Event dict forms; text by tools/gen/homeassistant-vectors.py"
T_CHANGED = "2026-11-20T10:15:30.123456+00:00"
T_UPDATED = "2026-11-20T10:16:02.500999+00:00"
T_UPDATED_OUT = "2026-11-20T10:16:02.500Z"
T_OLD = "2026-11-20T09:00:00+00:00"
MS = calendar.timegm((2026, 11, 20, 10, 16, 2, 0, 0, 0)) * 1000 + 500


def j(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def state_in():
    return {"entity_id": "device_tracker.boat", "state": "not_home",
            "attributes": {"source_type": "gps", "latitude": 52.37, "longitude": 4.89, "gps_accuracy": 12,
                           "battery_level": 87, "friendly_name": "Boat"},
            "last_changed": T_CHANGED, "last_reported": T_UPDATED, "last_updated": T_UPDATED,
            "context": {"id": "01JCX6Z3Q9K2M4N5P6R7S8T9V0", "parent_id": None, "user_id": None}}


def state_out():
    return {"entity_id": "device_tracker.boat", "state": "not_home",
            "attributes": {"latitude": 52.37, "longitude": 4.89, "gps_accuracy": 12, "friendly_name": "Boat",
                           "source_type": "gps", "battery_level": 87},
            "last_changed": T_CHANGED, "last_reported": T_UPDATED, "last_updated": T_UPDATED_OUT,
            "context": {"id": "01JCX6Z3Q9K2M4N5P6R7S8T9V0"}}


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
    model = {"uid": "device_tracker.boat", "lat": "52.37", "lon": "4.89", "time_ms": str(MS), "callsign": "Boat",
             "homeassistant.state": "not_home", "homeassistant.gps_accuracy": "12",
             "homeassistant.last_changed": T_CHANGED}
    files.append(("packs/homeassistant-state/vectors/01-device-tracker-canonical.json",
                  vec("homeassistant-state-device-tracker", "homeassistant-state", "homeassistant-state",
                      json.dumps(state_in(), indent=2), j(state_out()), model,
                      note="mapped attributes first, then the others in input order; null context members dropped; "
                           "last_updated truncated to the millisecond")))
    files.append(("packs/homeassistant-state/vectors/03-sensor-no-position.json",
                  vec("homeassistant-state-sensor", "homeassistant-state", "homeassistant-state",
                      j({"entity_id": "sensor.water_temp", "state": "14.5",
                         "attributes": {"unit_of_measurement": "°C", "friendly_name": "Water"},
                         "last_changed": T_OLD, "last_reported": T_OLD, "last_updated": T_OLD,
                         "context": {"id": "01JCX70000000000000000000A", "parent_id": None, "user_id": None}}),
                      j({"entity_id": "sensor.water_temp", "state": "14.5",
                         "attributes": {"friendly_name": "Water", "unit_of_measurement": "°C"},
                         "last_changed": T_OLD, "last_reported": T_OLD, "last_updated": "2026-11-20T09:00:00.000Z",
                         "context": {"id": "01JCX70000000000000000000A"}}),
                      note="an entity with no position: the state stays text")))
    gin = '{"type":"Feature","id":"device_tracker.boat","geometry":{"type":"Point","coordinates":[4.89,52.37]},' \
          '"properties":{"time_ms":%d,"callsign":"Boat"}}' % MS
    files.append(("packs/geojson/vectors/to-homeassistant-state-position.json",
                  vec("geojson-to-homeassistant-state", "geojson", "homeassistant-state", gin,
                      j({"entity_id": "device_tracker.boat", "attributes": {"latitude": 52.37, "longitude": 4.89,
                                                                            "friendly_name": "Boat"},
                         "last_updated": T_UPDATED_OUT}))))
    old = {"entity_id": "device_tracker.boat", "state": "home", "attributes": {"friendly_name": "Boat"},
           "last_changed": T_OLD, "last_reported": T_OLD, "last_updated": T_OLD,
           "context": {"id": "01JCX5000000000000000000AA", "parent_id": None, "user_id": None}}
    ev = {"id": 7, "type": "event", "event": {
        "event_type": "state_changed",
        "data": {"entity_id": "device_tracker.boat", "old_state": old, "new_state": state_in()},
        "origin": "LOCAL", "time_fired": T_UPDATED,
        "context": {"id": "01JCX6Z3Q9K2M4N5P6R7S8T9V0", "parent_id": None, "user_id": None}}}
    old_out = {"state": "home", "last_updated": T_OLD, "entity_id": "device_tracker.boat",
               "attributes": {"friendly_name": "Boat"}, "last_changed": T_OLD, "last_reported": T_OLD,
               "context": {"id": "01JCX5000000000000000000AA"}}
    ev_out = {"id": 7, "type": "event", "event": {
        "event_type": "state_changed",
        "data": {"entity_id": "device_tracker.boat", "old_state": old_out, "new_state": state_out()},
        "origin": "LOCAL", "time_fired": T_UPDATED,
        "context": {"id": "01JCX6Z3Q9K2M4N5P6R7S8T9V0"}}}
    files.append(("packs/homeassistant-ws-state-changed/vectors/01-state-changed-canonical.json",
                  vec("homeassistant-ws-state-changed", "homeassistant-ws-state-changed", "homeassistant-ws-state-changed",
                      j(ev), j(ev_out), dict(model, **{"@kind": "state_changed", "homeassistant.message_id": "7",
                                                       "homeassistant.old_state": "home"}),
                      note="old_state: state and last_updated mapped, the rest residue after them")))
    other = {"id": 8, "type": "event", "event": {"event_type": "call_service", "data": {"domain": "light"},
                                                  "origin": "LOCAL", "time_fired": T_OLD, "context": {"id": "x"}}}
    files.append(("packs/homeassistant-ws-state-changed/vectors/03-other-event.json",
                  vec("homeassistant-ws-other-event", "homeassistant-ws-state-changed", "homeassistant-ws-state-changed",
                      j(other), error="no-kind", note="only state_changed events are messages of this pack")))
    for rel, v in files:
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    return {"homeassistant": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("homeassistant-vectors", __doc__.split("\n")[0], build))
