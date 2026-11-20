#!/usr/bin/env python3
"""Write the vectors of the mrt, cef and leef packs.

mrt reads one BGP MRT record (RFC 6396, add-path subtypes of RFC 8050); cef one ArcSight CEF
record; leef one IBM QRadar LEEF record. This script builds every record from values written
for these vectors (no example of an RFC or a vendor guide is used): MRT records with an encoder
of its own written from RFC 6396 sections 2 to 4, RFC 8050 and RFC 4271 section 4, the text
records by joining their fields. It states the decoded values from the same inputs, and the
canonical output by the rules of spec/engine-spec.md (0.8 and 0.21 sequential layouts, 0.10
`text` wire). It reads no pack.def and calls no goat-transformers engine.

Usage: python3 -I tools/gen/logs-vectors.py [--out DIR] [--check]
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "derived by tools/gen/logs-vectors.py from records written for it and spec/engine-spec.md; no engine run"
REF_MRT = "IETF RFC 6396 (MRT) and RFC 8050 (additional paths); RFC 4271 section 4 (BGP messages)"
REF_CEF = "Implementing ArcSight Common Event Format (CEF), Version 26 (OpenText, 2023), section CEF Implementation"
REF_LEEF = "IBM QRadar DSM documentation, LEEF event components"


def vec(name, frm, to, inp, expect=None, model=None, error=None, ref="", note=None):
    v = {"name": name, "from": frm, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = {k: str(x) for k, x in model.items()}
    v["source"] = SOURCE
    v["reference"] = ref + ("; " + note if note else "")
    return v


# -- MRT encoder ----------------------------------------------------------------------------------

def u8(v):
    return struct.pack(">B", v)


def u16(v):
    return struct.pack(">H", v)


def u32(v):
    return struct.pack(">I", v)


def ip4(text):
    return int(ipaddress.IPv4Address(text))


def ip6(text):
    v = int(ipaddress.IPv6Address(text))
    return v >> 64, v & ((1 << 64) - 1)


def s64(v):
    """A 64-bit value as `uint` decodes it (ruling 2 of 0.5): negative when the top bit is set."""
    return v - (1 << 64) if v >> 63 else v


def prefix(net):
    """(length, octets) of a prefix as BGP writes it: as many whole octets as the length needs."""
    n = ipaddress.ip_network(net)
    plen = n.prefixlen
    octs = n.network_address.packed[:(plen + 7) // 8]
    return plen, list(octs)


def prefix_bytes(net):
    plen, octs = prefix(net)
    return u8(plen) + bytes(octs)


def attr(flags, code, value):
    """One path attribute: flags, type code, length (two octets when flag 0x10 is set), value."""
    return u8(flags) + u8(code) + (u16(len(value)) if flags & 0x10 else u8(len(value))) + value


def as_path(segments, asn_octets):
    out = b""
    for seg_type, asns in segments:
        out += u8(seg_type) + u8(len(asns)) + b"".join(u32(a) if asn_octets == 4 else u16(a) for a in asns)
    return out


def record(seconds, mtype, subtype, body):
    return u32(seconds) + u16(mtype) + u16(subtype) + u32(len(body)) + body


def bgp(msg_type, body):
    return b"\xff" * 16 + u16(19 + len(body)) + u8(msg_type) + body


def hx(b):
    return b.hex()


# expected model values of an attribute list, keyed under `prefix`
def attr_model(m, pre, attrs):
    for i, (flags, code, value_model) in enumerate(attrs):
        p = "%smrt.attributes[%d]." % (pre, i)
        m[p + "mrt.attr_type"] = code
        m[p + "mrt.attr_extended_length"] = (flags >> 4) & 1
        if value_model is not None:
            k, v = value_model
            m[p + k] = v


T0 = 1763640000


def mrt_vectors():
    V = {}
    F = "mrt"
    # 1. PEER_INDEX_TABLE
    p6h, p6l = ip6("2001:db8::1")
    body = (u32(ip4("192.0.2.1")) + u16(2) + b"rv" + u16(2) +
            u8(0) + u32(ip4("198.51.100.1")) + u32(ip4("198.51.100.1")) + u16(64500) +
            u8(3) + u32(ip4("198.51.100.2")) + struct.pack(">QQ", p6h, p6l) + u32(4200000001))
    rec = record(T0, 13, 1, body)
    V["01-peer-index-table-roundtrip"] = vec("peer-index-table-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "table-dump-v2-peer-index-table", "time_ms": T0 * 1000,
        "mrt.collector_bgp_id": ip4("192.0.2.1"), "mrt.view_name.#": 2, "mrt.view_name[0].mrt.view_name_octet": ord("r"),
        "mrt.peers.#": 2, "mrt.peers[0].mrt.peer_as": 64500, "mrt.peers[1].mrt.peer_type": 3,
        "mrt.peers[1].mrt.peer_ipv6_high": s64(p6h), "mrt.peers[1].mrt.peer_ipv6_low": p6l,
        "mrt.peers[1].mrt.peer_as": 4200000001}, ref=REF_MRT,
        note="a collector with the view name rv and two peers: IPv4 with a 2-octet AS, IPv6 with a 4-octet AS")
    # 2. RIB_IPV4_UNICAST
    attrs = [(0x40, 1, u8(0), ("mrt.origin", 0)),
             (0x40, 2, as_path([(2, [64500, 64496])], 4), None),
             (0x40, 3, u32(ip4("198.51.100.1")), ("mrt.next_hop", ip4("198.51.100.1"))),
             (0x80, 4, u32(100), ("mrt.multi_exit_disc", 100)),
             (0x50, 5, u32(200), ("mrt.local_pref", 200)),
             (0xC0, 8, u32(0xFDE80001), None)]
    attr_bytes = b"".join(attr(f, c, v) for f, c, v, _ in attrs)
    body = u32(7) + prefix_bytes("192.0.2.0/24") + u16(1) + u16(0) + u32(T0 - 1000) + u16(len(attr_bytes)) + attr_bytes
    rec = record(T0, 13, 2, body)
    m = {"@kind": "table-dump-v2-rib-ipv4-unicast", "mrt.sequence_number": 7, "mrt.prefix_length": 24,
         "mrt.prefix_octet_1": 192, "mrt.prefix_octet_3": 2, "mrt.rib_entries.#": 1,
         "mrt.rib_entries[0].mrt.originated_time": T0 - 1000, "mrt.rib_entries[0].mrt.attributes.#": 6,
         "mrt.rib_entries[0].mrt.attributes[1].mrt.as_path_segments[0].mrt.segment_asns[1].mrt.asn": 64496,
         "mrt.rib_entries[0].mrt.attributes[5].mrt.attr_value.#": 4}
    attr_model(m, "mrt.rib_entries[0].", [(f, c, vm) for f, c, _, vm in attrs])
    V["02-rib-ipv4-unicast-roundtrip"] = vec("rib-ipv4-unicast-roundtrip", F, F, hx(rec), hx(rec), m, ref=REF_MRT,
        note="192.0.2.0/24 with one entry: ORIGIN, AS_PATH of 4-octet AS numbers, NEXT_HOP, MULTI_EXIT_DISC, LOCAL_PREF "
             "with the extended-length flag, and COMMUNITIES kept as octets")
    # 3. RIB_IPV6_UNICAST, two entries, an AS_SET, MP_REACH_NLRI as octets
    mp = u16(2) + u8(1) + u8(16) + ip6_bytes("2001:db8::ff") + u8(0)
    e1 = [(0x40, 1, u8(2)), (0x40, 2, as_path([(2, [64500]), (1, [64510, 64511])], 4)), (0x80, 14, mp)]
    e2 = [(0x40, 1, u8(0)), (0x40, 2, as_path([(2, [4200000001])], 4))]
    entries = b""
    for peer, attrs_ in ((0, e1), (1, e2)):
        ab = b"".join(attr(f, c, v) for f, c, v in attrs_)
        entries += u16(peer) + u32(T0 - 60) + u16(len(ab)) + ab
    body = u32(8) + prefix_bytes("2001:db8::/32") + u16(2) + entries
    rec = record(T0, 13, 4, body)
    V["03-rib-ipv6-unicast-roundtrip"] = vec("rib-ipv6-unicast-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "table-dump-v2-rib-ipv6-unicast", "mrt.prefix_length": 32, "mrt.prefix_octet_1": 0x20,
        "mrt.prefix_octet_4": 0xb8, "mrt.rib_entries.#": 2,
        "mrt.rib_entries[0].mrt.attributes[0].mrt.origin": 2,
        "mrt.rib_entries[0].mrt.attributes[1].mrt.as_path_segments.#": 2,
        "mrt.rib_entries[0].mrt.attributes[1].mrt.as_path_segments[1].mrt.segment_type": 1,
        "mrt.rib_entries[0].mrt.attributes[2].mrt.attr_value.#": len(mp),
        "mrt.rib_entries[1].mrt.peer_index": 1,
        "mrt.rib_entries[1].mrt.attributes[1].mrt.as_path_segments[0].mrt.segment_asns[0].mrt.asn": 4200000001},
        ref=REF_MRT, note="2001:db8::/32 with two entries; an AS_SET segment; MP_REACH_NLRI is kept as octets")
    # 4. RIB_IPV4_UNICAST_ADDPATH
    ab = attr(0x40, 1, u8(0))
    body = u32(9) + prefix_bytes("203.0.113.128/25") + u16(2) + \
        u16(0) + u32(T0 - 5) + u32(1) + u16(len(ab)) + ab + u16(0) + u32(T0 - 4) + u32(2) + u16(len(ab)) + ab
    rec = record(T0, 13, 8, body)
    V["04-rib-ipv4-unicast-addpath-roundtrip"] = vec("rib-ipv4-unicast-addpath-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "table-dump-v2-rib-ipv4-unicast-addpath", "mrt.prefix_length": 25, "mrt.prefix_octet_4": 128,
        "mrt.rib_entries[0].mrt.path_identifier": 1, "mrt.rib_entries[1].mrt.path_identifier": 2},
        ref=REF_MRT, note="RFC 8050: one prefix, two paths from one peer told apart by their path identifiers; a /25 takes four octets")
    # 5. BGP4MP_STATE_CHANGE_AS4
    body = u32(4200000001) + u32(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.1")) + u32(ip4("198.51.100.254")) + u16(4) + u16(6)
    rec = record(T0 + 1, 16, 5, body)
    V["05-state-change-as4-roundtrip"] = vec("state-change-as4-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "bgp4mp-state-change-as4", "time_ms": (T0 + 1) * 1000, "mrt.peer_as": 4200000001,
        "mrt.local_as": 64496, "mrt.address_family": 1, "mrt.peer_ipv4": ip4("198.51.100.1"),
        "mrt.old_state": 4, "mrt.new_state": 6}, ref=REF_MRT, note="a session from OpenConfirm (4) to Established (6)")
    # 6. BGP4MP_ET MESSAGE_AS4, an UPDATE
    upd_attrs = attr(0x40, 1, u8(0)) + attr(0x40, 2, as_path([(2, [4200000001, 64500])], 4)) + attr(0x40, 3, u32(ip4("198.51.100.1")))
    withdrawn = prefix_bytes("198.51.100.0/24")
    nlri = prefix_bytes("203.0.113.0/24") + prefix_bytes("10.0.0.0/8") + prefix_bytes("0.0.0.0/0")
    upd = u16(len(withdrawn)) + withdrawn + u16(len(upd_attrs)) + upd_attrs + nlri
    body = u32(250000) + u32(4200000001) + u32(64496) + u16(3) + u16(1) + u32(ip4("198.51.100.1")) + \
        u32(ip4("198.51.100.254")) + bgp(2, upd)
    rec = record(T0 + 2, 17, 4, body)
    V["06-et-message-as4-update-roundtrip"] = vec("et-message-as4-update-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "bgp4mp-et-message-as4", "time_ms": (T0 + 2) * 1000, "mrt.microseconds": 250000,
        "mrt.interface_index": 3, "mrt.bgp_marker_high": -1, "mrt.bgp_type": 2,
        "mrt.withdrawn_routes.#": 1, "mrt.withdrawn_routes[0].mrt.prefix_octet_2": 51,
        "mrt.attributes.#": 3, "mrt.attributes[1].mrt.as_path_segments[0].mrt.segment_asns[0].mrt.asn": 4200000001,
        "mrt.nlri.#": 3, "mrt.nlri[1].mrt.prefix_length": 8, "mrt.nlri[1].mrt.prefix_octet_1": 10,
        "mrt.nlri[2].mrt.prefix_length": 0}, ref=REF_MRT,
        note="BGP4MP_ET with 250000 microseconds: time_ms holds the header's whole seconds and the microseconds stay a raw "
             "key; an UPDATE withdrawing one prefix and announcing three, the default route among them")
    # 7. BGP4MP_MESSAGE (2-octet AS), an OPEN
    opn = u8(4) + u16(64500) + u16(180) + u32(ip4("198.51.100.1")) + u8(8) + bytes([2, 6, 1, 4, 0, 1, 0, 1])
    body = u16(64500) + u16(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.1")) + u32(ip4("198.51.100.254")) + bgp(1, opn)
    rec = record(T0 + 3, 16, 1, body)
    V["07-message-open-roundtrip"] = vec("message-open-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "bgp4mp-message", "mrt.peer_as": 64500, "mrt.bgp_type": 1, "mrt.open_version": 4,
        "mrt.open_hold_time": 180, "mrt.open_parameters.#": 8}, ref=REF_MRT,
        note="an OPEN with one optional parameter (a capability), kept as its octets")
    # 8. BGP4MP_MESSAGE_AS4_ADDPATH, an UPDATE with path identifiers; 2-octet AS path in MESSAGE_ADDPATH is not used
    a8 = attr(0x40, 1, u8(1)) + attr(0x40, 2, as_path([(2, [64511])], 4)) + attr(0x40, 3, u32(ip4("198.51.100.9")))
    nl = u32(7) + prefix_bytes("192.0.2.64/26") + u32(8) + prefix_bytes("192.0.2.64/26")
    wd = u32(3) + prefix_bytes("192.0.2.0/26")
    upd = u16(len(wd)) + wd + u16(len(a8)) + a8 + nl
    body = u32(64511) + u32(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.9")) + u32(ip4("198.51.100.254")) + bgp(2, upd)
    rec = record(T0 + 4, 16, 9, body)
    V["08-message-as4-addpath-roundtrip"] = vec("message-as4-addpath-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "bgp4mp-message-as4-addpath", "mrt.withdrawn_routes[0].mrt.path_identifier": 3,
        "mrt.nlri.#": 2, "mrt.nlri[0].mrt.path_identifier": 7, "mrt.nlri[1].mrt.path_identifier": 8,
        "mrt.nlri[1].mrt.prefix_octet_4": 64}, ref=REF_MRT,
        note="RFC 8050: every withdrawn and announced prefix is preceded by a 4-octet path identifier")
    # 9. BGP4MP_MESSAGE with a 2-octet AS_PATH
    a2 = attr(0x40, 1, u8(0)) + attr(0x40, 2, as_path([(2, [64500, 64496])], 2))
    upd = u16(0) + u16(len(a2)) + a2 + prefix_bytes("192.0.2.0/24")
    body = u16(64500) + u16(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.1")) + u32(ip4("198.51.100.254")) + bgp(2, upd)
    rec = record(T0 + 5, 16, 1, body)
    V["09-message-2-octet-as-path-roundtrip"] = vec("message-2-octet-as-path-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "bgp4mp-message", "mrt.withdrawn_routes.#": 0,
        "mrt.attributes[1].mrt.as_path_segments[0].mrt.segment_asns.#": 2,
        "mrt.attributes[1].mrt.as_path_segments[0].mrt.segment_asns[1].mrt.asn": 64496}, ref=REF_MRT,
        note="BGP4MP_MESSAGE: the AS_PATH holds 2-octet AS numbers; no prefix is withdrawn, so the list is present and empty")
    # 10. KEEPALIVE and NOTIFICATION
    body = u16(64500) + u16(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.1")) + u32(ip4("198.51.100.254")) + bgp(4, b"")
    rec = record(T0 + 6, 16, 1, body)
    V["10-message-keepalive-roundtrip"] = vec("message-keepalive-roundtrip", F, F, hx(rec), hx(rec),
        {"@kind": "bgp4mp-message", "mrt.bgp_type": 4}, ref=REF_MRT, note="a KEEPALIVE: a BGP header and no body")
    body = u16(64500) + u16(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.1")) + u32(ip4("198.51.100.254")) + \
        bgp(3, u8(6) + u8(2) + b"\x00")
    rec = record(T0 + 7, 16, 1, body)
    V["11-message-notification-roundtrip"] = vec("message-notification-roundtrip", F, F, hx(rec), hx(rec), {
        "@kind": "bgp4mp-message", "mrt.error_code": 6, "mrt.error_subcode": 2, "mrt.notification_data.#": 1},
        ref=REF_MRT, note="a NOTIFICATION: Cease (6), administrative shutdown (2), one octet of data")
    # 12. to geojson: the record time
    rec = record(T0 + 1, 16, 5, u32(4200000001) + u32(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.1")) +
                 u32(ip4("198.51.100.254")) + u16(4) + u16(6))
    V["12-state-change-to-geojson"] = vec("state-change-to-geojson", F, "geojson", hx(rec),
        '{"type":"Feature","geometry":null,"properties":{"time_ms":%d}}' % ((T0 + 1) * 1000), ref=REF_MRT,
        note="the record time is time_ms, which the GeoJSON Feature carries; nothing else of the record is a shared key")
    # 13. refusals
    rec = record(T0, 12, 1, b"\x00" * 4)
    V["13-table-dump-v1-is-no-kind"] = vec("table-dump-v1-is-no-kind", F, F, hx(rec), error="no-kind", ref=REF_MRT,
        note="type 12 (TABLE_DUMP, deprecated) is not mapped")
    rec = record(T0, 16, 5, u32(4200000001) + u32(64496) + u16(0) + u16(1) + u32(ip4("198.51.100.1")) +
                 u32(ip4("198.51.100.254")) + u16(4) + u16(6))
    V["14-input-shorter-than-its-length"] = vec("input-shorter-than-its-length", F, F, hx(rec[:-2]), error="malformed-wire",
        ref=REF_MRT, note="a state change whose last two octets are missing: the length states more than the input holds")
    return V


def ip6_bytes(text):
    return ipaddress.IPv6Address(text).packed


# -- CEF and LEEF -----------------------------------------------------------------------------------

def cef_vectors():
    V = {}
    F = "cef"
    hdr = ["0", "Example Security", "ThreatSensor", "2.1", "100", "port scan", "7"]
    ext = "src=192.0.2.10 dst=198.51.100.5 spt=40000 act=blocked"
    r = "CEF:" + "|".join(hdr + [ext])
    V["01-event-roundtrip"] = vec("event-roundtrip", F, F, r, r, {
        "cef.version": 0, "cef.device_vendor": "Example Security", "cef.name": "port scan", "cef.severity": "7",
        "cef.extension.#": 1, "cef.extension[0].cef.extension_part": ext}, ref=REF_CEF,
        note="a CEF 0 record without a syslog prefix; the extension is one text")
    hdr1 = ["1", "Example Security", "ThreatSensor", "2.1", "signin:7", "sign-in", "High"]
    r = "CEF:" + "|".join(hdr1 + ["msg=user a", "b signed in suser=alice"])
    V["02-pipe-in-the-extension-roundtrip"] = vec("pipe-in-the-extension-roundtrip", F, F, r, r, {
        "cef.version": 1, "cef.severity": "High", "cef.extension.#": 2,
        "cef.extension[1].cef.extension_part": "b signed in suser=alice"}, ref=REF_CEF,
        note="a pipe in the extension needs no escape; the extension splits there into two items and is joined again")
    r = "CEF:0|Example Security|ThreatSensor|2.1|200|a \\| b|3|x=1"
    V["03-escaped-pipe-in-the-header"] = vec("escaped-pipe-in-the-header", F, F, r, r, {
        "cef.name": "a \\", "cef.severity": " b", "cef.extension.#": 2}, ref=REF_CEF,
        note="an escaped pipe in a header field is still a delimiter to the text wire: the fields after it shift by one, "
             "and the record comes back unchanged")
    r = "CEF:x|Example Security|ThreatSensor|2.1|100|port scan|7|src=192.0.2.10"
    V["04-version-not-a-number"] = vec("version-not-a-number", F, F, r, error="transform-decode", ref=REF_CEF,
                                       note="the version is an integer")
    r = "Jan 18 11:07:53 host CEF:0|Example Security|ThreatSensor|2.1|100|port scan|7|src=192.0.2.10"
    V["05-syslog-prefix-is-not-read"] = vec("syslog-prefix-is-not-read", F, F, r, error="malformed-wire", ref=REF_CEF,
        note="the pack reads CEF without its syslog prefix: a record must begin with CEF:")
    return V


def leef_vectors():
    V = {}
    F = "leef"
    r = "LEEF:2.0|Example|Gateway|3.2|login|^|src=192.0.2.10^dst=198.51.100.5^usrName=alice"
    V["01-leef-2-roundtrip"] = vec("leef-2-roundtrip", F, F, r, r, {
        "@kind": "leef-2", "leef.vendor": "Example", "leef.event_id": "login", "leef.attribute_delimiter": "^",
        "leef.attributes.#": 1, "leef.attributes[0].leef.attribute_part": "src=192.0.2.10^dst=198.51.100.5^usrName=alice"},
        ref=REF_LEEF, note="LEEF 2.0 with ^ separating the attributes; the attributes are one text")
    r = "LEEF:2.0|Example|Gateway|3.2|login|x5E|src=192.0.2.10^usrName=alice"
    V["02-leef-2-hex-delimiter-roundtrip"] = vec("leef-2-hex-delimiter-roundtrip", F, F, r, r, {
        "@kind": "leef-2", "leef.attribute_delimiter": "x5E"}, ref=REF_LEEF,
        note="the delimiter written as x and hex digits is kept as written")
    r = "LEEF:1.0|Example|Gateway|3.2|logout|usrName=alice"
    V["03-leef-1-one-attribute-roundtrip"] = vec("leef-1-one-attribute-roundtrip", F, F, r, r, {
        "@kind": "leef-1", "leef.product": "Gateway", "leef.attributes[0].leef.attribute_part": "usrName=alice"},
        ref=REF_LEEF, note="LEEF 1.0 with a single attribute, so no tab")
    r = "LEEF:1.0|Example|Gateway|3.2|logout|usrName=alice\tsrc=192.0.2.10"
    V["04-leef-1-tab-is-not-text"] = vec("leef-1-tab-is-not-text", F, F, r, error="malformed-wire", ref=REF_LEEF,
        note="LEEF 1.0 separates attributes with a tab, which the text wire does not read (0x20 to 0x7E only)")
    r = "LEEF:3.0|Example|Gateway|3.2|login|^|src=192.0.2.10"
    V["05-unknown-version"] = vec("unknown-version", F, F, r, error="no-kind", ref=REF_LEEF,
                                  note="only versions 1.0 and 2.0 are kinds")
    return V


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    w = {}
    for fmt, vs in (("mrt", mrt_vectors()), ("cef", cef_vectors()), ("leef", leef_vectors())):
        for fn, v in vs.items():
            out.write("packs/%s/vectors/%s.json" % (fmt, fn), dump(v))
            w[fmt] = w.get(fmt, 0) + 1
    return w


def main(argv=None):
    return genio.vector_main("logs-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
