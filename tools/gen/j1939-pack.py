#!/usr/bin/env python3
"""Write the SAE J1939 frame pack and its module.

A message is the 4-octet SocketCAN `can_id` (little-endian, as `struct can_frame` holds it on a
little-endian host: the 29-bit identifier and the EFF, RTR and ERR flags) followed by the frame's
data (or a transport-protocol message's reassembled data). The identifier is read as priority,
EDP, DP, PF, PS and SA; the data by PGN: Request (59904), Address Claimed (60928, the NAME
fields), TP.CM (60416: RTS, CTS, EOMA, BAM, Abort), TP.DT (60160), Acknowledgement (59392) and
DM1 (65226: lamps and DTCs); other PGNs as octets.

Sources: Linux Documentation/networking/j1939.rst (the identifier and the PDU1/PDU2 rule) and
include/uapi/linux/can.h (can_id and its flags); python-can-j1939 (message_id.py, name.py,
j1939_21.py, controller_application.py, diagnostic_messages.py) for the data layouts.
The vectors are not written here: tools/gen/j1939-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/j1939-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

LX = "c44104f3642da720164042623e4832836aefdd8e"
PJ = "01aba95cca43847bc272ec7ddb12048f587e6554"
SRC = ('source        "Linux kernel at commit %s: Documentation/networking/j1939.rst (GPL-2.0 OR MIT) and '
       'include/uapi/linux/can.h (GPL-2.0-only WITH Linux-syscall-note OR BSD-3-Clause); python-can-j1939, '
       'https://github.com/juergenH87/python-can-j1939 at commit %s, j1939/message_id.py, name.py, j1939_21.py, '
       'controller_application.py, diagnostic_messages.py (MIT License, Copyright (c) 2018 Frank Benkert); layouts restated, '
       'no code copied; SAE J1939 not used"' % (LX, PJ))
M = "j1939"


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
    return "field  j1939.%s  %d  %s" % (k, b, tr)


def octets(lst):
    return ["group  j1939.%s  rest" % lst, "  " + F("octet", 8), "end"]


def pack():
    name = [F("name_identity_number", 21), F("name_manufacturer_code", 11), F("name_ecu_instance", 3), F("name_function_instance", 5),
            F("name_function", 8), F("name_reserved", 1), F("name_vehicle_system", 7), F("name_vehicle_system_instance", 4),
            F("name_industry_group", 3), F("name_arbitrary_address_capable", 1)]
    tpcm = [F("tp_control", 8)] + sw("j1939.tp_control", [
        ("16", [F("tp_message_size", 16), F("tp_total_packets", 8), F("tp_max_packets", 8)]),
        ("17", [F("tp_packets", 8), F("tp_next_packet", 8), F("tp_reserved", 16)]),
        ("19,32", [F("tp_message_size", 16), F("tp_total_packets", 8), F("tp_reserved", 8)]),
        ("255", [F("tp_abort_reason", 8), F("tp_reserved", 24)])],
        [F("tp_control_bytes", 32)]) + [F("tp_pgn", 24)]
    ack = [F("ack_control", 8), F("ack_group_function", 8), F("ack_reserved", 16), F("ack_address", 8), F("ack_pgn", 24)]
    dm1 = [F("protect_lamp", 2), F("amber_warning_lamp", 2), F("red_stop_lamp", 2), F("malfunction_lamp", 2),
           F("protect_lamp_flash", 2), F("amber_warning_lamp_flash", 2), F("red_stop_lamp_flash", 2), F("malfunction_lamp_flash", 2),
           "group  j1939.dtcs  rest", "  " + F("spn_low", 16)] + ind(1, sw("j1939.spn_low", [("65535", [])],
           [F("fmi", 5), F("spn_high", 3), F("occurrence_count", 7), F("spn_conversion_method", 1)])) + ["end"]
    by_pf = sw("j1939.pdu_format", [
        ("234", [F("requested_pgn", 24)]),
        ("238", name),
        ("236", tpcm),
        ("235", [F("tp_sequence_number", 8)] + octets("data")),
        ("232", ack),
        ("254", sw("j1939.pdu_specific", [("202", dm1)], octets("data")))],
        octets("data"))
    body = sw("j1939.extended_data_page", [("0", sw("j1939.data_page", [("0", by_pf)], octets("data")))], octets("data"))
    L = ["# SAE J1939 frame: the SocketCAN can_id (4 octets, little-endian) and the data, read by PGN. Written by",
         "# tools/gen/j1939-pack.py; do not edit by hand.",
         "format        j1939-frame", "version       0.1.0", "distribution  public", SRC, "uses          j1939",
         "wire          bits", "layout        sequential", "bit_order     lsb", "",
         F("source_address", 8), F("pdu_specific", 8), F("pdu_format", 8), F("data_page", 1), F("extended_data_page", 1),
         F("priority", 3), F("can_err_flag", 1), F("can_rtr_flag", 1), F("can_eff_flag", 1)] + body
    return "\n".join(L) + "\n"


KEYS = [
    ("int", "source_address", "SA: the sender's address (254 null, 255 global)"),
    ("int", "pdu_specific", "PS: with PF below 240 (PDU1) the destination address, not part of the PGN; with PF 240 and above (PDU2) the group extension, part of the PGN"),
    ("int", "pdu_format", "PF: the PDU format"),
    ("int", "data_page", "DP: the data page bit of the PGN"),
    ("int", "extended_data_page", "EDP: the extended data page (reserved) bit of the PGN"),
    ("int", "priority", "priority, 0 highest to 7 lowest"),
    ("int", "can_err_flag", "SocketCAN can_id bit 29, error frame (0)"),
    ("int", "can_rtr_flag", "SocketCAN can_id bit 30, remote transmission request (0)"),
    ("int", "can_eff_flag", "SocketCAN can_id bit 31, extended frame format (1 for J1939)"),
    ("int", "requested_pgn", "Request (PGN 59904): the requested PGN"),
    ("int", "name_identity_number", "Address Claimed (PGN 60928) NAME: identity number, 21 bits"),
    ("int", "name_manufacturer_code", "NAME: manufacturer code, 11 bits"),
    ("int", "name_ecu_instance", "NAME: ECU instance, 3 bits"), ("int", "name_function_instance", "NAME: function instance, 5 bits"),
    ("int", "name_function", "NAME: function, 8 bits"), ("int", "name_reserved", "NAME: the reserved bit"),
    ("int", "name_vehicle_system", "NAME: vehicle system, 7 bits"), ("int", "name_vehicle_system_instance", "NAME: vehicle system instance, 4 bits"),
    ("int", "name_industry_group", "NAME: industry group, 3 bits"),
    ("int", "name_arbitrary_address_capable", "NAME: arbitrary address capable, 1 bit"),
    ("int", "tp_control", "TP.CM (PGN 60416): control byte, 16 RTS, 17 CTS, 19 end of message ACK, 32 BAM, 255 connection abort"),
    ("int", "tp_message_size", "TP.CM RTS, EOMA, BAM: the message size in octets"),
    ("int", "tp_total_packets", "TP.CM RTS, EOMA, BAM: the number of packets"),
    ("int", "tp_max_packets", "TP.CM RTS: the maximum number of packets in response to one CTS"),
    ("int", "tp_packets", "TP.CM CTS: the number of packets that can be sent"),
    ("int", "tp_next_packet", "TP.CM CTS: the next packet number to send"),
    ("int", "tp_abort_reason", "TP.CM Abort: the reason (1 busy, 2 resources, 3 timeout ...)"),
    ("int", "tp_reserved", "TP.CM: the reserved octets of the control's layout (0xFF fill), as one integer"),
    ("int", "tp_control_bytes", "TP.CM with another control byte: octets 2 to 5, as one integer"),
    ("int", "tp_pgn", "TP.CM: the PGN of the transported message"),
    ("int", "tp_sequence_number", "TP.DT (PGN 60160): which packet of the transfer this is, numbered from 1 up to 255"),
    ("int", "ack_control", "Acknowledgement (PGN 59392): control byte (0 ACK, 1 NACK, 2 access denied, 3 cannot respond)"),
    ("int", "ack_group_function", "Acknowledgement: group function value"),
    ("int", "ack_reserved", "Acknowledgement: two reserved octets (0xFF), as one integer"),
    ("int", "ack_address", "Acknowledgement: the address acknowledged"), ("int", "ack_pgn", "Acknowledgement: the PGN acknowledged"),
    ("int", "protect_lamp", "DM1 (PGN 65226): protect lamp status (0 off, 1 on, 3 not available)"),
    ("int", "amber_warning_lamp", "DM1: amber warning lamp status"), ("int", "red_stop_lamp", "DM1: red stop lamp status"),
    ("int", "malfunction_lamp", "DM1: malfunction indicator lamp status"),
    ("int", "protect_lamp_flash", "DM1: protect lamp flash (0 slow, 1 fast, 3 none or not available)"),
    ("int", "amber_warning_lamp_flash", "DM1: amber warning lamp flash"), ("int", "red_stop_lamp_flash", "DM1: red stop lamp flash"),
    ("int", "malfunction_lamp_flash", "DM1: malfunction indicator lamp flash"),
    ("list", "dtcs", "DM1: the diagnostic trouble codes, four octets each; an item whose low SPN octets are 0xFFFF is read as two octets alone (the padding of a one-DTC frame)"),
    ("int", "spn_low", "DTC: the low 16 bits of the SPN"), ("int", "fmi", "DTC: failure mode identifier, 5 bits"),
    ("int", "spn_high", "DTC: the high 3 bits of the SPN (SPN = spn_high x 65536 + spn_low)"),
    ("int", "occurrence_count", "DTC: occurrence count, 7 bits"), ("int", "spn_conversion_method", "DTC: SPN conversion method bit (0 in the current method)"),
    ("list", "data", "the data of another PGN, or a TP.DT packet's seven data octets, as octets"),
    ("int", "octet", "one octet"),
]


def module():
    w = max(len(k[1]) for k in KEYS)
    L = ["# The j1939 module: SAE J1939 identifier and data fields. Written by tools/gen/j1939-pack.py.",
         "module        j1939", "version       0.1.0", "distribution  public", SRC]
    for t, k, d in KEYS:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/j1939-frame/pack.def", pack())
    out.write("model/j1939.def", module())
    return {"j1939": 2}


def main(argv=None):
    return genio.vector_main("j1939-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
