#!/usr/bin/env python3
"""Write the metering packs and their modules:

- mbus-frame: a wired M-Bus frame (EN 13757-2/-3): the single-character ACK, the short frame, and
  the control and long frames with their doubled length, control field, address, CI field and, for
  CI 0x72/0x76 and 0x73/0x77, the variable-data header and its data records (DIF, DIFEs, VIF,
  VIFEs, plain-text VIF, the value by its DIF data field) or the fixed-data block. Layouts restated
  from libmbus (mbus/mbus-protocol.h and mbus-protocol.c).
- wmbus-frame: a wireless M-Bus link-layer frame (EN 13757-4) with the CRC blocks removed: length,
  control, manufacturer, address (identification, version, device type), CI and, for the extended
  link layer I and the short and long transport-layer headers, their fields; the application data
  as octets. Layouts restated from wmbusmeters (src/wmbus.cc).
- dlms-hdlc-frame: a DLMS/COSEM HDLC frame (IEC 62056-46): the flags, the frame format field with
  its length, the variable-length destination and source addresses, the control field, the header
  check and the information field with the frame check as octets. Layout restated from Gurux
  GuruxDLMS.c (development/src/dlms.c).

The vectors are not written here: tools/gen/meter2-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/meter2-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

LM = "94352715928182d9e1761959f887c6a66e70de93"
WM = "86c46f145077f66e988c25ee04c06f89230c12e3"
GX = "e9d77f926f3d3b8d1aa1a8f3374c7259d1c39b71"
SRC = {
    "mbus": ('source        "libmbus, https://github.com/rscada/libmbus at commit %s, mbus/mbus-protocol.h and mbus/mbus-protocol.c '
             '(Copyright (C) 2010-2012 Raditex AB and contributors; free to use with credit to rSCADA and Raditex Control); '
             'layouts restated, no code copied; EN 13757 not used"' % LM),
    "wmbus": ('source        "wmbusmeters, https://github.com/wmbusmeters/wmbusmeters at commit %s, src/wmbus.cc (GPL-3.0-or-later, '
              'Copyright (C) 2017-2024 Fredrik Oehrstroem); layouts restated, no code copied; EN 13757-4 not used"' % WM),
    "dlms": ('source        "Gurux GuruxDLMS.c, https://github.com/Gurux/GuruxDLMS.c at commit %s, development/src/dlms.c (GPL-2.0, '
             'Copyright (c) Gurux Ltd); layout restated, no code copied; IEC 62056-46 not used"' % GX),
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


def F(k, b, tr="uint", swap=False):
    return "field  %s  %d  %s%s" % (k, b, tr, "  swap" if swap else "")


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


# ---------------------------------------------------------------- wired M-Bus

def mbus_control():
    return [F("mbus.control_reserved", 1), F("mbus.control_prm", 1), F("mbus.control_fcb_acd", 1), F("mbus.control_fcv_dfc", 1),
            F("mbus.control_function", 4)]


def mbus_record():
    o = "mbus.octet"
    value = sw("mbus.data_field", [
        ("1", [F("mbus.value", 8)]), ("2", [F("mbus.value", 16, swap=True)]), ("3", [F("mbus.value", 24, swap=True)]),
        ("4", [F("mbus.value", 32, swap=True)]), ("5", [F("mbus.value_real", 32, "f32", swap=True)]),
        ("6", [F("mbus.value", 48, swap=True)]), ("7", [F("mbus.value", 64, swap=True)]),
        ("9", [F("mbus.value_bcd", 8, "hex")]), ("10", [F("mbus.value_bcd", 16, "hex")]),
        ("11", [F("mbus.value_bcd", 24, "hex")]), ("12", [F("mbus.value_bcd", 32, "hex")]),
        ("14", [F("mbus.value_bcd", 48, "hex")]),
        ("13", ["count  lvar  8", "group  mbus.value_lvar  count  @lvar", "  " + F(o, 8), "end"])], [])
    vib = ([F("mbus.vif_extension", 1), F("mbus.vif", 7)] +
           sw("mbus.vif_extension", [("1", ["group  mbus.vifes  more", "  " + F("mbus.vife", 7), "end"])], []) +
           sw("mbus.vif", [("124", ["count  vif_text_length  8", "group  mbus.vif_text  count  @vif_text_length", "  " + F(o, 8), "end"])], []))
    rec = ([F("mbus.dif_extension", 1), F("mbus.storage_lsb", 1), F("mbus.function_field", 2), F("mbus.data_field", 4)] +
           sw("mbus.dif_extension", [("1", ["group  mbus.difes  more", "  " + F("mbus.dife_unit", 1), "  " + F("mbus.dife_tariff", 2),
                                            "  " + F("mbus.dife_storage", 4), "end"])], []) +
           sw("mbus.data_field", [("15", sw("mbus.function_field", [("2", [])], octets("mbus.manufacturer_data", o)))],
              vib + value))
    return ["group  mbus.records  rest"] + ind(1, rec) + ["end"]


def mbus_pack():
    o = "mbus.octet"
    variable = ([F("mbus.identification", 32, "hex"), F("mbus.manufacturer", 16, swap=True), F("mbus.version", 8),
                 F("mbus.medium", 8), F("mbus.access_number", 8), F("mbus.status", 8), F("mbus.signature", 16, swap=True)] + mbus_record())
    fixed = [F("mbus.identification", 32, "hex"), F("mbus.access_number", 8), F("mbus.status", 8),
             F("mbus.counter1_type", 8), F("mbus.counter2_type", 8), F("mbus.counter1", 32, "hex"),
             F("mbus.counter2", 32, "hex")]
    body = (["field  mbus.length_repeat  8  uint", "const  8  104"] + mbus_control() + [F("mbus.address", 8), F("mbus.ci", 8)] +
            sw("mbus.ci", [("114,118", variable), ("115,119", fixed)], octets("mbus.data", o)))
    L = head("mbus-frame", ["Wired M-Bus frame: ACK, short, control and long frames, with the variable-data header and its records or the",
                            "fixed-data block. Written by tools/gen/meter2-pack.py; do not edit by hand."], "mbus", ["mbus"])
    L += ["kind  ack", "when  8  229", ""]
    L += ["kind  short", "when  8  16"] + mbus_control() + [F("mbus.address", 8), F("mbus.checksum", 8), "const  8  22", ""]
    L += ["kind  long", "when  8  104", "length  8  bytes  plus  -2"] + ind(1, body) + ["end", F("mbus.checksum", 8), "const  8  22"]
    return text(L)


MBUS_KEYS = [
    ("int", "control_reserved", "control field bit 7 (0)"),
    ("int", "control_prm", "control field bit 6: 1 a message from the master, 0 from a slave"),
    ("int", "control_fcb_acd", "control field bit 5: FCB from the master, ACD from a slave"),
    ("int", "control_fcv_dfc", "control field bit 4: FCV from the master, DFC from a slave"),
    ("int", "control_function", "control field bits 3-0: function (SND_NKE 0x40, SND_UD 0x53, REQ_UD2 0x5B, REQ_UD1 0x5A, RSP_UD 0x08 as whole bytes)"),
    ("int", "address", "address (0xFD network layer, 0xFE broadcast with reply, 0xFF broadcast without reply)"),
    ("int", "checksum", "the checksum octet, as sent (the sum of the control field to the last data octet, modulo 256; not computed)"),
    ("int", "length_repeat", "long and control frame: the second length octet, as sent (equal to the first)"),
    ("int", "ci", "control information field (0x72/0x76 variable data response, 0x73/0x77 fixed data response, 0x51 data send, 0x52 select slave, 0x50 application reset ...)"),
    ("string", "identification", "identification number: the 4 octets as sent, as hexadecimal digits (BCD, low octet first: 78563412 is 12345678)"),
    ("int", "manufacturer", "manufacturer code, the 16-bit value of three 5-bit letters"),
    ("int", "version", "version"), ("int", "medium", "medium (device type)"), ("int", "access_number", "access number (fixed data: transmission counter)"),
    ("int", "status", "status"), ("int", "signature", "signature"),
    ("list", "records", "the data records of the variable data structure"),
    ("int", "dif_extension", "DIF bit 7: a DIFE follows"), ("int", "storage_lsb", "DIF bit 6: storage number, least significant bit"),
    ("int", "function_field", "DIF bits 5-4: 0 instantaneous, 1 maximum, 2 minimum, 3 error state"),
    ("int", "data_field", "DIF bits 3-0: the data coding (0 none, 1-4 integer of 1-4 octets, 5 real, 6 integer of 6, 7 of 8, 8 no data, 9-12 BCD of 2-8 digits, 13 variable length, 14 BCD of 12 digits, 15 special)"),
    ("list", "difes", "the DIF extensions"), ("int", "dife_unit", "DIFE bit 6: device unit"), ("int", "dife_tariff", "DIFE bits 5-4: tariff"),
    ("int", "dife_storage", "DIFE bits 3-0: storage number"),
    ("int", "vif_extension", "VIF bit 7: a VIFE follows"), ("int", "vif", "VIF bits 6-0: the value information (unit and multiplier)"),
    ("list", "vifes", "the VIF extensions"), ("int", "vife", "VIFE bits 6-0"),
    ("list", "vif_text", "plain-text VIF (0x7C, 0xFC): the unit text, as octets"),
    ("int", "value", "an integer value, as an unsigned integer of its octets"),
    ("float", "value_real", "a 32-bit real value"), ("string", "value_bcd", "a BCD value: its octets as sent, as hexadecimal digits (low octet first)"),
    ("list", "value_lvar", "a variable-length value (LVAR 0x00-0xBF: that many characters), as octets"),
    ("list", "manufacturer_data", "DIF 0x0F or 0x1F: the manufacturer-specific data to the end, as octets"),
    ("int", "counter1_type", "fixed data: medium and unit of counter 1"), ("int", "counter2_type", "fixed data: medium and unit of counter 2"),
    ("string", "counter1", "fixed data: counter 1, its 4 octets as sent, as hexadecimal digits (BCD or binary by the status; low octet first)"),
    ("string", "counter2", "fixed data: counter 2, as hexadecimal digits"),
    ("list", "data", "another CI field's data, as octets"), ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- wireless M-Bus

def tpl(o):
    cfg = [F("wmbus.access_number", 8), F("wmbus.status", 8), F("wmbus.configuration", 16, swap=True)] + octets("wmbus.application_data", o)
    return [
        ("122", cfg),
        ("114", [F("wmbus.tpl_identification", 32, "hex"), F("wmbus.tpl_manufacturer", 16, swap=True), F("wmbus.tpl_version", 8),
                 F("wmbus.tpl_device_type", 8)] + cfg),
    ]


def wmbus_pack():
    o = "wmbus.octet"
    body = ([F("wmbus.control", 8), F("wmbus.manufacturer", 16, swap=True), F("wmbus.identification", 32, "hex"),
             F("wmbus.version", 8), F("wmbus.device_type", 8), F("wmbus.ci", 8)] +
            sw("wmbus.ci", tpl(o) + [("140", [F("wmbus.ell_cc", 8), F("wmbus.ell_acc", 8), F("wmbus.ell_next_ci", 8)] +
                                      sw("wmbus.ell_next_ci", tpl(o), octets("wmbus.application_data", o)))],
               octets("wmbus.application_data", o)))
    L = head("wmbus-frame", ["Wireless M-Bus link-layer frame (CRC blocks removed): length, control, manufacturer, address, CI and the",
                             "ELL and TPL headers. Written by tools/gen/meter2-pack.py; do not edit by hand."], "wmbus", ["wmbus"])
    L += ["length  8  bytes"] + ind(1, body) + ["end"]
    return text(L)


WMBUS_KEYS = [
    ("int", "control", "C field (0x44 SND_NR, 0x46 SND_IR, 0x08 RSP_UD2; others as sent)"),
    ("int", "manufacturer", "link-layer manufacturer code (three 5-bit letters)"),
    ("string", "identification", "link-layer identification number: the 4 octets as sent, as hexadecimal digits (BCD, low octet first)"),
    ("int", "version", "link-layer version"), ("int", "device_type", "link-layer device type (medium)"),
    ("int", "ci", "CI field: 0x7A short transport header, 0x72 long transport header, 0x78 no header, 0x8C extended link layer I, others"),
    ("int", "ell_cc", "extended link layer: communication control"), ("int", "ell_acc", "extended link layer: access number"),
    ("int", "ell_next_ci", "extended link layer I: the CI field that follows"),
    ("string", "tpl_identification", "long transport header: identification number, the 4 octets as sent, as hexadecimal digits"),
    ("int", "tpl_manufacturer", "long transport header: manufacturer"), ("int", "tpl_version", "long transport header: version"),
    ("int", "tpl_device_type", "long transport header: device type"),
    ("int", "access_number", "transport header: access number"), ("int", "status", "transport header: status"),
    ("int", "configuration", "transport header: configuration field (bits 12-8 the security mode)"),
    ("list", "application_data", "the application data (records, or encrypted blocks, and any configuration extension), as octets"),
    ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- DLMS HDLC

def hdlc_address(p, n=1):
    lines = [F("dlmshdlc.%s_part%d" % (p, n), 7), F("dlmshdlc.%s_last%d" % (p, n), 1)]
    if n < 4:
        lines += sw("dlmshdlc.%s_last%d" % (p, n), [("0", hdlc_address(p, n + 1))], [])
    return lines


def dlms_pack():
    body = (hdlc_address("destination") + hdlc_address("source") + [F("dlmshdlc.control", 8), F("dlmshdlc.header_check", 16, "hex")] +
            octets("dlmshdlc.information_and_fcs", "dlmshdlc.octet"))
    L = head("dlms-hdlc-frame", ["DLMS/COSEM HDLC frame: flags, frame format and length, addresses, control, header check, information and",
                                 "frame check. Written by tools/gen/meter2-pack.py; do not edit by hand."], "dlms", ["dlmshdlc"])
    L += ["kind  hdlc", "when  8  126", F("dlmshdlc.frame_type", 4), F("dlmshdlc.segmentation", 1), "length  11  bytes  plus  2"] + ind(1, body) + ["end", "const  8  126"]
    return text(L)


def dlms_keys():
    keys = [("int", "frame_type", "frame format type, 0xA"), ("int", "segmentation", "segmentation bit: more segments follow")]
    for p in ("destination", "source"):
        for n in range(1, 5):
            keys.append(("int", "%s_part%d" % (p, n), "%s address octet %d: its upper 7 bits" % (p, n)))
            keys.append(("int", "%s_last%d" % (p, n), "%s address octet %d: the low bit, 1 on the last octet (1, 2 or 4 octets)" % (p, n)))
    keys += [("int", "control", "control field, as sent"),
             ("string", "header_check", "the 16-bit check after the control field, as sent (the header check when an information field follows; in a frame without one, the frame check)"),
             ("list", "information_and_fcs", "the information field (the LLC header and the COSEM APDU) and the 16-bit frame check, as octets (empty in a frame without information)"),
             ("int", "octet", "one octet")]
    return keys


def build(out):
    out.write("packs/mbus-frame/pack.def", mbus_pack())
    out.write("packs/wmbus-frame/pack.def", wmbus_pack())
    out.write("packs/dlms-hdlc-frame/pack.def", dlms_pack())
    for m, h, src, keys in (("mbus", "wired M-Bus frame and data record fields", "mbus", MBUS_KEYS),
                            ("wmbus", "wireless M-Bus link layer and transport header fields", "wmbus", WMBUS_KEYS),
                            ("dlmshdlc", "DLMS/COSEM HDLC frame fields", "dlms", dlms_keys())):
        out.write("model/%s.def" % m, module(m, ["# The %s module: %s. Written by tools/gen/meter2-pack.py." % (m, h)], src, keys))
    return {"meter2": 6}


def main(argv=None):
    return genio.vector_main("meter2-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
