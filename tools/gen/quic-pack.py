#!/usr/bin/env python3
"""Write the QUIC packs and their modules: the long-header packet (RFC 9000 section 17.2, with the
version 2 type codes of RFC 9369), the frames of a decrypted packet payload (RFC 9000 section 19), and
the transport parameters (RFC 9000 section 18).

A QUIC variable-length integer gives its size in its first two bits; each is a 2-bit `<name>_size`
field and a `switch` reading a 6, 14, 30 or 62-bit value. Where such an integer counts what follows (a
token, CRYPTO data, a reason phrase, ACK ranges), each size case holds a `count` line of that width and
the counted group, so the count is written from the list.
The vectors are not written here: tools/gen/quic-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/quic-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "lh": ('source        "IETF RFC 9000, QUIC: A UDP-Based Multiplexed and Secure Transport, May 2021, sections 16, 17.2 and 17.2.1-17.2.5, '
           'https://www.rfc-editor.org/rfc/rfc9000.txt; IETF RFC 9369, QUIC Version 2, May 2023, section 3.2, '
           'https://www.rfc-editor.org/rfc/rfc9369.txt; layout restated"'),
    "fr": 'source        "IETF RFC 9000 sections 16 and 19, https://www.rfc-editor.org/rfc/rfc9000.txt; layout restated"',
    "tp": 'source        "IETF RFC 9000 sections 16 and 18, https://www.rfc-editor.org/rfc/rfc9000.txt; layout restated"',
}
WIDTH = {"0": 6, "1": 14, "2": 30, "3": 62}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def sw(key, cases, other=None):
    L = ["switch  %s" % key]
    for vals, lines in cases:
        L.append("  case  %s" % vals)
        L += ind(2, lines)
    if other is not None:
        L.append("  else")
        L += ind(2, other)
    L.append("end")
    return L


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def text(L):
    return "\n".join(L) + "\n"


def varint(mod, key):
    return [F(mod, key + "_size", 2)] + sw("%s.%s_size" % (mod, key), [(c, [F(mod, key, w)]) for c, w in WIDTH.items()])


def counted(mod, sizekey, cname, lst, body):
    """A variable-length integer that counts the items of lst."""
    return [F(mod, sizekey, 2)] + sw("%s.%s" % (mod, sizekey), [
        (c, ["count  %s  %d" % (cname, w), "group  %s.%s  count  @%s" % (mod, lst, cname)] + ind(1, body) + ["end"])
        for c, w in WIDTH.items()])


def octet(mod):
    return [F(mod, "octet", 8)]


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def vkeys(key, what):
    return [("key", key + "_size", what + ": the variable-length integer's size code (0 one octet, 1 two, 2 four, 3 eight)"), ("key", key, what)]


def module(name, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- long header

L_ = "quiclh"


def types(type_code):
    """The values of the 7 bits after the header form bit whose long packet type (bits 5-4) is type_code."""
    return ",".join(str(v) for v in range(128) if (v >> 4) & 3 == type_code)


def lh_pack():
    initial = counted(L_, "token_length_size", "token_length", "token", octet(L_)) + varint(L_, "length") + octets(L_, "protected")
    zero_rtt = varint(L_, "length") + octets(L_, "protected")
    retry = octets(L_, "retry_token_and_tag")
    by_type = lambda code_initial, code_0rtt, code_hs, code_retry: sw("inet.quic_version_specific", [
        (types(code_initial), initial), (types(code_0rtt), zero_rtt), (types(code_hs), zero_rtt), (types(code_retry), retry)])
    L = head("quic-long-header", ["QUIC long-header packet (RFC 9000 section 17.2; version 2 types of RFC 9369): the invariant fields on",
                                  "the inet keys of quic-invariant, then by version and long packet type the Version Negotiation list,",
                                  "the Initial token and length, the 0-RTT and Handshake length, or the Retry token. The packet number and",
                                  "payload are header- and packet-protected, so they are octets. Written by tools/gen/quic-pack.py."],
             "lh", ["inet", L_])
    L += ["kind      long-header", "when      1  1", "requires  inet.quic_version", "field  inet.quic_version_specific   7    uint",
          "field  inet.quic_version            32   uint", "group  inet.quic_dcid count 8", "  field  inet.quic_cid_octet        8    uint",
          "end", "group  inet.quic_scid count 8", "  field  inet.quic_cid_octet        8    uint", "end"]
    L += sw("inet.quic_version", [
        ("0", ["group  quiclh.supported_versions  rest", "  " + F(L_, "supported_version", 32), "end"]),
        ("1", by_type(0, 1, 2, 3)),
        (str(0x6b3343cf), by_type(1, 2, 3, 0))],
        octets(L_, "version_specific_data"))
    return text(L)


LH_KEYS = ([("list", "supported_versions", "Version Negotiation: the versions the server supports"),
            ("key", "supported_version", "one supported version"), ("key", "token_length_size", "Initial: the token length's size code"),
            ("list", "token", "Initial: the token, as octets (its length is written from the list)")] +
           vkeys("length", "Initial, 0-RTT, Handshake: the length of the packet number and payload, octets (carried, not computed)") +
           [("list", "protected", "Initial, 0-RTT, Handshake: the protected packet number and payload (and any coalesced packets after them), as octets"),
            ("list", "retry_token_and_tag", "Retry: the retry token and the 16-octet integrity tag, as octets"),
            ("list", "version_specific_data", "a version this pack does not lay out: the rest of the packet, as octets"),
            ("key", "octet", "one octet")])


# ---------------------------------------------------------------- frames

R = "quicfr"


def v(key):
    return varint(R, key)


def frames_pack():
    # RFC 9000 puts the range count before the first range and the ranges after it: the count line is read in
    # its place and the counted group follows the first range.
    ack_frame = (v("largest_acknowledged") + v("ack_delay") + [F(R, "ack_range_count_size", 2)] +
                 sw("quicfr.ack_range_count_size", [
                     (c, ["count  ack_range_count  %d" % w] + v("first_ack_range") +
                      ["group  quicfr.ack_ranges  count  @ack_range_count"] + ind(1, v("gap") + v("ack_range_length")) + ["end"])
                     for c, w in WIDTH.items()]))
    ecn = v("ect0_count") + v("ect1_count") + v("ecn_ce_count")
    stream = []
    for t in range(8, 16):
        off, ln = t & 4, t & 2
        body = v("stream_id") + (v("offset") if off else [])
        body += counted(R, "data_length_size", "data_length", "stream_data", octet(R)) if ln else octets(R, "stream_data")
        stream.append((str(t), body))
    reason = counted(R, "reason_length_size", "reason_length", "reason_phrase", octet(R))
    cases = [
        ("0,1,30", []),
        ("2", ack_frame), ("3", ack_frame + ecn),
        ("4", v("stream_id") + v("error_code") + v("final_size")),
        ("5", v("stream_id") + v("error_code")),
        ("6", v("offset") + counted(R, "data_length_size", "data_length", "crypto_data", octet(R))),
        ("7", counted(R, "token_length_size", "token_length", "token", octet(R))),
    ] + stream + [
        ("16,20", v("maximum_data")),
        ("17,21", v("stream_id") + v("maximum_data")),
        ("18,19,22,23", v("maximum_streams")),
        ("24", v("sequence_number") + v("retire_prior_to") + ["count  cid_length  8", "group  quicfr.connection_id  count  @cid_length",
                                                              "  " + F(R, "octet", 8), "end", F(R, "stateless_reset_token", 128, "hex")]),
        ("25", v("sequence_number")),
        ("26,27", [F(R, "path_data", 64, "hex")]),
        ("28", v("error_code") + v("frame_type_in_error") + reason),
        ("29", v("error_code") + reason),
    ]
    L = head("quic-frames", ["QUIC frames (RFC 9000 section 19): the decrypted payload of a packet, the frames to the end, each by its",
                             "variable-length type. Written by tools/gen/quic-pack.py; do not edit by hand."], "fr", [R])
    L += ["group  quicfr.frames  rest"] + ind(1, v("frame_type") + sw("quicfr.frame_type", cases)) + ["end"]
    return text(L)


FR_KEYS = ([("list", "frames", "the frames, in order")] +
           vkeys("frame_type", "frame type (0 PADDING, 1 PING, 2-3 ACK, 4 RESET_STREAM, 5 STOP_SENDING, 6 CRYPTO, 7 NEW_TOKEN, 8-15 STREAM with OFF 0x04, LEN 0x02, FIN 0x01, 16 MAX_DATA, 17 MAX_STREAM_DATA, 18-19 MAX_STREAMS, 20 DATA_BLOCKED, 21 STREAM_DATA_BLOCKED, 22-23 STREAMS_BLOCKED, 24 NEW_CONNECTION_ID, 25 RETIRE_CONNECTION_ID, 26 PATH_CHALLENGE, 27 PATH_RESPONSE, 28-29 CONNECTION_CLOSE, 30 HANDSHAKE_DONE)") +
           vkeys("largest_acknowledged", "ACK: largest packet number acknowledged") + vkeys("ack_delay", "ACK: acknowledgement delay, scaled by the ack_delay_exponent") +
           [("key", "ack_range_count_size", "ACK: the range count's size code (the count is written from ack_ranges)")] +
           vkeys("first_ack_range", "ACK: the first range, contiguous packets below the largest") +
           [("list", "ack_ranges", "ACK: the further ranges")] + vkeys("gap", "ACK range: gap") + vkeys("ack_range_length", "ACK range: length") +
           vkeys("ect0_count", "ACK ECN: ECT(0) count") + vkeys("ect1_count", "ACK ECN: ECT(1) count") + vkeys("ecn_ce_count", "ACK ECN: ECN-CE count") +
           vkeys("stream_id", "stream ID") + vkeys("error_code", "application or transport error code") + vkeys("final_size", "RESET_STREAM: final size") +
           vkeys("offset", "CRYPTO or STREAM: byte offset") +
           [("key", "data_length_size", "CRYPTO or STREAM with LEN: the data length's size code (the length is written from the list)"),
            ("list", "crypto_data", "CRYPTO: the cryptographic handshake data, as octets"),
            ("key", "token_length_size", "NEW_TOKEN: the token length's size code"), ("list", "token", "NEW_TOKEN: the token, as octets"),
            ("list", "stream_data", "STREAM: the stream data, as octets (to the end of the payload when LEN is clear)")] +
           vkeys("maximum_data", "MAX_DATA, MAX_STREAM_DATA, DATA_BLOCKED, STREAM_DATA_BLOCKED: the limit, octets") +
           vkeys("maximum_streams", "MAX_STREAMS, STREAMS_BLOCKED: the stream count limit") +
           vkeys("sequence_number", "NEW_CONNECTION_ID, RETIRE_CONNECTION_ID: sequence number") + vkeys("retire_prior_to", "NEW_CONNECTION_ID: retire prior to") +
           [("list", "connection_id", "NEW_CONNECTION_ID: the connection ID, as octets (its length is written from the list)"),
            ("key", "stateless_reset_token", "NEW_CONNECTION_ID: the stateless reset token, as hexadecimal digits"),
            ("key", "path_data", "PATH_CHALLENGE, PATH_RESPONSE: the 8 octets of data, as hexadecimal digits")] +
           vkeys("frame_type_in_error", "CONNECTION_CLOSE (0x1c): the type of the frame that triggered the error") +
           [("key", "reason_length_size", "CONNECTION_CLOSE: the reason length's size code"), ("list", "reason_phrase", "CONNECTION_CLOSE: the reason phrase, as UTF-8 octets"),
            ("key", "octet", "one octet")])


# ---------------------------------------------------------------- transport parameters

P = "quictp"


def tp_pack():
    L = head("quic-transport-parameters", ["QUIC transport parameters (RFC 9000 section 18): the quic_transport_parameters TLS extension's data,",
                                           "each parameter a variable-length ID, a variable-length value length and the value octets. Written",
                                           "by tools/gen/quic-pack.py; do not edit by hand."], "tp", [P])
    L += ["group  quictp.parameters  rest"] + ind(1, varint(P, "parameter_id") +
                                                  counted(P, "value_length_size", "value_length", "value", octet(P))) + ["end"]
    return text(L)


TP_KEYS = ([("list", "parameters", "the transport parameters, in order")] +
           vkeys("parameter_id", "parameter ID (0 original_destination_connection_id, 1 max_idle_timeout, 2 stateless_reset_token, 3 max_udp_payload_size, 4 initial_max_data, 5-7 initial_max_stream_data, 8-9 initial_max_streams, 10 ack_delay_exponent, 11 max_ack_delay, 12 disable_active_migration, 13 preferred_address, 14 active_connection_id_limit, 15 initial_source_connection_id, 16 retry_source_connection_id)") +
           [("key", "value_length_size", "the value length's size code (the length is written from the list)"),
            ("list", "value", "the parameter value, as octets (a variable-length integer for most IDs)"), ("key", "octet", "one octet")])


def build(out):
    out.write("packs/quic-long-header/pack.def", lh_pack())
    out.write("packs/quic-frames/pack.def", frames_pack())
    out.write("packs/quic-transport-parameters/pack.def", tp_pack())
    out.write("model/quiclh.def", module("quiclh", ["# The quiclh module: QUIC long-header packet fields beyond the invariants. Written by tools/gen/quic-pack.py."], "lh", LH_KEYS))
    out.write("model/quicfr.def", module("quicfr", ["# The quicfr module: QUIC frame fields (RFC 9000 section 19). Written by tools/gen/quic-pack.py."], "fr", FR_KEYS, ["stateless_reset_token", "path_data"]))
    out.write("model/quictp.def", module("quictp", ["# The quictp module: QUIC transport parameters (RFC 9000 section 18). Written by tools/gen/quic-pack.py."], "tp", TP_KEYS))
    return {"quic": 6}


def main(argv=None):
    return genio.vector_main("quic-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
