#!/usr/bin/env python3
"""gnss-time-vectors: write the vectors of the packs ntrip-sourcetable-line, ntp-packet, nts-ke-records
and ptp-message.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of the BKG NTRIP 1.0 documentation (section 6), RFC 5905 section 7.3,
RFC 7822, RFC 8915 sections 4 and 5, and the IEEE 1588 messages as linuxptp's msg.h, ddt.h and tlv.h
lay them out: multi-octet fields big-endian.

Inputs: records and packets built here from values chosen here; none is copied from a document or a
capture. Host names are under example.org; clock identities are invented.

`expect` of every round trip is this program's writing of the values, which for these inputs is the
input; `model` holds values that were written.

Usage: python3 -I tools/gen/gnss-time-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/gnss-time-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_NTRIP = "the BKG NTRIP 1.0 documentation, section 6"
R_NTP = "RFC 5905 section 7.3, RFC 7822 section 3 and RFC 8915 section 5"
R_KE = "RFC 8915 section 4"
R_PTP = "IEEE 1588 as linuxptp msg.h, ddt.h and tlv.h lay it out"


def vec(pack, name, inp, model=None, error=None, ref="", text=False):
    v = {"name": name, "from": pack, "to": pack, "input": inp if text else inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = v["input"]
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


# ---------------------------------------------------------------- NTRIP

def ntrip_vectors():
    p = "ntrip-sourcetable-line"
    T = "ntrip."
    out = []
    s = "STR;TEST0;Testtown;RTCM 3.2;1004(1),1006(10),1033(10);2;GPS+GLO;Misc;DEU;50.10;8.66;0;0;Generic RX;none;B;N;2400;demo stream"
    out.append((p, "01-str-roundtrip.json", vec(p, "str-roundtrip", s,
                {T + "mountpoint": "TEST0", T + "format": "RTCM 3.2", T + "format_details": "1004(1),1006(10),1033(10)",
                 T + "carrier": "2", T + "nav_system": "GPS+GLO", T + "str_latitude": "50.10", T + "str_nmea": "0",
                 T + "str_authentication": "B", T + "bitrate": "2400", T + "str_misc": "demo stream"},
                ref=R_NTRIP + "; a stream record", text=True)))
    v = "STR;VRS1;Network VRS;RTCM 3;1004(1),1012(1);2;GPS+GLO;EXNET;FRA;48.85;2.35;1;1;Network SW;none;D;Y;5000;none"
    out.append((p, "02-str-network-nmea-roundtrip.json", vec(p, "str-network-nmea-roundtrip", v,
                {T + "str_nmea": "1", T + "solution": "1", T + "str_fee": "Y", T + "str_authentication": "D"},
                ref=R_NTRIP + "; a network stream that needs the client's NMEA position", text=True)))
    c = "CAS;caster.example.org;2101;Example Caster;Example Org;1;DEU;50.10;8.66;0.0.0.0;0;none"
    out.append((p, "03-cas-roundtrip.json", vec(p, "cas-roundtrip", c,
                {T + "host": "caster.example.org", T + "port": "2101", T + "cas_operator": "Example Org", T + "cas_nmea": "1",
                 T + "fallback_host": "0.0.0.0", T + "fallback_port": "0"},
                ref=R_NTRIP + "; a caster record with no fallback", text=True)))
    n = "NET;EXNET;Example Org;B;N;https://example.org/net;none;https://example.org/register;none"
    out.append((p, "04-net-roundtrip.json", vec(p, "net-roundtrip", n,
                {T + "net_identifier": "EXNET", T + "web_net": "https://example.org/net", T + "web_str": "none"},
                ref=R_NTRIP + "; a network record", text=True)))
    out.append((p, "05-end-roundtrip.json", vec(p, "end-roundtrip", "ENDSOURCETABLE", ref=R_NTRIP + "; the end of the table", text=True)))
    out.append((p, "06-unknown-record-is-no-kind.json", vec(p, "unknown-record-is-no-kind", "XYZ;a;b", error="no-kind",
                ref=R_NTRIP + "; a record type that is not STR, CAS or NET", text=True)))
    return out


# ---------------------------------------------------------------- NTP

def ntp_header(mode, stratum, refid, li=0, vn=4, poll=6, precision=-20, delay=0x800, disp=0x1000, ts=(0, 0, 0, 0)):
    b = u8((li << 6) | (vn << 3) | mode, stratum, poll & 0xFF, precision & 0xFF) + u32(delay, disp) + refid
    for t in ts:
        b += u32(t, 0x40000000)
    return b


def ext(ftype, body):
    assert len(body) % 4 == 0
    return u16(ftype, len(body) + 4) + body


def ntp_vectors():
    p = "ntp-packet"
    out = []
    T = (3976000000, 3976000100, 3976000200, 3976000300)
    uid = bytes(range(32))
    cookie = bytes(range(100, 164))
    auth = u16(16, 32) + bytes(range(16)) + bytes(range(200, 232))
    a = ntp_header(4, 2, u32(0xC0000201), ts=T) + ext(0x0104, uid) + ext(0x0204, cookie) + ext(0x0404, auth)
    out.append((p, "01-server-nts-roundtrip.json", vec(p, "server-nts-roundtrip", a,
                {"inet.ntp_mode": "4", "inet.ntp_stratum": "2", "inet.ntp_poll": "6", "inet.ntp_precision": "-20",
                 "inet.ntp_root_delay": "0.03125", "inet.ntp_ref_id": str(0xC0000201), "inet.ntp_xmt_ts_sec": str(T[3]),
                 "ntpext.extensions.#": "3", "ntpext.extensions[0].ntpext.field_type": "260",
                 "ntpext.extensions[0].ntpext.unique_identifier.#": "32", "ntpext.extensions[1].ntpext.cookie.#": "64",
                 "ntpext.extensions[2].ntpext.nonce_length": "16", "ntpext.extensions[2].ntpext.ciphertext_length": "32",
                 "ntpext.extensions[2].ntpext.authenticator.#": "48"},
                ref=R_NTP + "; a server response with the unique identifier, a cookie and the NTS authenticator")))
    b = ntp_header(3, 16, u32(0), ts=(0, 0, 0, T[0])) + ext(0x0104, uid) + ext(0x0204, cookie) + ext(0x0304, bytes(64))
    out.append((p, "02-client-placeholder-roundtrip.json", vec(p, "client-placeholder-roundtrip", b,
                {"inet.ntp_mode": "3", "inet.ntp_stratum": "16", "ntpext.extensions.#": "3",
                 "ntpext.extensions[2].ntpext.field_type": "772", "ntpext.extensions[2].ntpext.cookie_placeholder.#": "64"},
                ref=R_NTP + "; a client request with a cookie and a cookie placeholder")))
    c = ntp_header(4, 1, b"GPS\x00", ts=T)
    out.append((p, "03-primary-no-extensions-roundtrip.json", vec(p, "primary-no-extensions-roundtrip", c,
                {"inet.ntp_stratum": "1", "inet.ntp_ref_clock": "GPS", "ntpext.extensions.#": "0"},
                ref=R_NTP + "; a stratum 1 response with no extension fields")))
    d = ntp_header(4, 0, b"RATE", li=3, ts=(0, 0, 0, 0))
    out.append((p, "04-kiss-of-death-roundtrip.json", vec(p, "kiss-of-death-roundtrip", d,
                {"inet.ntp_leap": "3", "inet.ntp_stratum": "0", "inet.ntp_kiss_code": "RATE"},
                ref=R_NTP + "; a kiss-o'-death RATE packet")))
    e = ntp_header(4, 0x7F, u32(1), ts=T) + ext(0xABCD, b"\x01\x02\x03\x04")
    out.append((p, "05-unknown-extension-roundtrip.json", vec(p, "unknown-extension-roundtrip", e,
                {"ntpext.extensions[0].ntpext.field_type": str(0xABCD), "ntpext.extensions[0].ntpext.value.#": "4"},
                ref=R_NTP + "; an extension field of an unassigned type, kept as octets")))
    out.append((p, "06-cut-extension-is-malformed.json", vec(p, "cut-extension-is-malformed", a[:48 + 20], error="malformed-wire",
                ref=R_NTP + "; the packet of vector 01 cut inside its first extension field")))
    return out


# ---------------------------------------------------------------- NTS-KE

def rec(rtype, body=b"", critical=1):
    return u16((critical << 15) | rtype, len(body)) + body


def ke_vectors():
    p = "nts-ke-records"
    out = []
    req = rec(1, u16(0)) + rec(4, u16(15, 17)) + rec(6, b"time.example.org", 0) + rec(7, u16(123), 0) + rec(0)
    out.append((p, "01-request-roundtrip.json", vec(p, "request-roundtrip", req,
                {"ntske.records.#": "5", "ntske.records[0].ntske.record_type": "1", "ntske.records[0].ntske.protocols.#": "1",
                 "ntske.records[1].ntske.aead_algorithms.#": "2", "ntske.records[1].ntske.aead_algorithms[1].ntske.aead_id": "17",
                 "ntske.records[2].ntske.critical": "0", "ntske.records[2].ntske.server.#": "16",
                 "ntske.records[3].ntske.port": "123", "ntske.records[4].ntske.record_type": "0", "ntske.records[4].ntske.critical": "1"},
                ref=R_KE + "; a client request: next protocol, AEAD algorithms, server and port, end of message")))
    resp = rec(1, u16(0)) + rec(4, u16(15)) + rec(5, bytes(range(32)), 0) + rec(5, bytes(range(32, 64)), 0) + rec(0)
    out.append((p, "02-response-cookies-roundtrip.json", vec(p, "response-cookies-roundtrip", resp,
                {"ntske.records.#": "5", "ntske.records[2].ntske.record_type": "5", "ntske.records[2].ntske.cookie.#": "32",
                 "ntske.records[3].ntske.cookie.#": "32"},
                ref=R_KE + "; a server response with two new cookies")))
    err = rec(2, u16(1)) + rec(0)
    out.append((p, "03-error-roundtrip.json", vec(p, "error-roundtrip", err,
                {"ntske.records[0].ntske.error_code": "1"}, ref=R_KE + "; an error response (bad request)")))
    unk = rec(0x1234, b"\x01\x02\x03", 0) + rec(0)
    out.append((p, "04-unknown-record-roundtrip.json", vec(p, "unknown-record-roundtrip", unk,
                {"ntske.records[0].ntske.record_type": str(0x1234), "ntske.records[0].ntske.body.#": "3"},
                ref=R_KE + "; a non-critical record of an unassigned type, kept as octets")))
    out.append((p, "05-cut-record-is-malformed.json", vec(p, "cut-record-is-malformed", req[:12], error="malformed-wire",
                ref=R_KE + "; the request of vector 01 cut inside its AEAD record")))
    return out


# ---------------------------------------------------------------- PTP

CLOCK = bytes.fromhex("001b21fffe123456")
GM = bytes.fromhex("0050c2fffe000001")


def ptp_header(mtype, body, tlvs=b"", flags0=0, flags1=0x08, seq=100, control=0, logi=-3, domain=0, correction=0):
    length = 34 + len(body) + len(tlvs)
    h = (u8((0 << 4) | mtype, (0 << 4) | 2) + u16(length) + u8(domain, 0) + u8(flags0, flags1) +
         struct.pack(">q", correction) + u32(0) + CLOCK + u16(1) + u16(seq) + u8(control) + struct.pack(">b", logi))
    return h + body + tlvs


def ts(sec, ns):
    return struct.pack(">Q", sec)[2:] + u32(ns)


def tlv(ttype, value):
    return u16(ttype, len(value)) + value


def ptp_vectors():
    p = "ptp-message"
    out = []
    a = ptp_header(0, ts(1700000000, 123456789), flags0=0x02)
    out.append((p, "01-sync-two-step-roundtrip.json", vec(p, "sync-two-step-roundtrip", a,
                {"ptp.message_type": "0", "ptp.version": "2", "ptp.two_step": "1", "ptp.ptp_timescale": "1",
                 "ptp.source_clock_identity": CLOCK.hex(), "ptp.source_port_number": "1", "ptp.sequence_id": "100",
                 "ptp.log_message_interval": "-3", "ptp.origin_seconds": "1700000000", "ptp.origin_nanoseconds": "123456789"},
                ref=R_PTP + "; a two-step Sync")))
    b = ptp_header(8, ts(1700000000, 123460000), control=2, correction=-655360)
    out.append((p, "02-follow-up-roundtrip.json", vec(p, "follow-up-roundtrip", b,
                {"ptp.message_type": "8", "ptp.control": "2", "ptp.correction": "-655360",
                 "ptp.precise_origin_nanoseconds": "123460000"},
                ref=R_PTP + "; a Follow_Up with a negative correction")))
    c = ptp_header(9, ts(1700000001, 5000) + GM + u16(2), control=3, logi=0)
    out.append((p, "03-delay-resp-roundtrip.json", vec(p, "delay-resp-roundtrip", c,
                {"ptp.message_type": "9", "ptp.receive_seconds": "1700000001", "ptp.requesting_clock_identity": GM.hex(),
                 "ptp.requesting_port_number": "2"},
                ref=R_PTP + "; a Delay_Resp")))
    ann = ts(0, 0) + struct.pack(">h", 37) + u8(0, 128, 6, 0x21) + u16(0x4E5D) + u8(128) + GM + u16(0) + u8(0x20)
    d = ptp_header(11, ann, tlvs=tlv(8, GM), flags1=0x0C, logi=1)
    out.append((p, "04-announce-path-trace-roundtrip.json", vec(p, "announce-path-trace-roundtrip", d,
                {"ptp.message_type": "11", "ptp.utc_offset_valid": "1", "ptp.current_utc_offset": "37", "ptp.gm_priority1": "128",
                 "ptp.gm_clock_class": "6", "ptp.gm_clock_accuracy": "33", "ptp.gm_offset_scaled_log_variance": str(0x4E5D),
                 "ptp.gm_identity": GM.hex(), "ptp.time_source": "32", "ptp.tlvs.#": "1", "ptp.tlvs[0].ptp.tlv_type": "8",
                 "ptp.tlvs[0].ptp.path_trace.#": "1", "ptp.tlvs[0].ptp.path_trace[0].ptp.path_clock_identity": GM.hex()},
                ref=R_PTP + "; an Announce from a GNSS-locked grandmaster with a path trace TLV")))
    e = ptp_header(2, ts(1700000002, 0) + bytes(10), control=5)
    out.append((p, "05-pdelay-req-roundtrip.json", vec(p, "pdelay-req-roundtrip", e,
                {"ptp.message_type": "2", "ptp.origin_seconds": "1700000002"}, ref=R_PTP + "; a Pdelay_Req")))
    f = ptp_header(13, CLOCK + u16(0xFFFF) + u8(1, 1, 0x00, 0), tlvs=tlv(1, u16(0x2000)), control=4)
    out.append((p, "06-management-get-roundtrip.json", vec(p, "management-get-roundtrip", f,
                {"ptp.message_type": "13", "ptp.target_port_number": str(0xFFFF), "ptp.action": "0", "ptp.tlvs[0].ptp.tlv_type": "1",
                 "ptp.tlvs[0].ptp.management_id": str(0x2000), "ptp.tlvs[0].ptp.tlv_data.#": "0"},
                ref=R_PTP + "; a Management GET with a management TLV and no data")))
    g = ptp_header(12, CLOCK + u16(0xFFFF), tlvs=tlv(3, bytes.fromhex("0080c2") + bytes.fromhex("000001") + b"\x0a\x0b"), control=5)
    out.append((p, "07-signaling-organization-tlv-roundtrip.json", vec(p, "signaling-organization-tlv-roundtrip", g,
                {"ptp.message_type": "12", "ptp.tlvs[0].ptp.tlv_type": "3", "ptp.tlvs[0].ptp.organization_id": "0080c2",
                 "ptp.tlvs[0].ptp.organization_subtype": "000001", "ptp.tlvs[0].ptp.tlv_data.#": "2"},
                ref=R_PTP + "; a Signaling message with an organization extension TLV")))
    out.append((p, "08-unassigned-type-is-no-kind.json", vec(p, "unassigned-type-is-no-kind", ptp_header(5, ts(0, 0)), error="no-kind",
                ref=R_PTP + "; a message type of 5, which has no body layout")))
    out.append((p, "09-cut-message-is-malformed.json", vec(p, "cut-message-is-malformed", a[:30], error="malformed-wire",
                ref=R_PTP + "; the Sync of vector 01 cut before its message length")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in ntrip_vectors() + ntp_vectors() + ke_vectors() + ptp_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("gnss-time-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
