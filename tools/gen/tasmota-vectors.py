#!/usr/bin/env python3
"""Hand-derived vectors of the tasmota-state, tasmota-sensor and tasmota-result packs.

The messages have the shape Tasmota v16.0.0 publishes: the telemetry STATE object (MqttShowState
in tasmota_support/support_tasmota.ino), the SENSOR object with the energy driver's ENERGY member
and the DS18x20, BMx280 and DHT members named by sensor type, and a RESULT object answering a
Power command. Every value here is my own; none is taken from the project's documentation.

Expected text follows the canonical rules of the json wire (engine-spec 0.5): mapped members in
field-line order, a nested object where its first line is, residue members after the mapped ones
in input order, no whitespace; floats as the shortest round-trip decimal (ruling 3 of 0.1.1), so
a float member written 45.0 comes back as 45. A JSON value of the wrong type for its transform,
an array included, is transform-decode (ruling 9 of 0.1.1). No engine is imported.

    python3 -I tools/gen/tasmota-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "Tasmota v16.0.0 STATE, SENSOR and RESULT payload shapes; text by tools/gen/tasmota-vectors.py"
T = "2026-11-21T10:15:30"


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
    wifi = {"AP": 1, "SSId": "garden-net", "BSSId": "3C:A6:2F:10:20:30", "Channel": 6, "Mode": "11n",
            "RSSI": 72, "Signal": -64, "LinkCount": 2, "Downtime": "0T00:00:07"}
    state_in = {"Time": T, "Uptime": "3T04:05:06", "UptimeSec": 273906, "Heap": 25, "SleepMode": "Dynamic",
                "Sleep": 50, "LoadAvg": 19, "MqttCount": 3, "Berry": {"HeapUsed": 4, "Objects": 44},
                "POWER": "ON", "Wifi": wifi}
    state_out = {"Time": T, "Uptime": "3T04:05:06", "UptimeSec": 273906, "Heap": 25, "SleepMode": "Dynamic",
                 "Sleep": 50, "LoadAvg": 19, "MqttCount": 3, "POWER": "ON", "Wifi": wifi,
                 "Berry": {"HeapUsed": 4, "Objects": 44}}
    files.append(("packs/tasmota-state/vectors/01-state-canonical.json",
                  vec("tasmota-state-single-relay", "tasmota-state", "tasmota-state", json.dumps(state_in, indent=2),
                      j(state_out), {"tasmota.time_local": T, "tasmota.uptime_s": "273906", "tasmota.power": "ON",
                                     "tasmota.wifi_ssid": "garden-net", "tasmota.wifi_signal": "-64",
                                     "tasmota.wifi_downtime": "0T00:00:07"},
                      note="the unmapped Berry object is residue and comes after the mapped members")))
    multi = {"Time": T, "Uptime": "0T00:12:00", "UptimeSec": 720, "POWER2": "OFF", "POWER1": "ON", "Dimmer": 40}
    files.append(("packs/tasmota-state/vectors/02-two-relays.json",
                  vec("tasmota-state-two-relays", "tasmota-state", "tasmota-state", j(multi),
                      j({"Time": T, "Uptime": "0T00:12:00", "UptimeSec": 720, "POWER1": "ON", "POWER2": "OFF",
                         "Dimmer": 40}),
                      {"tasmota.power1": "ON", "tasmota.power2": "OFF", "@absent": ["tasmota.power"]},
                      note="POWER1 and POWER2 in line order; Dimmer residue")))
    files.append(("packs/tasmota-state/vectors/03-uptime-as-text.json",
                  vec("tasmota-state-uptime-text", "tasmota-state", "tasmota-state",
                      j({"Time": T, "UptimeSec": "273906"}), error="transform-decode",
                      note="UptimeSec must be a number")))

    energy = {"TotalStartTime": "2026-01-02T03:04:05", "Total": 12.345, "Yesterday": 0.512, "Today": 0.208,
              "Period": 3, "Power": 45.0, "ApparentPower": 52, "ReactivePower": 26, "Factor": 0.87,
              "Voltage": 231, "Current": 0.226}
    energy_out = dict(energy, Power=45)
    files.append(("packs/tasmota-sensor/vectors/01-energy.json",
                  vec("tasmota-sensor-energy", "tasmota-sensor", "tasmota-sensor", j({"Time": T, "ENERGY": energy}),
                      j({"Time": T, "ENERGY": energy_out}),
                      {"tasmota.energy_total": "12.345", "tasmota.energy_power": "45", "tasmota.energy_factor": "0.87",
                       "tasmota.energy_voltage": "231", "tasmota.energy_current": "0.226"},
                      note="45.0 is written 45")))
    ds = {"Time": T, "DS18B20-2": {"Id": "01193A4B5C6D", "Temperature": -5.5},
          "DS18B20-1": {"Id": "0316A27984FF", "Temperature": 18.1}, "TempUnit": "C"}
    files.append(("packs/tasmota-sensor/vectors/02-two-ds18b20.json",
                  vec("tasmota-sensor-two-ds18b20", "tasmota-sensor", "tasmota-sensor", j(ds),
                      j({"Time": T, "DS18B20-1": {"Id": "0316A27984FF", "Temperature": 18.1},
                         "DS18B20-2": {"Id": "01193A4B5C6D", "Temperature": -5.5}, "TempUnit": "C"}),
                      {"tasmota.ds18b20_1_temperature": "18.1", "tasmota.ds18b20_2_temperature": "-5.5",
                       "tasmota.ds18b20_2_id": "01193A4B5C6D", "tasmota.temp_unit": "C"},
                      note="the numbered sensors in line order; a negative temperature")))
    env = {"Time": T, "BME280": {"Temperature": 21.4, "Humidity": 48.2, "DewPoint": 10.1, "Pressure": 1013.2},
           "AM2301": {"Temperature": 19.9, "Humidity": 55, "DewPoint": 10.7},
           "SHT3X": {"Temperature": 20.6, "Humidity": 51.3}, "PressureUnit": "hPa", "TempUnit": "C"}
    files.append(("packs/tasmota-sensor/vectors/03-bme280-am2301.json",
                  vec("tasmota-sensor-bme280-am2301", "tasmota-sensor", "tasmota-sensor", j(env),
                      j({"Time": T, "BME280": env["BME280"], "AM2301": env["AM2301"], "PressureUnit": "hPa",
                         "TempUnit": "C", "SHT3X": env["SHT3X"]}),
                      {"tasmota.bme280_pressure": "1013.2", "tasmota.am2301_humidity": "55",
                       "tasmota.pressure_unit": "hPa"},
                      note="PressureUnit before TempUnit, as MqttAppendSensorUnits writes them (line order); an unmapped sensor type is residue")))
    files.append(("packs/tasmota-sensor/vectors/04-energy-phases.json",
                  vec("tasmota-sensor-energy-phases", "tasmota-sensor", "tasmota-sensor",
                      j({"Time": T, "ENERGY": {"Total": 1.5, "Voltage": [230, 231, 229]}}), error="transform-decode",
                      note="a multi-phase meter writes an array where the float transform needs a number")))

    files.append(("packs/tasmota-result/vectors/01-power.json",
                  vec("tasmota-result-power", "tasmota-result", "tasmota-result", j({"POWER": "OFF"}),
                      j({"POWER": "OFF"}), {"tasmota.power": "OFF"})))
    files.append(("packs/tasmota-result/vectors/02-other-command.json",
                  vec("tasmota-result-other-command", "tasmota-result", "tasmota-result",
                      j({"Dimmer": 40, "Fade": "OFF"}), j({"Dimmer": 40, "Fade": "OFF"}),
                      {"@absent": ["tasmota.power"]}, note="a result with no mapped member is all residue")))
    files.append(("packs/tasmota-result/vectors/03-to-state.json",
                  vec("tasmota-result-to-state", "tasmota-result", "tasmota-state",
                      j({"POWER1": "ON", "Dimmer": 40}), j({"POWER1": "ON"}),
                      note="the residue of RESULT is not written to STATE")))
    for rel, v in files:
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    return {"tasmota": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("tasmota-vectors", __doc__.split("\n")[0], build))
