#!/usr/bin/env python3
"""routing-vectors: write the vectors of the routing control protocol packs.

Packs: bgp-bmp, bfd-control-auth (and one cross vector under bfd-control), rpki-rtr.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below
are this program's own restatement of RFC 7854 sections 4.1 to 4.10, RFC 8671 sections 4 to 6
and RFC 9069 sections 4 and 5 (BMP), RFC 4271 section 4 (the BGP messages BMP carries), RFC
5880 sections 4.1 to 4.4 (BFD control packet and authentication sections) and RFC 8210
section 5 (RPKI to Router PDUs): every multi-octet field big-endian.

Inputs: messages built here field by field from values chosen here. No message is taken from
a document. Addresses are from the documentation ranges of RFC 5737 and RFC 3849, AS numbers
from the documentation ranges of RFC 5398.

`expect` of a same-format vector is this program's packing of the decoded values, which for
these messages is the input. `expect` of the BFD conversions is worked out from the rules of
spec/engine-spec.md: the mandatory section carries through the keys both packs map; the fixed
`bfd-control` pack writes its 24 octets and no more. `model` holds the values that were packed.

Usage: python3 -I tools/gen/routing-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/routing-vectors.py from values chosen there; layout restated "
          "from %s; expect derived there, no engine run")
R_BMP = "RFC 7854 sections 4.1 to 4.10 (with RFC 8671 and RFC 9069) and RFC 4271 section 4"
R_BFD = "RFC 5880 sections 4.1 to 4.4"
R_RTR = "RFC 8210 section 5"


def v4(text):
    return int(ipaddress.IPv4Address(text))


def v6b(text):
    return ipaddress.IPv6Address(text).packed


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def u64(*v):
    return b"".join(struct.pack(">Q", x) for x in v)


def vec(name, frm, to, inp, expect=None, model=None, error=None, ref=""):
    v = {"name": name, "from": frm, "to": to, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


# ---------------------------------------------------------------- BGP (RFC 4271 section 4)

def bgp(msg_type, body):
    return b"\xff" * 16 + u16(19 + len(body)) + u8(msg_type) + body


def prefix(text):
    net = ipaddress.ip_network(text)
    n = net.prefixlen
    return u8(n) + net.network_address.packed[:(n + 7) // 8]


def attr(flags, code, value):
    if flags & 0x10:
        return u8(flags, code) + u16(len(value)) + value
    return u8(flags, code, len(value)) + value


def as_path(segments, asn_bytes):
    out = b""
    for seg_type, asns in segments:
        out += u8(seg_type, len(asns)) + b"".join(a.to_bytes(asn_bytes, "big") for a in asns)
    return out


def update(withdrawn, attrs, nlri):
    w = b"".join(prefix(p) for p in withdrawn)
    a = b"".join(attrs)
    return bgp(2, u16(len(w)) + w + u16(len(a)) + a + b"".join(prefix(p) for p in nlri))


def open_msg(my_as, hold, bgp_id, params=b""):
    return bgp(1, u8(4) + u16(my_as, hold) + u32(bgp_id) + u8(len(params)) + params)


# ---------------------------------------------------------------- BMP (RFC 7854)

def bmp(msg_type, body):
    return u8(3) + u32(6 + len(body)) + u8(msg_type) + body


def per_peer(peer_type=0, v=0, l=0, a=0, o=0, dist=0, addr="192.0.2.2", asn=64496, bgp_id="192.0.2.2",
             sec=1773480413, usec=250001):
    flags = (v << 7) | (l << 6) | (a << 5) | (o << 4)
    if v:
        address = v6b(addr)
    else:
        address = b"\0" * 12 + u32(v4(addr))
    return u8(peer_type, flags) + u64(dist) + address + u32(asn, v4(bgp_id), sec, usec)


def tlv(t, value):
    return u16(t, len(value)) + value


def bmp_vectors():
    out = []
    attrs4 = [attr(0x40, 1, u8(0)), attr(0x40, 2, as_path([(2, [64496, 65551])], 4)),
              attr(0x40, 3, u32(v4("192.0.2.2"))), attr(0x80, 4, u32(100)), attr(0x40, 5, u32(200)),
              attr(0xC0, 8, u32(0xFBF00064))]
    up = update(["198.51.100.0/24"], attrs4, ["203.0.113.0/24", "192.0.2.128/25"])
    msg = bmp(0, per_peer() + up)
    m = {"@kind": "message", "bmp.msg_type": "0", "bmp.peer_type": "0", "bmp.peer_flag_v": "0",
         "bmp.peer_flag_a": "0", "bmp.peer_ipv4": str(v4("192.0.2.2")), "bmp.peer_as": "64496",
         "bmp.timestamp_sec": "1773480413", "bmp.timestamp_usec": "250001", "bmp.bgp_type": "2",
         "bmp.withdrawn_routes.#": "1", "bmp.withdrawn_routes[0].bmp.prefix_length": "24",
         "bmp.attributes.#": "6", "bmp.attributes[1].bmp.as_path_segments[0].bmp.segment_asns[1].bmp.asn": "65551",
         "bmp.attributes[2].bmp.next_hop": str(v4("192.0.2.2")), "bmp.attributes[4].bmp.local_pref": "200",
         "bmp.attributes[5].bmp.attr_value.#": "4", "bmp.nlri.#": "2",
         "bmp.nlri[1].bmp.prefix_length": "25", "bmp.nlri[1].bmp.prefix_octet_4": "128"}
    out.append(("01-route-monitoring-roundtrip.json",
                vec("route-monitoring-roundtrip", "bgp-bmp", "bgp-bmp", msg, msg, m,
                    ref=R_BMP + "; an IPv4 peer, pre-policy, 4-octet AS_PATH; an UPDATE that withdraws one prefix "
                        "and announces two, with ORIGIN, AS_PATH, NEXT_HOP, MED, LOCAL_PREF and COMMUNITIES (kept "
                        "as octets)")))
    attrs2 = [attr(0x40, 1, u8(2)), attr(0x40, 2, as_path([(2, [64497, 64498, 64499])], 2)),
              attr(0x40, 3, u32(v4("192.0.2.9")))]
    msg2 = bmp(0, per_peer(v=1, l=1, a=1, addr="2001:db8::2", asn=64497, bgp_id="192.0.2.9") +
               update([], attrs2, ["198.51.100.64/26"]))
    m2 = {"bmp.peer_flag_v": "1", "bmp.peer_flag_l": "1", "bmp.peer_flag_a": "1",
          "bmp.peer_ipv6_high": str(int.from_bytes(v6b("2001:db8::2")[:8], "big")),
          "bmp.peer_ipv6_low": "2",
          "bmp.attributes[1].bmp.as_path_segments[0].bmp.segment_asns.#": "3",
          "bmp.attributes[1].bmp.as_path_segments[0].bmp.segment_asns[2].bmp.asn": "64499"}
    out.append(("02-route-monitoring-ipv6-peer-2-octet-as-roundtrip.json",
                vec("route-monitoring-ipv6-peer-2-octet-as-roundtrip", "bgp-bmp", "bgp-bmp", msg2, msg2, m2,
                    ref=R_BMP + "; an IPv6 peer (V), post-policy (L), legacy 2-octet AS_PATH (A)")))
    msg3 = bmp(0, per_peer(o=1, l=1) + update([], [], []))
    out.append(("03-adj-rib-out-end-of-rib-roundtrip.json",
                vec("adj-rib-out-end-of-rib-roundtrip", "bgp-bmp", "bgp-bmp", msg3, msg3,
                    {"bmp.peer_flag_o": "1", "bmp.withdrawn_routes.#": "0", "bmp.attributes.#": "0", "bmp.nlri.#": "0"},
                    ref=R_BMP + "; post-policy Adj-RIB-Out (O flag, RFC 8671) and an empty UPDATE")))
    msg4 = bmp(0, per_peer(peer_type=3, v=1, dist=0x0000FDE800000001, addr="::", asn=64496,
                           bgp_id="192.0.2.1") + update([], attrs4[:3], ["203.0.113.0/24"]))
    out.append(("04-loc-rib-roundtrip.json",
                vec("loc-rib-roundtrip", "bgp-bmp", "bgp-bmp", msg4, msg4,
                    {"bmp.peer_type": "3", "bmp.peer_flag_v": "1", "bmp.peer_distinguisher": str(0x0000FDE800000001)},
                    ref=R_BMP + "; a Loc-RIB instance peer (peer type 3, RFC 9069) with the F flag set and a "
                        "zero-filled address")))
    stats = [tlv(0, u32(17)), tlv(7, u64(912345)), tlv(9, u16(1) + u8(1) + u64(800001)), tlv(14, u64(5000)),
             tlv(16, u16(2) + u8(1) + u64(1200)), tlv(100, u32(7))]
    msg5 = bmp(1, per_peer() + u32(len(stats)) + b"".join(stats))
    m5 = {"bmp.msg_type": "1", "bmp.stats.#": "6", "bmp.stats[0].bmp.stat_counter": "17",
          "bmp.stats[1].bmp.stat_gauge": "912345", "bmp.stats[2].bmp.stat_afi": "1",
          "bmp.stats[2].bmp.stat_safi": "1", "bmp.stats[2].bmp.stat_gauge": "800001",
          "bmp.stats[3].bmp.stat_type": "14", "bmp.stats[4].bmp.stat_afi": "2",
          "bmp.stats[5].bmp.stat_value.#": "4"}
    out.append(("05-statistics-roundtrip.json",
                vec("statistics-roundtrip", "bgp-bmp", "bgp-bmp", msg5, msg5, m5,
                    ref=R_BMP + "; stat types 0 (counter), 7 (gauge), 9 (AFI/SAFI gauge), 14 and 16 (RFC 8671), "
                        "and type 100, kept as octets")))
    msg6 = bmp(2, per_peer() + u8(1) + bgp(3, u8(6, 2) + u8(0, 1)))
    out.append(("06-peer-down-notification-roundtrip.json",
                vec("peer-down-notification-roundtrip", "bgp-bmp", "bgp-bmp", msg6, msg6,
                    {"bmp.down_reason": "1", "bmp.bgp_type": "3", "bmp.error_code": "6", "bmp.error_subcode": "2",
                     "bmp.notification_data.#": "2"},
                    ref=R_BMP + "; Peer Down reason 1 with a NOTIFICATION (Cease, administrative shutdown)")))
    msg7 = bmp(2, per_peer() + u8(2) + u16(24))
    out.append(("07-peer-down-fsm-event-roundtrip.json",
                vec("peer-down-fsm-event-roundtrip", "bgp-bmp", "bgp-bmp", msg7, msg7,
                    {"bmp.down_reason": "2", "bmp.fsm_event": "24"},
                    ref=R_BMP + "; Peer Down reason 2 with an FSM event code")))
    msg8 = bmp(2, per_peer(peer_type=3, v=1, addr="::") + u8(6) + tlv(3, b"blue"))
    out.append(("08-peer-down-loc-rib-roundtrip.json",
                vec("peer-down-loc-rib-roundtrip", "bgp-bmp", "bgp-bmp", msg8, msg8,
                    {"bmp.down_reason": "6", "bmp.down_tlvs.#": "1", "bmp.down_tlvs[0].bmp.info_type": "3",
                     "bmp.down_tlvs[0].bmp.info_value.#": "4", "bmp.down_tlvs[0].bmp.info_value[0].bmp.octet": "98"},
                    ref=R_BMP + "; Peer Down reason 6 of a Loc-RIB instance with a VRF/Table name TLV (RFC 9069)")))
    cap_as4 = u8(2, 6) + u8(65, 4) + u32(65551)
    sent = open_msg(64496, 90, v4("192.0.2.1"), cap_as4)
    recv = open_msg(23456, 180, v4("192.0.2.2"), u8(2, 6) + u8(65, 4) + u32(4200000000))
    body = per_peer() + b"\0" * 12 + u32(v4("192.0.2.1")) + u16(179, 50123) + sent + recv + \
        tlv(0, b"edge-1") + tlv(3, b"blue")
    msg9 = bmp(3, body)
    m9 = {"bmp.msg_type": "3", "bmp.local_ipv4": str(v4("192.0.2.1")), "bmp.local_port": "179",
          "bmp.remote_port": "50123", "bmp.sent_bgp_type": "1", "bmp.sent_open_my_as": "64496",
          "bmp.sent_open_hold_time": "90", "bmp.sent_open_parameters.#": "8",
          "bmp.received_open_my_as": "23456", "bmp.received_open_bgp_identifier": str(v4("192.0.2.2")),
          "bmp.up_tlvs.#": "2", "bmp.up_tlvs[1].bmp.info_type": "3"}
    out.append(("09-peer-up-roundtrip.json",
                vec("peer-up-roundtrip", "bgp-bmp", "bgp-bmp", msg9, msg9, m9,
                    ref=R_BMP + "; Peer Up of an IPv4 session: local address and ports, the sent and the received "
                        "OPEN (each with a 4-octet AS capability, kept as octets), a string and a VRF name TLV")))
    msg10 = bmp(4, tlv(1, b"Example Router OS 1.0") + tlv(2, b"edge-1.example") + tlv(0, b"lab"))
    out.append(("10-initiation-roundtrip.json",
                vec("initiation-roundtrip", "bgp-bmp", "bgp-bmp", msg10, msg10,
                    {"bmp.msg_type": "4", "bmp.init_tlvs.#": "3", "bmp.init_tlvs[0].bmp.info_type": "1",
                     "bmp.init_tlvs[1].bmp.info_value.#": "14"},
                    ref=R_BMP + "; Initiation with sysDescr, sysName and a string")))
    msg11 = bmp(5, tlv(1, u16(2)) + tlv(0, b"low memory"))
    out.append(("11-termination-roundtrip.json",
                vec("termination-roundtrip", "bgp-bmp", "bgp-bmp", msg11, msg11,
                    {"bmp.term_tlvs.#": "2", "bmp.term_tlvs[0].bmp.termination_reason": "2",
                     "bmp.term_tlvs[1].bmp.info_value.#": "10"},
                    ref=R_BMP + "; Termination with reason 2 (out of resources) and a string")))
    msg12 = bmp(6, per_peer() + tlv(0, bgp(4, b"")) + tlv(1, u16(1)))
    out.append(("12-route-mirroring-roundtrip.json",
                vec("route-mirroring-roundtrip", "bgp-bmp", "bgp-bmp", msg12, msg12,
                    {"bmp.msg_type": "6", "bmp.mirror_tlvs.#": "2", "bmp.mirror_tlvs[0].bmp.bgp_type": "4",
                     "bmp.mirror_tlvs[1].bmp.mirror_code": "1"},
                    ref=R_BMP + "; Route Mirroring with a mirrored KEEPALIVE and the code for lost messages")))
    bad = bytearray(msg7)
    bad[0] = 2
    out.append(("13-version-2-is-no-kind.json",
                vec("version-2-is-no-kind", "bgp-bmp", "bgp-bmp", bytes(bad), error="no-kind",
                    ref=R_BMP + "; the seventh message with version 2 in place of 3")))
    out.append(("14-truncated-is-malformed.json",
                vec("truncated-is-malformed", "bgp-bmp", "bgp-bmp", msg1_short(msg), error="malformed-wire",
                    ref=R_BMP + "; the first message without its last 5 octets, shorter than its length field")))
    return [("bgp-bmp",) + x for x in out]


def msg1_short(msg):
    return msg[:-5]


# ---------------------------------------------------------------- BFD (RFC 5880)

def bfd(auth=b"", a=None, state=3, my=0x1A2B3C4D, your=0x00C0FFEE):
    a = (1 if auth else 0) if a is None else a
    length = 24 + len(auth)
    head = u8((1 << 5) | 0, (state << 6) | (a << 2), 3, length)
    return head + u32(my, your, 300000, 300000, 0) + auth


def bfd_vectors():
    out = []
    plain = bfd()
    mp = {"inet.bfd_version": "1", "inet.bfd_state": "3", "inet.bfd_auth_present": "0", "inet.bfd_detect_mult": "3",
          "inet.bfd_length": "24", "inet.bfd_my_disc": str(0x1A2B3C4D), "inet.bfd_desired_min_tx": "300000"}
    out.append(("bfd-control-auth", "01-no-auth-roundtrip.json",
                vec("no-auth-roundtrip", "bfd-control-auth", "bfd-control-auth", plain, plain, mp,
                    ref=R_BFD + "; an Up packet without authentication")))
    pw = b"s3cret"
    simple = bfd(u8(1, 3 + len(pw), 7) + pw)
    out.append(("bfd-control-auth", "02-simple-password-roundtrip.json",
                vec("simple-password-roundtrip", "bfd-control-auth", "bfd-control-auth", simple, simple,
                    {"inet.bfd_auth_present": "1", "inet.bfd_length": "33", "bfdauth.auth_type": "1",
                     "bfdauth.auth_key_id": "7", "bfdauth.password.#": "6", "bfdauth.password[0].bfdauth.octet": "115"},
                    ref=R_BFD + "; simple password authentication with key ID 7 and a password of 6 octets")))
    digest = bytes(range(16))
    md5 = bfd(u8(3, 24, 2, 0) + u32(1001) + digest)
    out.append(("bfd-control-auth", "03-meticulous-keyed-md5-roundtrip.json",
                vec("meticulous-keyed-md5-roundtrip", "bfd-control-auth", "bfd-control-auth", md5, md5,
                    {"inet.bfd_length": "48", "bfdauth.auth_type": "3", "bfdauth.auth_key_id": "2",
                     "bfdauth.auth_sequence": "1001", "bfdauth.auth_value.#": "16"},
                    ref=R_BFD + "; meticulous keyed MD5: key ID 2, sequence 1001, a digest of 16 octets chosen here")))
    hsh = bytes(range(100, 120))
    sha = bfd(u8(4, 28, 1, 0) + u32(1234) + hsh)
    out.append(("bfd-control-auth", "04-keyed-sha1-roundtrip.json",
                vec("keyed-sha1-roundtrip", "bfd-control-auth", "bfd-control-auth", sha, sha,
                    {"inet.bfd_length": "52", "bfdauth.auth_type": "4", "bfdauth.auth_sequence": "1234",
                     "bfdauth.auth_value.#": "20", "bfdauth.auth_value[19].bfdauth.octet": "119"},
                    ref=R_BFD + "; keyed SHA1: key ID 1, sequence 1234, a hash of 20 octets chosen here")))
    # to bfd-control: the fixed pack maps the 24 octets of the mandatory section, with the A bit
    # and the length as they are; the authentication section is not in that pack
    out.append(("bfd-control-auth", "05-to-bfd-control.json",
                vec("bfd-control-auth-to-bfd-control", "bfd-control-auth", "bfd-control", sha, sha[:24],
                    ref=R_BFD + "; the keyed SHA1 packet to bfd-control: the mandatory section carries")))
    out.append(("bfd-control-auth", "06-missing-auth-section-is-malformed.json",
                vec("missing-auth-section-is-malformed", "bfd-control-auth", "bfd-control-auth",
                    bfd(a=1), error="malformed-wire",
                    ref=R_BFD + "; the A bit set and no authentication section after the 24 octets")))
    out.append(("bfd-control", "to-bfd-control-auth-mandatory-section.json",
                vec("to-bfd-control-auth-mandatory-section", "bfd-control", "bfd-control-auth", plain, plain,
                    ref=R_BFD + "; a packet without authentication from the fixed pack to bfd-control-auth: "
                        "every field carries, the A bit is 0 so no section is written")))
    return out


# ---------------------------------------------------------------- RPKI to Router (RFC 8210)

def pdu(t, field16, body):
    return u8(1, t) + u16(field16) + u32(8 + len(body)) + body


def rtr_vectors():
    S = 0x6A3F
    v6 = v6b("2001:db8:40::")
    ski = bytes(range(1, 21))
    spki = bytes(range(0x30, 0x30 + 13))
    items = [
        ("serial_notify", pdu(0, S, u32(4711)), {"rtr.session_id": str(S), "rtr.serial": "4711"}),
        ("serial_query", pdu(1, S, u32(4710)), {"rtr.serial": "4710"}),
        ("reset_query", pdu(2, 0, b""), {}),
        ("cache_response", pdu(3, S, b""), {"rtr.session_id": str(S)}),
        ("ipv4_prefix", pdu(4, 0, u8(1, 22, 24, 0) + u32(v4("192.0.2.0")) + u32(64496)),
         {"rtr.announce": "1", "rtr.prefix_length": "22", "rtr.max_length": "24",
          "rtr.ipv4_prefix": str(v4("192.0.2.0")), "rtr.asn": "64496"}),
        ("ipv6_prefix", pdu(6, 0, u8(0, 48, 48, 0) + v6 + u32(65551)),
         {"rtr.announce": "0", "rtr.prefix_length": "48",
          "rtr.ipv6_prefix_high": str(int.from_bytes(v6[:8], "big")), "rtr.ipv6_prefix_low": "0", "rtr.asn": "65551"}),
        ("end_of_data", pdu(7, S, u32(4711, 3600, 600, 7200)),
         {"rtr.serial": "4711", "rtr.refresh_interval": "3600", "rtr.retry_interval": "600",
          "rtr.expire_interval": "7200"}),
        ("cache_reset", pdu(8, 0, b""), {}),
        ("router_key", pdu(9, 0x0100, ski + u32(64496) + spki),
         {"rtr.announce": "1", "rtr.ski_0": str(int.from_bytes(ski[:8], "big")), "rtr.ski_2": str(int.from_bytes(ski[16:], "big")),
          "rtr.asn": "64496", "rtr.spki.#": "13"}),
        ("error_report", pdu(10, 2, u32(12) + pdu(1, S, u32(4710)) + u32(10) + b"no data ye"),
         {"rtr.error_code": "2", "rtr.erroneous_pdu.#": "12", "rtr.erroneous_pdu[1].rtr.octet": "1",
          "rtr.error_text.#": "10"}),
    ]
    out = []
    for i, (kind, msg, m) in enumerate(items, 1):
        mm = {"@kind": kind}
        mm.update(m)
        out.append(("rpki-rtr", "%02d-%s-roundtrip.json" % (i, kind.replace("_", "-")),
                    vec("%s-roundtrip" % kind.replace("_", "-"), "rpki-rtr", "rpki-rtr", msg, msg, mm,
                        ref=R_RTR + "; a %s PDU" % kind.replace("_", " "))))
    bad = bytearray(items[0][1])
    bad[0] = 0
    out.append(("rpki-rtr", "11-version-0-is-no-kind.json",
                vec("version-0-is-no-kind", "rpki-rtr", "rpki-rtr", bytes(bad), error="no-kind",
                    ref=R_RTR + "; a Serial Notify of version 0, which this version 1 pack does not read")))
    out.append(("rpki-rtr", "12-unknown-type-is-no-kind.json",
                vec("unknown-type-is-no-kind", "rpki-rtr", "rpki-rtr", pdu(5, 0, b""), error="no-kind",
                    ref=R_RTR + "; PDU type 5, which RFC 8210 does not define")))
    out.append(("rpki-rtr", "13-truncated-is-malformed.json",
                vec("truncated-is-malformed", "rpki-rtr", "rpki-rtr", items[4][1][:-4], error="malformed-wire",
                    ref=R_RTR + "; the IPv4 Prefix PDU without its AS number")))
    return out


def build_files(out):
    written = {}
    for pack_name, fname, v in bmp_vectors() + bfd_vectors() + rtr_vectors():
        assert v["from"] == pack_name
        out.write("packs/%s/vectors/%s" % (pack_name, fname), json.dumps(v, indent=2) + "\n")
        written[pack_name] = written.get(pack_name, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("routing-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
