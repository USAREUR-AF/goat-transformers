#!/usr/bin/env python3
"""Hand-derived vectors of the omg-bt and omg-rf packs.

The payloads have the shape OpenMQTTGateway v1.9.1 publishes: a BTtoMQTT object for one BLE
advertisement (the raw members gatewayBT.cpp writes, and the members a decoder adds for a
recognised device), and an RFtoMQTT object for one code the RCSwitch receiver decoded
(gatewayRF.cpp). Addresses, codes and readings are my own. The RF example is self-consistent:
the 24-bit code 1381717 is 0x151555, its binary text is the 24 bits, and its tri-state text reads
the bits in pairs (00 is 0, 01 is F, 11 is 1).

Expected text follows the canonical rules of the json wire (engine-spec 0.5): mapped members in
field-line order, residue after them in input order, `null` absent, floats as the shortest
round-trip decimal. No engine is imported.

    python3 -I tools/gen/omg-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "OpenMQTTGateway v1.9.1 BTtoMQTT and RFtoMQTT payload shapes; text by tools/gen/omg-vectors.py"


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


def tristate(bits):
    return "".join({"00": "0", "01": "F", "11": "1"}[bits[i:i + 2]] for i in range(0, len(bits), 2))


def build(out):
    files = []
    code = 1381717
    binary = format(code, "024b")
    assert binary == "000101010001010101010101"
    rf_in = {"value": code, "protocol": 1, "length": 24, "delay": 317, "tre_state": tristate(binary),
             "binary": binary, "raw": "9868,312,940,312,940", "frequency": 433.92, "origin": "home/omg1/433toMQTT"}
    rf_canon = j(rf_in)
    files.append(("packs/omg-rf/vectors/01-code-canonical.json",
                  vec("omg-rf-code", "omg-rf", "omg-rf", rf_canon, rf_canon,
                      {"omg.rf_value": str(code), "omg.rf_protocol": "1", "omg.rf_length": "24", "omg.rf_delay": "317",
                       "omg.rf_tre_state": "0FFF0FFFFFFF", "omg.rf_binary": binary, "omg.rf_frequency": "433.92"},
                      note="already canonical; origin is residue and stays last")))
    files.append(("packs/omg-rf/vectors/02-reordered.json",
                  vec("omg-rf-reordered", "omg-rf", "omg-rf",
                      j({"protocol": 2, "value": 5393, "delay": 650, "length": 24}),
                      j({"value": 5393, "protocol": 2, "length": 24, "delay": 650}),
                      note="members come back in line order")))
    files.append(("packs/omg-rf/vectors/03-value-fraction.json",
                  vec("omg-rf-value-fraction", "omg-rf", "omg-rf", j({"value": 1381717.5, "protocol": 1}),
                      error="transform-decode", note="a code value is an integer")))

    bt_in = {"id": "A4:C1:38:5E:21:9B", "mac_type": 0, "adv_type": 0, "name": "ATC_5E219B", "rssi": -71,
             "brand": "Xiaomi", "model": "LYWSD03MMC", "model_id": "LYWSD03MMC_ATC", "type": "THB", "cidc": False,
             "tempc": 21.4, "tempf": 70.52, "hum": 47, "batt": 89, "volt": 2.954}
    bt_out = {"id": "A4:C1:38:5E:21:9B", "mac_type": 0, "adv_type": 0, "name": "ATC_5E219B", "rssi": -71,
              "brand": "Xiaomi", "model": "LYWSD03MMC", "model_id": "LYWSD03MMC_ATC", "type": "THB",
              "tempc": 21.4, "tempf": 70.52, "hum": 47, "batt": 89, "volt": 2.954, "cidc": False}
    files.append(("packs/omg-bt/vectors/01-decoded-sensor.json",
                  vec("omg-bt-decoded", "omg-bt", "omg-bt", j(bt_in), j(bt_out),
                      {"omg.bt_id": "A4:C1:38:5E:21:9B", "omg.bt_rssi": "-71", "omg.bt_model_id": "LYWSD03MMC_ATC",
                       "omg.bt_tempc": "21.4", "omg.bt_hum": "47", "omg.bt_volt": "2.954"},
                      note="cidc is residue and comes after the mapped members")))
    raw_in = {"id": "C8:47:8C:01:02:03", "rssi": -88, "servicedatauuid": "0x181a",
              "servicedata": "0302018c47c8e100a00f4c0b", "manufacturerdata": "4c0002150102", "name": None,
              "txpower": -12}
    raw_out = {"id": "C8:47:8C:01:02:03", "manufacturerdata": "4c0002150102", "servicedata": "0302018c47c8e100a00f4c0b",
               "servicedatauuid": "0x181a", "rssi": -88, "txpower": -12}
    files.append(("packs/omg-bt/vectors/02-raw-advertisement.json",
                  vec("omg-bt-raw", "omg-bt", "omg-bt", j(raw_in), j(raw_out),
                      {"omg.bt_txpower": "-12", "@absent": ["omg.bt_name", "omg.bt_tempc"]},
                      note="a null name is absent; members come back in line order")))
    files.append(("packs/omg-bt/vectors/03-tempc-as-text.json",
                  vec("omg-bt-tempc-text", "omg-bt", "omg-bt", j({"id": "A4:C1:38:5E:21:9B", "tempc": "21.4"}),
                      error="transform-decode", note="a decoded reading must be a number")))
    for rel, v in files:
        out.write(rel, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    return {"omg": len(files)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("omg-vectors", __doc__.split("\n")[0], build))
