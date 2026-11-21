#!/usr/bin/env python3
"""Write the vectors of the eddystone, altbeacon, remote-id-ble and wifi-beacon packs.

Every payload is built here from values written for these vectors (no example of a source is
used), with an encoder of its own: AD structures (a length octet counting the AD type and the
data, the AD type, the data; 16-bit UUIDs and company identifiers little-endian) as
google/eddystone and opendroneid/transmitter-linux write them, the Eddystone and AltBeacon
fields as their specifications list them (big-endian), and the Wi-Fi beacon body (little-endian
fixed fields, then elements of ID, length and value) as google/gopacket and opendroneid-core-c
write it. The decoded values are stated from the same inputs; a round trip expects the input,
which every payload is written to be in the packs' canonical form (spec/engine-spec.md 0.8,
0.20 and 0.21). It reads no pack.def and calls no goat-transformers engine.

Usage: python3 -I tools/gen/beacons-vectors.py [--out DIR] [--check]
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/beacons-vectors.py from payloads written for it and spec/engine-spec.md; no engine run"
REF_EDDY = "google/eddystone protocol-specification.md and the frame documents (UID, URL, TLM, EID)"
REF_ALT = "AltBeacon Protocol Specification v1.0 (altbeacon/spec)"
REF_RID = "opendroneid/transmitter-linux bluetooth.c: the ASTM Remote ID service data of Bluetooth 4 and 5 advertising"
REF_WIFI = "google/gopacket layers/dot11.go (beacon body, information element); opendroneid-core-c wifi.c (Remote ID vendor element)"


def vec(name, frm, inp, expect=None, model=None, error=None, ref="", note=None):
    v = {"name": name, "from": frm, "to": frm, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = {k: str(x) for k, x in model.items()}
    v["source"] = SOURCE
    v["reference"] = ref + ("; " + note if note else "")
    return v


def ad(ad_type, data):
    return bytes([len(data) + 1, ad_type]) + data


FLAGS = ad(0x01, b"\x06")


def le16(v):
    return struct.pack("<H", v)


def be(v, n):
    return v.to_bytes(n, "big")


def s64(v):
    return v - (1 << 64) if v >> 63 else v


def hx(b):
    return b.hex()


P = "ble.ad_structures"


def eddy_payload(frame):
    return FLAGS + ad(0x03, le16(0xFEAA)) + ad(0x16, le16(0xFEAA) + frame)


def eddystone_vectors():
    V = {}
    F = "eddystone"
    ns = bytes.fromhex("8b0ca750e7a74e14bd99")
    inst = bytes.fromhex("0000000a0b0c")
    frame = bytes([0x00, 0xEC]) + ns + inst + b"\x00\x00"
    x = eddy_payload(frame)
    V["01-uid-roundtrip"] = vec("uid-roundtrip", F, hx(x), hx(x), {
        P + ".#": 3, P + "[0].ble.flags": 6, P + "[1].ble.service_uuids16[0].ble.service_uuid16": 0xFEAA,
        P + "[2].ble.service_data_uuid16": 0xFEAA, P + "[2].eddystone.frame_type": 0, P + "[2].eddystone.tx_power_0m": -20,
        P + "[2].eddystone.namespace_high": int.from_bytes(ns[:2], "big"), P + "[2].eddystone.namespace_low": s64(int.from_bytes(ns[2:], "big")),
        P + "[2].eddystone.instance": int.from_bytes(inst, "big"), P + "[2].eddystone.uid_rfu": 0},
        ref=REF_EDDY, note="Flags, the UUID list with 0xFEAA, and a UID frame with its two reserved octets (service data length 0x17)")
    frame = bytes([0x10, 0xEE, 0x03]) + b"example" + bytes([0x07])
    x = eddy_payload(frame)
    V["03-url-roundtrip"] = vec("url-roundtrip", F, hx(x), hx(x), {
        P + "[2].eddystone.frame_type": 0x10, P + "[2].eddystone.tx_power_0m": -18, P + "[2].eddystone.url_scheme": 3,
        P + "[2].eddystone.url_octets.#": 8, P + "[2].eddystone.url_octets[7].eddystone.url_octet": 7},
        ref=REF_EDDY, note="https:// then example and the code 0x07 (.com): the encoded URL is kept as its octets")
    frame = bytes([0x20, 0x00]) + be(3000, 2) + be(0x1880, 2) + be(1000, 4) + be(36000, 4)
    x = eddy_payload(frame)
    V["04-tlm-roundtrip"] = vec("tlm-roundtrip", F, hx(x), hx(x), {
        P + "[2].eddystone.tlm_version": 0, P + "[2].eddystone.battery_voltage": 3000,
        P + "[2].eddystone.temperature": "24.5", P + "[2].eddystone.adv_count": 1000, P + "[2].eddystone.sec_count": 36000},
        ref=REF_EDDY, note="plain TLM: 3000 mV, 24.5 degrees C (0x1880 in 8.8 fixed point), 1000 PDUs, an hour in tenths of a second")
    frame = bytes([0x20, 0x00]) + be(2950, 2) + be(0x8000, 2) + be(5, 4) + be(50, 4)
    x = eddy_payload(frame)
    V["05-tlm-temperature-not-supported-roundtrip"] = vec("tlm-temperature-not-supported-roundtrip", F, hx(x), hx(x), {
        P + "[2].eddystone.battery_voltage": 2950}, ref=REF_EDDY,
        note="0x8000 means the beacon has no temperature: the key is absent (absent 32768), and the value is written back")
    frame = bytes([0x20, 0x01]) + bytes(range(1, 13)) + be(0xABCD, 2) + be(0x1234, 2)
    x = eddy_payload(frame)
    V["06-tlm-encrypted-roundtrip"] = vec("tlm-encrypted-roundtrip", F, hx(x), hx(x), {
        P + "[2].eddystone.tlm_version": 1, P + "[2].eddystone.etlm_high": int.from_bytes(bytes(range(1, 9)), "big"),
        P + "[2].eddystone.etlm_low": int.from_bytes(bytes(range(9, 13)), "big"), P + "[2].eddystone.salt": 0xABCD,
        P + "[2].eddystone.mic": 0x1234}, ref=REF_EDDY, note="encrypted TLM: 12 octets of encrypted data, salt and check")
    frame = bytes([0x30, 0xE2]) + bytes.fromhex("1122334455667788")
    x = eddy_payload(frame)
    V["07-eid-roundtrip"] = vec("eid-roundtrip", F, hx(x), hx(x), {
        P + "[2].eddystone.frame_type": 0x30, P + "[2].eddystone.tx_power_0m": -30,
        P + "[2].eddystone.eid": 0x1122334455667788}, ref=REF_EDDY, note="an ephemeral identifier of 8 octets")
    x = FLAGS + bytes([0x09, 0x16]) + le16(0xFEAA) + b"\x00\xEC"
    V["08-structure-longer-than-the-payload"] = vec("structure-longer-than-the-payload", F, hx(x), error="malformed-wire",
        ref=REF_EDDY, note="the last structure states 9 octets and 4 follow")
    return V


def altbeacon_vectors():
    V = {}
    F = "altbeacon"
    bid = bytes.fromhex("2f234454cf6d4a0fadf2f4911ba9ffa600010002")
    mfg = le16(0x0118) + be(0xBEAC, 2) + bid + bytes([0xC5, 0x00])
    x = FLAGS + ad(0xFF, mfg)
    V["01-altbeacon-roundtrip"] = vec("altbeacon-roundtrip", F, hx(x), hx(x), {
        P + ".#": 2, P + "[1].ble.ad_type": 255, P + "[1].ble.company_id": 0x0118, P + "[1].altbeacon.beacon_code": 0xBEAC,
        P + "[1].altbeacon.beacon_id_1": s64(int.from_bytes(bid[:8], "big")),
        P + "[1].altbeacon.beacon_id_2": s64(int.from_bytes(bid[8:16], "big")),
        P + "[1].altbeacon.beacon_id_3": int.from_bytes(bid[16:], "big"),
        P + "[1].altbeacon.reference_rssi": -59, P + "[1].altbeacon.mfg_reserved": 0},
        ref=REF_ALT, note="Flags and the AltBeacon advertisement: company 0x0118 (little-endian), 0xBEAC, a 20-octet beacon ID, "
                          "-59 dBm at 1 m")
    other = le16(0x0059) + bytes([0x01, 0x02, 0x03])
    x = FLAGS + ad(0xFF, other)
    V["02-other-manufacturer-data-roundtrip"] = vec("other-manufacturer-data-roundtrip", F, hx(x), hx(x), {
        P + "[1].ble.company_id": 0x0059, P + "[1].altbeacon.beacon_code": 0x0102,
        P + "[1].ble.manufacturer_data.#": 1}, ref=REF_ALT,
        note="manufacturer data that is not an AltBeacon: its first two octets are read as the beacon code, which is "
             "not 0xBEAC, and the rest is kept as octets")
    return V


def basic_id_message():
    """A Remote ID Basic ID message (25 octets): type 0, protocol version 2; ID type 1 (serial),
    UA type 2 (helicopter or multirotor); a 20-character ID; three reserved octets."""
    return bytes([0x02, 0x12]) + b"1581F4ABCD1234567890" + b"\x00\x00\x00"


def rid_vectors():
    V = {}
    F = "remote-id-ble"
    msg = basic_id_message()
    x = ad(0x16, le16(0xFFFA) + bytes([0x0D, 0x05]) + msg)
    V["01-bluetooth-4-message-roundtrip"] = vec("bluetooth-4-message-roundtrip", F, hx(x), hx(x), {
        P + ".#": 1, P + "[0].ble.service_data_uuid16": 0xFFFA, P + "[0].ridble.application_code": 13,
        P + "[0].ridble.message_counter": 5, P + "[0].ridble.message.#": 25,
        P + "[0].ridble.message[0].ridble.message_octet": 2}, ref=REF_RID,
        note="Bluetooth 4 legacy advertising: one structure of 30 octets, a Basic ID message after the counter")
    pack = bytes([0xF2, 25, 2]) + msg + bytes([0x52]) + bytes(24)
    x = ad(0x16, le16(0xFFFA) + bytes([0x0D, 0xFE]) + pack)
    V["02-bluetooth-5-message-pack-roundtrip"] = vec("bluetooth-5-message-pack-roundtrip", F, hx(x), hx(x), {
        P + "[0].ridble.message_counter": 254, P + "[0].ridble.message.#": 53,
        P + "[0].ridble.message[0].ridble.message_octet": 0xF2}, ref=REF_RID,
        note="Bluetooth 5 extended advertising: the message pack (type 0xF, size 25, two messages) after the counter")
    x = FLAGS + ad(0x16, le16(0xFFFA) + bytes([0x0E, 0x01, 0x02]))
    V["03-other-application-code-roundtrip"] = vec("other-application-code-roundtrip", F, hx(x), hx(x), {
        P + "[1].ridble.application_code": 14, P + "[1].ble.service_data.#": 2}, ref=REF_RID,
        note="an application code other than 0x0D: the rest of the service data is kept as octets")
    return V


def element(eid, data):
    return bytes([eid, len(data)]) + data


def wifi_vectors():
    V = {}
    F = "wifi-beacon"
    fixed = struct.pack("<QHH", 0x0000000123456789, 100, 0x0421)
    pack = bytes([0xF2, 25, 1]) + basic_id_message()
    body = fixed + element(0, b"UAS-1") + element(1, bytes([0x8C])) + element(3, bytes([6])) + \
        element(221, be(0xFA0BBC, 3) + bytes([0x0D, 0x07]) + pack)
    V["01-remote-id-beacon-roundtrip"] = vec("remote-id-beacon-roundtrip", F, hx(body), hx(body), {
        "wifi.timestamp": 0x0000000123456789, "wifi.beacon_interval": 100, "wifi.capability": 0x0421,
        "wifi.elements.#": 4, "wifi.elements[0].wifi.ssid.#": 5, "wifi.elements[1].wifi.rates[0].wifi.rate": 0x8C,
        "wifi.elements[2].wifi.channel": 6, "wifi.elements[3].wifi.oui": 0xFA0BBC, "wifi.elements[3].wifi.oui_type": 13,
        "wifi.elements[3].wifi.rid_message_counter": 7, "wifi.elements[3].wifi.rid_message_pack.#": 28},
        ref=REF_WIFI, note="a Remote ID beacon body: SSID, one rate, the channel, and the ASTM vendor element holding a message "
                           "counter and a message pack of one Basic ID message")
    body = struct.pack("<QHH", 0x8000000000000001, 102, 0x0011) + element(0, b"") + element(5, bytes([0, 3, 0, 0])) + \
        element(221, be(0x0050F2, 3) + bytes([0x02, 0x01, 0x01])) + element(48, bytes([1, 0]))
    V["02-access-point-beacon-roundtrip"] = vec("access-point-beacon-roundtrip", F, hx(body), hx(body), {
        "wifi.timestamp": s64(0x8000000000000001), "wifi.elements.#": 4, "wifi.elements[0].wifi.ssid.#": 0,
        "wifi.elements[1].wifi.dtim_period": 3, "wifi.elements[1].wifi.partial_virtual_bitmap.#": 1,
        "wifi.elements[2].wifi.oui": 0x0050F2, "wifi.elements[2].wifi.vendor_data.#": 3,
        "wifi.elements[3].wifi.element_id": 48, "wifi.elements[3].wifi.element_data.#": 2}, ref=REF_WIFI,
        note="a hidden SSID (length 0), a TIM, a vendor element of another OUI and an element the pack does not read; "
             "a timestamp with its top bit set reads as a negative integer (ruling 2 of 0.5)")
    body = fixed + bytes([0, 9]) + b"UAS"
    V["03-element-longer-than-the-body"] = vec("element-longer-than-the-body", F, hx(body), error="malformed-wire",
                                               ref=REF_WIFI, note="an SSID element that states 9 octets and has 3")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("eddystone", eddystone_vectors()), ("altbeacon", altbeacon_vectors()),
                    ("remote-id-ble", rid_vectors()), ("wifi-beacon", wifi_vectors())):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("beacons-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
