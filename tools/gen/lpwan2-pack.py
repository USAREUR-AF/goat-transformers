#!/usr/bin/env python3
"""Write the LoRaWAN packs and their modules:

- lorawan-phypayload: a LoRaWAN PHYPayload: MHDR (MType, RFU, Major) and by MType the join
  request (JoinEUI, DevEUI, DevNonce, MIC), the join accept (encrypted, as octets), the data frames
  (FHDR: DevAddr, FCtrl with the FOpts length, FCnt, FOpts; then FPort, FRMPayload and MIC as
  octets), the rejoin requests (type 0/2 and type 1, with their MIC), proprietary frames as octets.
  Layouts restated from brocaar/lorawan (phypayload.go, fhdr.go, macpayload.go, payload.go,
  netid.go).
- semtech-udp-forwarder: the Semtech UDP packet forwarder protocol (PUSH_DATA, PUSH_ACK, PULL_DATA,
  PULL_ACK, PULL_RESP, TX_ACK): version, token, identifier, gateway identifier, and the JSON object
  as octets. Layout restated from Lora-net/packet_forwarder PROTOCOL.TXT.

The vectors are not written here: tools/gen/lpwan2-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/lpwan2-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

BL = "4bb09b3bdacba097680894e8d35dbcbc0d260c7e"
PF = "d0226eae6e7b6bbaec6117d0d2372bf17819c438"
SRC = {
    "lw": ('source        "brocaar/lorawan, https://github.com/brocaar/lorawan at commit %s, phypayload.go, fhdr.go, macpayload.go, '
           'payload.go, netid.go (MIT License, Copyright (c) 2019 Orne Brocaar); layouts restated, no code copied; the LoRaWAN '
           'specification not used"' % BL),
    "pf": ('source        "Lora-net/packet_forwarder, https://github.com/Lora-net/packet_forwarder at commit %s, PROTOCOL.TXT '
           '(Copyright (C) 2013 Semtech S.A., the repository licence, BSD-3-Clause terms); layout restated, no text copied"' % PF),
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


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for t, k, d in keys:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


def lorawan_pack():
    o = "lorawan.octet"
    mic = [F("lorawan.mic", 32, "hex")]
    data = ([F("lorawan.dev_addr", 32, swap=True), F("lorawan.fctrl_adr", 1), F("lorawan.fctrl_adr_ack_req", 1), F("lorawan.fctrl_ack", 1),
             F("lorawan.fctrl_fpending_class_b", 1), "count  fopts_len  4", F("lorawan.fcnt", 16, swap=True),
             "group  lorawan.fopts  count  @fopts_len", "  " + F(o, 8), "end"] + octets("lorawan.port_payload_mic", o))
    rejoin = [F("lorawan.rejoin_type", 8)] + sw("lorawan.rejoin_type", [
        ("0,2", [F("lorawan.net_id", 24, swap=True), F("lorawan.dev_eui", 64, "hex"), F("lorawan.rj_count", 16, swap=True)] + mic),
        ("1", [F("lorawan.join_eui", 64, "hex"), F("lorawan.dev_eui", 64, "hex"), F("lorawan.rj_count", 16, swap=True)] + mic)],
        octets("lorawan.payload", o))
    L = head("lorawan-phypayload", ["LoRaWAN PHYPayload: MHDR and, by message type, the join request, join accept, data frame header, rejoin",
                                    "request or proprietary payload. Written by tools/gen/lpwan2-pack.py; do not edit by hand."], "lw", ["lorawan"])
    L += [F("lorawan.mtype", 3), F("lorawan.rfu", 3), F("lorawan.major", 2)]
    L += sw("lorawan.mtype", [
        ("0", [F("lorawan.join_eui", 64, "hex"), F("lorawan.dev_eui", 64, "hex"), F("lorawan.dev_nonce", 16, swap=True)] + mic),
        ("2,3,4,5", data),
        ("6", rejoin)],
        octets("lorawan.payload", o))
    return "\n".join(L) + "\n"


LORAWAN_KEYS = [
    ("int", "mtype", "MHDR message type: 0 join request, 1 join accept, 2 unconfirmed data up, 3 unconfirmed data down, 4 confirmed data up, 5 confirmed data down, 6 rejoin request, 7 proprietary"),
    ("int", "rfu", "MHDR: the three reserved bits"), ("int", "major", "MHDR: major version (0 LoRaWAN R1)"),
    ("string", "join_eui", "JoinEUI (AppEUI): the 8 octets as sent (low octet first), as hexadecimal digits"),
    ("string", "dev_eui", "DevEUI: the 8 octets as sent (low octet first), as hexadecimal digits"),
    ("int", "dev_nonce", "join request: DevNonce"),
    ("string", "mic", "message integrity code, the 4 octets as sent, as hexadecimal digits (not computed)"),
    ("int", "dev_addr", "data frame: DevAddr, the 32-bit value (sent low octet first)"),
    ("int", "fctrl_adr", "FCtrl bit 7: ADR"), ("int", "fctrl_adr_ack_req", "FCtrl bit 6: ADRACKReq in an uplink (reserved in a downlink)"),
    ("int", "fctrl_ack", "FCtrl bit 5: ACK"), ("int", "fctrl_fpending_class_b", "FCtrl bit 4: FPending in a downlink, ClassB in an uplink"),
    ("int", "fcnt", "data frame: FCnt, the low 16 bits of the frame counter"),
    ("list", "fopts", "data frame: FOpts, the MAC commands in the header (their count is FCtrl's FOptsLen), as octets"),
    ("list", "port_payload_mic", "data frame: FPort (when present), FRMPayload and the 4-octet MIC, as octets"),
    ("int", "rejoin_type", "rejoin request: type 0, 1 or 2"), ("int", "net_id", "rejoin request type 0/2: NetID (24 bits, sent low octet first)"),
    ("int", "rj_count", "rejoin request: RJcount0 (types 0, 2) or RJcount1 (type 1)"),
    ("list", "payload", "join accept (encrypted, MIC included), proprietary or other payload, as octets"),
    ("int", "octet", "one octet"),
]


def forwarder_pack():
    o = "semtechudp.octet"
    L = head("semtech-udp-forwarder", ["Semtech UDP packet forwarder datagram: version, token, identifier, gateway identifier and the JSON object.",
                                       "Written by tools/gen/lpwan2-pack.py; do not edit by hand."], "pf", ["semtechudp"])
    L += [F("semtechudp.protocol_version", 8), F("semtechudp.token", 16), F("semtechudp.identifier", 8)]
    L += sw("semtechudp.identifier", [
        ("0,5", [F("semtechudp.gateway_eui", 64, "hex")] + octets("semtechudp.json", o)),
        ("2", [F("semtechudp.gateway_eui", 64, "hex")]),
        ("3", octets("semtechudp.json", o)),
        ("1,4", [])],
        octets("semtechudp.json", o))
    return "\n".join(L) + "\n"


FWD_KEYS = [
    ("int", "protocol_version", "protocol version (2)"), ("int", "token", "random token, repeated in the acknowledgement"),
    ("int", "identifier", "packet type: 0 PUSH_DATA, 1 PUSH_ACK, 2 PULL_DATA, 3 PULL_RESP, 4 PULL_ACK, 5 TX_ACK"),
    ("string", "gateway_eui", "gateway unique identifier (MAC address), the 8 octets as hexadecimal digits"),
    ("list", "json", "the JSON object (rxpk and stat for PUSH_DATA, txpk for PULL_RESP, txpk_ack for TX_ACK), its UTF-8 octets"),
    ("int", "octet", "one octet"),
]


def build(out):
    out.write("packs/lorawan-phypayload/pack.def", lorawan_pack())
    out.write("packs/semtech-udp-forwarder/pack.def", forwarder_pack())
    out.write("model/lorawan.def", module("lorawan", ["# The lorawan module: LoRaWAN PHYPayload fields. Written by tools/gen/lpwan2-pack.py."], "lw", LORAWAN_KEYS))
    out.write("model/semtechudp.def", module("semtechudp", ["# The semtechudp module: Semtech UDP packet forwarder fields. Written by tools/gen/lpwan2-pack.py."], "pf", FWD_KEYS))
    return {"lpwan2": 4}


def main(argv=None):
    return genio.vector_main("lpwan2-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
