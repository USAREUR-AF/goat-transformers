#!/usr/bin/env python3
"""Hand-derived vectors of the sml-message pack (Smart Message Language 1.04).

Messages are built with the TL-field rules of BSI TR-03109-1 Annex IV part b, section 6: one TL
byte (bit 7 0, the type in bits 6-4, the length or element count in bits 3-0), octet strings of
at most 14 bytes (the length counts the TL byte), unsigned and signed integers big-endian in as
many bytes as the TL length says, lists by their element count, an absent optional element as the
byte 0x01, and the end of a message as 0x00. The messageBody tag is an Unsigned32. Timestamps are
seconds since 1970-01-01 UTC, so `time_ms` is the seconds x 1000. No engine is imported.

    python3 -I tools/gen/sml-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "BSI TR-03109-1 Annex IV part b (SML 1.04) sections 5 and 6; bytes by tools/gen/sml-vectors.py"
ABSENT = b"\x01"


def oc(b):
    assert len(b) <= 14
    return bytes([len(b) + 1]) + b


def un(v, n):
    return bytes([0x60 | (n + 1)]) + v.to_bytes(n, "big")


def si(v, n):
    return bytes([0x50 | (n + 1)]) + (v & ((1 << (8 * n)) - 1)).to_bytes(n, "big")


def lst(n):
    return bytes([0x70 | n])


def message(txid, tag, body, crc=0x1234):
    return lst(6) + oc(txid) + un(0, 1) + un(0, 1) + lst(2) + un(tag, 4) + body + un(crc, 2) + b"\x00"


def octets(key, b):
    out = {key + ".#": str(len(b))}
    for i, x in enumerate(b):
        out["%s[%d].%s_byte" % (key, i, key)] = str(x)
    return out


def vec(name, data, model, note):
    h = data.hex()
    return {"name": "sml-message-" + name, "from": "sml-message", "to": "sml-message", "input": h, "expect": h,
            "model": model, "source": "constructed", "reference": REF + "; " + note}


def build(out):
    v = []
    secs = 1795253415
    body = lst(6) + ABSENT + ABSENT + oc(b"\x0a\x01") + oc(b"\x0a\x01\x48\x41\x47\x00\x01\x02\x03\x04") + \
        lst(2) + un(2, 1) + un(secs, 4) + ABSENT
    m = message(b"\x00\x01", 0x0101, body)
    model = {"sml.message_count": "6", "sml.body_tag": "257", "sml.group_no": "0", "sml.crc16": "4660", "time_ms": str(secs * 1000),
             "sml.open_res_codepage.#": "0", "sml.open_res_ref_time_choice": "2"}
    model.update(octets("sml.transaction_id", b"\x00\x01"))
    model.update(octets("sml.open_res_server_id", b"\x0a\x01\x48\x41\x47\x00\x01\x02\x03\x04"))
    v.append(("01-open-response.json", vec("open-response", m, model,
              "PublicOpen.Res with refTime as a timestamp; absent codepage and clientId are empty octet strings")))
    entry1 = lst(7) + oc(bytes([1, 0, 1, 8, 0, 255])) + un(0x00010104, 4) + ABSENT + un(30, 1) + si(-1, 1) + si(123456789, 4) + ABSENT
    entry2 = lst(7) + oc(bytes([1, 0, 16, 7, 0, 255])) + ABSENT + ABSENT + un(27, 1) + si(0, 1) + si(-1500, 2) + ABSENT
    body = lst(7) + ABSENT + oc(b"\x0a\x01\x48\x41\x47\x00\x01\x02\x03\x04") + oc(bytes([1, 0, 0, 0, 0, 255])) + ABSENT + \
        lst(2) + entry1 + entry2 + ABSENT + ABSENT
    m = message(b"\x00\x02", 0x0701, body, crc=0xBEEF)
    E = "sml.entries[%d]."
    model = {"sml.body_tag": "1793", "sml.entries.#": "2", "sml.crc16": str(0xBEEF),
             E % 0 + "sml.entry_status": str(0x00010104), E % 0 + "sml.entry_unit": "30", E % 0 + "sml.entry_scaler": "-1",
             E % 0 + "sml.entry_value_int": "123456789",
             E % 1 + "sml.entry_unit": "27", E % 1 + "sml.entry_value_int": "-1500"}
    model.update({E % 0 + k: x for k, x in octets("sml.entry_obj_name", bytes([1, 0, 1, 8, 0, 255])).items()})
    v.append(("02-get-list-response.json", vec("get-list-response", m, model,
              "GetList.Res with two entries: energy 1.8.0 in Wh with scaler -1, power 16.7.0 in W as a two-byte integer")))
    m = message(b"\x00\x03", 0x0201, lst(1) + ABSENT)
    v.append(("03-close-response.json", vec("close-response", m, {"sml.body_tag": "513", "sml.close_res_global_signature.#": "0"},
              "PublicClose.Res without a signature")))
    body = lst(7) + ABSENT + oc(b"CLIENT01") + oc(b"\x00\x09") + oc(b"\x0a\x01\x48\x41\x47\x00\x01\x02\x03\x04") + ABSENT + ABSENT + un(1, 1)
    m = message(b"\x00\x04", 0x0100, body)
    model = {"sml.body_tag": "256", "sml.open_req_sml_version": "1"}
    model.update(octets("sml.open_req_client_id", b"CLIENT01"))
    v.append(("04-open-request.json", vec("open-request", m, model, "PublicOpen.Req with smlVersion 1")))
    m = message(b"\x00\x05", 0x0501, lst(1) + ABSENT)
    v.append(("05-other-body.json", {"name": "sml-message-other-body", "from": "sml-message", "to": "sml-message",
              "input": m.hex(), "expect_error": "no-kind", "source": "constructed",
              "reference": REF + "; a GetProcParameter.Res body (tag 0x0501) has no case in the pack"}))
    for n, x in v:
        out.write("packs/sml-message/vectors/" + n, json.dumps(x, indent=2) + "\n")
    return {"sml-message": len(v)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("sml-vectors", __doc__.split("\n")[0], build))
