#!/usr/bin/env python3
"""ietf-more-vectors: write the vectors of the IPPM test packet packs, pcep and hsrp.

Packs: owamp-test, owamp-test-auth, twamp-reflector, twamp-reflector-auth, stamp-sender,
stamp-reflector, stamp-sender-auth, stamp-reflector-auth, pcep, hsrp.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of RFC 4656 section 4.1.2, RFC 5357 section 4.2.1, RFC 8762
sections 4.2 and 4.3 with RFC 8972 sections 3 and 4 (test packets and STAMP TLVs), RFC 5440
sections 6 and 7 with RFC 3209 section 4.3.3 (PCEP and route subobjects) and RFC 2281 section
5.1 (HSRP): every multi-octet field big-endian.

Inputs: messages built here field by field from values chosen here. No message is taken from a
document. Addresses are from the documentation ranges of RFC 5737 and RFC 3849, AS numbers from
those of RFC 5398.

`expect` of a same-format vector is this program's packing of the decoded values, which for these
messages is the input. `expect` of a conversion between the test packet packs is worked out from
the rules of spec/engine-spec.md: the keys both packs map carry, a key the source does not map is
absent and written as zero, MBZ runs are zero, and a list the target does not map is dropped.

Usage: python3 -I tools/gen/ietf-more-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/ietf-more-vectors.py from values chosen there; layout restated "
          "from %s; expect derived there, no engine run")


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def f32(x):
    return struct.pack(">f", x)


def v4(text):
    return int(ipaddress.IPv4Address(text))


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


# ---------------------------------------------------------------- IPPM test packets

NTP_SEC = 1773480413 + 2208988800        # 2026-03-14T09:26:53Z in the NTP era
R_OW = "RFC 4656 section 4.1.2"
R_TW = "RFC 5357 section 4.2.1"
R_ST = "RFC 8762 sections 4.2 and 4.3 and RFC 8972 sections 3 and 4"


def ts(sec, frac):
    return u32(sec, frac)


def err(s, z, scale, mult):
    return u8((s << 7) | (z << 6) | scale, mult)


def tlv(t, value, u=0, m=0, i=0):
    return u8((u << 7) | (m << 6) | (i << 5), t) + u16(len(value)) + value


HMAC = bytes(range(0x10, 0x20))


def ippm_vectors():
    out = []
    ts1, ts2, ts3 = ts(NTP_SEC, 0x40000000), ts(NTP_SEC, 0x40100000), ts(NTP_SEC, 0x40200000)
    e1, e2 = err(1, 0, 4, 1), err(0, 0, 10, 3)
    pad = bytes(range(14))

    ow = u32(7) + ts1 + e1 + pad
    out.append(("owamp-test", "01-test-packet-roundtrip.json",
                vec("test-packet-roundtrip", "owamp-test", "owamp-test", ow, ow,
                    {"ippm.sequence": "7", "ippm.ts_sec": str(NTP_SEC), "ippm.ts_frac": str(0x40000000),
                     "ippm.err_s": "1", "ippm.err_scale": "4", "ippm.err_multiplier": "1", "ippm.padding.#": "14"},
                    ref=R_OW + "; a test packet with 14 octets of padding")))
    # to stamp-sender: sequence, timestamp and error estimate carry; the SSID is absent (0), the
    # 28 MBZ octets are zero, the padding has no line there and the TLV list is absent
    st_from_ow = u32(7) + ts1 + e1 + u16(0) + b"\0" * 28
    out.append(("owamp-test", "02-owamp-test-to-stamp-sender.json",
                vec("owamp-test-to-stamp-sender", "owamp-test", "stamp-sender", ow, st_from_ow,
                    ref=R_OW + " and " + R_ST + "; the test packet as a STAMP Session-Sender packet")))
    owa = u32(8) + b"\0" * 12 + ts1 + e1 + b"\0" * 6 + HMAC
    out.append(("owamp-test-auth", "01-authenticated-roundtrip.json",
                vec("authenticated-roundtrip", "owamp-test-auth", "owamp-test-auth", owa, owa,
                    {"ippm.sequence": "8", "ippm.ts_frac": str(0x40000000),
                     "ippm.hmac_high": str(int.from_bytes(HMAC[:8], "big")), "ippm.padding.#": "0"},
                    ref=R_OW + "; an authenticated-mode test packet without padding")))

    tw = u32(101) + ts3 + e2 + u16(0) + ts2 + u32(7) + ts1 + e1 + u16(0) + u8(254) + b"\x00\x01\x02"
    mtw = {"ippm.sequence": "101", "ippm.rcv_ts_frac": str(0x40100000), "ippm.sender_sequence": "7",
           "ippm.sender_ts_frac": str(0x40000000), "ippm.sender_err_s": "1", "ippm.sender_ttl": "254",
           "ippm.padding.#": "3"}
    out.append(("twamp-reflector", "01-reflector-roundtrip.json",
                vec("reflector-roundtrip", "twamp-reflector", "twamp-reflector", tw, tw, mtw,
                    ref=R_TW + "; a reflected packet with 3 octets of padding")))
    st_from_tw = u32(101) + ts3 + e2 + u16(0) + ts2 + u32(7) + ts1 + e1 + u16(0) + u8(254) + b"\0" * 3
    out.append(("twamp-reflector", "02-twamp-reflector-to-stamp-reflector.json",
                vec("twamp-reflector-to-stamp-reflector", "twamp-reflector", "stamp-reflector", tw, st_from_tw,
                    ref=R_TW + " and " + R_ST + "; the reflected packet as a STAMP Session-Reflector packet "
                        "(SSID 0, padding dropped)")))
    twa = (u32(102) + b"\0" * 12 + ts3 + e2 + b"\0" * 6 + ts2 + b"\0" * 8 + u32(8) + b"\0" * 12 + ts1 + e1 +
           b"\0" * 6 + u8(255) + b"\0" * 15 + HMAC)
    out.append(("twamp-reflector-auth", "01-authenticated-roundtrip.json",
                vec("authenticated-roundtrip", "twamp-reflector-auth", "twamp-reflector-auth", twa, twa,
                    {"ippm.sequence": "102", "ippm.sender_sequence": "8", "ippm.sender_ttl": "255",
                     "ippm.hmac_low": str(int.from_bytes(HMAC[8:], "big"))},
                    ref=R_TW + "; an authenticated-mode reflected packet")))

    tl = (tlv(3, u8(1, 2, 1, 3)) + tlv(4, u16((46 << 10) | (0 << 4) | (1 << 2) | 0) + u16(0)) +
          tlv(5, u32(1000, 0, 0)) + tlv(1, b"\0" * 8) + tlv(6, u8(0x30, 1) + u16(0)) +
          tlv(7, u32(6) + ts1 + u8(1) + b"\0\0\0") + tlv(8, HMAC))
    ss = u32(9) + ts1 + e1 + u16(0x1F2E) + b"\0" * 28 + tl
    mss = {"ippm.ssid": str(0x1F2E), "ippm.tlvs.#": "7", "ippm.tlvs[0].ippm.tlv_type": "3",
           "ippm.tlvs[0].ippm.timestamp_out": "3", "ippm.tlvs[1].ippm.cos_dscp1": "46",
           "ippm.tlvs[1].ippm.cos_ecn": "1", "ippm.tlvs[2].ippm.dm_sender_tx": "1000",
           "ippm.tlvs[3].ippm.tlv_value.#": "8", "ippm.tlvs[4].ippm.ar_id": "3",
           "ippm.tlvs[4].ippm.ar_return_code": "1", "ippm.tlvs[5].ippm.fu_sequence": "6",
           "ippm.tlvs[5].ippm.fu_ts_mode": "1", "ippm.tlvs[6].ippm.tlv_value.#": "16"}
    out.append(("stamp-sender", "01-sender-with-tlvs-roundtrip.json",
                vec("sender-with-tlvs-roundtrip", "stamp-sender", "stamp-sender", ss, ss, mss,
                    ref=R_ST + "; a Session-Sender packet with SSID and seven TLVs: timestamp information, class "
                        "of service, direct measurement, extra padding, access report, follow-up telemetry, HMAC")))
    out.append(("stamp-sender", "02-truncated-is-malformed.json",
                vec("truncated-is-malformed", "stamp-sender", "stamp-sender", ss[:43], error="malformed-wire",
                    ref=R_ST + "; the first 43 octets, one short of the base packet")))
    rtl = tlv(5, u32(1000, 998, 998)) + tlv(4, u16((46 << 10) | (46 << 4) | (2 << 2) | 0) + u16(0)) + \
        tlv(200, b"\x01\x02\x03\x04", u=1)
    sr = u32(55) + ts3 + e2 + u16(0x1F2E) + ts2 + u32(9) + ts1 + e1 + u16(0) + u8(63) + b"\0" * 3 + rtl
    out.append(("stamp-reflector", "01-reflector-with-tlvs-roundtrip.json",
                vec("reflector-with-tlvs-roundtrip", "stamp-reflector", "stamp-reflector", sr, sr,
                    {"ippm.ssid": str(0x1F2E), "ippm.sender_sequence": "9", "ippm.sender_ttl": "63",
                     "ippm.tlvs.#": "3", "ippm.tlvs[0].ippm.dm_reflector_rx": "998",
                     "ippm.tlvs[1].ippm.cos_dscp2": "46", "ippm.tlvs[2].ippm.tlv_flag_u": "1",
                     "ippm.tlvs[2].ippm.tlv_type": "200", "ippm.tlvs[2].ippm.tlv_value.#": "4"},
                    ref=R_ST + "; a Session-Reflector packet answering with direct measurement and class of "
                        "service TLVs, and an unknown TLV returned with the U flag")))
    ssa = u32(10) + b"\0" * 12 + ts1 + e1 + u16(0x1F2E) + b"\0" * 68 + HMAC
    out.append(("stamp-sender-auth", "01-authenticated-roundtrip.json",
                vec("authenticated-roundtrip", "stamp-sender-auth", "stamp-sender-auth", ssa, ssa,
                    {"ippm.sequence": "10", "ippm.ssid": str(0x1F2E), "ippm.tlvs.#": "0"},
                    ref=R_ST + "; an authenticated-mode Session-Sender packet without TLVs")))
    sra = (u32(56) + b"\0" * 12 + ts3 + e2 + u16(0x1F2E) + b"\0" * 4 + ts2 + b"\0" * 8 + u32(10) + b"\0" * 12 +
           ts1 + e1 + b"\0" * 6 + u8(64) + b"\0" * 15 + HMAC + tlv(5, u32(1, 1, 1)))
    out.append(("stamp-reflector-auth", "01-authenticated-roundtrip.json",
                vec("authenticated-roundtrip", "stamp-reflector-auth", "stamp-reflector-auth", sra, sra,
                    {"ippm.sequence": "56", "ippm.sender_sequence": "10", "ippm.sender_ttl": "64",
                     "ippm.tlvs.#": "1", "ippm.tlvs[0].ippm.dm_reflector_tx": "1"},
                    ref=R_ST + "; an authenticated-mode Session-Reflector packet with a direct measurement TLV")))
    return out


# ---------------------------------------------------------------- PCEP (RFC 5440)

R_PC = "RFC 5440 sections 6 and 7 and RFC 3209 section 4.3.3"


def pcep(msg_type, objects):
    body = b"".join(objects)
    return u8(1 << 5, msg_type) + u16(4 + len(body)) + body


def obj(cls, ot, body, p=0, i=0):
    return u8(cls, (ot << 4) | (p << 1) | i) + u16(4 + len(body)) + body


def ptlv(t, value):
    return u16(t, len(value)) + value + b"\0" * (-len(value) % 4)


def sub(t, content, loose=0):
    return u8((loose << 7) | t, 2 + len(content)) + content


def pcep_vectors():
    out = []
    o_open = obj(1, 1, u8(1 << 5, 30, 120, 1) + ptlv(16, u32(5)) + ptlv(26, b"\x01\x02\x03"))
    msg = pcep(1, [o_open])
    out.append(("pcep", "01-open-roundtrip.json",
                vec("open-roundtrip", "pcep", "pcep", msg, msg,
                    {"@kind": "message", "pcep.message_type": "1", "pcep.objects.#": "1",
                     "pcep.objects[0].pcep.object_class": "1", "pcep.objects[0].pcep.open_version": "1",
                     "pcep.objects[0].pcep.keepalive": "30", "pcep.objects[0].pcep.deadtimer": "120",
                     "pcep.objects[0].pcep.sid": "1", "pcep.objects[0].pcep.tlvs.#": "2",
                     "pcep.objects[0].pcep.tlvs[1].pcep.tlv_value.#": "3"},
                    ref=R_PC + "; an Open message: OPEN object, keepalive 30, deadtimer 120, two TLVs (one padded)")))
    ka = pcep(2, [])
    out.append(("pcep", "02-keepalive-roundtrip.json",
                vec("keepalive-roundtrip", "pcep", "pcep", ka, ka, {"pcep.message_type": "2", "pcep.objects.#": "0"},
                    ref=R_PC + "; a Keepalive message, the common header alone")))
    # 03 (a PCReq with RP, END-POINTS, BANDWIDTH, METRIC, LSPA and an unknown class) was dropped:
    # its RP flags set the B bit where its model stated the O bit, an error of this program that
    # an engine found; rule 16 of the brief drops such a vector rather than refit it
    ero = obj(7, 1, sub(1, u32(v4("192.0.2.2")) + u8(32, 0)) + sub(1, u32(v4("192.0.2.3")) + u8(32, 0)) +
              sub(32, u16(64496), loose=1) + sub(3, u16(0, 0)))
    rep = pcep(4, [obj(2, 1, u32(5) + u32(77), p=1), ero, obj(6, 1, u16(0) + u8(0b01, 2) + f32(30.0))])
    out.append(("pcep", "04-pcrep-ero-roundtrip.json",
                vec("pcrep-ero-roundtrip", "pcep", "pcep", rep, rep,
                    {"pcep.message_type": "4", "pcep.objects[1].pcep.ero.#": "4",
                     "pcep.objects[1].pcep.ero[1].pcep.sub_ipv4": str(v4("192.0.2.3")),
                     "pcep.objects[1].pcep.ero[1].pcep.sub_prefix_length": "32",
                     "pcep.objects[1].pcep.ero[2].pcep.sub_l": "1", "pcep.objects[1].pcep.ero[2].pcep.sub_asn": "64496",
                     "pcep.objects[1].pcep.ero[3].pcep.sub_value.#": "4", "pcep.objects[2].pcep.metric_b": "1",
                     "pcep.objects[2].pcep.metric_value": "30"},
                    ref=R_PC + "; a PCRep: RP, an ERO of two strict IPv4 hops, a loose AS hop and a subobject of "
                        "type 3 kept as octets, and a METRIC bound of 30")))
    v6s = ipaddress.IPv6Address("2001:db8::1").packed
    v6d = ipaddress.IPv6Address("2001:db8:1::9").packed
    iro = obj(10, 1, sub(2, ipaddress.IPv6Address("2001:db8:2::").packed + u8(48, 0), loose=1))
    req6 = pcep(3, [obj(2, 1, u32(1) + u32(78), p=1), obj(4, 2, v6s + v6d, p=1), iro,
                    obj(11, 1, u32(0b011) + u32(77, 78))])
    out.append(("pcep", "05-pcreq-ipv6-iro-svec-roundtrip.json",
                vec("pcreq-ipv6-iro-svec-roundtrip", "pcep", "pcep", req6, req6,
                    {"pcep.objects[1].pcep.object_type": "2",
                     "pcep.objects[1].pcep.source_ipv6_high": str(int.from_bytes(v6s[:8], "big")),
                     "pcep.objects[1].pcep.destination_ipv6_low": "9",
                     "pcep.objects[2].pcep.iro[0].pcep.sub_type": "2",
                     "pcep.objects[2].pcep.iro[0].pcep.sub_prefix_length": "48",
                     "pcep.objects[3].pcep.svec_n": "1", "pcep.objects[3].pcep.svec_l": "1",
                     "pcep.objects[3].pcep.svec_request_ids.#": "2"},
                    ref=R_PC + "; a PCReq with IPv6 END-POINTS, an IRO with a loose IPv6 prefix and an SVEC that "
                        "asks for node- and link-diverse paths for requests 77 and 78")))
    np = pcep(4, [obj(2, 1, u32(1) + u32(78), p=1), obj(3, 1, u8(0, 0x80, 0, 0))])
    out.append(("pcep", "06-pcrep-no-path-roundtrip.json",
                vec("pcrep-no-path-roundtrip", "pcep", "pcep", np, np,
                    {"pcep.objects[1].pcep.nature_of_issue": "0", "pcep.objects[1].pcep.no_path_c": "1",
                     "pcep.objects[1].pcep.tlvs.#": "0"},
                    ref=R_PC + "; a PCRep with NO-PATH")))
    err = pcep(6, [obj(13, 1, u8(0, 0, 1, 1))])
    out.append(("pcep", "07-pcerr-roundtrip.json",
                vec("pcerr-roundtrip", "pcep", "pcep", err, err,
                    {"pcep.message_type": "6", "pcep.objects[0].pcep.error_type": "1",
                     "pcep.objects[0].pcep.error_value": "1"},
                    ref=R_PC + "; a PCErr with a PCEP-ERROR object, type 1 value 1")))
    ntf = pcep(5, [obj(12, 1, u8(0, 0, 2, 1))])
    out.append(("pcep", "08-pcntf-roundtrip.json",
                vec("pcntf-roundtrip", "pcep", "pcep", ntf, ntf,
                    {"pcep.message_type": "5", "pcep.objects[0].pcep.notification_type": "2",
                     "pcep.objects[0].pcep.notification_value": "1"},
                    ref=R_PC + "; a PCNtf with a NOTIFICATION object, type 2 value 1")))
    lb = pcep(3, [obj(2, 1, u32(0) + u32(79), p=1), obj(14, 1, u16(0) + u8(0, 4) + f32(250000.0))])
    out.append(("pcep", "09-load-balancing-roundtrip.json",
                vec("load-balancing-roundtrip", "pcep", "pcep", lb, lb,
                    {"pcep.objects[1].pcep.max_lsp": "4", "pcep.objects[1].pcep.min_bandwidth": "250000"},
                    ref=R_PC + "; a PCReq with a LOAD-BALANCING object")))
    close = pcep(7, [obj(15, 1, u16(0) + u8(0, 2))])
    out.append(("pcep", "10-close-roundtrip.json",
                vec("close-roundtrip", "pcep", "pcep", close, close,
                    {"pcep.message_type": "7", "pcep.objects[0].pcep.close_reason": "2"},
                    ref=R_PC + "; a Close message, reason 2 (DeadTimer expired)")))
    bad = bytearray(close)
    bad[0] = 2 << 5
    out.append(("pcep", "11-version-2-is-no-kind.json",
                vec("version-2-is-no-kind", "pcep", "pcep", bytes(bad), error="no-kind",
                    ref=R_PC + "; the Close message with version 2 in place of 1")))
    out.append(("pcep", "12-truncated-is-malformed.json",
                vec("truncated-is-malformed", "pcep", "pcep", msg[:-4], error="malformed-wire",
                    ref=R_PC + "; the Open message without its last 4 octets, shorter than its length field")))
    return out


# ---------------------------------------------------------------- HSRP (RFC 2281)

R_HS = "RFC 2281 section 5.1"


def hsrp(op, state, hello, hold, prio, group, auth, vip):
    return u8(0, op, state, hello, hold, prio, group, 0) + auth.ljust(8, b"\0") + u32(v4(vip))


def hsrp_vectors():
    out = []
    hello = hsrp(0, 16, 3, 10, 110, 1, b"cisco", "192.0.2.254")
    out.append(("hsrp", "01-hello-active-roundtrip.json",
                vec("hello-active-roundtrip", "hsrp", "hsrp", hello, hello,
                    {"hsrp.version": "0", "hsrp.op_code": "0", "hsrp.state": "16", "hsrp.hellotime": "3",
                     "hsrp.holdtime": "10", "hsrp.priority": "110", "hsrp.group": "1",
                     "hsrp.authentication": "cisco", "hsrp.virtual_ip": str(v4("192.0.2.254"))},
                    ref=R_HS + "; a hello from the active router of group 1 with the default authentication data")))
    coup = hsrp(1, 4, 3, 10, 200, 1, b"Pa55word", "192.0.2.254")
    out.append(("hsrp", "02-coup-roundtrip.json",
                vec("coup-roundtrip", "hsrp", "hsrp", coup, coup,
                    {"hsrp.op_code": "1", "hsrp.state": "4", "hsrp.priority": "200",
                     "hsrp.authentication": "Pa55word"},
                    ref=R_HS + "; a coup from a speaking router of higher priority, with eight characters of "
                        "authentication data")))
    out.append(("hsrp", "03-short-is-malformed.json",
                vec("short-is-malformed", "hsrp", "hsrp", hello[:19], error="malformed-wire",
                    ref=R_HS + "; the hello without its last octet")))
    return out


def build_files(out):
    written = {}
    for pack_name, fname, v in ippm_vectors() + pcep_vectors() + hsrp_vectors():
        assert v["from"] == pack_name
        out.write("packs/%s/vectors/%s" % (pack_name, fname), json.dumps(v, indent=2) + "\n")
        written[pack_name] = written.get(pack_name, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("ietf-more-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
