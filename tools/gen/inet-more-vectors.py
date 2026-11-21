#!/usr/bin/env python3
"""inet-more-vectors: write the vectors of the packs dns-message, dhcpv6-message and icmpv6-nd.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of RFC 1035 sections 3 and 4 (with RFC 3596, 2782, 6891 and 8659), RFC 9915
sections 8, 9 and 21, and RFC 4861 sections 4.1 to 4.6 with RFC 8106 section 5: multi-octet fields
big-endian, names as length-prefixed labels.

Inputs: messages built here from values chosen here; none is copied from a document or a capture.
Names are under example.org and example.com; addresses are from the documentation ranges of RFC 5737
and RFC 3849.

`expect` of every round trip is this program's packing of the values, which for these messages is
the input; `model` holds values that were packed.

Usage: python3 -I tools/gen/inet-more-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/inet-more-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_DNS = "RFC 1035 sections 3 and 4"
R_DHCP = "RFC 9915 sections 8, 9 and 21"
R_ND = "RFC 4861 sections 4.1 to 4.6 and RFC 8106 section 5"


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


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def v4(s):
    return int(ipaddress.IPv4Address(s))


def v6(s):
    return ipaddress.IPv6Address(s).packed


# ---------------------------------------------------------------- DNS

def dname(name, pointer=None):
    out = b""
    for label in (name.split(".") if name else []):
        out += u8(len(label)) + label.encode("ascii")
    return out + (u16(0xC000 | pointer) if pointer is not None else u8(0))


def header(id_, flags, qd, an, ns, ar):
    return u16(id_, flags, qd, an, ns, ar)


def flags(qr=0, opcode=0, aa=0, tc=0, rd=0, ra=0, z=0, rcode=0):
    return (qr << 15) | (opcode << 11) | (aa << 10) | (tc << 9) | (rd << 8) | (ra << 7) | (z << 4) | rcode


def question(name, qtype=1, qclass=1, pointer=None):
    return dname(name, pointer) + u16(qtype, qclass)


def rr(owner, rtype, rdata, ttl=300, rclass=1, pointer=None):
    return dname(owner, pointer) + u16(rtype, rclass) + u32(ttl) + u16(len(rdata)) + rdata


def dns_vectors():
    p = "dns-message"
    D = "dnsmsg."
    out = []
    q = header(0x1234, flags(rd=1), 1, 0, 0, 0) + question("www.example.org")
    out.append((p, "01-query-a-roundtrip.json", vec(p, "query-a-roundtrip", q,
                {"inet.dns_id": str(0x1234), "inet.dns_rd": "1", D + "questions.#": "1",
                 D + "questions[0]." + D + "qname_label1": "www", D + "questions[0]." + D + "qname_label2": "example",
                 D + "questions[0]." + D + "qname_label3": "org", D + "questions[0]." + D + "qname_len4": "0",
                 D + "questions[0]." + D + "qtype": "1", D + "answers.#": "0"},
                ref=R_DNS + "; a recursive query for the A record of www.example.org")))
    r = (header(0x1234, flags(qr=1, rd=1, ra=1), 1, 2, 0, 0) + question("www.example.org") +
         rr("", 5, dname("web", 16), pointer=12) + rr("web", 1, u32(v4("192.0.2.80")), pointer=16))
    out.append((p, "02-cname-and-a-compressed-roundtrip.json", vec(p, "cname-and-a-compressed-roundtrip", r,
                {"inet.dns_qr": "1", D + "answers.#": "2", D + "answers[0]." + D + "owner_t1": "3",
                 D + "answers[0]." + D + "owner_pointer": "12", D + "answers[0]." + D + "type": "5",
                 D + "answers[0]." + D + "target_label1": "web", D + "answers[0]." + D + "target_pointer": "16",
                 D + "answers[1]." + D + "owner_label1": "web", D + "answers[1]." + D + "a": str(v4("192.0.2.80"))},
                ref=R_DNS + "; a response with a CNAME and an A record whose names use compression pointers (kept as offsets)")))
    mx = (header(7, flags(qr=1, aa=1), 1, 2, 0, 0) + question("example.com", 15) +
          rr("example.com", 15, u16(10) + dname("mail.example.com")) +
          rr("example.com", 16, u8(11) + b"v=spf1 -all" + u8(3) + b"abc"))
    out.append((p, "03-mx-and-txt-roundtrip.json", vec(p, "mx-and-txt-roundtrip", mx,
                {D + "answers[0]." + D + "preference": "10", D + "answers[0]." + D + "target_label1": "mail",
                 D + "answers[1]." + D + "type": "16", D + "answers[1]." + D + "txt.#": "2",
                 D + "answers[1]." + D + "txt[0]." + D + "txt_chars.#": "11", D + "answers[1]." + D + "txt[1]." + D + "txt_chars.#": "3"},
                ref=R_DNS + "; MX and TXT records (two character strings)")))
    soa = dname("ns1.example.com") + dname("hostmaster.example.com") + u32(2026112101, 7200, 900, 1209600, 3600)
    nx = header(9, flags(qr=1, aa=1, rcode=3), 1, 0, 1, 0) + question("nope.example.com") + rr("example.com", 6, soa, ttl=3600)
    out.append((p, "04-nxdomain-soa-roundtrip.json", vec(p, "nxdomain-soa-roundtrip", nx,
                {"inet.dns_rcode": "3", D + "authority.#": "1", D + "authority[0]." + D + "mname_label1": "ns1",
                 D + "authority[0]." + D + "rname_label1": "hostmaster", D + "authority[0]." + D + "serial": "2026112101",
                 D + "authority[0]." + D + "minimum": "3600"},
                ref=R_DNS + "; a name error with the zone's SOA in the authority section")))
    srv = (header(0, flags(qr=1, aa=1), 0, 2, 0, 0) +
           rr("_http._tcp.local", 33, u16(0, 0, 8080) + dname("printer.local"), ttl=120, rclass=0x8001) +
           rr("printer.local", 28, v6("2001:db8::7"), ttl=120, rclass=0x8001))
    out.append((p, "05-mdns-srv-aaaa-roundtrip.json", vec(p, "mdns-srv-aaaa-roundtrip", srv,
                {D + "answers.#": "2", D + "answers[0]." + D + "owner_label1": "_http", D + "answers[0]." + D + "class": str(0x8001),
                 D + "answers[0]." + D + "port": "8080", D + "answers[0]." + D + "target_label1": "printer",
                 D + "answers[1]." + D + "aaaa": v6("2001:db8::7").hex()},
                ref=R_DNS + ", RFC 2782 and RFC 3596; an mDNS-style response with SRV and AAAA records (cache-flush class)")))
    opt_rr = u8(0) + u16(41, 1232) + u8(0, 0) + u16(0x8000) + u16(12) + u16(10, 8) + bytes(range(8))
    e = header(0x55AA, flags(rd=1), 1, 0, 0, 1) + question("example.org", 28) + opt_rr
    out.append((p, "06-edns-opt-cookie-roundtrip.json", vec(p, "edns-opt-cookie-roundtrip", e,
                {D + "additional.#": "1", D + "additional[0]." + D + "owner_len1": "0", D + "additional[0]." + D + "type": "41",
                 D + "additional[0]." + D + "udp_payload_size": "1232", D + "additional[0]." + D + "dnssec_ok": "1",
                 D + "additional[0]." + D + "edns_options.#": "1",
                 D + "additional[0]." + D + "edns_options[0]." + D + "option_code": "10"},
                ref=R_DNS + " and RFC 6891 section 6; a query with an EDNS OPT record (DO set, a client cookie)")))
    caa = header(3, flags(qr=1), 0, 1, 0, 0) + rr("example.org", 257, u8(0, 5) + b"issue" + b"ca.example.net")
    out.append((p, "07-caa-roundtrip.json", vec(p, "caa-roundtrip", caa,
                {D + "answers[0]." + D + "type": "257", D + "answers[0]." + D + "caa_flags": "0",
                 D + "answers[0]." + D + "caa_tag.#": "5", D + "answers[0]." + D + "caa_value.#": "14"},
                ref=R_DNS + " and RFC 8659 section 4.1; a CAA issue record")))
    hinfo = header(4, flags(qr=1), 0, 1, 0, 0) + rr("host.example.org", 13, u8(3) + b"x86" + u8(5) + b"linux")
    out.append((p, "08-other-type-octets-roundtrip.json", vec(p, "other-type-octets-roundtrip", hinfo,
                {D + "answers[0]." + D + "type": "13", D + "answers[0]." + D + "rdata.#": "10"},
                ref=R_DNS + "; an HINFO record, a type the pack keeps as octets")))
    long_name = ".".join("l%d" % i for i in range(11))
    out.append((p, "09-eleven-labels-is-no-kind.json", vec(p, "eleven-labels-is-no-kind",
                header(1, 0, 1, 0, 0, 0) + question(long_name), error="no-kind",
                ref=R_DNS + "; a name of eleven labels, beyond the ten the pack reads")))
    out.append((p, "10-cut-question-is-malformed.json", vec(p, "cut-question-is-malformed", q[:20], error="malformed-wire",
                ref=R_DNS + "; the query of vector 01 cut inside its question name")))
    return out


# ---------------------------------------------------------------- DHCPv6

def opt(code, body):
    return u16(code, len(body)) + body


def dhcp_vectors():
    p = "dhcpv6-message"
    H = "dhcpv6msg."
    out = []
    llt = u16(1, 1) + u32(800000000) + bytes.fromhex("02005e0010aa")
    s = (u8(1) + bytes.fromhex("a1b2c3") + opt(8, u16(0)) + opt(1, llt) + opt(3, u32(1, 0, 0)) + opt(6, u16(23, 24)) + opt(14, b""))
    out.append((p, "01-solicit-roundtrip.json", vec(p, "solicit-roundtrip", s,
                {H + "msg_type": "1", H + "transaction_id": str(0xA1B2C3), H + "options.#": "5",
                 H + "options[0]." + H + "elapsed_time": "0", H + "options[1]." + H + "duid_type": "1",
                 H + "options[1]." + H + "duid_time": "800000000", H + "options[1]." + H + "link_layer_address.#": "6",
                 H + "options[2]." + H + "iaid": "1", H + "options[3]." + H + "requested_options.#": "2",
                 H + "options[4]." + H + "option_code": "14"},
                ref=R_DHCP + "; a SOLICIT with elapsed time, a DUID-LLT client ID, an empty IA_NA, an ORO and rapid commit")))
    iaaddr = v6("2001:db8::100") + u32(3600, 7200) + opt(13, u16(0) + b"ok")
    rp = (u8(7) + bytes.fromhex("a1b2c3") + opt(2, u16(3, 1) + bytes.fromhex("02005e0010bb")) +
          opt(1, u16(2) + u32(32473) + b"\x01\x02\x03\x04") + opt(3, u32(1, 1800, 2880) + opt(5, iaaddr)) + opt(7, u8(255)) +
          opt(23, v6("2001:db8::53") + v6("2001:db8::54")))
    out.append((p, "02-reply-ia-address-roundtrip.json", vec(p, "reply-ia-address-roundtrip", rp,
                {H + "msg_type": "7", H + "options[0]." + H + "duid_type": "3", H + "options[1]." + H + "enterprise_number": "32473",
                 H + "options[2]." + H + "t1": "1800", H + "options[2]." + H + "ia_options.#": "1",
                 H + "options[2]." + H + "ia_options[0]." + H + "ia_address": v6("2001:db8::100").hex(),
                 H + "options[2]." + H + "ia_options[0]." + H + "valid_lifetime": "7200",
                 H + "options[2]." + H + "ia_options[0]." + H + "addr_options[0]." + H + "status_code": "0",
                 H + "options[3]." + H + "preference": "255", H + "options[4]." + H + "dns_servers.#": "2"},
                ref=R_DHCP + "; a REPLY with server and client IDs, an IA_NA holding an address with a status option, preference and DNS servers")))
    pd = u8(7) + bytes.fromhex("000001") + opt(25, u32(7, 0, 0) + opt(26, u32(3600, 7200) + u8(56) + v6("2001:db8:ab00::")))
    out.append((p, "03-ia-pd-prefix-roundtrip.json", vec(p, "ia-pd-prefix-roundtrip", pd,
                {H + "options[0]." + H + "option_code": "25", H + "options[0]." + H + "ia_options[0]." + H + "prefix_length": "56",
                 H + "options[0]." + H + "ia_options[0]." + H + "ia_prefix": v6("2001:db8:ab00::").hex()},
                ref=R_DHCP + "; a REPLY with an IA_PD delegating a /56")))
    relay = u8(12, 0) + v6("2001:db8:1::1") + v6("fe80::1") + opt(18, b"eth0") + opt(9, s)
    out.append((p, "04-relay-forward-roundtrip.json", vec(p, "relay-forward-roundtrip", relay,
                {H + "msg_type": "12", H + "hop_count": "0", H + "link_address": v6("2001:db8:1::1").hex(),
                 H + "peer_address": v6("fe80::1").hex(), H + "options[0]." + H + "option_code": "18",
                 H + "options[1]." + H + "option_code": "9", H + "options[1]." + H + "option_data.#": str(len(s))},
                ref=R_DHCP + "; a RELAY-FORW with an interface ID and the relayed SOLICIT (kept as octets)")))
    oth = u8(11) + bytes.fromhex("0000ff") + opt(1, u16(4) + bytes(range(16))) + opt(39, u8(1) + b"\x04host")
    out.append((p, "05-uuid-and-other-option-roundtrip.json", vec(p, "uuid-and-other-option-roundtrip", oth,
                {H + "options[0]." + H + "duid_type": "4", H + "options[0]." + H + "duid_uuid": bytes(range(16)).hex(),
                 H + "options[1]." + H + "option_code": "39", H + "options[1]." + H + "option_data.#": "6"},
                ref=R_DHCP + "; an INFORMATION-REQUEST with a DUID-UUID and a client FQDN option kept as octets")))
    out.append((p, "06-cut-option-is-malformed.json", vec(p, "cut-option-is-malformed", s[:12], error="malformed-wire",
                ref=R_DHCP + "; the SOLICIT of vector 01 cut inside an option")))
    return out


# ---------------------------------------------------------------- ICMPv6 ND

def ndopt(t, body):
    assert (len(body) + 2) % 8 == 0
    return u8(t, (len(body) + 2) // 8) + body


MAC = bytes.fromhex("02005e0010aa")


def nd_vectors():
    p = "icmpv6-nd"
    N = "icmpnd."
    out = []
    rs = u8(133, 0) + u16(0x1111) + u32(0) + ndopt(1, MAC)
    out.append((p, "01-router-solicitation-roundtrip.json", vec(p, "router-solicitation-roundtrip", rs,
                {"inet.icmpv6_type": "133", N + "options.#": "1", N + "options[0]." + N + "option_type": "1",
                 N + "options[0]." + N + "link_layer_address": MAC.hex()},
                ref=R_ND + "; a router solicitation with the source link-layer address")))
    pio = u8(64) + u8(0xC0) + u32(86400, 14400, 0) + v6("2001:db8:1::")
    ra = (u8(134, 0) + u16(0x2222) + u8(64, 0x40) + u16(1800) + u32(0, 0) + ndopt(3, pio) + ndopt(5, u16(0) + u32(1500)) +
          ndopt(1, MAC) + ndopt(25, u16(0) + u32(3600) + v6("2001:db8::53")))
    out.append((p, "02-router-advertisement-roundtrip.json", vec(p, "router-advertisement-roundtrip", ra,
                {"inet.icmpv6_type": "134", "inet.icmpv6_ra_cur_hop_limit": "64", "inet.icmpv6_ra_other": "1",
                 "inet.icmpv6_ra_router_lifetime": "1800", N + "options.#": "4", N + "options[0]." + N + "prefix_length": "64",
                 N + "options[0]." + N + "on_link": "1", N + "options[0]." + N + "autonomous": "1",
                 N + "options[0]." + N + "prefix": v6("2001:db8:1::").hex(), N + "options[1]." + N + "mtu": "1500",
                 N + "options[3]." + N + "rdnss_lifetime": "3600", N + "options[3]." + N + "rdnss_addresses": v6("2001:db8::53").hex()},
                ref=R_ND + "; a router advertisement with prefix information, MTU, source link-layer address and RDNSS")))
    ns = u8(135, 0) + u16(0x3333) + u32(0) + v6("2001:db8:1::5") + ndopt(1, MAC)
    out.append((p, "03-neighbor-solicitation-roundtrip.json", vec(p, "neighbor-solicitation-roundtrip", ns,
                {"inet.icmpv6_type": "135", N + "target": v6("2001:db8:1::5").hex()}, ref=R_ND + "; a neighbor solicitation")))
    na = u8(136, 0) + u16(0x4444) + u32(0xE0000000) + v6("2001:db8:1::5") + ndopt(2, MAC)
    out.append((p, "04-neighbor-advertisement-roundtrip.json", vec(p, "neighbor-advertisement-roundtrip", na,
                {"inet.icmpv6_type": "136", N + "router": "1", N + "solicited": "1", N + "override": "1",
                 N + "options[0]." + N + "option_type": "2"}, ref=R_ND + "; a neighbor advertisement with R, S and O set")))
    rd = (u8(137, 0) + u16(0x5555) + u32(0) + v6("fe80::1") + v6("2001:db8:2::9") + ndopt(2, MAC) +
          ndopt(4, bytes(6) + bytes.fromhex("6000000000083a40")))
    out.append((p, "05-redirect-roundtrip.json", vec(p, "redirect-roundtrip", rd,
                {"inet.icmpv6_type": "137", N + "destination": v6("2001:db8:2::9").hex(), N + "options.#": "2",
                 N + "options[1]." + N + "option_length": "2", N + "options[1]." + N + "redirected_packet": "6000000000083a40"},
                ref=R_ND + "; a redirect with the target link-layer address and the start of the redirected packet")))
    nonce = u8(135, 0) + u16(0x6666) + u32(0) + v6("2001:db8:1::5") + ndopt(14, bytes(range(1, 7)))
    out.append((p, "06-other-option-roundtrip.json", vec(p, "other-option-roundtrip", nonce,
                {N + "options[0]." + N + "option_type": "14", N + "options[0]." + N + "option_data": bytes(range(1, 7)).hex()},
                ref=R_ND + "; a neighbor solicitation with a nonce option, kept as hex")))
    out.append((p, "07-cut-option-is-malformed.json", vec(p, "cut-option-is-malformed", ra[:30], error="malformed-wire",
                ref=R_ND + "; the router advertisement of vector 02 cut inside its prefix option")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in dns_vectors() + dhcp_vectors() + nd_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("inet-more-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
