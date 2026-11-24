#!/usr/bin/env python3
"""Write the industrial and building automation framing packs and their modules:

- bacnet-ip-bvlc: the BACnet/IPv4 virtual link layer (BVLC) message and, where it carries one, the
  BACnet NPDU header (control octet, destination and source networks and addresses, hop count,
  network message type and vendor), the APDU or network message after it as octets. Layouts
  restated from bacnet-stack (src/bacnet/datalink/bvlc.c and src/bacnet/npdu.c).
- enip-encapsulation: the EtherNet/IP encapsulation header (24 octets, little-endian) and, for
  RegisterSession, SendRRData and SendUnitData, the command data with the common packet format
  item list; item data by type (connected address, sequenced address, socket address info),
  other items as octets. Layouts restated from Wireshark epan/dissectors/packet-enip.c.
- hart-ip-message: the HART-IP header with its whole-message length and the body by message
  type and ID (session initiate, error code, pass-through HART frame). Layouts restated from
  Wireshark epan/dissectors/packet-hartip.c.

The vectors are not written here: tools/gen/indauto2-vectors.py derives them with an encoder of
its own.

Usage: python3 -I tools/gen/indauto2-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

BS = "229ba806601d4459a2b7889ec1280cb0ed4efcb4"
WS = "de1eec95b2007952f7399173d2f0904275a31c6f"
SRC = {
    "bacnet": ('source        "bacnet-stack, https://github.com/bacnet-stack/bacnet-stack at commit %s, src/bacnet/datalink/bvlc.c, '
               'bvlc.h and src/bacnet/npdu.c (GPL-2.0-or-later WITH GCC-exception-2.0); layouts restated, no code copied; '
               'ASHRAE 135 not used"' % BS),
    "enip": ('source        "Wireshark, https://github.com/wireshark/wireshark at commit %s, epan/dissectors/packet-enip.c '
             '(GPL-2.0-or-later); layouts restated, no code copied; the ODVA specification not used"' % WS),
    "hartip": ('source        "Wireshark, https://github.com/wireshark/wireshark at commit %s, epan/dissectors/packet-hartip.c '
               '(GPL-2.0-or-later); layouts restated, no code copied; the FieldComm Group specification not used"' % WS),
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


def head(name, comment, src, uses, order="msb"):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     %s" % order, ""])


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


# ---------------------------------------------------------------- BACnet/IP

B = "bacnetip"


def npdu():
    o = "bacnetip.octet"
    dest = [F("bacnetip.dnet", 16), "count  dlen  8", "group  bacnetip.dadr  count  @dlen", "  " + F(o, 8), "end"]
    src = [F("bacnetip.snet", 16), "count  slen  8", "group  bacnetip.sadr  count  @slen", "  " + F(o, 8), "end"]
    netmsg = [F("bacnetip.network_message_type", 8)] + sw("bacnetip.network_message_type",
                                                          [(",".join(str(v) for v in range(128, 256)), [F("bacnetip.vendor_id", 16)])], [])
    return ([F("bacnetip.npdu_version", 8), F("bacnetip.network_message", 1), F("bacnetip.control_reserved6", 1),
             F("bacnetip.destination_present", 1), F("bacnetip.control_reserved4", 1), F("bacnetip.source_present", 1),
             F("bacnetip.expecting_reply", 1), F("bacnetip.priority", 2)] +
            sw("bacnetip.destination_present", [("1", dest)], []) + sw("bacnetip.source_present", [("1", src)], []) +
            sw("bacnetip.destination_present", [("1", [F("bacnetip.hop_count", 8)])], []) +
            sw("bacnetip.network_message", [("1", netmsg)], []) + octets("bacnetip.payload", o))


def bacnet_pack():
    addr = [F("bacnetip.ip_address", 32), F("bacnetip.udp_port", 16)]
    bdt = ["group  bacnetip.bdt_entries  rest", "  " + F("bacnetip.bdt_address", 32), "  " + F("bacnetip.bdt_port", 16),
           "  " + F("bacnetip.bdt_mask", 32), "end"]
    fdt = ["group  bacnetip.fdt_entries  rest", "  " + F("bacnetip.fdt_address", 32), "  " + F("bacnetip.fdt_port", 16),
           "  " + F("bacnetip.fdt_ttl", 16), "  " + F("bacnetip.fdt_remaining", 16), "end"]
    L = head("bacnet-ip-bvlc", ["BACnet/IPv4 virtual link layer message (BVLC) with the BACnet NPDU header where it carries one. Written",
                                "by tools/gen/indauto2-pack.py; do not edit by hand."], "bacnet", [B])
    L += ["kind  bvlc", "when  8  129", F("bacnetip.function", 8), "length  16  whole"]
    L += sw("bacnetip.function", [
        ("0", [F("bacnetip.result_code", 16)]),
        ("1,3", bdt),
        ("2,6", []),
        ("4", addr + npdu()),
        ("5", [F("bacnetip.ttl", 16)]),
        ("7", fdt),
        ("8", addr),
        ("9,10,11", npdu())],
        octets("bacnetip.body", "bacnetip.octet"))
    return text(L)


BACNET_KEYS = [
    ("int", "function", "BVLC function: 0 result, 1 write BDT, 2 read BDT, 3 read BDT ack, 4 forwarded NPDU, 5 register foreign device, 6 read FDT, 7 read FDT ack, 8 delete FDT entry, 9 distribute broadcast to network, 10 original unicast NPDU, 11 original broadcast NPDU, 12 secure BVLL"),
    ("int", "result_code", "BVLC result: 0 successful completion, 0x10, 0x20, 0x30, 0x40, 0x50, 0x60 the NAK of functions 1, 2, 5, 6, 8, 9"),
    ("list", "bdt_entries", "broadcast distribution table entries"),
    ("int", "bdt_address", "BDT entry: the BBMD's IPv4 address, as an unsigned 32-bit integer"), ("int", "bdt_port", "BDT entry: its UDP port"),
    ("int", "bdt_mask", "BDT entry: the broadcast distribution mask, as an unsigned 32-bit integer"),
    ("list", "fdt_entries", "foreign device table entries"),
    ("int", "fdt_address", "FDT entry: the registrant's IPv4 address"), ("int", "fdt_port", "FDT entry: its UDP port"),
    ("int", "fdt_ttl", "FDT entry: the time to live given at registration, seconds"), ("int", "fdt_remaining", "FDT entry: seconds remaining"),
    ("int", "ip_address", "forwarded NPDU: the original source IPv4 address; delete FDT entry: the entry's address"),
    ("int", "udp_port", "forwarded NPDU, delete FDT entry: the UDP port with that address"),
    ("int", "ttl", "register foreign device: time to live, seconds"),
    ("int", "npdu_version", "NPDU protocol version"),
    ("int", "network_message", "NPDU control bit 7: a network layer message (message type present) rather than an APDU"),
    ("int", "control_reserved6", "NPDU control bit 6, reserved, 0"),
    ("int", "destination_present", "NPDU control bit 5: DNET, DLEN, DADR and the hop count present"),
    ("int", "control_reserved4", "NPDU control bit 4, reserved, 0"),
    ("int", "source_present", "NPDU control bit 3: SNET, SLEN and SADR present"),
    ("int", "expecting_reply", "NPDU control bit 2: a confirmed request, a segment of a complex ACK or a network message expecting a reply"),
    ("int", "priority", "NPDU control bits 1-0: 0 normal, 1 urgent, 2 critical equipment, 3 life safety"),
    ("int", "dnet", "destination network number"), ("list", "dadr", "destination MAC address, as octets (empty: broadcast)"),
    ("int", "snet", "source network number"), ("list", "sadr", "source MAC address, as octets"),
    ("int", "hop_count", "hop count (with a destination)"),
    ("int", "network_message_type", "network layer message type"), ("int", "vendor_id", "vendor ID (message types 0x80 and above)"),
    ("list", "payload", "the APDU, or the network layer message's data, as octets"),
    ("list", "body", "the body of another function (secure BVLL), as octets"), ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- EtherNet/IP

E = "enip"


def cpf():
    o = "enip.octet"
    items = sw("enip.item_type", [
        ("161", [F("enip.connection_id", 32)]),
        ("32770", [F("enip.connection_id", 32), F("enip.sequence_number", 32)]),
        ("32768,32769", [F("enip.sin_family", 16, swap=True), F("enip.sin_port", 16, swap=True), F("enip.sin_addr", 32, swap=True),
                         F("enip.sin_zero", 64, "hex")])],
        octets("enip.item_data", o))
    return (["count  item_count  16", "group  enip.items  count  @item_count"] +
            ind(1, [F("enip.item_type", 16), "length  16  bytes"] + ind(1, items) + ["end"]) + ["end"])


def enip_pack():
    L = head("enip-encapsulation", ["EtherNet/IP encapsulation message: the 24-octet header (little-endian) and, for RegisterSession, SendRRData",
                                    "and SendUnitData, the command data with the common packet format items. Written by",
                                    "tools/gen/indauto2-pack.py; do not edit by hand."], "enip", [E], order="lsb")
    # The length counts the command data after the 24-octet header; the 20 header octets after the length
    # field are inside the block here, so the length written is the block's size minus 20.
    body = ([F("enip.session_handle", 32), F("enip.status", 32), F("enip.sender_context", 64, "hex"), F("enip.options", 32)] +
            sw("enip.command", [
                ("101", [F("enip.protocol_version", 16), F("enip.option_flags", 16)]),
                ("111,112", [F("enip.interface_handle", 32), F("enip.timeout", 16)] + cpf())],
               octets("enip.command_data", "enip.octet")))
    L += [F("enip.command", 16), "length  16  bytes  plus  -20"] + ind(1, body) + ["end"]
    return text(L)


ENIP_KEYS = [
    ("int", "command", "encapsulation command: 0 NOP, 4 ListServices, 0x63 ListIdentity, 0x64 ListInterfaces, 0x65 RegisterSession, 0x66 UnRegisterSession, 0x6F SendRRData, 0x70 SendUnitData, 0xC8 StartDTLS"),
    ("int", "session_handle", "session handle"), ("int", "status", "status (0 success)"),
    ("string", "sender_context", "sender context, 8 octets as hexadecimal digits (under the little-endian bit order, each octet's low digit first)"),
    ("int", "options", "options, as sent"),
    ("int", "protocol_version", "RegisterSession: protocol version"), ("int", "option_flags", "RegisterSession: option flags"),
    ("int", "interface_handle", "SendRRData, SendUnitData: interface handle"),
    ("int", "timeout", "SendRRData, SendUnitData: timeout"),
    ("list", "items", "common packet format items (their count is written from the list)"),
    ("int", "item_type", "item type: 0 null address, 0x0C CIP identity, 0xA1 connected address, 0xB1 connected data, 0xB2 unconnected data, 0x100 list services response, 0x8000 and 0x8001 socket address info O->T and T->O, 0x8002 sequenced address"),
    ("int", "connection_id", "connected or sequenced address item: connection identifier"),
    ("int", "sequence_number", "sequenced address item: sequence number"),
    ("int", "sin_family", "socket address item: sin_family (big-endian on the wire)"), ("int", "sin_port", "socket address item: sin_port (big-endian)"),
    ("int", "sin_addr", "socket address item: sin_addr, an IPv4 address as an unsigned 32-bit integer (big-endian)"),
    ("string", "sin_zero", "socket address item: sin_zero, 8 octets as hexadecimal digits"),
    ("list", "item_data", "another item's data (CIP messages, connected data, identity), as octets"),
    ("list", "command_data", "another command's data, as octets"), ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- HART-IP

H = "hartip"


def pass_through():
    o = "hartip.octet"
    return ([F("hartip.address_type", 1), "count  expansion_count  2", F("hartip.physical_layer_type", 2), F("hartip.frame_type", 3)] +
            sw("hartip.address_type", [("0", [F("hartip.short_reserved", 2), F("hartip.short_address", 6)]),
                                       ("1", [F("hartip.long_address", 40, "hex")])]) +
            ["group  hartip.expansion  count  @expansion_count", "  " + F(o, 8), "end", F("hartip.command", 8), F("hartip.byte_count", 8)] +
            sw("hartip.frame_type", [("1,6", [F("hartip.response_code", 8), F("hartip.device_status", 8)])], []) +
            octets("hartip.data", o))


def hartip_pack():
    L = head("hart-ip-message", ["HART-IP message: the 8-octet header with the whole-message length, and the body by message type and ID.",
                                 "Written by tools/gen/indauto2-pack.py; do not edit by hand."], "hartip", [H])
    L += [F("hartip.version", 8), F("hartip.message_type", 8), F("hartip.message_id", 8), F("hartip.status", 8),
          F("hartip.sequence_number", 16), "length  16  whole"]
    L += sw("hartip.message_type", [
        ("3,15", [F("hartip.error_code", 8)] + octets("hartip.body", "hartip.octet"))],
        sw("hartip.message_id", [
            ("0", [F("hartip.master_type", 8), F("hartip.inactivity_close_timer", 32)]),
            ("3", pass_through())],
            octets("hartip.body", "hartip.octet")))
    return text(L)


HARTIP_KEYS = [
    ("int", "version", "HART-IP version"), ("int", "message_type", "message type: 0 request, 1 response, 2 publish, 3 error, 15 NAK"),
    ("int", "message_id", "message ID: 0 session initiate, 1 session close, 2 keep alive, 3 pass through"),
    ("int", "status", "status"), ("int", "sequence_number", "sequence number (transaction ID)"),
    ("int", "error_code", "error or NAK: the error code (0 session closed, 1 primary session unavailable, 2 service unavailable)"),
    ("int", "master_type", "session initiate: master type, 0 secondary, 1 primary"),
    ("int", "inactivity_close_timer", "session initiate: inactivity close timer"),
    ("int", "address_type", "pass-through delimiter bit 7: 0 short (polling) address, 1 long (unique) address"),
    ("int", "physical_layer_type", "pass-through delimiter bits 4-3: physical layer type"),
    ("int", "frame_type", "pass-through delimiter bits 2-0: frame type (1 and 6 are responses)"),
    ("int", "short_reserved", "short address: the two high bits"), ("int", "short_address", "short address: the polling address"),
    ("string", "long_address", "long address: 5 octets as hexadecimal digits"),
    ("list", "expansion", "pass-through expansion octets (their count is in delimiter bits 6-5)"),
    ("int", "command", "pass-through: HART command number"), ("int", "byte_count", "pass-through: byte count, as sent"),
    ("int", "response_code", "pass-through response: response code"), ("int", "device_status", "pass-through response: device status"),
    ("list", "data", "pass-through: the command data and, as the last octet, the checksum"),
    ("list", "body", "another body, or an error body beyond the code, as octets"), ("int", "octet", "one octet"),
]


def build(out):
    out.write("packs/bacnet-ip-bvlc/pack.def", bacnet_pack())
    out.write("packs/enip-encapsulation/pack.def", enip_pack())
    out.write("packs/hart-ip-message/pack.def", hartip_pack())
    for m, h, src, keys in (("bacnetip", "BACnet/IP BVLC and NPDU header fields", "bacnet", BACNET_KEYS),
                            ("enip", "EtherNet/IP encapsulation and common packet format fields", "enip", ENIP_KEYS),
                            ("hartip", "HART-IP header and body fields", "hartip", HARTIP_KEYS)):
        out.write("model/%s.def" % m, module(m, ["# The %s module: %s. Written by tools/gen/indauto2-pack.py." % (m, h)], src, keys))
    return {"indauto2": 6}


def main(argv=None):
    return genio.vector_main("indauto2-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
