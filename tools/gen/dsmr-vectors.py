#!/usr/bin/env python3
"""Hand-derived vectors of the dsmr-p1-line pack (lines of a DSMR 5.0.2 P1 telegram).

The lines are written for these vectors, not copied from the standard's example telegram, in the
forms the P1 Companion Standard states (section 6.4 value formats, section 6.12 objects): an OBIS
reduced code, '(', the value in its fixed format, '*' and the unit where there is one, ')'. The
expected text and model follow the `text` wire (engine-spec 0.10): fields split at '(', columns of
field 1 read through the column's transform. No engine is imported.

    python3 -I tools/gen/dsmr-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "DSMR 5.0.2 P1 Companion Standard sections 6.4 and 6.12; lines written by tools/gen/dsmr-vectors.py"


def rt(name, line, model, note=""):
    return {"name": "dsmr-p1-line-" + name, "from": "dsmr-p1-line", "to": "dsmr-p1-line", "input": line, "expect": line,
            "model": model, "source": "constructed", "reference": REF + ("; " + note if note else "")}


def err(name, line, kind, note):
    return {"name": "dsmr-p1-line-" + name, "from": "dsmr-p1-line", "to": "dsmr-p1-line", "input": line,
            "expect_error": kind, "source": "constructed", "reference": REF + "; " + note}


def build(out):
    v = [
        ("01-energy-tariff1.json", rt("energy-tariff1", "1-0:1.8.1(004567.891*kWh)",
            {"@kind": "energy_delivered_tariff1_kwh", "dsmr.energy_delivered_tariff1_kwh": "4567.891"}, "F9(3,3) kWh")),
        ("02-power-delivered.json", rt("power-delivered", "1-0:1.7.0(02.345*kW)",
            {"@kind": "power_delivered_kw", "dsmr.power_delivered_kw": "2.345"}, "F5(3,3) kW")),
        ("03-voltage-l1.json", rt("voltage-l1", "1-0:32.7.0(229.4*V)",
            {"@kind": "voltage_l1_v", "dsmr.voltage_l1_v": "229.4"}, "F4(1,1) V")),
        ("04-current-l2.json", rt("current-l2", "1-0:51.7.0(007*A)",
            {"@kind": "current_l2_a", "dsmr.current_l2_a": "7"}, "F3(0,0) A")),
        ("05-power-failures.json", rt("power-failures", "0-0:96.7.21(00012)",
            {"@kind": "power_failures", "dsmr.power_failures": "12"}, "F5(0,0)")),
        ("06-timestamp.json", rt("timestamp", "0-0:1.0.0(261121093015W)",
            {"@kind": "timestamp", "dsmr.timestamp": "261121093015W"}, "TST, kept as text: local time with a DST letter")),
        ("07-tariff.json", rt("tariff", "0-0:96.14.0(0001)", {"@kind": "tariff_indicator", "dsmr.tariff_indicator": "0001"})),
        ("08-header.json", rt("header", "/XYZ5\\2MT999-0001", {"@kind": "header", "dsmr.header": "/XYZ5\\2MT999-0001"},
                              "the header line has no '(': one field")),
        ("09-end.json", rt("end", "!1A2B", {"@kind": "end", "dsmr.end": "!1A2B"}, "the CRC is not checked")),
        ("10-mbus-value.json", rt("mbus-value", "0-2:24.2.1(261121090000W)(00456.789*m3)",
            {"@kind": "mbus2_value", "dsmr.mbus_channel": "2", "dsmr.mbus_capture_time": "261121090000W",
             "dsmr.mbus_value": "00456.789*m3)"}, "M-Bus channel 2, the value kept as text")),
        ("11-power-failure-log.json", rt("power-failure-log", "1-0:99.97.0(2)(0-0:96.7.19)(261120101500W)(0000000120*s)(261119080000W)(0000000045*s)",
            {"@kind": "power_failure_log", "dsmr.power_failure_log_count": "2)", "dsmr.power_failure_log.#": "2",
             "dsmr.power_failure_log[0].dsmr.power_failure_end_time": "261120101500W)",
             "dsmr.power_failure_log[1].dsmr.power_failure_duration": "0000000045*s)"}, "two log entries as a group of two fields each")),
        ("12-equipment-id.json", rt("equipment-id", "0-0:96.1.1(4142434445)",
            {"@kind": "equipment_id", "dsmr.equipment_id": "4142434445)"}, "variable length: the field with its ')'")),
        ("13-short-value.json", err("short-value", "1-0:1.8.1(4567.891*kWh)", "transform-decode",
            "the value is not in its F9(3,3) width: the ten-character column holds '4567.891*k', not a number")),
        ("14-unknown-obis.json", err("unknown-obis", "1-0:99.1.0(00001)", "no-kind", "an OBIS code the pack does not list")),
    ]
    for n, vec in v:
        out.write("packs/dsmr-p1-line/vectors/" + n, json.dumps(vec, indent=2) + "\n")
    return {"dsmr-p1-line": len(v)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("dsmr-vectors", __doc__.split("\n")[0], build))
