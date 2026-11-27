#!/usr/bin/env python3
"""Hand-derived vectors of the knx-* packs.

Every frame is written out byte by byte from the layout calimero-core reads (cEMI L_Data:
message code, additional-information length and bytes, control fields 1 and 2, source and
destination addresses, the NPDU length (the TPDU's length minus one) and the TPDU; KNXnet/IP:
header length 6, version 0x10, service type, total length, connection header). The data values:

  DPT 9   21.5 = 0.01 x M x 2^E with E = 1, M = 1075 (0x433): sign 0, exponent 0001, mantissa
          10000110011 -> 0x0C33
  DPT 14  1013.25 as an IEEE 754 single is 0x447D5000
  DPT 5   0x80 = 128
  DPT 1   1 in the low bit of the six-bit data: second TPDU byte 0x81

The frame 29 00 BC E0 11 05 0A 03 03 00 80 0C 33 is an L_Data.ind from 1.1.5 to group 1/2/3
(1 << 11 | 2 << 8 | 3 = 0x0A03), low priority, hop count 6, GroupValueWrite (APCI 0b0010).

    python3 -I tools/gen/knx-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "calimero-core 68c99bff (cEMI and KNXnet/IP layouts); bytes worked by hand in tools/gen/knx-vectors.py"
HEAD = "29" "00" "bc" "e0" "1105" "0a03"           # L_Data.ind, no add info, ctrl1, ctrl2, 1.1.5 -> 1/2/3
HDR_MODEL = {"knx.message_code": "41", "knx.additional_info.#": "0", "knx.frame_format": "1", "knx.ctrl1_reserved": "0",
             "knx.repeat": "1", "knx.system_broadcast": "1", "knx.priority": "3", "knx.ack_request": "0",
             "knx.confirm": "0", "knx.destination_is_group": "1", "knx.hop_count": "6",
             "knx.extended_frame_format": "0", "knx.source_area": "1", "knx.source_line": "1",
             "knx.source_device": "5", "knx.destination": "2563", "knx.tpci": "0"}
DPT9 = HEAD + "03" + "0080" + "0c33"


def v(name, fmt, inp, model=None, note="", error=None, kind=None):
    out = {"name": name, "from": fmt, "to": fmt, "input": inp}
    if error:
        out["expect_error"] = error
    else:
        out["expect"] = inp
        m = {"@kind": kind} if kind else {}
        m.update(model or {})
        out["model"] = m
    out["source"] = "constructed"
    out["reference"] = REF + ("; " + note if note else "")
    return out


def build(out):
    f = []
    gen = dict(HDR_MODEL, **{"knx.apci": "2", "knx.apci_data": "0", "knx.data.#": "2",
                             "knx.data[0].knx.data_byte": "12", "knx.data[1].knx.data_byte": "51"})
    f.append(("knx-cemi", "01-group-write-bytes.json", v("knx-cemi-group-write", "knx-cemi", DPT9, gen,
                                                        "GroupValueWrite with two data bytes")))
    f.append(("knx-cemi", "02-group-read.json", v("knx-cemi-group-read", "knx-cemi", "11" + HEAD[2:] + "01" + "0000",
                                                  dict(HDR_MODEL, **{"knx.message_code": "17", "knx.apci": "0",
                                                                     "knx.apci_data": "0", "knx.data.#": "0"}),
                                                  "L_Data.req GroupValueRead: a TPDU of two bytes")))
    f.append(("knx-cemi", "03-additional-info.json",
              v("knx-cemi-additional-info", "knx-cemi", "29" "02" "aabb" + HEAD[4:] + "03" + "0080" + "0c33",
                dict(gen, **{"knx.additional_info.#": "2", "knx.additional_info[0].knx.additional_info_byte": "170",
                             "knx.additional_info[1].knx.additional_info_byte": "187"}),
                "two bytes of additional information, carried as bytes")))
    f.append(("knx-cemi", "04-short-tpdu.json", v("knx-cemi-npdu-too-long", "knx-cemi", HEAD + "03" + "0080" + "0c",
                                                  error="malformed-wire", note="the NPDU length says four TPDU bytes; three follow")))
    f.append(("knx-cemi-dpt9", "01-temperature.json",
              v("knx-cemi-dpt9-21-5", "knx-cemi-dpt9", DPT9,
                dict(HDR_MODEL, **{"knx.apci": "2", "knx.apci_data": "0", "knx.dpt9_sign": "0",
                                   "knx.dpt9_exponent": "1", "knx.dpt9_mantissa": "1075"}), "21.5 = 0.01 x 1075 x 2^1")))
    f.append(("knx-cemi-dpt1", "01-switch-on.json",
              v("knx-cemi-dpt1-on", "knx-cemi-dpt1", HEAD + "01" + "0081",
                dict(HDR_MODEL, **{"knx.apci": "2", "knx.apci_data_high": "0", "knx.dpt1_value": "1"}),
                "the value in the low bit of the second TPDU byte")))
    f.append(("knx-cemi-dpt5", "01-value-128.json",
              v("knx-cemi-dpt5-128", "knx-cemi-dpt5", HEAD + "02" + "0080" + "80",
                dict(HDR_MODEL, **{"knx.apci": "2", "knx.apci_data": "0", "knx.dpt5_value": "128"}), "raw 128")))
    f.append(("knx-cemi-dpt14", "01-pressure.json",
              v("knx-cemi-dpt14-1013-25", "knx-cemi-dpt14", HEAD + "05" + "0080" + "447d5000",
                dict(HDR_MODEL, **{"knx.apci": "2", "knx.apci_data": "0", "knx.dpt14_value": "1013.25"}),
                "1013.25 as a big-endian single")))
    # A GroupValueRead (APCI 0) carries no value: the TPDU is the two octets 00 00, and the value
    # lines sit under `case 1,2` of `switch knx.apci`, so they are absent and nothing is added on encode.
    for pk, key in (("knx-cemi-dpt1", "knx.dpt1_value"), ("knx-cemi-dpt5", "knx.dpt5_value"),
                    ("knx-cemi-dpt9", "knx.dpt9_mantissa"), ("knx-cemi-dpt14", "knx.dpt14_value")):
        f.append((pk, "02-group-value-read.json",
                  v(pk + "-read", pk, HEAD + "01" + "0000",
                    dict(HDR_MODEL, **{"knx.apci": "0", "knx.apci_data": "0", "@absent": [key]}),
                    "a GroupValueRead: APCI 0, a two-octet TPDU and no value (calimero passes no ASDU for a read)")))
    cemi_len = len(DPT9) // 2
    f.append(("knx-ip", "01-routing-indication.json",
              v("knx-ip-routing-indication", "knx-ip", "0610" "0530" + "%04x" % (6 + cemi_len) + DPT9,
                dict(gen, **{"knx.header_length": "6", "knx.protocol_version": "16"}),
                "header 6 bytes + the cEMI frame of knx-cemi 01 = %d bytes" % (6 + cemi_len), kind="routing_indication")))
    f.append(("knx-ip", "02-tunneling-request.json",
              v("knx-ip-tunneling-request", "knx-ip", "0610" "0420" + "%04x" % (10 + cemi_len) + "04072a00" + DPT9,
                dict(gen, **{"knx.header_length": "6", "knx.protocol_version": "16", "knx.connection_header_length": "4",
                             "knx.channel_id": "7", "knx.sequence_counter": "42", "knx.connection_reserved": "0"}),
                "channel 7, sequence 42", kind="tunneling_request")))
    f.append(("knx-ip", "03-tunneling-ack.json",
              v("knx-ip-tunneling-ack", "knx-ip", "0610" "0421" "000a" "04072a00",
                {"knx.header_length": "6", "knx.protocol_version": "16", "knx.connection_header_length": "4",
                 "knx.channel_id": "7", "knx.sequence_counter": "42", "knx.status": "0"}, "status 0", kind="tunneling_ack")))
    for pack, name, vec in f:
        out.write("packs/%s/vectors/%s" % (pack, name), json.dumps(vec, indent=2) + "\n")
    return {"knx": len(f)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("knx-vectors", __doc__.split("\n")[0], build))
