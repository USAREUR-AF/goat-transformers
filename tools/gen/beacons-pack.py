#!/usr/bin/env python3
"""Write the packs and modules of BLE advertising beacons and the Wi-Fi beacon frame body.

Three BLE packs read one advertising payload (AD structures: a length octet, an AD type, data)
and each reads its own beacon in full: eddystone (google/eddystone), altbeacon (altbeacon/spec)
and remote-id-ble (the ASTM Remote ID service data, as opendroneid/transmitter-linux writes it).
They share the AD framing, written here once, and the module `ble`. wifi-beacon reads the body of
an IEEE 802.11 beacon frame as google/gopacket decodes it, with the ASTM Remote ID vendor element
as opendroneid-core-c writes it. Vectors are written by tools/gen/beacons-vectors.py.

Usage: python3 -I tools/gen/beacons-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


class W:
    def __init__(self):
        self.lines, self.ind = [], 0

    def __call__(self, text):
        self.lines.append(("  " * self.ind + text) if text else "")

    def open(self, head):
        self(head)
        self.ind += 1

    def end(self):
        self.ind -= 1
        self("end")

    def case(self, head):
        self.ind -= 1
        self(head)
        self.ind += 1


def octets(w, lst, key):
    w.open("group  %s  rest" % lst)
    w("field  %s  8  uint" % key)
    w.end()


def ad_payload(w, service_cases, manufacturer):
    """The AD structures of one advertising payload, to its end. `service_cases(w)` writes the
    cases of the 16-bit service data UUID; `manufacturer(w)` the lines after the company ID."""
    w.open("group  ble.ad_structures  rest")
    w.open("length 8 bytes                       # the length counts the AD type and the data")
    w("field  ble.ad_type  8  uint")
    w.open("switch ble.ad_type")
    w("case 1                               # Flags")
    w("  field  ble.flags  8  uint")
    w("case 2,3                             # Incomplete and complete list of 16-bit service UUIDs")
    w.ind += 1
    w.open("group  ble.service_uuids16  rest")
    w("field  ble.service_uuid16  16  uint  swap")
    w.end()
    w.ind -= 1
    w("case 10                              # Tx Power Level")
    w("  field  ble.tx_power_level  8  twos")
    w("case 22                              # Service Data, 16-bit UUID")
    w.ind += 1
    w("field  ble.service_data_uuid16  16  uint  swap")
    w.open("switch ble.service_data_uuid16")
    service_cases(w)
    w("else")
    w.ind += 1
    octets(w, "ble.service_data", "ble.service_data_octet")
    w.ind -= 1
    w.end()
    w.ind -= 1
    w("case 255                             # Manufacturer Specific Data")
    w.ind += 1
    w("field  ble.company_id  16  uint  swap")
    manufacturer(w)
    w.ind -= 1
    w("else")
    w.ind += 1
    octets(w, "ble.ad_data", "ble.ad_data_octet")
    w.ind -= 1
    w.end()
    w.end()
    w.end()


def plain_manufacturer(w):
    octets(w, "ble.manufacturer_data", "ble.manufacturer_data_octet")


def no_service(w):
    w("case 0                               # (none: every UUID is the else case)")


def eddystone_service(w):
    w("case 65194                           # 0xFEAA, Eddystone")
    w.ind += 1
    w("field  eddystone.frame_type  8  uint")
    w.open("switch eddystone.frame_type")
    w("case 0                               # UID")
    w("  field  eddystone.tx_power_0m      8   twos")
    w("  field  eddystone.namespace_high   16  uint")
    w("  field  eddystone.namespace_low    64  uint")
    w("  field  eddystone.instance         48  uint")
    w("  field  eddystone.uid_rfu          16  uint   # absent when the frame omits it")
    w("case 16                              # URL")
    w("  field  eddystone.tx_power_0m      8   twos")
    w("  field  eddystone.url_scheme       8   uint")
    w.ind += 1
    octets(w, "eddystone.url_octets", "eddystone.url_octet")
    w.ind -= 1
    w("case 32                              # TLM")
    w.ind += 1
    w("field  eddystone.tlm_version  8  uint")
    w.open("switch eddystone.tlm_version")
    w("case 0                               # unencrypted")
    w("  field  eddystone.battery_voltage  16  uint")
    w("  field  eddystone.temperature      16  sscale:1/256  absent 32768")
    w("  field  eddystone.adv_count        32  uint")
    w("  field  eddystone.sec_count        32  uint")
    w("case 1                               # encrypted")
    w("  field  eddystone.etlm_high        64  uint")
    w("  field  eddystone.etlm_low         32  uint")
    w("  field  eddystone.salt             16  uint")
    w("  field  eddystone.mic              16  uint")
    w("else")
    w.ind += 1
    octets(w, "eddystone.tlm_octets", "eddystone.tlm_octet")
    w.ind -= 1
    w.end()
    w.ind -= 1
    w("case 48                              # EID")
    w("  field  eddystone.tx_power_0m      8   twos")
    w("  field  eddystone.eid              64  uint")
    w("else")
    w.ind += 1
    octets(w, "eddystone.frame_octets", "eddystone.frame_octet")
    w.ind -= 1
    w.end()
    w.ind -= 1


def altbeacon_manufacturer(w):
    w("field  altbeacon.beacon_code  16  uint")
    w.open("switch altbeacon.beacon_code")
    w("case 48812                           # 0xBEAC")
    w("  field  altbeacon.beacon_id_1    64  uint")
    w("  field  altbeacon.beacon_id_2    64  uint")
    w("  field  altbeacon.beacon_id_3    32  uint")
    w("  field  altbeacon.reference_rssi  8  twos")
    w("  field  altbeacon.mfg_reserved    8  uint")
    w("else")
    w.ind += 1
    octets(w, "ble.manufacturer_data", "ble.manufacturer_data_octet")
    w.ind -= 1
    w.end()


def rid_service(w):
    w("case 65530                           # 0xFFFA, ASTM Remote ID")
    w.ind += 1
    w("field  ridble.application_code  8  uint")
    w.open("switch ridble.application_code")
    w("case 13                              # Open Drone ID")
    w("  field  ridble.message_counter  8  uint")
    w.ind += 1
    octets(w, "ridble.message", "ridble.message_octet")
    w.ind -= 1
    w("else")
    w.ind += 1
    octets(w, "ble.service_data", "ble.service_data_octet")
    w.ind -= 1
    w.end()
    w.ind -= 1


def header(w, fmt, comment, sources, modules):
    for c in comment:
        w("# " + c)
    w("format     " + fmt)
    w("version    0.1.0")
    w("distribution public")
    for s in sources:
        w('source     "%s"' % s)
    for m in modules:
        w("uses       " + m)
    w("wire       bits")
    w("layout     sequential")
    w("bit_order  msb")


SRC_EDDY = ("google/eddystone, https://github.com/google/eddystone commit bb8738d7ddac0ddd3dfa70e594d011a0475e763d: "
            "protocol-specification.md, eddystone-uid, eddystone-url, eddystone-tlm (tlm-plain, tlm-encrypted), eddystone-eid (Apache-2.0)")
SRC_ALT = ("AltBeacon Protocol Specification v1.0, https://github.com/altbeacon/spec commit d5c7f6da1192313d28222f9da2e0251074153252, "
           "README.md; altbeacon.org states CC BY-SA 4.0")
SRC_RID = ("opendroneid/transmitter-linux, https://github.com/opendroneid/transmitter-linux commit 6852afd0d4bed0d139b9dac3cd3a45eb595e30f0, "
           "bluetooth.c (Apache-2.0): the Bluetooth 4 and 5 advertising data of ASTM F3411 broadcast Remote ID")
SRC_GOPACKET = ("google/gopacket, https://github.com/google/gopacket commit b7d9dbd15ae4c4621a62119b0c682dc23061a8bc, "
                "layers/dot11.go (BSD-3-Clause): the beacon frame body and the information element")
SRC_ODID = ("opendroneid/opendroneid-core-c, https://github.com/opendroneid/opendroneid-core-c commit a92bd5ffe113edd076c159a06799152aed3b1fb0, "
            "libopendroneid/wifi.c and odid_wifi.h (Apache-2.0): the ASTM Remote ID vendor element of a Wi-Fi beacon")


def ble_pack(fmt, comment, sources, own, service, manufacturer):
    w = W()
    header(w, fmt, comment, sources, ["ble", own])
    w("")
    ad_payload(w, service, manufacturer)
    return "\n".join(w.lines) + "\n"


def wifi_pack():
    w = W()
    header(w, "wifi-beacon", [
        "IEEE 802.11 beacon frame body: the fixed fields (timestamp, beacon interval, capability",
        "information, little-endian) and the information elements (ID, length, value) to the end.",
        "Public. Written by tools/gen/beacons-pack.py from google/gopacket's decoder (BSD-3-Clause) and",
        "opendroneid-core-c's Remote ID beacon (Apache-2.0); the IEEE standard was not used. See pack.md."],
        [SRC_GOPACKET, SRC_ODID], ["wifi"])
    w("field  wifi.timestamp          64  uint  swap   # microseconds of the transmitter's timer")
    w("field  wifi.beacon_interval    16  uint  swap   # time units of 1024 microseconds")
    w("field  wifi.capability         16  uint  swap")
    w.open("group  wifi.elements  rest")
    w("field  wifi.element_id  8  uint")
    w.open("length 8 bytes")
    w.open("switch wifi.element_id")
    w("case 0                               # SSID")
    w.ind += 1
    octets(w, "wifi.ssid", "wifi.ssid_octet")
    w.ind -= 1
    w("case 1                               # Supported Rates")
    w.ind += 1
    octets(w, "wifi.rates", "wifi.rate")
    w.ind -= 1
    w("case 3                               # DS Parameter Set")
    w("  field  wifi.channel  8  uint")
    w("case 5                               # TIM")
    w("  field  wifi.dtim_count      8  uint")
    w("  field  wifi.dtim_period     8  uint")
    w("  field  wifi.bitmap_control  8  uint")
    w.ind += 1
    octets(w, "wifi.partial_virtual_bitmap", "wifi.bitmap_octet")
    w.ind -= 1
    w("case 221                             # Vendor Specific")
    w.ind += 1
    w("field  wifi.oui  24  uint")
    w.open("switch wifi.oui")
    w("case 16387004                        # 0xFA0BBC, ASTM")
    w.ind += 1
    w("field  wifi.oui_type  8  uint")
    w.open("switch wifi.oui_type")
    w("case 13                              # ASTM Remote ID")
    w("  field  wifi.rid_message_counter  8  uint")
    w.ind += 1
    octets(w, "wifi.rid_message_pack", "wifi.rid_message_pack_octet")
    w.ind -= 1
    w("else")
    w.ind += 1
    octets(w, "wifi.vendor_data", "wifi.vendor_octet")
    w.ind -= 1
    w.end()
    w.ind -= 1
    w("else")
    w.ind += 1
    octets(w, "wifi.vendor_data", "wifi.vendor_octet")
    w.ind -= 1
    w.end()
    w.ind -= 1
    w("else")
    w.ind += 1
    octets(w, "wifi.element_data", "wifi.element_octet")
    w.ind -= 1
    w.end()
    w.end()
    w.end()
    return "\n".join(w.lines) + "\n"


def module(name, comment, source, rows):
    L = ["# " + c for c in comment] + ["module        " + name, "version       0.1.0", "distribution  public",
                                       'source        "%s"' % source]
    width = max(len(r[1]) for r in rows)
    for kind, key, vt, unit, meaning in rows:
        if kind == "list":
            L.append('list  %-*s  "%s"' % (width, key, meaning))
        else:
            L.append('key   %-*s  %-6s  %-4s  "%s"' % (width, key, vt, unit, meaning))
    return "\n".join(L) + "\n"


BLE_ROWS = [
    ("list", "ad_structures", None, None, "AD structures of the advertising payload, in order"),
    ("key", "ad_type", "int", "-", "AD type of a structure: 1 Flags, 2 and 3 16-bit service UUID lists, 10 Tx Power Level, 22 Service Data (16-bit UUID), 255 Manufacturer Specific Data, ..."),
    ("key", "flags", "int", "-", "Flags: discoverable modes and BR/EDR support bits"),
    ("list", "service_uuids16", None, None, "16-bit service UUIDs of a UUID list structure"),
    ("key", "service_uuid16", "int", "-", "one 16-bit service UUID (little-endian on the wire)"),
    ("key", "tx_power_level", "int", "dBm", "Tx Power Level structure"),
    ("key", "service_data_uuid16", "int", "-", "16-bit UUID of a Service Data structure (little-endian on the wire)"),
    ("list", "service_data", None, None, "data of a Service Data structure the pack does not read, as octets"),
    ("key", "service_data_octet", "int", "-", "one octet of that data"),
    ("key", "company_id", "int", "-", "company identifier of a Manufacturer Specific Data structure (little-endian on the wire), as the Bluetooth SIG assigns it"),
    ("list", "manufacturer_data", None, None, "manufacturer data after the company identifier that the pack does not read, as octets"),
    ("key", "manufacturer_data_octet", "int", "-", "one octet of that data"),
    ("list", "ad_data", None, None, "data of an AD structure of another type, as octets"),
    ("key", "ad_data_octet", "int", "-", "one octet of that data"),
]

EDDY_ROWS = [
    ("key", "frame_type", "int", "-", "Eddystone frame type: 0x00 UID, 0x10 URL, 0x20 TLM, 0x30 EID"),
    ("key", "tx_power_0m", "int", "dBm", "calibrated transmit power as received at 0 m"),
    ("key", "namespace_high", "int", "-", "first 2 octets of the 10-octet UID namespace"),
    ("key", "namespace_low", "int", "-", "last 8 octets of the UID namespace (as uint reads 64 bits: negative when the top bit is set)"),
    ("key", "instance", "int", "-", "6-octet UID instance"),
    ("key", "uid_rfu", "int", "-", "the two reserved octets at the end of a UID frame; absent when the frame omits them"),
    ("key", "url_scheme", "int", "-", "URL frame: the code of the scheme prefix (0 http://www., 1 https://www., 2 http://, 3 https://)"),
    ("list", "url_octets", None, None, "URL frame: the encoded URL, as octets (an octet below 0x0E stands for a domain suffix)"),
    ("key", "url_octet", "int", "-", "one octet of the encoded URL"),
    ("key", "tlm_version", "int", "-", "TLM frame version: 0 plain, 1 encrypted"),
    ("key", "battery_voltage", "int", "mV", "TLM: battery voltage"),
    ("key", "temperature", "float", "degC", "TLM: beacon temperature, signed 8.8 fixed point; absent when not supported (0x8000)"),
    ("key", "adv_count", "int", "-", "TLM: advertising PDUs sent since power-on or reboot"),
    ("key", "sec_count", "int", "ds", "TLM: time since power-on or reboot, in tenths of a second"),
    ("key", "etlm_high", "int", "-", "encrypted TLM: first 8 of the 12 octets of encrypted data"),
    ("key", "etlm_low", "int", "-", "encrypted TLM: last 4 octets of encrypted data"),
    ("key", "salt", "int", "-", "encrypted TLM: salt"),
    ("key", "mic", "int", "-", "encrypted TLM: message integrity check"),
    ("list", "tlm_octets", None, None, "TLM frame of another version, as octets"),
    ("key", "tlm_octet", "int", "-", "one octet of that frame"),
    ("key", "eid", "int", "-", "EID frame: the 8-octet ephemeral identifier"),
    ("list", "frame_octets", None, None, "Eddystone frame of another type, as octets"),
    ("key", "frame_octet", "int", "-", "one octet of that frame"),
]

ALT_ROWS = [
    ("key", "beacon_code", "int", "-", "AltBeacon code, 0xBEAC (big-endian on the wire), after the company identifier"),
    ("key", "beacon_id_1", "int", "-", "beacon identifier, octets 1 to 8 of 20"),
    ("key", "beacon_id_2", "int", "-", "beacon identifier, octets 9 to 16"),
    ("key", "beacon_id_3", "int", "-", "beacon identifier, octets 17 to 20"),
    ("key", "reference_rssi", "int", "dBm", "average received signal strength at 1 m"),
    ("key", "mfg_reserved", "int", "-", "octet reserved for the manufacturer"),
]

RID_ROWS = [
    ("key", "application_code", "int", "-", "application code in the ASTM Remote ID service data: 0x0D Open Drone ID"),
    ("key", "message_counter", "int", "-", "message counter, 0 to 255, wrapping"),
    ("list", "message", None, None, "the Remote ID message (25 octets) or message pack, as octets; the remote-id pack reads it"),
    ("key", "message_octet", "int", "-", "one octet of the message"),
]

WIFI_ROWS = [
    ("key", "timestamp", "int", "us", "timer of the transmitter when the beacon was sent (little-endian on the wire; as uint reads 64 bits)"),
    ("key", "beacon_interval", "int", "TU", "time between beacons, in time units of 1024 microseconds"),
    ("key", "capability", "int", "-", "capability information bits (little-endian on the wire)"),
    ("list", "elements", None, None, "information elements of the frame body, in order"),
    ("key", "element_id", "int", "-", "element ID: 0 SSID, 1 Supported Rates, 3 DS Parameter Set, 5 TIM, 221 Vendor Specific, ..."),
    ("list", "ssid", None, None, "SSID, as octets"),
    ("key", "ssid_octet", "int", "-", "one octet of the SSID"),
    ("list", "rates", None, None, "supported rates, one octet each (units of 500 kbit/s; the top bit marks a basic rate)"),
    ("key", "rate", "int", "-", "one supported rate octet"),
    ("key", "channel", "int", "-", "DS Parameter Set: the current channel"),
    ("key", "dtim_count", "int", "-", "TIM: beacons before the next DTIM"),
    ("key", "dtim_period", "int", "-", "TIM: beacons between DTIMs"),
    ("key", "bitmap_control", "int", "-", "TIM: bitmap control octet"),
    ("list", "partial_virtual_bitmap", None, None, "TIM: partial virtual bitmap, as octets"),
    ("key", "bitmap_octet", "int", "-", "one octet of the bitmap"),
    ("key", "oui", "int", "-", "Vendor Specific: the organisationally unique identifier, 24 bits"),
    ("key", "oui_type", "int", "-", "Vendor Specific: the vendor's type octet after the OUI"),
    ("key", "rid_message_counter", "int", "-", "ASTM Remote ID element: message counter"),
    ("list", "rid_message_pack", None, None, "ASTM Remote ID element: the message pack, as octets; the remote-id pack reads it"),
    ("key", "rid_message_pack_octet", "int", "-", "one octet of the message pack"),
    ("list", "vendor_data", None, None, "Vendor Specific data the pack does not read, as octets"),
    ("key", "vendor_octet", "int", "-", "one octet of that data"),
    ("list", "element_data", None, None, "data of an element of another ID, as octets"),
    ("key", "element_octet", "int", "-", "one octet of that data"),
]


def build(out):
    out.write("packs/eddystone/pack.def", ble_pack("eddystone", [
        "Eddystone BLE beacon: one advertising payload, its AD structures, and the Eddystone frame",
        "(UID, URL, TLM plain and encrypted, EID) in the Service Data of UUID 0xFEAA. Public.",
        "Written by tools/gen/beacons-pack.py from google/eddystone (Apache-2.0). See pack.md."],
        [SRC_EDDY], "eddystone", eddystone_service, plain_manufacturer))
    out.write("packs/altbeacon/pack.def", ble_pack("altbeacon", [
        "AltBeacon BLE beacon: one advertising payload, its AD structures, and the AltBeacon",
        "advertisement in the Manufacturer Specific Data (beacon code 0xBEAC). Public. Written by",
        "tools/gen/beacons-pack.py from altbeacon/spec (CC BY-SA 4.0, as altbeacon.org states). See pack.md."],
        [SRC_ALT], "altbeacon", no_service, altbeacon_manufacturer))
    out.write("packs/remote-id-ble/pack.def", ble_pack("remote-id-ble", [
        "ASTM F3411 broadcast Remote ID over Bluetooth: one advertising payload, its AD structures, and",
        "the Service Data of UUID 0xFFFA (application code 0x0D, a message counter, then the 25-octet",
        "message or the message pack, which the remote-id pack reads). Public. Written by",
        "tools/gen/beacons-pack.py from opendroneid/transmitter-linux (Apache-2.0). See pack.md."],
        [SRC_RID], "ridble", rid_service, plain_manufacturer))
    out.write("packs/wifi-beacon/pack.def", wifi_pack())
    out.write("model/ble.def", module("ble", [
        "The ble module: the AD structures of a Bluetooth LE advertising payload, shared by the",
        "eddystone, altbeacon and remote-id-ble packs. Written by tools/gen/beacons-pack.py."],
        "AD structure framing (length, AD type, data) as google/eddystone protocol-specification.md and opendroneid/transmitter-linux bluetooth.c write it (Apache-2.0); restated by goat-transformers", BLE_ROWS))
    out.write("model/eddystone.def", module("eddystone", ["The eddystone module: the Eddystone frames. Written by tools/gen/beacons-pack.py."],
                                            SRC_EDDY + "; restated by goat-transformers", EDDY_ROWS))
    out.write("model/altbeacon.def", module("altbeacon", ["The altbeacon module: the AltBeacon advertisement. Written by tools/gen/beacons-pack.py."],
                                            SRC_ALT + "; restated by goat-transformers", ALT_ROWS))
    out.write("model/ridble.def", module("ridble", ["The ridble module: the ASTM Remote ID service data over Bluetooth. Written by tools/gen/beacons-pack.py."],
                                         SRC_RID + "; restated by goat-transformers", RID_ROWS))
    out.write("model/wifi.def", module("wifi", ["The wifi module: the body of an IEEE 802.11 beacon frame. Written by tools/gen/beacons-pack.py."],
                                       SRC_GOPACKET + "; " + SRC_ODID + "; restated by goat-transformers", WIFI_ROWS))
    return {"packs": 4, "modules": 5}


def main(argv=None):
    return genio.vector_main("beacons-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
