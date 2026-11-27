#!/usr/bin/env python3
"""mesh-vectors: write the vectors of the low-power mesh packs.

Packs: lowpan-frame, rpl-control.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of RFC 4944 sections 5.1 to 5.3 and 11.1, RFC 6282 sections 3 and
4, RFC 7400 section 3 (the NHC bytes) and RFC 6550 sections 6.1 to 6.7: every multi-octet field
big-endian, bit fields most significant bit first.

Inputs: frames built here field by field from values chosen here; no frame is taken from a
document or a capture. Addresses are from the documentation range of RFC 3849.

`expect` of every vector is this program's packing of the decoded values, which for these frames
is the input; `model` holds values that were packed.

Usage: python3 -I tools/gen/mesh-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/mesh-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_LP = "RFC 4944 sections 5.1 to 5.3 and 11.1, RFC 6282 sections 3 and 4"
R_GHC = "RFC 6282 section 4 and RFC 7400 section 3"
R_RPL = "RFC 6550 section 6"


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def bits(fields):
    """[(value, width)] packed most significant bit first into whole octets."""
    acc, n = 0, 0
    for v, w in fields:
        assert 0 <= v < (1 << w), (v, w)
        acc, n = (acc << w) | v, n + w
    assert n % 8 == 0, n
    return acc.to_bytes(n // 8, "big")


def v6(s):
    return ipaddress.IPv6Address(s).packed


def vec(pack, name, inp, model=None, error=None, ref=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


# ---------------------------------------------------------------- 6LoWPAN

def iphc(tf, nh, hlim, sac, sam, m, dac, dam, cid=None, inline=b""):
    """The IPHC base (with the CID octet when cid is (sci, dci)) and the inline fields packed by the caller."""
    base = bits([(3, 3), (tf, 2), (nh, 1), (hlim, 2), (1 if cid else 0, 1), (sac, 1), (sam, 2), (m, 1), (dac, 1), (dam, 2)])
    if cid:
        base += bits([(cid[0], 4), (cid[1], 4)])
    return base + inline


def mesh(v, f, hops, orig, final, deep=None):
    h = bits([(2, 2), (v, 1), (f, 1), (hops, 4)])
    if hops == 15:
        h += u8(deep)
    return h + orig + final


def frag1(size, tag):
    return bits([(0b11000, 5), (size, 11), (tag, 16)])


def fragn(size, tag, offset):
    return bits([(0b11100, 5), (size, 11), (tag, 16)]) + u8(offset)


def udp_nhc(c, p, ports, checksum=None, ghc=False):
    return bits([(0b11010 if ghc else 0b11110, 5), (c, 1), (p, 2)]) + ports + (u16(checksum) if checksum is not None else b"")


def lowpan_vectors():
    p = "lowpan-frame"
    out = []
    a = iphc(3, 1, 2, 0, 3, 0, 0, 3) + udp_nhc(0, 3, bits([(1, 4), (2, 4)]), 0x1234) + b"hello"
    out.append((p, "01-iphc-link-local-udp-roundtrip.json", vec(p, "iphc-link-local-udp-roundtrip", a,
                {"lowpan.s0_a": "1", "lowpan.s0_b": "1", "lowpan.tf": "3", "lowpan.nh": "1", "lowpan.hlim": "2",
                 "lowpan.sam": "3", "lowpan.dam": "3", "lowpan.nhc_a": "15", "lowpan.nhc_b": "0", "lowpan.udp_c": "0",
                 "lowpan.udp_p": "3", "lowpan.udp_src_port_low4": "1", "lowpan.udp_dst_port_low4": "2",
                 "lowpan.udp_checksum": str(0x1234), "lowpan.udp_payload.#": "5"},
                ref=R_LP + "; IPHC with every address bit elided, hop limit 64, UDP NHC with 4-bit ports and the checksum")))
    inl = (bits([(1, 2), (10, 6), (0, 4), (0x12345, 20)]) + u8(58) + u8(17) + v6("2001:db8::1") + u8(0x1A))
    b = iphc(0, 0, 0, 0, 0, 1, 0, 3, cid=(2, 3), inline=inl) + bytes(range(8))
    out.append((p, "02-iphc-inline-fields-roundtrip.json", vec(p, "iphc-inline-fields-roundtrip", b,
                {"lowpan.cid": "1", "lowpan.sci": "2", "lowpan.dci": "3", "lowpan.ecn": "1", "lowpan.dscp": "10",
                 "lowpan.flow_label": str(0x12345), "lowpan.next_header": "58", "lowpan.hop_limit": "17",
                 "lowpan.src_inline": v6("2001:db8::1").hex(), "lowpan.m": "1", "lowpan.dst_inline": "1a",
                 "lowpan.ipv6_payload.#": "8"},
                ref=R_LP + "; IPHC with the context octet, traffic class and flow label inline, next header and hop limit "
                    "inline, a full source address and an 8-bit multicast destination")))
    inl = bits([(2, 2), (0, 2), (0xABCDE, 20)]) + u8(17) + bytes.fromhex("0211223344556677") + bytes.fromhex("ff0e00001234")
    c = iphc(1, 0, 1, 1, 1, 1, 1, 0, inline=inl) + b"\x01\x02"
    out.append((p, "03-iphc-context-and-prefix-multicast-roundtrip.json", vec(p, "iphc-context-and-prefix-multicast-roundtrip", c,
                {"lowpan.tf": "1", "lowpan.ecn": "2", "lowpan.flow_label": str(0xABCDE), "lowpan.sac": "1", "lowpan.sam": "1",
                 "lowpan.src_inline": "0211223344556677", "lowpan.dac": "1", "lowpan.dam": "0",
                 "lowpan.dst_inline": "ff0e00001234"},
                ref=R_LP + "; IPHC with the flow label only, a context-based 64-bit source and a 48-bit unicast-prefix-based "
                    "multicast destination")))
    d = iphc(2, 0, 3, 1, 0, 0, 1, 2, inline=bits([(0, 2), (46, 6)]) + u8(6) + u16(0xBEEF)) + b"\xaa"
    out.append((p, "04-iphc-unspecified-source-roundtrip.json", vec(p, "iphc-unspecified-source-roundtrip", d,
                {"lowpan.tf": "2", "lowpan.dscp": "46", "lowpan.sac": "1", "lowpan.sam": "0", "lowpan.dac": "1",
                 "lowpan.dam": "2", "lowpan.dst_inline": "beef"},
                ref=R_LP + "; IPHC with the traffic class only, the unspecified source (SAC 1, SAM 0, nothing inline) and "
                    "a context-based 16-bit destination")))
    e = (mesh(1, 1, 5, u16(1), u16(2)) + frag1(120, 0xAB) +
         iphc(3, 0, 3, 0, 2, 0, 0, 2, inline=u8(58) + u16(1) + u16(2)) + bytes(range(4)))
    out.append((p, "05-mesh-frag1-iphc-roundtrip.json", vec(p, "mesh-frag1-iphc-roundtrip", e,
                {"lowpan.s0_a": "2", "lowpan.mesh_v": "1", "lowpan.mesh_f": "1", "lowpan.hops_left": "5",
                 "lowpan.originator": "0001", "lowpan.final": "0002", "lowpan.s1_a": "3", "lowpan.s1_d": "0",
                 "lowpan.datagram_size": "120", "lowpan.datagram_tag": str(0xAB), "lowpan.s3_a": "1", "lowpan.s3_b": "1",
                 "lowpan.src_inline": "0001", "lowpan.dst_inline": "0002", "lowpan.ipv6_payload.#": "4"},
                ref=R_LP + "; a mesh header with short addresses, a first fragment header, and IPHC with 16-bit addresses")))
    ext = bits([(0b1110, 4), (0, 3), (1, 1)]) + u8(6) + bytes([1, 4, 0, 0, 0, 0])
    f = (mesh(0, 1, 15, bytes.fromhex("0011223344556677"), u16(0xFFFF), deep=40) + bits([(0b01010000, 8)]) + u8(7) +
         iphc(3, 1, 3, 0, 3, 0, 0, 3) + ext + udp_nhc(1, 0, u16(5683, 5683)) + b"\x40\x01")
    out.append((p, "06-deep-hops-broadcast-extension-header-roundtrip.json", vec(p, "deep-hops-broadcast-extension-header-roundtrip", f,
                {"lowpan.mesh_v": "0", "lowpan.hops_left": "15", "lowpan.deep_hops_left": "40",
                 "lowpan.originator": "0011223344556677", "lowpan.final": "ffff", "lowpan.s1_a": "1", "lowpan.s1_c": "16",
                 "lowpan.bc0_sequence": "7", "lowpan.s2_a": "1", "lowpan.s2_b": "1", "lowpan.nhc_a": "14",
                 "lowpan.ext_eid": "0", "lowpan.ext_nh": "1", "lowpan.ext_header.#": "6", "lowpan.after_ext.#": "7"},
                ref=R_LP + "; a mesh header with deep hops left, LOWPAN_BC0, IPHC and a hop-by-hop extension header NHC "
                    "followed by octets (a UDP NHC and payload)")))
    g = fragn(120, 0xAB, 12) + bytes(range(10))
    out.append((p, "07-fragn-roundtrip.json", vec(p, "fragn-roundtrip", g,
                {"lowpan.s0_a": "3", "lowpan.s0_d": "4", "lowpan.datagram_size": "120", "lowpan.datagram_offset": "12",
                 "lowpan.fragment_octets.#": "10"}, ref=R_LP + "; a subsequent fragment header and its octets")))
    h = u8(0x41) + bytes(range(44))
    out.append((p, "08-uncompressed-ipv6-roundtrip.json", vec(p, "uncompressed-ipv6-roundtrip", h,
                {"lowpan.s0_b": "0", "lowpan.s0_c": "1", "lowpan.ipv6_packet.#": "44"},
                ref=R_LP + "; dispatch 0x41 and an uncompressed packet, kept as octets")))
    i = u8(0x3F, 1, 2, 3)
    out.append((p, "09-not-a-lowpan-frame-roundtrip.json", vec(p, "not-a-lowpan-frame-roundtrip", i,
                {"lowpan.s0_a": "0", "lowpan.nalp_bits": str(0x3F), "lowpan.frame_octets.#": "3"},
                ref=R_LP + "; a frame of the NALP pattern 00, kept as octets")))
    j = iphc(3, 1, 3, 0, 3, 0, 0, 3) + u8(0xDF) + b"\x87\x00\x12\x34"
    out.append((p, "10-ghc-icmpv6-roundtrip.json", vec(p, "ghc-icmpv6-roundtrip", j,
                {"lowpan.nhc_a": "13", "lowpan.nhc_d": "1", "lowpan.nhc_e": "7", "lowpan.ghc_payload.#": "4"},
                ref=R_GHC + "; the ICMPv6 GHC NHC byte and a compressed payload, kept as octets")))
    k = iphc(3, 1, 3, 0, 3, 0, 0, 3) + udp_nhc(0, 0, u16(547, 546), 0x0F0F, ghc=True) + b"\x01\x02"
    out.append((p, "11-ghc-udp-roundtrip.json", vec(p, "ghc-udp-roundtrip", k,
                {"lowpan.nhc_d": "0", "lowpan.ghc_udp_c": "0", "lowpan.ghc_udp_p": "0", "lowpan.udp_src_port": "547",
                 "lowpan.udp_dst_port": "546", "lowpan.udp_checksum": str(0x0F0F), "lowpan.ghc_payload.#": "2"},
                ref=R_GHC + "; the UDP GHC NHC byte with inline ports and checksum, the compressed payload as octets")))
    out.append((p, "12-cut-iphc-is-malformed.json", vec(p, "cut-iphc-is-malformed", u8(0x7E), error="malformed-wire",
                ref=R_LP + "; the first octet of an IPHC header alone")))
    out.append((p, "13-cut-fragn-is-malformed.json", vec(p, "cut-fragn-is-malformed", fragn(120, 0xAB, 12)[:3],
                error="malformed-wire", ref=R_LP + "; a subsequent fragment header without its offset")))
    return out


# ---------------------------------------------------------------- RPL

def icmp(code, body, checksum=0x1A2B):
    return u8(155, code) + u16(checksum) + body


def opt(t, data):
    return u8(t, len(data)) + data


def rpl_vectors():
    p = "rpl-control"
    out = []
    root = v6("2001:db8::1")
    a = icmp(0, u8(0, 0))
    out.append((p, "01-dis-roundtrip.json", vec(p, "dis-roundtrip", a,
                {"inet.icmpv6_type": "155", "inet.icmpv6_code": "0", "inet.icmpv6_checksum": str(0x1A2B), "rpl.options.#": "0"},
                ref=R_RPL + ".2; a DIS with no options")))
    cfg = opt(4, bits([(0, 4), (0, 1), (1, 3)]) + u8(20, 3, 10) + u16(2048, 256, 1) + u8(0, 0xFF) + u16(0xFFFF))
    pio = opt(8, u8(64) + bits([(0, 1), (1, 1), (0, 1), (0, 5)]) + u32(0xFFFFFFFF, 0xFFFFFFFF, 0) + v6("2001:db8::"))
    b = icmp(1, u8(30, 240) + u16(256) + bits([(1, 1), (0, 1), (2, 3), (0, 3)]) + u8(240, 0, 0) + root + cfg + pio)
    out.append((p, "02-dio-config-prefix-roundtrip.json", vec(p, "dio-config-prefix-roundtrip", b,
                {"rpl.instance_id": "30", "rpl.version": "240", "rpl.rank": "256", "rpl.grounded": "1", "rpl.mop": "2",
                 "rpl.dtsn": "240", "rpl.dodagid": root.hex(), "rpl.options.#": "2",
                 "rpl.options[0].rpl.option_type": "4", "rpl.options[0].rpl.path_control_size": "1",
                 "rpl.options[0].rpl.dio_interval_doublings": "20", "rpl.options[0].rpl.dio_interval_min": "3",
                 "rpl.options[0].rpl.max_rank_increase": "2048", "rpl.options[0].rpl.min_hop_rank_increase": "256",
                 "rpl.options[0].rpl.objective_code_point": "1", "rpl.options[0].rpl.lifetime_unit": "65535",
                 "rpl.options[1].rpl.option_type": "8", "rpl.options[1].rpl.prefix_length": "64",
                 "rpl.options[1].rpl.autonomous": "1", "rpl.options[1].rpl.valid_lifetime": str(0xFFFFFFFF),
                 "rpl.options[1].rpl.prefix": v6("2001:db8::").hex()},
                ref=R_RPL + ".3 and 6.7; a grounded storing-mode DIO with DODAG configuration and prefix information options")))
    target = opt(5, u8(0, 128) + v6("2001:db8::2"))
    transit = opt(6, bits([(0, 1), (0, 7)]) + u8(0, 1, 0xFF) + root)
    c = icmp(2, u8(30) + bits([(1, 1), (0, 1), (0, 6)]) + u8(0, 5) + target + transit)
    out.append((p, "03-dao-target-transit-roundtrip.json", vec(p, "dao-target-transit-roundtrip", c,
                {"rpl.dao_k": "1", "rpl.dao_d": "0", "rpl.dao_sequence": "5", "rpl.options.#": "2",
                 "rpl.options[0].rpl.prefix_length": "128", "rpl.options[0].rpl.prefix_octets.#": "16",
                 "rpl.options[1].rpl.path_sequence": "1", "rpl.options[1].rpl.path_lifetime": "255",
                 "rpl.options[1].rpl.parent_address.#": "16"},
                ref=R_RPL + ".4 and 6.7; a non-storing DAO asking for an acknowledgement, with a target and a transit "
                    "information option naming the parent")))
    d = icmp(3, u8(30) + bits([(1, 1), (0, 7)]) + u8(5, 0) + root)
    out.append((p, "04-dao-ack-with-dodagid-roundtrip.json", vec(p, "dao-ack-with-dodagid-roundtrip", d,
                {"rpl.dao_d": "1", "rpl.dao_sequence": "5", "rpl.status": "0", "rpl.dodagid": root.hex()},
                ref=R_RPL + ".5; a DAO-ACK with the DODAGID")))
    e = icmp(0, u8(0, 0) + u8(0) + opt(1, b"\x00\x00") + opt(99, b"\x01\x02\x03"))
    out.append((p, "05-pad1-padn-unknown-option-roundtrip.json", vec(p, "pad1-padn-unknown-option-roundtrip", e,
                {"rpl.options.#": "3", "rpl.options[0].rpl.option_type": "0", "rpl.options[1].rpl.option_type": "1",
                 "rpl.options[1].rpl.option_octets.#": "2", "rpl.options[2].rpl.option_type": "99",
                 "rpl.options[2].rpl.option_octets.#": "3"},
                ref=R_RPL + ".7; a Pad1 option (no length), a PadN option and an option of an unassigned type")))
    sec = u8(0, 0, 0x00, 0) + u32(9) + u8(1)  # T 0, algorithm 0, KIM 0 LVL 0, flags, counter 9, key index 1
    f = icmp(0x8A, sec + u8(30) + bits([(1, 1), (0, 7)]) + u16(0x1234) + root + u32(7))
    out.append((p, "06-consistency-check-secured-octets-roundtrip.json", vec(p, "consistency-check-secured-octets-roundtrip", f,
                {"inet.icmpv6_code": "138", "rpl.secured_octets.#": str(len(f) - 4),
                 "@absent": ["rpl.cc_response", "rpl.cc_nonce", "rpl.destination_counter", "rpl.instance_id"]},
                ref=R_RPL + ".1 and 6.6; a consistency check, which is always secured: its security section "
                    "(9 octets) and base object kept as octets, as for 0x80-0x83")))
    g = icmp(0x80, bytes(range(12)))
    out.append((p, "07-secure-dis-octets-roundtrip.json", vec(p, "secure-dis-octets-roundtrip", g,
                {"inet.icmpv6_code": "128", "rpl.secured_octets.#": "12"},
                ref=R_RPL + ".1 and 6.2.2; a secure DIS, its security section and body kept as octets")))
    sol = opt(7, u8(30) + bits([(1, 1), (1, 1), (1, 1), (0, 5)]) + root + u8(240))
    rio = opt(3, u8(64) + bits([(0, 3), (1, 2), (0, 3)]) + u32(3600) + v6("2001:db8::")[:8])
    h = icmp(0, u8(0, 0) + sol + rio)
    out.append((p, "08-dis-solicited-route-information-roundtrip.json", vec(p, "dis-solicited-route-information-roundtrip", h,
                {"rpl.options[0].rpl.solicited_instance": "30", "rpl.options[0].rpl.solicited_v": "1",
                 "rpl.options[0].rpl.solicited_dodagid": root.hex(), "rpl.options[0].rpl.solicited_version": "240",
                 "rpl.options[1].rpl.route_preference": "1", "rpl.options[1].rpl.route_lifetime": "3600",
                 "rpl.options[1].rpl.prefix_octets.#": "8"},
                ref=R_RPL + ".2 and 6.7; a DIS with solicited information and a route information option of a /64")))
    out.append((p, "09-echo-request-is-no-kind.json", vec(p, "echo-request-is-no-kind", u8(128, 0) + u16(0) + u16(1, 1),
                error="no-kind", ref=R_RPL + "; an ICMPv6 message of type 128, not RPL")))
    out.append((p, "10-cut-dio-is-malformed.json", vec(p, "cut-dio-is-malformed", b[:20], error="malformed-wire",
                ref=R_RPL + ".3; the DIO of vector 02 cut inside its DODAGID")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in lowpan_vectors() + rpl_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("mesh-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
