#!/usr/bin/env python3
"""Hand-derived vectors of the shelly-notify-status, shelly-notify-event, shelly-rpc-response and
shelly-rpc-request packs.

The frames have the shape the Shelly Gen2+ API documentation describes: a JSON-RPC frame with src
and dst, a notification whose params carry ts (Unix seconds, a number with a fraction) and the
changed component status objects keyed by component key (switch:0, cover:0, input:0,
temperature:100, sys), an event list, a response with result or error, a request with method
and params. Device names, times and values are my own; none is taken from the documentation.

Expected text follows the canonical rules of the json wire (engine-spec 0.5): common lines, then
the kind's, with the kind's `when` member (method) at its line; a nested object where its first
line is; residue after the mapped members of each object, in input order; arrays no group maps
are not carried; `null` is absent; an object left with no members is not written. Group items
carry no residue (0.7). `ts` is `time_ms` through `iscale:1000`: decode rounds the exact decimal
times 1000 half away from zero, encode writes the exact quotient with no trailing zero (0.14 and
rulings 4 and 7 of 0.15). No engine is imported.

    python3 -I tools/gen/shelly-vectors.py [--check] [<checkout>]
"""
import calendar
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "Shelly Gen2+ API frame shapes (RPCProtocol, Notifications, component Status objects); " \
      "text by tools/gen/shelly-vectors.py"
DEV = "shellypro4pm-0c8b95f1e2d4"
BASE = calendar.timegm((2026, 11, 21, 10, 16, 2, 0, 0, 0))   # Unix seconds


