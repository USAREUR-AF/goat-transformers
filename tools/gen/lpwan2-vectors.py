#!/usr/bin/env python3
"""lpwan2-vectors: write the vectors of lorawan-phypayload and semtech-udp-forwarder.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of:
- brocaar/lorawan: MHDR is MType in the top three bits and Major in the low two; the MIC is the
  last four octets; a join request is JoinEUI (8), DevEUI (8), DevNonce (2); a data frame's FHDR is
  DevAddr (4), FCtrl (ADR 0x80, ADRACKReq 0x40, ACK 0x20, FPending/ClassB 0x10, FOptsLen in the low
  four bits), FCnt (2), FOpts (FOptsLen octets), then FPort and FRMPayload; a rejoin request of type
  0 or 2 is the type, NetID (3), DevEUI, RJcount0 (2), of type 1 the type, JoinEUI, DevEUI, RJcount1;
  EUIs, DevAddr, NetID and the counters are sent low octet first;
- Lora-net/packet_forwarder PROTOCOL.TXT: version 2, a 2-octet token, the identifier (0 PUSH_DATA,
  1 PUSH_ACK, 2 PULL_DATA, 3 PULL_RESP, 4 PULL_ACK, 5 TX_ACK), the 8-octet gateway identifier in
  PUSH_DATA, PULL_DATA and TX_ACK, then the JSON object in PUSH_DATA, PULL_RESP and (optionally)
  TX_ACK.

Inputs: frames built here field by field from values chosen here; no frame is taken from a document
or a capture. MICs and encrypted payloads are arbitrary octets (the pack does not compute or decrypt
them). `expect` of a round trip is the input. `model` holds values that were packed.

Usage: python3 -I tools/gen/lpwan2-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/lpwan2-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_L = "brocaar/lorawan phypayload.go, fhdr.go, payload.go"
R_P = "Lora-net/packet_forwarder PROTOCOL.TXT"


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


def le(v, n):
    return v.to_bytes(n, "little")


def mhdr(mtype, major=0, rfu=0):
    return bytes([(mtype << 5) | (rfu << 2) | major])


JOIN_EUI = bytes.fromhex("0807060504030201")   # 0102030405060708 sent low octet first
DEV_EUI = bytes.fromhex("1817161514131211")
MIC = bytes.fromhex("a1b2c3d4")


def data_frame(mtype, devaddr, adr, adrack, ack, fpend, fcnt, fopts=b"", rest=b""):
    fctrl = (adr << 7) | (adrack << 6) | (ack << 5) | (fpend << 4) | len(fopts)
    return mhdr(mtype) + le(devaddr, 4) + bytes([fctrl]) + le(fcnt, 2) + fopts + rest + MIC


def lorawan_vectors():
    P = "lorawan-phypayload"
    out = []
    a = mhdr(0) + JOIN_EUI + DEV_EUI + le(0x1234, 2) + MIC
    out.append(("01-join-request-roundtrip.json", vec(P, "join-request-roundtrip", a,
                {"lorawan.mtype": "0", "lorawan.major": "0", "lorawan.join_eui": JOIN_EUI.hex(), "lorawan.dev_eui": DEV_EUI.hex(),
                 "lorawan.dev_nonce": str(0x1234), "lorawan.mic": MIC.hex()},
                ref=R_L, note="a join request")))
    b = mhdr(1) + bytes(range(0x40, 0x50))
    out.append(("02-join-accept-encrypted-roundtrip.json", vec(P, "join-accept-encrypted-roundtrip", b,
                {"lorawan.mtype": "1", "lorawan.payload.#": "16"},
                ref=R_L, note="a join accept: 16 encrypted octets (the 12 fields and the MIC), kept as octets")))
    c = data_frame(2, 0x26011BDA, 1, 0, 0, 0, 7, rest=bytes([0x0A]) + bytes.fromhex("1c2d3e"))
    out.append(("03-unconfirmed-uplink-roundtrip.json", vec(P, "unconfirmed-uplink-roundtrip", c,
                {"lorawan.mtype": "2", "lorawan.dev_addr": str(0x26011BDA), "lorawan.fctrl_adr": "1", "lorawan.fcnt": "7",
                 "lorawan.fopts.#": "0", "lorawan.port_payload_mic.#": "8"},
                ref=R_L, note="ADR set, FCnt 7, FPort 10, three payload octets and the MIC")))
    d = data_frame(5, 0x26011BDA, 0, 0, 1, 1, 3, fopts=bytes([0x03, 0x51, 0x07, 0x00, 0x01]), rest=b"")
    out.append(("04-confirmed-downlink-with-fopts-roundtrip.json", vec(P, "confirmed-downlink-with-fopts-roundtrip", d,
                {"lorawan.mtype": "5", "lorawan.fctrl_ack": "1", "lorawan.fctrl_fpending_class_b": "1", "lorawan.fopts.#": "5",
                 "lorawan.port_payload_mic.#": "4"},
                ref=R_L, note="a confirmed downlink with ACK and FPending, a LinkADRReq in FOpts, no FPort, the MIC alone after the header")))
    e = mhdr(6) + bytes([0]) + le(0x000013, 3) + DEV_EUI + le(5, 2) + MIC
    out.append(("05-rejoin-type-0-roundtrip.json", vec(P, "rejoin-type-0-roundtrip", e,
                {"lorawan.mtype": "6", "lorawan.rejoin_type": "0", "lorawan.net_id": str(0x13), "lorawan.rj_count": "5"},
                ref=R_L + " and netid.go", note="a rejoin request of type 0")))
    f = mhdr(6) + bytes([1]) + JOIN_EUI + DEV_EUI + le(2, 2) + MIC
    out.append(("06-rejoin-type-1-roundtrip.json", vec(P, "rejoin-type-1-roundtrip", f,
                {"lorawan.rejoin_type": "1", "lorawan.join_eui": JOIN_EUI.hex(), "lorawan.rj_count": "2"},
                ref=R_L, note="a rejoin request of type 1")))
    g = mhdr(7) + bytes([0xDE, 0xAD, 0xBE, 0xEF])
    out.append(("07-proprietary-as-octets-roundtrip.json", vec(P, "proprietary-as-octets-roundtrip", g,
                {"lorawan.mtype": "7", "lorawan.payload.#": "4"}, ref=R_L, note="a proprietary frame")))
    out.append(("08-cut-fhdr-is-malformed.json", vec(P, "cut-fhdr-is-malformed", c[:6], error="malformed-wire",
                ref=R_L, note="the frame stops inside FCtrl and FCnt")))
    return P, out


def fwd(ident, token, gw=None, payload=b""):
    out = bytes([2]) + struct.pack(">H", token) + bytes([ident])
    if gw is not None:
        out += gw
    return out + payload


GW = bytes.fromhex("aa555a0000000101")


def forwarder_vectors():
    P = "semtech-udp-forwarder"
    out = []
    js = b'{"stat":{"rxnb":2,"rxok":2}}'
    a = fwd(0, 0x1F2E, GW, js)
    out.append(("01-push-data-roundtrip.json", vec(P, "push-data-roundtrip", a,
                {"semtechudp.protocol_version": "2", "semtechudp.token": str(0x1F2E), "semtechudp.identifier": "0",
                 "semtechudp.gateway_eui": GW.hex(), "semtechudp.json.#": str(len(js))},
                ref=R_P, note="PUSH_DATA with a stat object")))
    out.append(("02-push-ack-roundtrip.json", vec(P, "push-ack-roundtrip", fwd(1, 0x1F2E), {"semtechudp.identifier": "1"}, ref=R_P)))
    out.append(("03-pull-data-roundtrip.json", vec(P, "pull-data-roundtrip", fwd(2, 0x0042, GW),
                {"semtechudp.identifier": "2", "semtechudp.gateway_eui": GW.hex()}, ref=R_P)))
    js2 = b'{"txpk":{"imme":true,"freq":869.525,"powe":14,"size":0,"data":""}}'
    out.append(("04-pull-resp-roundtrip.json", vec(P, "pull-resp-roundtrip", fwd(3, 0x0043, None, js2),
                {"semtechudp.identifier": "3", "semtechudp.json.#": str(len(js2))}, ref=R_P, note="PULL_RESP with a txpk object")))
    out.append(("05-pull-ack-roundtrip.json", vec(P, "pull-ack-roundtrip", fwd(4, 0x0042), {"semtechudp.identifier": "4"}, ref=R_P)))
    out.append(("06-tx-ack-without-json-roundtrip.json", vec(P, "tx-ack-without-json-roundtrip", fwd(5, 0x0043, GW),
                {"semtechudp.identifier": "5", "semtechudp.json.#": "0"}, ref=R_P, note="TX_ACK with no JSON: no error")))
    out.append(("07-cut-gateway-id-is-malformed.json", vec(P, "cut-gateway-id-is-malformed", fwd(2, 0x0042, GW[:5]),
                error="malformed-wire", ref=R_P, note="PULL_DATA with five of the eight gateway identifier octets")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (lorawan_vectors(), forwarder_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("lpwan2-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
