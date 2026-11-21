#!/usr/bin/env python3
"""tunnels-vectors: write the vectors of the tunnelling packs.

Packs: vxlan-gpe-header, geneve-options, mpls-label-stack, ikev2-message and the ikev2-* payload
packs (sa, ke, id, cert, auth, notify, delete, ts, cp, eap).

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of draft-ietf-nvo3-vxlan-gpe-13 section 3.1, RFC 7348 section 5,
RFC 8926 sections 3.4 and 3.5, RFC 3032 section 2.1 and RFC 7296 section 3: every multi-octet
field big-endian.

Inputs: packets built here field by field from values chosen here; no packet is taken from a
document or a capture. Addresses are from the documentation ranges of RFC 5737 and RFC 3849.

`expect` of a round trip is this program's packing of the decoded values, which for these packets
is the input; of a conversion, the target header packed here from the shared values; `model`
holds values that were packed.

Usage: python3 -I tools/gen/tunnels-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/tunnels-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_GPE = "draft-ietf-nvo3-vxlan-gpe-13 section 3.1"
R_VX = "RFC 7348 section 5"
R_GEN = "RFC 8926 sections 3.4 and 3.5"
R_MPLS = "RFC 3032 section 2.1"
R_IKE = "RFC 7296 section 3"


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


def v4(s):
    return int(ipaddress.IPv4Address(s))


def v6(s):
    return ipaddress.IPv6Address(s).packed


def vec(pack, name, inp, model=None, error=None, ref="", to=None, expect=None):
    v = {"name": name, "from": pack, "to": to or pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


# ---------------------------------------------------------------- VXLAN-GPE and VXLAN

def gpe(vni, nxt, i=1, p=1, b=0, o=0, ver=0, rflags=0, res=0, res2=0):
    return bits([(rflags, 2), (ver, 2), (i, 1), (p, 1), (b, 1), (o, 1), (res, 16), (nxt, 8), (vni, 24), (res2, 8)])


def vxlan(vni, i=1, res2=0):
    # flags octet with the I bit (bit 4), 24 reserved bits, VNI, 8 reserved bits
    return bits([(0, 4), (i, 1), (0, 3), (0, 24), (vni, 24), (res2, 8)])


def gpe_vectors():
    p = "vxlan-gpe-header"
    out = []
    a = gpe(0x123456, 1)
    out.append((p, "01-ipv4-next-protocol-roundtrip.json", vec(p, "ipv4-next-protocol-roundtrip", a,
                {"inet.vxlan_i_flag": "1", "vxlangpe.p_flag": "1", "vxlangpe.next_protocol": "1", "inet.vxlan_vni": str(0x123456)},
                ref=R_GPE + "; I and P set, next protocol 1 (IPv4)")))
    b = gpe(1, 4, b=1, o=1)
    out.append((p, "02-bum-oam-nsh-roundtrip.json", vec(p, "bum-oam-nsh-roundtrip", b,
                {"vxlangpe.b_flag": "1", "vxlangpe.o_flag": "1", "vxlangpe.next_protocol": "4", "inet.vxlan_vni": "1"},
                ref=R_GPE + "; I, P, B and O set, next protocol 4 (NSH)")))
    c = gpe(5000, 3)
    out.append((p, "03-to-vxlan-header.json", vec(p, "to-vxlan-header", c, to="vxlan-header", expect=vxlan(5000),
                ref=R_GPE + " and " + R_VX + "; the I bit and the VNI carry over, the next protocol and P are dropped")))
    d = vxlan(5000)
    out.append(("vxlan-header", "08-to-vxlan-gpe-header.json",
                {**vec("vxlan-header", "to-vxlan-gpe-header", d, to=p, expect=gpe(5000, 0, p=0),
                       ref=R_VX + " and " + R_GPE + "; a VXLAN header read as VXLAN-GPE: the I bit and VNI, P and the "
                           "next protocol 0")}))
    out.append((p, "04-seven-octets-is-malformed.json", vec(p, "seven-octets-is-malformed", a[:7], error="malformed-wire",
                ref=R_GPE + "; the header without its last octet")))
    return out


# ---------------------------------------------------------------- Geneve

def gopt(cls, typ, data=b"", res=0):
    assert len(data) % 4 == 0 and len(data) <= 124
    return u16(cls) + u8(typ) + bits([(res, 3), (len(data) // 4, 5)]) + data


def geneve(opts, proto=0x6558, vni=0, o=0, c=0, ver=0, optlen=None):
    body = b"".join(opts)
    ol = len(body) // 4 if optlen is None else optlen
    return bits([(ver, 2), (ol, 6), (o, 1), (c, 1), (0, 6), (proto, 16), (vni, 24), (0, 8)]) + body


def geneve_vectors():
    p = "geneve-options"
    out = []
    two = geneve([gopt(0x0102, 0x80, b"\xde\xad\xbe\xef"), gopt(0xFFFF, 0x01)], vni=0xABCDEF, c=1)
    out.append((p, "01-two-options-roundtrip.json", vec(p, "two-options-roundtrip", two,
                {"geneve.opt_len": "3", "inet.geneve_critical": "1", "inet.geneve_vni": str(0xABCDEF), "geneve.options.#": "2",
                 "geneve.options[0].geneve.option_class": "258", "geneve.options[0].geneve.option_type": "128",
                 "geneve.options[0].geneve.length": "1", "geneve.options[0].geneve.data": "deadbeef",
                 "geneve.options[1].geneve.option_class": "65535", "geneve.options[1].geneve.length": "0"},
                ref=R_GEN + "; a critical option with 4 octets of data and an option with no data")))
    none = geneve([], proto=0x0800, vni=7, o=1)
    out.append((p, "02-control-no-options-roundtrip.json", vec(p, "control-no-options-roundtrip", none,
                {"geneve.opt_len": "0", "inet.geneve_control": "1", "inet.geneve_protocol_type": "2048", "geneve.options.#": "0"},
                ref=R_GEN + "; a control message with no options")))
    big = geneve([gopt(0x0001, 0x02, bytes(range(124)))], vni=1)
    out.append((p, "03-largest-option-roundtrip.json", vec(p, "largest-option-roundtrip", big,
                {"geneve.opt_len": "32", "geneve.options[0].geneve.length": "31"},
                ref=R_GEN + "; one option of the largest size, 124 octets of data")))
    out.append((p, "04-to-geneve-header.json", vec(p, "to-geneve-header", two, to="geneve-header",
                expect=geneve([], vni=0xABCDEF, c=1),
                ref=R_GEN + "; the base header carries over; the options are not the raw words of geneve-header, so the "
                    "option length is written 0")))
    cut = geneve([gopt(0x0102, 0x03, b"\x01\x02\x03\x04\x05\x06\x07\x08")], vni=2)[:-4]
    out.append((p, "05-cut-option-data-is-malformed.json", vec(p, "cut-option-data-is-malformed", cut, error="malformed-wire",
                ref=R_GEN + "; an option of length 2 with only one word of data")))
    return out


# ---------------------------------------------------------------- MPLS

def entry(label, tc, s, ttl):
    return bits([(label, 20), (tc, 3), (s, 1), (ttl, 8)])


def mpls_vectors():
    p = "mpls-label-stack"
    out = []
    three = entry(16000, 0, 0, 64) + entry(17000, 5, 0, 63) + entry(24001, 0, 1, 255)
    out.append((p, "01-three-entries-roundtrip.json", vec(p, "three-entries-roundtrip", three,
                {"inet.mpls_label": "16000", "inet.mpls_bottom_of_stack": "0", "mpls.entries.#": "2",
                 "mpls.entries[0].mpls.label": "17000", "mpls.entries[0].mpls.tc": "5", "mpls.entries[1].mpls.label": "24001",
                 "mpls.entries[1].mpls.bottom_of_stack": "1", "mpls.entries[1].mpls.ttl": "255"},
                ref=R_MPLS + "; a stack of three entries")))
    one = entry(100, 7, 1, 1)
    out.append((p, "02-single-entry-roundtrip.json", vec(p, "single-entry-roundtrip", one,
                {"inet.mpls_label": "100", "inet.mpls_tc": "7", "inet.mpls_bottom_of_stack": "1", "inet.mpls_ttl": "1"},
                ref=R_MPLS + "; a stack of one entry")))
    out.append((p, "03-to-mpls-label-entry.json", vec(p, "to-mpls-label-entry", three, to="mpls-label-entry",
                expect=entry(16000, 0, 0, 64), ref=R_MPLS + "; the top entry carries over, the entries below it are dropped")))
    out.append(("mpls-label-entry", "06-to-mpls-label-stack.json",
                vec("mpls-label-entry", "to-mpls-label-stack", one, to=p, expect=one,
                    ref=R_MPLS + "; one bottom entry read as a stack of one")))
    out.append((p, "04-cut-second-entry-is-malformed.json", vec(p, "cut-second-entry-is-malformed", three[:6],
                error="malformed-wire", ref=R_MPLS + "; a top entry that is not the bottom, then half an entry")))
    return out


# ---------------------------------------------------------------- IKEv2

def payload(nxt, body, c=0):
    return u8(nxt) + bits([(c, 1), (0, 7)]) + u16(len(body) + 4) + body


def ike(spi_i, spi_r, first, exch, flags, msgid, payloads=b"", length=None):
    n = 28 + len(payloads) if length is None else length
    return spi_i + spi_r + u8(first, 0x20, exch, flags) + u32(msgid, n) + payloads


def attr_tv(t, val):
    return u16(0x8000 | t, val)


def attr_tlv(t, val):
    return u16(t, len(val)) + val


def transform(last, ttype, tid, attrs=b""):
    body = u8(ttype, 0) + u16(tid) + attrs
    return u8(last, 0) + u16(len(body) + 4) + body


def proposal(last, num, proto, spi, transforms):
    body = u8(num, proto, len(spi), len(transforms)) + spi + b"".join(transforms)
    return u8(last, 0) + u16(len(body) + 4) + body


def ike_proposals():
    return proposal(0, 1, 1, b"", [transform(3, 1, 20, attr_tv(14, 256)), transform(3, 2, 5), transform(0, 4, 19)])


def ikev2_vectors():
    out = []
    SPI_I = bytes.fromhex("0102030405060708")
    SPI_R = bytes.fromhex("a1a2a3a4a5a6a7a8")

    # ---- message
    p = "ikev2-message"
    sa = ike_proposals()
    ke = u16(19, 0) + bytes(range(64))
    ni = bytes(range(100, 116))
    init = ike(SPI_I, bytes(8), 33, 34, 0x08, 0, payload(34, sa) + payload(40, ke) + payload(0, ni))
    out.append((p, "01-ike-sa-init-request-roundtrip.json", vec(p, "ike-sa-init-request-roundtrip", init,
                {"ikev2.spi_i": "0102030405060708", "ikev2.spi_r": "0000000000000000", "ikev2.first_payload": "33",
                 "ikev2.major_version": "2", "ikev2.exchange_type": "34", "ikev2.initiator": "1", "ikev2.response": "0",
                 "ikev2.payloads.#": "3", "ikev2.payloads[0].ikev2.next_payload": "34",
                 "ikev2.payloads[0].ikev2.body.#": str(len(sa)), "ikev2.payloads[1].ikev2.next_payload": "40",
                 "ikev2.payloads[1].ikev2.body.#": "68", "ikev2.payloads[2].ikev2.next_payload": "0",
                 "ikev2.payloads[2].ikev2.body.#": "16"},
                ref=R_IKE + "; an IKE_SA_INIT request: SA, KE and Nonce payloads")))
    sk = bytes(range(0x30, 0x48))
    info = ike(SPI_I, SPI_R, 46, 37, 0x20, 5, payload(42, sk))
    out.append((p, "02-informational-response-encrypted-roundtrip.json", vec(p, "informational-response-encrypted-roundtrip", info,
                {"ikev2.spi_r": "a1a2a3a4a5a6a7a8", "ikev2.first_payload": "46", "ikev2.exchange_type": "37",
                 "ikev2.response": "1", "ikev2.initiator": "0", "ikev2.message_id": "5", "ikev2.payloads.#": "1",
                 "ikev2.payloads[0].ikev2.next_payload": "42", "ikev2.payloads[0].ikev2.body.#": "24"},
                ref=R_IKE + "; an INFORMATIONAL response holding one Encrypted payload whose first inner payload is a Delete")))
    crit = ike(SPI_I, SPI_R, 49, 35, 0x08, 1, payload(0, b"\x00\x01", c=1))
    out.append((p, "03-critical-unknown-payload-roundtrip.json", vec(p, "critical-unknown-payload-roundtrip", crit,
                {"ikev2.first_payload": "49", "ikev2.payloads[0].ikev2.critical": "1", "ikev2.payloads[0].ikev2.body.#": "2"},
                ref=R_IKE + "; a payload of an unassigned type with the critical bit set, kept as octets")))
    empty = ike(SPI_I, SPI_R, 0, 37, 0x08, 2)
    out.append((p, "04-header-only-roundtrip.json", vec(p, "header-only-roundtrip", empty,
                {"ikev2.first_payload": "0", "ikev2.payloads.#": "0"}, ref=R_IKE + "; a header with no payloads")))
    out.append((p, "05-length-beyond-input-is-malformed.json", vec(p, "length-beyond-input-is-malformed",
                ike(SPI_I, SPI_R, 0, 37, 0x08, 2, length=100), error="malformed-wire",
                ref=R_IKE + "; a header whose length is longer than the input")))
    cut = ike(SPI_I, bytes(8), 40, 34, 0x08, 0, payload(0, ni)[:10], length=28 + 10)
    out.append((p, "06-cut-payload-is-malformed.json", vec(p, "cut-payload-is-malformed", cut, error="malformed-wire",
                ref=R_IKE + "; a payload whose length runs past the end of the message")))

    # ---- SA
    p = "ikev2-sa"
    a = payload(34, sa)
    out.append((p, "01-ike-proposal-roundtrip.json", vec(p, "ike-proposal-roundtrip", a,
                {"ikev2.next_payload": "34", "ikev2.proposals.#": "1", "ikev2.proposals[0].ikev2.proposal_num": "1",
                 "ikev2.proposals[0].ikev2.protocol_id": "1", "ikev2.proposals[0].ikev2.proposal_spi.#": "0",
                 "ikev2.proposals[0].ikev2.transforms.#": "3",
                 "ikev2.proposals[0].ikev2.transforms[0].ikev2.transform_type": "1",
                 "ikev2.proposals[0].ikev2.transforms[0].ikev2.transform_id": "20",
                 "ikev2.proposals[0].ikev2.transforms[0].ikev2.attributes[0].ikev2.af": "1",
                 "ikev2.proposals[0].ikev2.transforms[0].ikev2.attributes[0].ikev2.attr_type": "14",
                 "ikev2.proposals[0].ikev2.transforms[0].ikev2.attributes[0].ikev2.attr_value": "256",
                 "ikev2.proposals[0].ikev2.transforms[2].ikev2.last_substruc": "0",
                 "ikev2.proposals[0].ikev2.transforms[2].ikev2.transform_id": "19"},
                ref=R_IKE + ".3; one IKE proposal: AES-GCM with a 256-bit key length attribute, PRF HMAC-SHA-256, group 19")))
    esp = payload(0, proposal(2, 1, 3, b"\x11\x22\x33\x44", [transform(3, 1, 12, attr_tv(14, 128)), transform(3, 3, 12),
                                                            transform(0, 5, 0)]) +
                  proposal(0, 2, 3, b"\x11\x22\x33\x44", [transform(3, 1, 20, attr_tv(14, 256)), transform(0, 5, 0)]))
    out.append((p, "02-esp-two-proposals-roundtrip.json", vec(p, "esp-two-proposals-roundtrip", esp,
                {"ikev2.proposals.#": "2", "ikev2.proposals[0].ikev2.last_substruc": "2",
                 "ikev2.proposals[0].ikev2.proposal_spi.#": "4", "ikev2.proposals[0].ikev2.transforms.#": "3",
                 "ikev2.proposals[1].ikev2.proposal_num": "2", "ikev2.proposals[1].ikev2.transforms.#": "2"},
                ref=R_IKE + ".3; two ESP proposals with a 4-octet SPI: AES-CBC with HMAC-SHA-256-128, and AES-GCM; no ESN")))
    lf = payload(0, proposal(0, 1, 1, b"", [transform(0, 1, 20, attr_tlv(17, b"\x01\x02\x03"))]))
    out.append((p, "03-long-form-attribute-roundtrip.json", vec(p, "long-form-attribute-roundtrip", lf,
                {"ikev2.proposals[0].ikev2.transforms[0].ikev2.attributes[0].ikev2.af": "0",
                 "ikev2.proposals[0].ikev2.transforms[0].ikev2.attributes[0].ikev2.attr_type": "17",
                 "ikev2.proposals[0].ikev2.transforms[0].ikev2.attributes[0].ikev2.attr_octets.#": "3"},
                ref=R_IKE + ".3.5; an attribute in the type, length and value form, with 3 octets")))
    out.append((p, "04-cut-proposal-is-malformed.json", vec(p, "cut-proposal-is-malformed", a[:20] + b"",
                error="malformed-wire", ref=R_IKE + ".3; the first SA payload cut inside its proposal")))

    # ---- KE
    p = "ikev2-ke"
    k = payload(40, ke)
    out.append((p, "01-group-19-roundtrip.json", vec(p, "group-19-roundtrip", k,
                {"ikev2.next_payload": "40", "ikev2.dh_group": "19", "ikev2.ke_data.#": "64"},
                ref=R_IKE + ".4; group 19 with 64 octets of key exchange data")))
    out.append((p, "02-cut-is-malformed.json", vec(p, "cut-is-malformed", k[:30], error="malformed-wire",
                ref=R_IKE + ".4; the payload cut before the end its length gives")))

    # ---- ID
    p = "ikev2-id"
    i4 = payload(39, u8(1, 0, 0, 0) + u32(v4("192.0.2.10")))
    out.append((p, "01-ipv4-roundtrip.json", vec(p, "ipv4-roundtrip", i4,
                {"ikev2.id_type": "1", "ikev2.id_ipv4": str(v4("192.0.2.10"))}, ref=R_IKE + ".5; an IPv4 address identity")))
    fq = payload(39, u8(2, 0, 0, 0) + b"vpn.example.net")
    out.append((p, "02-fqdn-roundtrip.json", vec(p, "fqdn-roundtrip", fq, {"ikev2.id_type": "2", "ikev2.id_data.#": "15"},
                ref=R_IKE + ".5; a fully qualified domain name identity, kept as octets")))
    i6 = payload(0, u8(5, 0, 0, 0) + v6("2001:db8::1"))
    out.append((p, "03-ipv6-roundtrip.json", vec(p, "ipv6-roundtrip", i6,
                {"ikev2.id_type": "5", "ikev2.id_ipv6": v6("2001:db8::1").hex()}, ref=R_IKE + ".5; an IPv6 address identity")))

    # ---- CERT / CERTREQ
    p = "ikev2-cert"
    out.append((p, "01-x509-signature-roundtrip.json", vec(p, "x509-signature-roundtrip", payload(39, u8(4) + bytes(range(1, 21))),
                {"ikev2.cert_encoding": "4", "ikev2.cert_data.#": "20"},
                ref=R_IKE + ".6; encoding 4 with 20 octets of data (not a real certificate)")))
    out.append((p, "02-certreq-hash-roundtrip.json", vec(p, "certreq-hash-roundtrip", payload(35, u8(4) + bytes([0xAA] * 20)),
                {"ikev2.next_payload": "35", "ikev2.cert_encoding": "4", "ikev2.cert_data.#": "20"},
                ref=R_IKE + ".7; a certificate request naming one certification authority by a 20-octet hash")))

    # ---- AUTH
    p = "ikev2-auth"
    out.append((p, "01-shared-key-roundtrip.json", vec(p, "shared-key-roundtrip", payload(44, u8(2, 0, 0, 0) + bytes(range(32))),
                {"ikev2.next_payload": "44", "ikev2.auth_method": "2", "ikev2.auth_data.#": "32"},
                ref=R_IKE + ".8; shared key message integrity code, 32 octets")))

    # ---- Notify
    p = "ikev2-notify"
    nat = payload(41, u8(0, 0) + u16(16388) + bytes(range(20)))
    out.append((p, "01-nat-detection-roundtrip.json", vec(p, "nat-detection-roundtrip", nat,
                {"ikev2.protocol_id": "0", "ikev2.notify_type": "16388", "ikev2.spi_bytes.#": "0", "ikev2.notify_data.#": "20"},
                ref=R_IKE + ".10; NAT_DETECTION_SOURCE_IP with no SPI and a 20-octet hash")))
    spi = payload(0, u8(3, 4) + u16(11) + b"\x0a\x0b\x0c\x0d")
    out.append((p, "02-esp-spi-roundtrip.json", vec(p, "esp-spi-roundtrip", spi,
                {"ikev2.protocol_id": "3", "ikev2.notify_type": "11", "ikev2.spi_bytes.#": "4", "ikev2.notify_data.#": "0"},
                ref=R_IKE + ".10; a notification of type 11 about an ESP SPI of 4 octets, no data")))
    # 03 (an SPI size of 8 with 3 octets left in the payload, expected malformed-wire) was dropped: ruling
    # 14 of engine-spec 0.8 compares a count with the bits left, and ruling 7 reads the items that start
    # at the end of the extent as absent; an engine found the error, so rule 16 of the brief drops it

    # ---- Delete
    p = "ikev2-delete"
    d4 = payload(0, u8(3, 4) + u16(2) + u32(0x01020304, 0xA0B0C0D0))
    out.append((p, "01-two-esp-spis-roundtrip.json", vec(p, "two-esp-spis-roundtrip", d4,
                {"ikev2.protocol_id": "3", "ikev2.spi_size_field": "4", "ikev2.spis.#": "2",
                 "ikev2.spis[0].ikev2.spi": "01020304", "ikev2.spis[1].ikev2.spi": "a0b0c0d0"},
                ref=R_IKE + ".11; two ESP SPIs of 4 octets")))
    d0 = payload(0, u8(1, 0) + u16(0))
    out.append((p, "02-ike-sa-roundtrip.json", vec(p, "ike-sa-roundtrip", d0,
                {"ikev2.protocol_id": "1", "ikev2.spi_size_field": "0", "ikev2.num_spis_field": "0", "ikev2.spi_octets.#": "0"},
                ref=R_IKE + ".11; the deletion of the IKE SA: SPI size 0 and no SPIs")))
    d8 = payload(42, u8(1, 8) + u16(1) + bytes.fromhex("1122334455667788"))
    out.append((p, "03-eight-octet-spi-roundtrip.json", vec(p, "eight-octet-spi-roundtrip", d8,
                {"ikev2.spi_size_field": "8", "ikev2.spis.#": "1", "ikev2.spis[0].ikev2.spi": "1122334455667788"},
                ref=R_IKE + ".11; one SPI of 8 octets")))

    # ---- TS
    p = "ikev2-ts"
    sel4 = u8(7, 0) + u16(16) + u16(0, 65535) + u32(v4("192.0.2.0"), v4("192.0.2.255"))
    sel6 = u8(8, 6) + u16(40) + u16(443, 443) + v6("2001:db8::") + v6("2001:db8::ffff")
    ts = payload(45, u8(2, 0, 0, 0) + sel4 + sel6)
    out.append((p, "01-ipv4-and-ipv6-roundtrip.json", vec(p, "ipv4-and-ipv6-roundtrip", ts,
                {"ikev2.selectors.#": "2", "ikev2.selectors[0].ikev2.ts_type": "7",
                 "ikev2.selectors[0].ikev2.end_port": "65535", "ikev2.selectors[0].ikev2.start_ipv4": str(v4("192.0.2.0")),
                 "ikev2.selectors[0].ikev2.end_ipv4": str(v4("192.0.2.255")), "ikev2.selectors[1].ikev2.ip_protocol": "6",
                 "ikev2.selectors[1].ikev2.start_port": "443", "ikev2.selectors[1].ikev2.start_ipv6": v6("2001:db8::").hex(),
                 "ikev2.selectors[1].ikev2.end_ipv6": v6("2001:db8::ffff").hex()},
                ref=R_IKE + ".13; an IPv4 range of any protocol and port, and an IPv6 range for TCP port 443")))
    other = payload(0, u8(1, 0, 0, 0) + u8(13, 0) + u16(12) + u16(0, 0) + b"\x01\x02\x03\x04")
    out.append((p, "02-other-type-roundtrip.json", vec(p, "other-type-roundtrip", other,
                {"ikev2.selectors[0].ikev2.ts_type": "13", "ikev2.selectors[0].ikev2.selector_octets.#": "8"},
                ref=R_IKE + ".13; a selector of another type (13), its content after the length kept as octets")))

    # ---- CP
    p = "ikev2-cp"
    req = payload(39, u8(1, 0, 0, 0) + attr_tlv(1, b"") + attr_tlv(3, b""))
    out.append((p, "01-request-roundtrip.json", vec(p, "request-roundtrip", req,
                {"ikev2.cfg_type": "1", "ikev2.cfg_attributes.#": "2", "ikev2.cfg_attributes[0].ikev2.cfg_attr_type": "1",
                 "ikev2.cfg_attributes[0].ikev2.attr_octets.#": "0", "ikev2.cfg_attributes[1].ikev2.cfg_attr_type": "3"},
                ref=R_IKE + ".15; CFG_REQUEST for an internal IPv4 address and DNS server, empty values")))
    rep = payload(0, u8(2, 0, 0, 0) + attr_tlv(1, u32(v4("198.51.100.7"))) + attr_tlv(3, u32(v4("198.51.100.53"))))
    out.append((p, "02-reply-roundtrip.json", vec(p, "reply-roundtrip", rep,
                {"ikev2.cfg_type": "2", "ikev2.cfg_attributes[0].ikev2.attr_octets.#": "4"},
                ref=R_IKE + ".15; CFG_REPLY with an internal IPv4 address and DNS server")))

    # ---- EAP
    p = "ikev2-eap"
    rq = payload(0, u8(1, 7) + u16(5) + u8(1))
    out.append((p, "01-identity-request-roundtrip.json", vec(p, "identity-request-roundtrip", rq,
                {"ikev2.eap_code": "1", "ikev2.eap_identifier": "7", "ikev2.eap_type": "1", "ikev2.eap_data.#": "0"},
                ref=R_IKE + ".16; an EAP identity request with no type data")))
    rs = payload(0, u8(2, 7) + u16(10) + u8(1) + b"user1")
    out.append((p, "02-identity-response-roundtrip.json", vec(p, "identity-response-roundtrip", rs,
                {"ikev2.eap_code": "2", "ikev2.eap_type": "1", "ikev2.eap_data.#": "5"},
                ref=R_IKE + ".16; an EAP identity response with 5 octets of type data")))
    ok = payload(39, u8(3, 7) + u16(4))
    out.append((p, "03-success-roundtrip.json", vec(p, "success-roundtrip", ok,
                {"ikev2.eap_code": "3", "ikev2.eap_length": "4"}, ref=R_IKE + ".16; an EAP success, which has no type")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in gpe_vectors() + geneve_vectors() + mpls_vectors() + ikev2_vectors():
        assert v["from"] == pack, (pack, fname)
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("tunnels-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
