#!/usr/bin/env python3
"""smarthome-vectors: write the vectors of zwave-serial-frame and enocean-esp3.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of:
- zwave-js Message.ts: SOF 0x01, a length octet equal to the payload length plus 3, the message type
  (0 request, 1 response), the function, the payload, and a checksum that starts at 0xFF and XORs every
  octet after SOF up to the checksum; the single-octet headers ACK 0x06, NAK 0x15, CAN 0x18;
- kipe/enocean packet.py: sync 0x55, data length (2 octets, high first), optional length, packet type,
  a CRC8 over those four octets, the data, the optional data, a CRC8 over both; the CRC8 table in
  crc8.py (polynomial 0x07).

Inputs: frames built here field by field from values chosen here; no frame is taken from a document or a
capture. The checksums and CRCs are computed here. `expect` of a round trip is the input. `model` holds
values that were packed.

Usage: python3 -I tools/gen/smarthome-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/smarthome-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_Z = "zwave-js packages/serial/src/message/Message.ts"
R_E = "kipe/enocean protocol/packet.py and crc8.py"


def vec(pack, name, inp, model=None, error=None, ref="", note=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def zwave(mtype, func, payload):
    body = bytes([len(payload) + 3, mtype, func]) + payload
    cs = 0xFF
    for b in body:
        cs ^= b
    return b"\x01" + body + bytes([cs])


def crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def esp3(ptype, data, opt=b""):
    hdr = struct.pack(">HBB", len(data), len(opt), ptype)
    return b"\x55" + hdr + bytes([crc8(hdr)]) + data + opt + bytes([crc8(data + opt)])


def zwave_vectors():
    P = "zwave-serial-frame"
    out = []
    out.append(("01-ack-roundtrip.json", vec(P, "ack-roundtrip", b"\x06", {"@kind": "ack"}, ref=R_Z)))
    out.append(("02-nak-roundtrip.json", vec(P, "nak-roundtrip", b"\x15", {"@kind": "nak"}, ref=R_Z)))
    a = zwave(0, 0x15, b"")
    out.append(("03-get-controller-version-request-roundtrip.json", vec(P, "get-controller-version-request-roundtrip", a,
                {"@kind": "data-frame", "zwave.message_type": "0", "zwave.function_id": str(0x15), "zwave.payload.#": "0",
                 "zwave.checksum": str(a[-1])}, ref=R_Z, note="GetControllerVersion request, no payload")))
    b = zwave(0, 0x04, bytes([0x00, 0x05, 0x03, 0x25, 0x03, 0xFF]))
    out.append(("04-application-command-roundtrip.json", vec(P, "application-command-roundtrip", b,
                {"zwave.function_id": "4", "zwave.payload.#": "6"}, ref=R_Z,
                note="ApplicationCommand from node 5 carrying a 3-octet command (switch binary report on)")))
    c = zwave(1, 0x13, bytes([0x01]))
    out.append(("05-send-data-response-roundtrip.json", vec(P, "send-data-response-roundtrip", c,
                {"zwave.message_type": "1", "zwave.function_id": str(0x13), "zwave.payload.#": "1"}, ref=R_Z, note="SendData response, accepted")))
    out.append(("06-unknown-header-is-no-kind.json", vec(P, "unknown-header-is-no-kind", b"\x02\x03\x00\x15\xe9", error="no-kind",
                ref=R_Z, note="0x02 is not SOF, ACK, NAK or CAN")))
    out.append(("07-cut-frame-is-malformed.json", vec(P, "cut-frame-is-malformed", b[:6], error="malformed-wire",
                ref=R_Z, note="the length states more octets than the input holds")))
    return P, out


def esp3_vectors():
    P = "enocean-esp3"
    out = []
    erp1 = bytes([0xF6, 0x50]) + bytes.fromhex("0029a1b2") + bytes([0x30])
    opt = bytes([0x01]) + bytes.fromhex("ffffffff") + bytes([0x45, 0x00])
    a = esp3(1, erp1, opt)
    out.append(("01-radio-erp1-roundtrip.json", vec(P, "radio-erp1-roundtrip", a,
                {"esp3.packet_type": "1", "esp3.header_crc": str(a[5]), "esp3.data.#": "7", "esp3.optional_data.#": "7",
                 "esp3.data_crc": str(a[-1])}, ref=R_E, note="an RPS (F6) rocker telegram with the usual 7 optional octets")))
    b = esp3(2, bytes([0x00]))
    out.append(("02-response-ok-roundtrip.json", vec(P, "response-ok-roundtrip", b,
                {"esp3.packet_type": "2", "esp3.data.#": "1", "esp3.optional_data.#": "0"}, ref=R_E, note="a response with return code OK")))
    c = esp3(5, bytes([0x03]))
    out.append(("03-common-command-roundtrip.json", vec(P, "common-command-roundtrip", c, {"esp3.packet_type": "5"},
                ref=R_E, note="common command 3 (read version)")))
    out.append(("04-no-sync-is-no-kind.json", vec(P, "no-sync-is-no-kind", b"\x56" + b[1:], error="no-kind", ref=R_E,
                note="the first octet is not the sync 0x55")))
    out.append(("05-cut-packet-is-malformed.json", vec(P, "cut-packet-is-malformed", a[:12], error="malformed-wire",
                ref=R_E, note="the data length states more octets than the input holds")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (zwave_vectors(), esp3_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("smarthome-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
