#!/usr/bin/env python3
"""Hand-derived vectors of the davis-wll-http and davis-wll-udp packs.

The JSON documents follow the shapes of the WeatherLink Live local API document (API.md at commit
4383b984 of github.com/weatherlink/weatherlink-live-local-api): the current conditions response
with records by data_structure_type, the real-time broadcast request's response, an error
response, and a UDP broadcast packet. The values are written for these vectors. Expected text
follows the json wire's canonical rules (engine-spec 0.5: members in field-line order, `null`
not written, numbers as the shortest round-trip decimal) and geojson's (0.1.1 rulings 3 and 4).
No engine is imported.

    python3 -I tools/gen/davis-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "WeatherLink Live local API (API.md, 4383b984); documents by tools/gen/davis-vectors.py"


def j(o):
    return json.dumps(o, separators=(",", ":"))


def vec(name, frm, to, inp, exp, model=None, note=""):
    v = {"name": name, "from": frm, "to": to, "input": inp, "expect": exp}
    if model:
        v["model"] = model
    v["source"] = "constructed"
    v["reference"] = REF + ("; " + note if note else "")
    return v


ISS = {"lsid": 51001, "data_structure_type": 1, "txid": 1, "temp": 61.3, "hum": 72.5, "dew_point": 52.1,
       "wind_speed_last": 3, "wind_dir_last": 245, "rain_size": 2, "rain_rate_last": 0, "solar_rad": 412,
       "uv_index": 2.5, "rx_state": 0, "trans_battery_flag": 0, "rainfall_daily": 14}
BAR = {"lsid": 51002, "data_structure_type": 3, "bar_sea_level": 30.112, "bar_trend": -0.015, "bar_absolute": 29.874}
TS = 1795252800


def build(out):
    files = []
    inp = {"data": {"did": "001D0AF10203", "ts": TS, "conditions": [dict(ISS, wet_bulb=None), BAR]}, "error": None}
    exp = {"data": {"did": "001D0AF10203", "ts": TS, "conditions": [ISS, BAR]}}
    model = {"uid": "001D0AF10203", "time_ms": str(TS * 1000), "davis.conditions.#": "2",
             "davis.conditions[0].davis.cond_temp": "61.3", "davis.conditions[0].davis.cond_rain_size": "2",
             "davis.conditions[1].davis.cond_bar_sea_level": "30.112", "davis.conditions[1].davis.cond_bar_trend": "-0.015"}
    files.append(("davis-wll-http", "01-current-conditions.json",
                  vec("davis-wll-http-current-conditions", "davis-wll-http", "davis-wll-http", j(inp), j(exp), model,
                      "an ISS and a barometer record; null members and the null error are not written")))
    files.append(("davis-wll-http", "02-current-conditions-to-geojson.json",
                  vec("davis-wll-http-current-conditions-to-geojson", "davis-wll-http", "geojson", j(inp),
                      '{"type":"Feature","geometry":null,"properties":{"time_ms":%d},"id":"001D0AF10203"}' % (TS * 1000),
                      note="no position in the message; the device id is the feature id")))
    rt = {"data": {"broadcast_port": 22222, "duration": 600}, "error": None}
    files.append(("davis-wll-http", "03-real-time-response.json",
                  vec("davis-wll-http-real-time-response", "davis-wll-http", "davis-wll-http", j(rt),
                      j({"data": {"broadcast_port": 22222, "duration": 600}}),
                      {"davis.broadcast_port": "22222", "davis.duration_s": "600"})))
    er = {"data": None, "error": {"code": 400, "message": "Bad request"}}
    files.append(("davis-wll-http", "04-error.json",
                  vec("davis-wll-http-error", "davis-wll-http", "davis-wll-http", j(er), j({"error": {"code": 400, "message": "Bad request"}}),
                      {"davis.error_code": "400", "davis.error_message": "Bad request"})))
    u1 = {"lsid": 51001, "data_structure_type": 1, "txid": 1, "wind_speed_last": 4.5, "wind_dir_last": 250, "rain_size": 2,
          "rain_rate_last": 0, "rain_15_min": 0, "rain_60_min": 1, "rain_24_hr": 3, "rain_storm": 3,
          "rain_storm_start_at": 1795240000, "rainfall_daily": 14, "rainfall_monthly": 40, "rainfall_year": 210}
    udp = {"did": "001D0AF10203", "ts": TS + 3, "conditions": [dict(u1, wind_speed_hi_last_10_min=None)]}
    files.append(("davis-wll-udp", "01-broadcast.json",
                  vec("davis-wll-udp-broadcast", "davis-wll-udp", "davis-wll-udp", j(udp),
                      j({"did": "001D0AF10203", "ts": TS + 3, "conditions": [u1]}),
                      {"uid": "001D0AF10203", "time_ms": str((TS + 3) * 1000), "davis.conditions.#": "1",
                       "davis.conditions[0].davis.cond_rain_storm_start_at": "1795240000",
                       "davis.conditions[0].davis.cond_wind_speed_last": "4.5"})))
    for pack, n, v in files:
        out.write("packs/%s/vectors/%s" % (pack, n), json.dumps(v, indent=2) + "\n")
    return {"davis": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("davis-vectors", __doc__.split("\n")[0], build))
