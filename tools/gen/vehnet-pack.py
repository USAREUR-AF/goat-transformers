#!/usr/bin/env python3
"""Write the vehicle diagnostic network packs and their modules:

- isotp-frame: one ISO-TP (ISO 15765-2) frame, the data of one CAN or CAN FD frame: the protocol
  control information by frame type (single frame with or without the escape length, first frame
  with or without the 32-bit escape length, consecutive frame, flow control) and the data and
  padding. Layout restated from python-can-isotp isotp/protocol.py (class PDU).
- uds-message: one UDS (ISO 14229-1) message: the service identifier and, for the common services
  (0x10, 0x11, 0x22, 0x27, 0x2E, 0x31, 0x3E) and their positive responses, the fields that follow;
  the negative response (0x7F). Layouts restated from python-udsoncan (Request.py, Response.py and
  the service modules).
- doip-message: one DoIP (ISO 13400-2) message: the generic header with its payload length and
  the payload by type. Layouts restated from Wireshark epan/dissectors/packet-doip.c.

The vectors are not written here: tools/gen/vehnet-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/vehnet-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

IT = "90ebb425c2f8156f7e6db873f1e467fa410463be"
UD = "07d7be1fcfd17e41af9a30f1c5573774e45bcdbd"
WS = "de1eec95b2007952f7399173d2f0904275a31c6f"
SRC = {
    "isotp": ('source        "python-can-isotp, https://github.com/pylessard/python-can-isotp at commit %s, isotp/protocol.py '
              '(class PDU), MIT License, Copyright (c) 2017 Pier-Yves Lessard; layout restated, no code copied; ISO 15765-2 not used"' % IT),
    "uds": ('source        "python-udsoncan, https://github.com/pylessard/python-udsoncan at commit %s, udsoncan/Request.py, '
            'Response.py and services/DiagnosticSessionControl.py, ECUReset.py, ReadDataByIdentifier.py, WriteDataByIdentifier.py, '
            'SecurityAccess.py, RoutineControl.py, TesterPresent.py, MIT License, Copyright (c) 2017 Pier-Yves Lessard; '
            'layouts restated, no code copied; ISO 14229-1 not used"' % UD),
    "doip": ('source        "Wireshark, https://github.com/wireshark/wireshark at commit %s, epan/dissectors/packet-doip.c '
             '(GPL-2.0-or-later); layouts restated, no code copied; ISO 13400-2 not used"' % WS),
}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def sw(key, cases, other=None):
    L = ["switch  %s" % key]
    for vals, lines in cases:
        L.append("  case  %s" % vals)
        L += ind(2, lines)
    if other is not None:
        L.append("  else")
        L += ind(2, other)
    L.append("end")
    return L


def F(k, b, tr="uint"):
    return "field  %s  %d  %s" % (k, b, tr)


def octets(lst, octet):
    return ["group  %s  rest" % lst, "  " + F(octet, 8), "end"]


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def text(L):
    return "\n".join(L) + "\n"


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], k[0], k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- ISO-TP

def isotp_pack():
    o = "isotp.octet"
    data_n = lambda cnt: ["group  isotp.data  count  @%s" % cnt, "  " + F(o, 8), "end"] + octets("isotp.padding", o)
    L = head("isotp-frame", ["ISO-TP (ISO 15765-2) frame: the data field of one CAN or CAN FD frame, by frame type. Written by",
                             "tools/gen/vehnet-pack.py; do not edit by hand."], "isotp", ["isotp"])
    L += ["kind  single-frame-escape", "when  8  0", "count  sf_escape_length  8"] + data_n("sf_escape_length") + [""]
    L += ["kind  single-frame", "when  4  0", "count  sf_length  4"] + data_n("sf_length") + [""]
    L += ["kind  first-frame-escape", "when  16  4096", F("isotp.message_length", 32)] + octets("isotp.data", o) + [""]
    L += ["kind  first-frame", "when  4  1", F("isotp.message_length", 12)] + octets("isotp.data", o) + [""]
    L += ["kind  consecutive-frame", "when  4  2", F("isotp.sequence_number", 4)] + octets("isotp.data", o) + [""]
    L += ["kind  flow-control", "when  4  3", F("isotp.flow_status", 4), F("isotp.block_size", 8), F("isotp.st_min", 8)] + octets("isotp.padding", o)
    return text(L)


ISOTP_KEYS = [
    ("list", "data", "the payload octets of the frame (single frame: as many as its length says; first and consecutive frame: the rest of the frame, padding included)"),
    ("list", "padding", "single frame and flow control: the octets after the data or the flow control fields (the CAN frame's padding)"),
    ("int", "message_length", "first frame: the length of the whole message in octets (12 bits, or 32 bits after the escape value 0)"),
    ("int", "sequence_number", "consecutive frame: the sequence number, 0 to 15"),
    ("int", "flow_status", "flow control: 0 continue to send, 1 wait, 2 overflow"),
    ("int", "block_size", "flow control: consecutive frames to send before the next flow control (0: no limit)"),
    ("int", "st_min", "flow control: minimum separation time, 0x00-0x7F milliseconds, 0xF1-0xF9 100 to 900 microseconds"),
    ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- UDS

def uds_pack():
    o = "uds.octet"
    sub = [F("uds.suppress_positive_response", 1), F("uds.subfunction", 7)]
    L = head("uds-message", ["UDS (ISO 14229-1) message: the service identifier and the fields of the common services, their positive",
                             "responses and the negative response. Written by tools/gen/vehnet-pack.py; do not edit by hand."], "uds", ["uds"])
    L += [F("uds.sid", 8)]
    L += sw("uds.sid", [
        ("16,17,62", sub + octets("uds.data", o)),
        ("39", sub + octets("uds.security_data", o)),
        ("49", sub + [F("uds.routine_id", 16)] + octets("uds.routine_option", o)),
        ("34", ["group  uds.dids  rest", "  " + F("uds.did", 16), "end"]),
        ("46", [F("uds.data_identifier", 16)] + octets("uds.data_record", o)),
        ("80", [F("uds.session_echo", 8)] + octets("uds.session_parameter_record", o)),
        ("81", [F("uds.reset_type_echo", 8)] + octets("uds.data", o)),
        ("98", [F("uds.data_identifier", 16)] + octets("uds.data_record", o)),
        ("103", [F("uds.security_level_echo", 8)] + octets("uds.security_data", o)),
        ("110", [F("uds.data_identifier", 16)]),
        ("113", [F("uds.control_type_echo", 8), F("uds.routine_id", 16)] + octets("uds.routine_status", o)),
        ("126", [F("uds.subfunction_echo", 8)]),
        ("127", [F("uds.rejected_sid", 8), F("uds.nrc", 8)])],
        octets("uds.data", o))
    return text(L)


UDS_KEYS = [
    ("int", "sid", "service identifier: requests 0x10 session control, 0x11 ECU reset, 0x22 read data by identifier, 0x27 security access, 0x2E write data by identifier, 0x31 routine control, 0x3E tester present; positive responses are the request's value plus 0x40; 0x7F a negative response"),
    ("int", "suppress_positive_response", "request with a subfunction: bit 7 of the subfunction octet, the server sends no positive response"),
    ("int", "subfunction", "request with a subfunction: the subfunction (session type, reset type, security level, routine control type, 0 for tester present)"),
    ("list", "data", "the remaining octets (session and reset requests normally have none; other services), as octets"),
    ("list", "security_data", "security access: the key (send key, even levels) or the seed (positive response to request seed), as octets"),
    ("int", "routine_id", "routine control: the routine identifier"),
    ("list", "routine_option", "routine control request: the routine control option record, as octets"),
    ("list", "routine_status", "routine control response: the routine status record, as octets"),
    ("list", "dids", "read data by identifier request: the data identifiers"), ("int", "did", "a data identifier"),
    ("int", "data_identifier", "write data by identifier request and response, read data by identifier response: the (first) data identifier"),
    ("list", "data_record", "the data record after the identifier (in a read response: the first identifier's value and any further identifiers and values), as octets"),
    ("int", "session_echo", "session control response: the session type echoed"),
    ("list", "session_parameter_record", "session control response: the session parameter record, as octets (from the 2013 edition, P2 server maximum in milliseconds then P2* in 10-millisecond units, two octets each)"),
    ("int", "reset_type_echo", "ECU reset response: the reset type echoed"),
    ("int", "security_level_echo", "security access response: the level echoed"),
    ("int", "control_type_echo", "routine control response: the control type echoed"),
    ("int", "subfunction_echo", "tester present response: the subfunction echoed (0)"),
    ("int", "rejected_sid", "negative response: the service identifier of the rejected request"),
    ("int", "nrc", "negative response: the negative response code (0x11 service not supported, 0x12 subfunction not supported, 0x13 incorrect length, 0x22 conditions not correct, 0x31 request out of range, 0x33 security access denied, 0x35 invalid key, 0x78 response pending ...)"),
    ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- DoIP

def doip_pack():
    o = "doip.octet"
    sd = [F("doip.source_address", 16), F("doip.target_address", 16)]
    body = sw("doip.payload_type", [
        ("0", [F("doip.nack_code", 8)]),
        ("1,7,16385,16387", []),
        ("2", [F("doip.eid", 48, "hex")]),
        ("3", ["field  doip.vin  136  chars:ascii8"]),
        ("4", ["field  doip.vin  136  chars:ascii8", F("doip.logical_address", 16), F("doip.eid", 48, "hex"), F("doip.gid", 48, "hex"),
               F("doip.further_action", 8), F("doip.sync_status", 8)]),
        ("5", [F("doip.source_address", 16)] + sw("doip.version", [("1", [F("doip.activation_type", 16)])], [F("doip.activation_type", 8)]) +
         [F("doip.reserved_iso", 32)] + octets("doip.reserved_oem", o)),
        ("6", [F("doip.tester_address", 16), F("doip.source_address", 16), F("doip.response_code", 8), F("doip.reserved_iso", 32)] +
         octets("doip.reserved_oem", o)),
        ("8", [F("doip.source_address", 16)]),
        ("16386", [F("doip.node_type", 8), F("doip.max_sockets", 8), F("doip.current_sockets", 8), F("doip.max_data_size", 32)]),
        ("16388", [F("doip.power_mode", 8)]),
        ("32769", sd + octets("doip.user_data", o)),
        ("32770", sd + [F("doip.ack_code", 8)] + octets("doip.previous_message", o)),
        ("32771", sd + [F("doip.nack_code", 8)] + octets("doip.previous_message", o))],
        octets("doip.payload", o))
    L = head("doip-message", ["DoIP (ISO 13400-2) message: the generic header with the payload length, and the payload by type. Written",
                              "by tools/gen/vehnet-pack.py; do not edit by hand."], "doip", ["doip"])
    L += [F("doip.version", 8), F("doip.inverse_version", 8), F("doip.payload_type", 16), "length  32  bytes"] + ind(1, body) + ["end"]
    return text(L)


DOIP_KEYS = [
    ("int", "version", "protocol version: 1 ISO 13400-2:2010, 2 :2012, 3 :2019, 4 :2019/Amd1, 0xFF default (vehicle identification request)"),
    ("int", "inverse_version", "the version's bitwise inverse"),
    ("int", "payload_type", "payload type: 0 generic header NACK, 1-3 vehicle identification request (plain, by EID, by VIN), 4 vehicle announcement or identification response, 5 routing activation request, 6 response, 7 alive check request, 8 response, 0x4001-0x4004 entity status and power mode information request and response, 0x8001 diagnostic message, 0x8002 ACK, 0x8003 NACK"),
    ("int", "nack_code", "generic header NACK or diagnostic message NACK: the code"),
    ("string", "eid", "entity identifier, 6 octets as hexadecimal digits"), ("string", "gid", "group identifier, 6 octets as hexadecimal digits"),
    ("string", "vin", "vehicle identification number, 17 characters"),
    ("int", "logical_address", "vehicle announcement: the entity's logical address"),
    ("int", "further_action", "vehicle announcement: further action required"),
    ("int", "sync_status", "vehicle announcement: VIN/GID synchronisation status (from version 2, optional)"),
    ("int", "source_address", "the source (tester or entity) logical address"), ("int", "target_address", "diagnostic message: the target logical address"),
    ("int", "activation_type", "routing activation request: activation type (16 bits in version 1, 8 bits later)"),
    ("int", "reserved_iso", "routing activation: the 4 octets reserved by ISO"),
    ("list", "reserved_oem", "routing activation: the optional 4 octets reserved for the OEM, as octets"),
    ("int", "tester_address", "routing activation response: the tester's logical address"),
    ("int", "response_code", "routing activation response: the code (0x10 activated ...)"),
    ("int", "node_type", "entity status response: node type (0 gateway, 1 node)"),
    ("int", "max_sockets", "entity status response: maximum concurrent TCP sockets"),
    ("int", "current_sockets", "entity status response: currently open TCP sockets"),
    ("int", "max_data_size", "entity status response: maximum data size (from version 2, optional)"),
    ("int", "power_mode", "power mode information response: the power mode"),
    ("list", "user_data", "diagnostic message: the user data (a UDS message), as octets"),
    ("int", "ack_code", "diagnostic message ACK: the code"),
    ("list", "previous_message", "diagnostic message ACK or NACK: the previous diagnostic message, as octets"),
    ("list", "payload", "another payload type's payload, as octets"), ("int", "octet", "one octet"),
]


def build(out):
    out.write("packs/isotp-frame/pack.def", isotp_pack())
    out.write("packs/uds-message/pack.def", uds_pack())
    out.write("packs/doip-message/pack.def", doip_pack())
    for m, h, src, keys in (("isotp", "ISO-TP frame fields", "isotp", ISOTP_KEYS), ("uds", "UDS message fields", "uds", UDS_KEYS),
                            ("doip", "DoIP header and payload fields", "doip", DOIP_KEYS)):
        out.write("model/%s.def" % m, module(m, ["# The %s module: %s. Written by tools/gen/vehnet-pack.py." % (m, h)], src, keys))
    return {"vehnet": 6}


def main(argv=None):
    return genio.vector_main("vehnet-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
