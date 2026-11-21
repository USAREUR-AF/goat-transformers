#!/usr/bin/env python3
"""quic-vectors: write the vectors of the packs quic-long-header, quic-frames and quic-transport-parameters.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of RFC 9000 sections 16, 17.2, 18 and 19 and RFC 9369 section 3.2: variable-
length integers with their 2-bit size, other fields big-endian.

Inputs: packets, payloads and parameter lists built here from values chosen here; none is copied from a
document or a capture. Connection IDs, tokens and protected octets are invented.

`expect` of every round trip is this program's packing of the values, which for these inputs is the
input; `model` holds values that were packed.

Usage: python3 -I tools/gen/quic-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/quic-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_LH = "RFC 9000 sections 16 and 17.2 and RFC 9369 section 3.2"
R_FR = "RFC 9000 sections 16 and 19"
R_TP = "RFC 9000 sections 16 and 18"
V2 = 0x6b3343cf


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


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def qv(v, size=None):
    if size is None:
        size = 0 if v < 64 else 1 if v < 16384 else 2 if v < 2**30 else 3
    n = 1 << size
    return (v | (size << (8 * n - 2))).to_bytes(n, "big")


# ---------------------------------------------------------------- long header

DCID = bytes.fromhex("8394c8f03e515708")
SCID = bytes.fromhex("f067a5502a4262b5")


def long_hdr(first, version, dcid=DCID, scid=SCID):
    return u8(first) + u32(version) + u8(len(dcid)) + dcid + u8(len(scid)) + scid


def lh_vectors():
    p, K = "quic-long-header", "quiclh."
    out = []
    prot = bytes(range(20))
    a = long_hdr(0xC3, 1, scid=b"") + qv(0) + qv(1162, 1) + prot
    out.append((p, "01-initial-roundtrip.json", vec(p, "initial-roundtrip", a,
                {"inet.quic_version_specific": str(0x43), "inet.quic_version": "1", "inet.quic_dcid.#": "8", "inet.quic_scid.#": "0",
                 K + "token_length_size": "0", K + "token.#": "0", K + "length_size": "1", K + "length": "1162", K + "protected.#": "20"},
                ref=R_LH + "; a client Initial with no token (the packet number and payload protected)")))
    tok = bytes(range(100, 116))
    b = long_hdr(0xC1, 1) + qv(len(tok)) + tok + qv(500, 1) + prot
    out.append((p, "02-initial-with-token-roundtrip.json", vec(p, "initial-with-token-roundtrip", b,
                {K + "token.#": "16", K + "length": "500"}, ref=R_LH + "; an Initial with a 16-octet token")))
    c = long_hdr(0xE2, 1) + qv(300, 1) + prot
    out.append((p, "03-handshake-roundtrip.json", vec(p, "handshake-roundtrip", c,
                {"inet.quic_version_specific": str(0x62), K + "length": "300", K + "protected.#": "20"}, ref=R_LH + "; a Handshake packet")))
    d = long_hdr(0xD0, 1) + qv(40) + prot
    out.append((p, "04-zero-rtt-roundtrip.json", vec(p, "zero-rtt-roundtrip", d,
                {"inet.quic_version_specific": str(0x50), K + "length_size": "0", K + "length": "40"}, ref=R_LH + "; a 0-RTT packet")))
    e = long_hdr(0xF5, 1) + bytes(range(50, 74)) + bytes(range(200, 216))
    out.append((p, "05-retry-roundtrip.json", vec(p, "retry-roundtrip", e,
                {"inet.quic_version_specific": str(0x75), K + "retry_token_and_tag.#": "40"}, ref=R_LH + "; a Retry with its token and integrity tag")))
    f = long_hdr(0xAA, 0) + u32(1, V2, 0x0A0A0A0A)
    out.append((p, "06-version-negotiation-roundtrip.json", vec(p, "version-negotiation-roundtrip", f,
                {"inet.quic_version": "0", K + "supported_versions.#": "3", K + "supported_versions[1]." + K + "supported_version": str(V2)},
                ref=R_LH + "; Version Negotiation listing version 1, version 2 and a greasing version")))
    g = long_hdr(0xD3, V2, scid=b"") + qv(0) + qv(1200, 1) + prot
    out.append((p, "07-v2-initial-roundtrip.json", vec(p, "v2-initial-roundtrip", g,
                {"inet.quic_version": str(V2), "inet.quic_version_specific": str(0x53), K + "length": "1200"},
                ref=R_LH + "; a version 2 Initial, whose type code is 01")))
    h = long_hdr(0xC0, 0xFF00001D) + bytes(range(10))
    out.append((p, "08-other-version-roundtrip.json", vec(p, "other-version-roundtrip", h,
                {"inet.quic_version": str(0xFF00001D), K + "version_specific_data.#": "10"},
                ref=R_LH + "; a draft version this pack does not lay out, its rest as octets")))
    out.append((p, "09-short-header-is-no-kind.json", vec(p, "short-header-is-no-kind", u8(0x40) + DCID + bytes(4), error="no-kind",
                ref=R_LH + "; a short-header packet")))
    out.append((p, "10-cut-connection-id-is-malformed.json", vec(p, "cut-connection-id-is-malformed", a[:9], error="malformed-wire",
                ref=R_LH + "; the Initial of vector 01 cut inside its destination connection ID")))
    return out


# ---------------------------------------------------------------- frames

def lenbytes(data):
    return qv(len(data)) + data


def fr_vectors():
    p, K = "quic-frames", "quicfr."
    out = []
    F = lambda i: K + "frames[%d]." % i + K
    a = qv(0) + qv(0) + qv(0) + qv(1) + qv(6) + qv(0) + lenbytes(b"\x01\x00\x00\x01\x03")
    out.append((p, "01-padding-ping-crypto-roundtrip.json", vec(p, "padding-ping-crypto-roundtrip", a,
                {K + "frames.#": "5", F(0) + "frame_type": "0", F(3) + "frame_type": "1", F(4) + "frame_type": "6",
                 F(4) + "offset": "0", F(4) + "crypto_data.#": "5"},
                ref=R_FR + "; three PADDING frames, a PING and a CRYPTO frame")))
    b = qv(2) + qv(100) + qv(25) + qv(1) + qv(3) + qv(2) + qv(5)
    out.append((p, "02-ack-roundtrip.json", vec(p, "ack-roundtrip", b,
                {F(0) + "frame_type": "2", F(0) + "largest_acknowledged_size": "1", F(0) + "largest_acknowledged": "100",
                 F(0) + "ack_delay": "25", F(0) + "first_ack_range": "3", F(0) + "ack_ranges.#": "1",
                 F(0) + "ack_ranges[0]." + K + "gap": "2", F(0) + "ack_ranges[0]." + K + "ack_range_length": "5"},
                ref=R_FR + "; an ACK with a first range and one further range")))
    c = qv(3) + qv(50) + qv(0) + qv(0) + qv(10) + qv(7) + qv(0) + qv(1)
    out.append((p, "03-ack-ecn-roundtrip.json", vec(p, "ack-ecn-roundtrip", c,
                {F(0) + "frame_type": "3", F(0) + "ack_ranges.#": "0", F(0) + "ect0_count": "7", F(0) + "ecn_ce_count": "1"},
                ref=R_FR + "; an ACK with ECN counts and no further ranges")))
    d = qv(0x0E) + qv(4) + qv(1000, 1) + lenbytes(b"hello") + qv(0x09) + qv(8) + b"end"
    out.append((p, "04-stream-frames-roundtrip.json", vec(p, "stream-frames-roundtrip", d,
                {K + "frames.#": "2", F(0) + "frame_type": "14", F(0) + "stream_id": "4", F(0) + "offset": "1000",
                 F(0) + "stream_data.#": "5", F(1) + "frame_type": "9", F(1) + "stream_id": "8", F(1) + "stream_data.#": "3"},
                ref=R_FR + "; a STREAM frame with OFF and LEN, then one with FIN whose data runs to the end")))
    e = (qv(0x10) + qv(1048576) + qv(0x11) + qv(4) + qv(65536) + qv(0x12) + qv(100) + qv(0x14) + qv(1048576) +
         qv(0x16) + qv(100) + qv(0x04) + qv(4) + qv(0x10C, 1) + qv(5) + qv(0x05) + qv(8) + qv(0))
    out.append((p, "05-flow-control-and-reset-roundtrip.json", vec(p, "flow-control-and-reset-roundtrip", e,
                {K + "frames.#": "7", F(0) + "maximum_data": "1048576", F(1) + "maximum_data": "65536", F(2) + "maximum_streams": "100",
                 F(5) + "error_code": str(0x10C), F(5) + "final_size": "5", F(6) + "frame_type": "5"},
                ref=R_FR + "; MAX_DATA, MAX_STREAM_DATA, MAX_STREAMS, DATA_BLOCKED, STREAMS_BLOCKED, RESET_STREAM and STOP_SENDING")))
    f = (qv(0x18) + qv(1) + qv(0) + u8(8) + bytes(range(8)) + bytes(range(16, 32)) + qv(0x19) + qv(0) +
         qv(0x1A) + bytes(range(8)) + qv(0x1B) + bytes(range(8)) + qv(0x07) + lenbytes(b"tokn") + qv(0x1E))
    out.append((p, "06-connection-ids-paths-token-roundtrip.json", vec(p, "connection-ids-paths-token-roundtrip", f,
                {K + "frames.#": "6", F(0) + "sequence_number": "1", F(0) + "connection_id.#": "8",
                 F(0) + "stateless_reset_token": bytes(range(16, 32)).hex(), F(2) + "path_data": bytes(range(8)).hex(),
                 F(4) + "token.#": "4", F(5) + "frame_type": "30"},
                ref=R_FR + "; NEW_CONNECTION_ID, RETIRE_CONNECTION_ID, PATH_CHALLENGE, PATH_RESPONSE, NEW_TOKEN and HANDSHAKE_DONE")))
    g = qv(0x1C) + qv(0x0A) + qv(0x06) + lenbytes(b"bad crypto") + qv(0x1D) + qv(0) + lenbytes(b"")
    out.append((p, "07-connection-close-roundtrip.json", vec(p, "connection-close-roundtrip", g,
                {F(0) + "error_code": "10", F(0) + "frame_type_in_error": "6", F(0) + "reason_phrase.#": "10",
                 F(1) + "frame_type": "29", F(1) + "reason_phrase.#": "0"},
                ref=R_FR + "; a transport CONNECTION_CLOSE with a reason and an application one without")))
    out.append((p, "08-unknown-frame-type-is-no-kind.json", vec(p, "unknown-frame-type-is-no-kind", qv(0x40) + b"\x00", error="no-kind",
                ref=R_FR + "; a frame type of 0x40, which this pack has no layout for (and cannot skip)")))
    out.append((p, "09-cut-crypto-is-malformed.json", vec(p, "cut-crypto-is-malformed", a[:8], error="malformed-wire",
                ref=R_FR + "; the payload of vector 01 cut inside its CRYPTO data")))
    return out


# ---------------------------------------------------------------- transport parameters

def tp_vectors():
    p, K = "quic-transport-parameters", "quictp."
    out = []
    P = lambda i: K + "parameters[%d]." % i + K
    a = (qv(4) + lenbytes(qv(1048576)) + qv(1) + lenbytes(qv(30000)) + qv(15) + lenbytes(bytes(range(8))) + qv(0x1A2A, 1) + lenbytes(b""))
    out.append((p, "01-client-parameters-roundtrip.json", vec(p, "client-parameters-roundtrip", a,
                {K + "parameters.#": "4", P(0) + "parameter_id": "4", P(0) + "value.#": "4", P(1) + "parameter_id": "1",
                 P(2) + "value.#": "8", P(3) + "parameter_id_size": "1", P(3) + "parameter_id": str(0x1A2A), P(3) + "value.#": "0"},
                ref=R_TP + "; initial_max_data, max_idle_timeout, initial_source_connection_id and a reserved (greasing) ID")))
    out.append((p, "02-cut-value-is-malformed.json", vec(p, "cut-value-is-malformed", a[:4], error="malformed-wire",
                ref=R_TP + "; the parameters of vector 01 cut inside the first value")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in lh_vectors() + fr_vectors() + tp_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("quic-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
