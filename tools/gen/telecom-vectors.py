#!/usr/bin/env python3
"""telecom-vectors: write the vectors of the diameter and sctp-packet packs (and one cross vector
under sctp-common-header).

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of RFC 6733 sections 3, 4.1 to 4.5 (Diameter header, AVP header,
basic and derived data formats, the base protocol AVPs) and RFC 9260 sections 3.1 to 3.3 (SCTP
common header, chunks, parameters, error causes): every multi-octet field big-endian; AVPs, chunks,
parameters and causes padded with zero octets to a multiple of 4.

Inputs: messages built here field by field from values chosen here; no message is taken from a
document. The SCTP checksums are values chosen here: the packs carry the checksum, they do not
compute or check it. Addresses are from the documentation ranges of RFC 5737 and RFC 3849.

`expect` of a same-format vector is this program's packing of the decoded values, which for these
messages is the input. `expect` of the conversions between sctp-packet and sctp-common-header is
worked out from the rules of spec/engine-spec.md: the common header carries through the inet keys
both packs map; the fixed pack writes its 12 octets, and the chunk list is absent in the other.

Usage: python3 -I tools/gen/telecom-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/telecom-vectors.py from values chosen there; layout restated from %s; "
          "expect derived there, no engine run")
RD = "RFC 6733 sections 3 and 4"
RS = "RFC 9260 sections 3.1 to 3.3"


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def u64(v):
    return struct.pack(">Q", v)


def pad4(b):
    return b + b"\0" * (-len(b) % 4)


def v4(t):
    return int(ipaddress.IPv4Address(t))


def vec(frm, name, inp, to=None, expect=None, model=None, error=None, ref=""):
    v = {"name": name, "from": frm, "to": to or frm, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


# ---------------------------------------------------------------- Diameter

def avp(code, data, m=1, vendor=None):
    flags = (0x80 if vendor is not None else 0) | (0x40 if m else 0)
    head = u32(code) + u8(flags) + (8 + (4 if vendor is not None else 0) + len(data)).to_bytes(3, "big")
    return pad4(head + (u32(vendor) if vendor is not None else b"") + data)


def diameter(code, app, hbh, e2e, avps, r=1, p=0, e=0, t=0):
    body = b"".join(avps)
    flags = (r << 7) | (p << 6) | (e << 5) | (t << 4)
    return u8(1) + (20 + len(body)).to_bytes(3, "big") + u8(flags) + code.to_bytes(3, "big") + u32(app, hbh, e2e) + body


def diameter_vectors():
    out = []
    cer = diameter(257, 0, 0x1001, 0x52000001, [
        avp(264, b"client.example.org"), avp(296, b"example.org"), avp(257, u16(1) + u32(v4("192.0.2.10"))),
        avp(266, u32(32473)), avp(269, b"goat-test", m=0), avp(267, u32(3), m=0), avp(258, u32(4294967295)),
        avp(260, avp(266, u32(10415)) + avp(258, u32(16777251)))])
    out.append(("01-capabilities-exchange-request-roundtrip.json", vec("diameter", "capabilities-exchange-request-roundtrip", cer,
                model={"@kind": "message", "diameter.flag_r": "1", "diameter.command_code": "257",
                       "diameter.hop_by_hop_id": str(0x1001), "diameter.avps.#": "8",
                       "diameter.avps[0].diameter.avp_code": "264", "diameter.avps[0].diameter.avp_flag_m": "1",
                       "diameter.avps[0].diameter.avp_data.#": "18", "diameter.avps[2].diameter.address_family": "1",
                       "diameter.avps[2].diameter.address_ipv4": str(v4("192.0.2.10")),
                       "diameter.avps[4].diameter.avp_flag_m": "0", "diameter.avps[6].diameter.unsigned32": "4294967295",
                       "diameter.avps[7].diameter.grouped_avps.#": "2",
                       "diameter.avps[7].diameter.grouped_avps[1].diameter.unsigned32": "16777251"},
                ref=RD + "; a Capabilities-Exchange-Request with identities, an IPv4 Host-IP-Address, Vendor-Id, "
                    "Product-Name, Firmware-Revision, Auth-Application-Id and a grouped Vendor-Specific-Application-Id")))
    cea = diameter(257, 0, 0x1001, 0x52000001, [
        avp(268, u32(2001)), avp(264, b"server.example.org"), avp(296, b"example.org"),
        avp(257, u16(2) + ipaddress.IPv6Address("2001:db8::10").packed), avp(269, b"srv", m=0)], r=0)
    out.append(("02-capabilities-exchange-answer-roundtrip.json", vec("diameter", "capabilities-exchange-answer-roundtrip", cea,
                model={"diameter.flag_r": "0", "diameter.avps[0].diameter.unsigned32": "2001",
                       "diameter.avps[3].diameter.address_family": "2",
                       "diameter.avps[3].diameter.address_ipv6": ipaddress.IPv6Address("2001:db8::10").packed.hex(),
                       "diameter.avps[4].diameter.avp_data.#": "3"},
                ref=RD + "; a Capabilities-Exchange-Answer with Result-Code 2001, an IPv6 Host-IP-Address and a "
                    "three-octet Product-Name padded to four")))
    dwr = diameter(280, 0, 0x1002, 0x52000002, [
        avp(264, b"client.example.org"), avp(296, b"example.org"), avp(278, u32(1773480413)),
        avp(1000, u32(7), vendor=10415)], t=1)
    out.append(("03-device-watchdog-vendor-avp-roundtrip.json", vec("diameter", "device-watchdog-vendor-avp-roundtrip", dwr,
                model={"diameter.command_code": "280", "diameter.flag_t": "1", "diameter.avps[2].diameter.unsigned32": "1773480413",
                       "diameter.avps[3].diameter.avp_flag_v": "1", "diameter.avps[3].diameter.vendor_id": "10415",
                       "diameter.avps[3].diameter.avp_data.#": "4"},
                ref=RD + "; a Device-Watchdog-Request with Origin-State-Id and a vendor-specific AVP (vendor 10415, "
                    "its data kept as octets)")))
    nested = avp(297, avp(266, u32(10415)) + avp(298, u32(5001)))
    acr = diameter(271, 3, 0x1003, 0x52000003, [
        avp(263, b"client.example.org;1;77"), avp(268, u32(5005)), avp(55, u32(3982469213)), avp(287, u64(42)),
        avp(279, nested)], r=0, e=1)
    out.append(("04-accounting-answer-failed-avp-roundtrip.json", vec("diameter", "accounting-answer-failed-avp-roundtrip", acr,
                model={"diameter.application_id": "3", "diameter.flag_e": "1", "diameter.avps[2].diameter.time": "3982469213",
                       "diameter.avps[3].diameter.unsigned64": "42", "diameter.avps[4].diameter.grouped_avps.#": "1",
                       "diameter.avps[4].diameter.grouped_avps[0].diameter.avp_code": "297",
                       "diameter.avps[4].diameter.grouped_avps[0].diameter.avp_data.#": str(len(nested) - 8)},
                ref=RD + "; an Accounting-Answer with an error: Event-Timestamp, Accounting-Sub-Session-Id and a "
                    "Failed-AVP holding a grouped Experimental-Result, which, two levels down, is kept as octets")))
    bad = bytearray(dwr)
    bad[0] = 2
    out.append(("05-version-2-is-no-kind.json", vec("diameter", "version-2-is-no-kind", bytes(bad), error="no-kind",
                ref=RD + "; the watchdog request with version 2 in place of 1")))
    out.append(("06-truncated-is-malformed.json", vec("diameter", "truncated-is-malformed", dwr[:-4], error="malformed-wire",
                ref=RD + "; the watchdog request without its last 4 octets, shorter than its length")))
    return [("diameter",) + x for x in out]


# ---------------------------------------------------------------- SCTP

def chunk(t, flags, body):
    return pad4(u8(t, flags) + u16(4 + len(body)) + body)


def tlv(t, value):
    return pad4(u16(t, 4 + len(value)) + value)


def sctp(sport, dport, vtag, cksum, chunks):
    return u16(sport, dport) + u32(vtag, cksum) + b"".join(chunks)


def sctp_vectors():
    out = []
    init_params = (tlv(5, u32(v4("192.0.2.10"))) + tlv(6, ipaddress.IPv6Address("2001:db8::10").packed) +
                   tlv(12, u16(5, 6)) + tlv(9, u32(1000)))
    init = sctp(5000, 3868, 0, 0x1A2B3C4D, [chunk(1, 0, u32(0xA1B2C3D4, 65535) + u16(10, 10) + u32(100) + init_params)])
    out.append(("sctp-packet", "01-init-roundtrip.json", vec("sctp-packet", "init-roundtrip", init,
                model={"inet.src_port": "5000", "inet.dst_port": "3868", "inet.sctp_verification_tag": "0",
                       "sctp.chunks.#": "1", "sctp.chunks[0].sctp.chunk_type": "1",
                       "sctp.chunks[0].sctp.initiate_tag": str(0xA1B2C3D4), "sctp.chunks[0].sctp.outbound_streams": "10",
                       "sctp.chunks[0].sctp.parameters.#": "4",
                       "sctp.chunks[0].sctp.parameters[0].sctp.ipv4_address": str(v4("192.0.2.10")),
                       "sctp.chunks[0].sctp.parameters[1].sctp.ipv6_address": ipaddress.IPv6Address("2001:db8::10").packed.hex(),
                       "sctp.chunks[0].sctp.parameters[2].sctp.address_types.#": "2",
                       "sctp.chunks[0].sctp.parameters[3].sctp.cookie_increment": "1000"},
                ref=RS + "; an INIT with IPv4 and IPv6 addresses, the supported address types and a cookie "
                    "preservative")))
    ack = sctp(3868, 5000, 0xA1B2C3D4, 0x0BADF00D, [chunk(2, 0, u32(0x55667788, 65535) + u16(10, 10) + u32(900) +
                                                          tlv(7, b"cookie-bytes-x") + tlv(8, tlv(0x8001, b"")))])
    out.append(("sctp-packet", "02-init-ack-roundtrip.json", vec("sctp-packet", "init-ack-roundtrip", ack,
                model={"sctp.chunks[0].sctp.chunk_type": "2", "sctp.chunks[0].sctp.parameters.#": "2",
                       "sctp.chunks[0].sctp.parameters[0].sctp.param_type": "7",
                       "sctp.chunks[0].sctp.parameters[0].sctp.value.#": "14",
                       "sctp.chunks[0].sctp.parameters[1].sctp.value.#": "4"},
                ref=RS + "; an INIT ACK with a state cookie of 14 octets (padded) and an unrecognized parameter")))
    data = sctp(5000, 3868, 0x55667788, 0x11111111, [
        chunk(0, 0x03, u32(100) + u16(1, 0) + u32(46) + b"hello"),
        chunk(3, 0, u32(99, 65000) + u16(2, 1) + u16(2, 3, 5, 5) + u32(97))])
    out.append(("sctp-packet", "03-data-and-sack-roundtrip.json", vec("sctp-packet", "data-and-sack-roundtrip", data,
                model={"sctp.chunks.#": "2", "sctp.chunks[0].sctp.chunk_flags": "3", "sctp.chunks[0].sctp.tsn": "100",
                       "sctp.chunks[0].sctp.ppid": "46", "sctp.chunks[0].sctp.user_data.#": "5",
                       "sctp.chunks[1].sctp.cum_tsn_ack": "99", "sctp.chunks[1].sctp.gap_blocks.#": "2",
                       "sctp.chunks[1].sctp.gap_blocks[1].sctp.gap_end": "5", "sctp.chunks[1].sctp.duplicate_tsns.#": "1",
                       "sctp.chunks[1].sctp.duplicate_tsns[0].sctp.duplicate_tsn": "97"},
                ref=RS + "; a packet bundling a DATA chunk (beginning and end, 5 octets of data, padded) and a SACK "
                    "with two gap blocks and one duplicate TSN")))
    hb = sctp(5000, 3868, 0x55667788, 0x22222222, [chunk(4, 0, tlv(1, b"0123456789")), chunk(5, 0, tlv(1, b"0123456789"))])
    out.append(("sctp-packet", "04-heartbeat-roundtrip.json", vec("sctp-packet", "heartbeat-roundtrip", hb,
                model={"sctp.chunks[0].sctp.parameters[0].sctp.param_type": "1",
                       "sctp.chunks[1].sctp.parameters[0].sctp.value.#": "10"},
                ref=RS + "; a HEARTBEAT and a HEARTBEAT ACK with heartbeat information of 10 octets")))
    ab = sctp(5000, 3868, 0x55667788, 0x33333333, [chunk(6, 0x01, tlv(1, u16(7, 0)) + tlv(12, b"bye") + tlv(3, u32(5000000)))])
    out.append(("sctp-packet", "05-abort-roundtrip.json", vec("sctp-packet", "abort-roundtrip", ab,
                model={"sctp.chunks[0].sctp.chunk_flags": "1", "sctp.chunks[0].sctp.causes.#": "3",
                       "sctp.chunks[0].sctp.causes[0].sctp.stream_id": "7",
                       "sctp.chunks[0].sctp.causes[1].sctp.value.#": "3",
                       "sctp.chunks[0].sctp.causes[2].sctp.staleness": "5000000"},
                ref=RS + "; an ABORT with the T bit and three causes: invalid stream identifier, a user-initiated "
                    "abort reason, a stale cookie")))
    end = sctp(5000, 3868, 0x55667788, 0x44444444, [
        chunk(10, 0, b"cookie"), chunk(11, 0, b""), chunk(9, 0, tlv(9, u32(101))), chunk(7, 0, u32(101)),
        chunk(8, 0, b""), chunk(14, 0x01, b"")])
    out.append(("sctp-packet", "06-cookie-error-shutdown-roundtrip.json", vec("sctp-packet", "cookie-error-shutdown-roundtrip", end,
                model={"sctp.chunks.#": "6", "sctp.chunks[0].sctp.cookie.#": "6",
                       "sctp.chunks[2].sctp.causes[0].sctp.tsn": "101", "sctp.chunks[3].sctp.cum_tsn_ack": "101",
                       "sctp.chunks[5].sctp.chunk_type": "14"},
                ref=RS + "; COOKIE ECHO, COOKIE ACK, an ERROR with a No User Data cause, SHUTDOWN, SHUTDOWN ACK and "
                    "SHUTDOWN COMPLETE in one packet (a sequence for the test, not one association's)")))
    unk = sctp(5000, 3868, 1, 0x55555555, [chunk(192, 0, b"\x01\x02\x03")])
    out.append(("sctp-packet", "07-unknown-chunk-roundtrip.json", vec("sctp-packet", "unknown-chunk-roundtrip", unk,
                model={"sctp.chunks[0].sctp.chunk_type": "192", "sctp.chunks[0].sctp.value.#": "3"},
                ref=RS + "; a chunk of type 192 (FORWARD TSN of RFC 3758) kept as octets")))
    out.append(("sctp-packet", "08-truncated-is-malformed.json", vec("sctp-packet", "truncated-is-malformed", data[:-4],
                error="malformed-wire", ref=RS + "; the DATA and SACK packet without its last 4 octets")))
    out.append(("sctp-packet", "09-to-sctp-common-header.json", vec("sctp-packet", "sctp-packet-to-sctp-common-header", data,
                to="sctp-common-header", expect=data[:12],
                ref=RS + "; the DATA and SACK packet to sctp-common-header: the 12 octets of the common header")))
    hdr = data[:12]
    out.append(("sctp-common-header", "to-sctp-packet-common-header.json", vec("sctp-common-header", "to-sctp-packet-common-header",
                hdr, to="sctp-packet", expect=hdr,
                ref=RS + "; a common header from sctp-common-header to sctp-packet: the header carries, the chunk list "
                    "is absent and writes nothing")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in diameter_vectors() + sctp_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("telecom-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