def j(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


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
    ts = "%d.53" % BASE
    ms = str(BASE * 1000 + 530)
    sw_in = {"id": 0, "source": "WS_in", "output": True, "apower": 12.5, "voltage": 229.8, "current": 0.071,
             "aenergy": {"total": 1234.567, "by_minute": [205.1, 210.4, 0], "minute_ts": BASE - 2},
             "temperature": {"tC": 41.2, "tF": 106.2}}
    sw_out = {"id": 0, "source": "WS_in", "output": True, "apower": 12.5, "voltage": 229.8, "current": 0.071,
              "aenergy": {"total": 1234.567, "minute_ts": BASE - 2}, "temperature": {"tC": 41.2, "tF": 106.2}}
    ns_in = '{"src":"%s","dst":"user_1","method":"NotifyStatus","params":{"ts":%s,"switch:0":%s}}' % (DEV, ts, j(sw_in))
    ns_out = '{"src":"%s","dst":"user_1","method":"NotifyStatus","params":{"ts":%s,"switch:0":%s}}' % (DEV, ts, j(sw_out))
    files.append(("packs/shelly-notify-status/vectors/01-switch-canonical.json",
                  vec("shelly-notify-status-switch", "shelly-notify-status", "shelly-notify-status", ns_in, ns_out,
                      {"@kind": "notify_status", "time_ms": ms, "shelly.src": DEV, "shelly.switch0_output": "1",
                       "shelly.switch0_apower": "12.5", "shelly.switch0_aenergy_total": "1234.567",
                       "shelly.switch0_aenergy_minute_ts": str(BASE - 2), "shelly.switch0_temperature_tc": "41.2"},
                      note="the by_minute array is not carried; ts .53 is 530 ms")))

    full_in = ('{"src":"%s","dst":"user_1","method":"NotifyFullStatus","params":{"ts":%d.0,"ble":{},'
               '"cloud":{"connected":true},"cover:0":{"id":0,"source":"limit_switch","state":"stopped","apower":0,'
               '"current_pos":35,"target_pos":null,"pos_control":true,"last_direction":"close"},'
               '"input:0":{"id":0,"state":null},"sys":{"mac":"0C8B95F1E2D4","restart_required":false,"time":"11:16",'
               '"unixtime":%d,"uptime":86400,"ram_size":246128,"ram_free":117300,"fs_size":458752,"fs_free":135168,'
               '"cfg_rev":12,"kvs_rev":0,"available_updates":{},"utc_offset":3600},'
               '"temperature:100":{"id":100,"tC":21.5,"tF":70.7},"wifi":{"sta_ip":"192.0.2.20","rssi":-58}}}'
               % (DEV, BASE, BASE))
    full_out = ('{"src":"%s","dst":"user_1","method":"NotifyFullStatus","params":{"ts":%d,'
                '"cover:0":{"id":0,"source":"limit_switch","state":"stopped","apower":0,"current_pos":35,'
                '"pos_control":true,"last_direction":"close"},"input:0":{"id":0},'
                '"temperature:100":{"id":100,"tC":21.5,"tF":70.7},'
                '"sys":{"mac":"0C8B95F1E2D4","restart_required":false,"time":"11:16","unixtime":%d,"uptime":86400,'
                '"ram_size":246128,"ram_free":117300,"fs_size":458752,"fs_free":135168,"cfg_rev":12,"kvs_rev":0,'
                '"utc_offset":3600},"cloud":{"connected":true},"wifi":{"sta_ip":"192.0.2.20","rssi":-58}}}'
                % (DEV, BASE, BASE))
    files.append(("packs/shelly-notify-status/vectors/02-full-status.json",
                  vec("shelly-notify-full-status", "shelly-notify-status", "shelly-notify-status", full_in, full_out,
                      {"@kind": "notify_full_status", "time_ms": str(BASE * 1000), "shelly.cover0_current_pos": "35",
                       "shelly.cover0_pos_control": "1", "shelly.sys_restart_required": "0",
                       "shelly.temperature100_tc": "21.5", "shelly.sys_utc_offset": "3600",
                       "@absent": ["shelly.cover0_target_pos", "shelly.input0_state",
                                   "shelly.sys_available_updates_stable_version"]},
                      note="ts written .0 comes back as an integer; null members absent; the empty "
                           "available_updates and ble objects are not written; components in line order "
                           "(cover, input, temperature, sys), then the unmapped cloud and wifi objects")))
    files.append(("packs/shelly-notify-status/vectors/03-event-is-not-status.json",
                  vec("shelly-notify-status-wrong-method", "shelly-notify-status", "shelly-notify-status",
                      '{"src":"%s","dst":"user_1","method":"NotifyEvent","params":{"ts":%d.1,"events":[]}}' % (DEV, BASE),
                      error="no-kind", note="only NotifyStatus and NotifyFullStatus are kinds of this pack")))
    files.append(("packs/shelly-notify-status/vectors/04-ts-sub-millisecond.json",
                  vec("shelly-notify-status-ts-round", "shelly-notify-status", "shelly-notify-status",
                      '{"method":"NotifyStatus","params":{"ts":%d.5235,"sys":{"cfg_rev":13}}}' % BASE,
                      '{"method":"NotifyStatus","params":{"ts":%d.524,"sys":{"cfg_rev":13}}}' % BASE,
                      {"time_ms": str(BASE * 1000 + 524), "shelly.sys_cfg_rev": "13"},
                      note="523.5 ms rounds half away from zero to 524")))
    files.append(("packs/shelly-notify-status/vectors/05-output-as-text.json",
                  vec("shelly-notify-status-output-text", "shelly-notify-status", "shelly-notify-status",
                      '{"method":"NotifyStatus","params":{"ts":%d,"switch:1":{"id":1,"output":"true"}}}' % BASE,
                      error="transform-decode", note="output must be a JSON boolean")))
    files.append(("packs/shelly-notify-status/vectors/06-to-rpc-response.json",
                  vec("shelly-notify-status-to-rpc-response", "shelly-notify-status", "shelly-rpc-response",
                      ns_in, '{"src":"%s","dst":"user_1","result":{"switch:0":%s}}' % (DEV, j(sw_out)),
                      note="the status objects carry over; ts has no place in a response")))

    ev_in = ('{"src":"shellyplusi4-a8032ab0c0d0","dst":"user_1","method":"NotifyEvent","params":{"ts":%d.48,'
             '"events":[{"component":"input:2","id":2,"event":"double_push","ts":%d.47},'
             '{"component":"sys","event":"scheduled_restart","time_ms":1000,"ts":%d.48}]}}' % (BASE, BASE, BASE))
    ev_out = ('{"src":"shellyplusi4-a8032ab0c0d0","dst":"user_1","method":"NotifyEvent","params":{"ts":%d.48,'
              '"events":[{"component":"input:2","id":2,"event":"double_push","ts":%d.47},'
              '{"component":"sys","event":"scheduled_restart","ts":%d.48}]}}' % (BASE, BASE, BASE))
    files.append(("packs/shelly-notify-event/vectors/01-two-events.json",
                  vec("shelly-notify-event-two", "shelly-notify-event", "shelly-notify-event", ev_in, ev_out,
                      {"@kind": "notify_event", "time_ms": str(BASE * 1000 + 480), "shelly.events.#": "2",
                       "shelly.events[0].shelly.event_component": "input:2", "shelly.events[0].shelly.event_id": "2",
                       "shelly.events[0].shelly.event_name": "double_push",
                       "shelly.events[0].shelly.event_time_ms": str(BASE * 1000 + 470),
                       "shelly.events[1].shelly.event_name": "scheduled_restart"},
                      note="the second event has no id; its unmapped time_ms member is dropped, as items carry "
                           "no residue")))
    files.append(("packs/shelly-notify-event/vectors/02-status-is-not-event.json",
                  vec("shelly-notify-event-wrong-method", "shelly-notify-event", "shelly-notify-event",
                      '{"method":"NotifyStatus","params":{"ts":%d}}' % BASE, error="no-kind")))

    rs_in = ('{"id":7,"src":"%s","dst":"user_1","result":{"sys":{"mac":"0C8B95F1E2D4","uptime":90061,'
             '"available_updates":{"stable":{"version":"1.7.2"}}},"switch:3":{"id":3,"output":false,'
             '"source":"timer","timer_started_at":%d.25,"timer_duration":60}}}' % (DEV, BASE))
    rs_out = ('{"src":"%s","dst":"user_1","result":{"switch:3":{"id":3,"source":"timer","output":false,'
              '"timer_started_at":%d.25,"timer_duration":60},"sys":{"mac":"0C8B95F1E2D4","uptime":90061,'
              '"available_updates":{"stable":{"version":"1.7.2"}}}},"id":7}' % (DEV, BASE))
    files.append(("packs/shelly-rpc-response/vectors/01-get-status.json",
                  vec("shelly-rpc-response-result", "shelly-rpc-response", "shelly-rpc-response", rs_in, rs_out,
                      {"shelly.switch3_output": "0", "shelly.switch3_timer_started_at": "%d.25" % BASE,
                       "shelly.sys_available_updates_stable_version": "1.7.2"},
                      note="the request id is residue and comes last")))
    files.append(("packs/shelly-rpc-response/vectors/02-error.json",
                  vec("shelly-rpc-response-error", "shelly-rpc-response", "shelly-rpc-response",
                      '{"id":"q-8","src":"%s","dst":"user_1","error":{"code":-105,"message":"no such component"}}' % DEV,
                      '{"src":"%s","dst":"user_1","error":{"code":-105,"message":"no such component"},"id":"q-8"}' % DEV,
                      {"shelly.error_code": "-105", "shelly.error_message": "no such component"},
                      note="a text id stays text")))
    files.append(("packs/shelly-rpc-response/vectors/03-to-notify-status.json",
                  vec("shelly-rpc-response-to-notify-status", "shelly-rpc-response", "shelly-notify-status",
                      '{"id":7,"src":"%s","dst":"user_1","result":{"switch:0":{"id":0,"output":true}}}' % DEV,
                      '{"src":"%s","dst":"user_1","method":"NotifyStatus","params":{"switch:0":{"id":0,"output":true}}}' % DEV,
                      note="no kind carries over, so the first kind is chosen and its method written; no ts")))

    rq_in = '{"id":3,"jsonrpc":"2.0","src":"user_1","method":"Switch.Set","params":{"on":true,"id":1,"toggle_after":30}}'
    rq_out = '{"jsonrpc":"2.0","src":"user_1","method":"Switch.Set","params":{"id":1,"on":true,"toggle_after":30},"id":3}'
    files.append(("packs/shelly-rpc-request/vectors/01-switch-set.json",
                  vec("shelly-rpc-request-switch-set", "shelly-rpc-request", "shelly-rpc-request", rq_in, rq_out,
                      {"shelly.method": "Switch.Set", "shelly.param_id": "1", "shelly.param_on": "1"},
                      note="params.toggle_after is residue after the mapped params")))
    files.append(("packs/shelly-rpc-request/vectors/02-id-fraction.json",
                  vec("shelly-rpc-request-param-id-fraction", "shelly-rpc-request", "shelly-rpc-request",
                      '{"id":4,"src":"user_1","method":"Switch.Set","params":{"id":0.5,"on":false}}',
                      error="transform-decode", note="a component id is an integer")))

    gin = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[8.68,50.11]},'
           '"properties":{"time_ms":%d}}' % (BASE * 1000 + 250))
    files.append(("packs/geojson/vectors/to-shelly-notify-status-time.json",
                  vec("geojson-to-shelly-notify-status", "geojson", "shelly-notify-status", gin,
                      '{"method":"NotifyStatus","params":{"ts":%d.25}}' % BASE,
                      note="only time_ms is shared; the position has no place in a Shelly frame")))
    for rel, v in files:
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    return {"shelly": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("shelly-vectors", __doc__.split("\n")[0], build))
