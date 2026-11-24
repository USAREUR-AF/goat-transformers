#!/usr/bin/env python3
"""Write the web transport framing packs and their modules: the HTTP/2 frame (RFC 9113), the HTTP/3
frame (RFC 9114, with QUIC variable-length integers), the WebSocket frame (RFC 6455) and the TLS 1.3
record with its handshake messages (RFC 8446).

A QUIC variable-length integer names its size in its first two bits, so it is stated as a 2-bit field
and a `switch` on it choosing a 6, 14, 30 or 62-bit value; the two-bit size is kept, so a round trip
writes the same size back.
The vectors are not written here: tools/gen/webframes-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/webframes-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "h2": 'source        "IETF RFC 9113, HTTP/2, June 2022, sections 4.1 and 6, https://www.rfc-editor.org/rfc/rfc9113.txt; layout restated"',
    "h3": ('source        "IETF RFC 9114, HTTP/3, June 2022, section 7, https://www.rfc-editor.org/rfc/rfc9114.txt; IETF RFC 9000 section 16 '
           '(variable-length integers), https://www.rfc-editor.org/rfc/rfc9000.txt; layout restated"'),
    "ws": 'source        "IETF RFC 6455, The WebSocket Protocol, December 2011, section 5.2, https://www.rfc-editor.org/rfc/rfc6455.txt; layout restated"',
    "tls": ('source        "IETF RFC 8446, The Transport Layer Security (TLS) Protocol Version 1.3, August 2018, sections 4, 4.1.2, 4.1.3, '
            '4.2, 4.2.1, 5.1 and 6, https://www.rfc-editor.org/rfc/rfc8446.txt; IETF RFC 6066 section 3 (server_name); layout restated"'),
}


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


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def text(L):
    return "\n".join(L) + "\n"


def module(name, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- HTTP/2

T = "h2"


def h2_pack():
    pad = sw("h2.flag_padded", [("1", [F(T, "pad_length", 8)])], [])
    payload = sw("h2.frame_type", [
        ("0", pad + octets(T, "data")),
        ("1", pad + sw("h2.flag_priority", [("1", [F(T, "exclusive", 1), F(T, "stream_dependency", 31), F(T, "weight", 8)])], []) +
         octets(T, "header_block")),
        ("2", [F(T, "exclusive", 1), F(T, "stream_dependency", 31), F(T, "weight", 8)]),
        ("3", [F(T, "error_code", 32)]),
        ("4", ["group  h2.settings  rest", "  " + F(T, "setting_id", 16), "  " + F(T, "setting_value", 32), "end"]),
        ("5", pad + [F(T, "promised_reserved", 1), F(T, "promised_stream_id", 31)] + octets(T, "header_block")),
        ("6", [F(T, "opaque_data", 64, "hex")]),
        ("7", [F(T, "goaway_reserved", 1), F(T, "last_stream_id", 31), F(T, "error_code", 32)] + octets(T, "debug_data")),
        ("8", [F(T, "window_reserved", 1), F(T, "window_size_increment", 31)]),
        ("9", octets(T, "header_block"))],
        octets(T, "payload"))
    L = head("http2-frame", ["HTTP/2 frame (RFC 9113): the 9-octet header and the payload by frame type. The header block (HPACK) is",
                             "octets. Written by tools/gen/webframes-pack.py; do not edit by hand."], "h2", [T])
    L += ["length  24  bytes  plus  -6", "  " + F(T, "frame_type", 8)]
    L += ind(1, [F(T, "flag_0x80", 1), F(T, "flag_0x40", 1), F(T, "flag_priority", 1), F(T, "flag_0x10", 1), F(T, "flag_padded", 1),
                 F(T, "flag_end_headers", 1), F(T, "flag_0x02", 1), F(T, "flag_end_stream_or_ack", 1),
                 F(T, "stream_reserved", 1), F(T, "stream_id", 31)] + payload) + ["end"]
    return text(L)


H2_KEYS = [
    ("key", "frame_type", "frame type: 0 DATA, 1 HEADERS, 2 PRIORITY, 3 RST_STREAM, 4 SETTINGS, 5 PUSH_PROMISE, 6 PING, 7 GOAWAY, 8 WINDOW_UPDATE, 9 CONTINUATION"),
    ("key", "flag_0x80", "flag bit 0x80 (unused by the frame types of RFC 9113)"), ("key", "flag_0x40", "flag bit 0x40 (unused)"),
    ("key", "flag_priority", "flag 0x20: PRIORITY (HEADERS)"), ("key", "flag_0x10", "flag bit 0x10 (unused)"),
    ("key", "flag_padded", "flag 0x08: PADDED (DATA, HEADERS, PUSH_PROMISE)"), ("key", "flag_end_headers", "flag 0x04: END_HEADERS (HEADERS, PUSH_PROMISE, CONTINUATION)"),
    ("key", "flag_0x02", "flag bit 0x02 (unused)"), ("key", "flag_end_stream_or_ack", "flag 0x01: END_STREAM (DATA, HEADERS) or ACK (SETTINGS, PING)"),
    ("key", "stream_reserved", "the reserved bit before the stream identifier"), ("key", "stream_id", "stream identifier (0 for the connection)"),
    ("key", "pad_length", "PADDED: the length of the padding at the end of the payload"),
    ("list", "data", "DATA: the data and any padding, as octets"),
    ("key", "exclusive", "priority: E, the dependency is exclusive"), ("key", "stream_dependency", "priority: the stream depended on"),
    ("key", "weight", "priority: weight minus one"), ("list", "header_block", "HEADERS, PUSH_PROMISE, CONTINUATION: the field block fragment (HPACK) and any padding, as octets"),
    ("key", "error_code", "RST_STREAM, GOAWAY: error code (0 NO_ERROR, 1 PROTOCOL_ERROR, 2 INTERNAL_ERROR, 3 FLOW_CONTROL_ERROR, 7 REFUSED_STREAM, 8 CANCEL ...)"),
    ("list", "settings", "SETTINGS: the settings"), ("key", "setting_id", "setting identifier (1 HEADER_TABLE_SIZE, 2 ENABLE_PUSH, 3 MAX_CONCURRENT_STREAMS, 4 INITIAL_WINDOW_SIZE, 5 MAX_FRAME_SIZE, 6 MAX_HEADER_LIST_SIZE)"),
    ("key", "setting_value", "setting value"), ("key", "promised_reserved", "PUSH_PROMISE: the reserved bit"),
    ("key", "promised_stream_id", "PUSH_PROMISE: the promised stream identifier"), ("key", "opaque_data", "PING: the 8 octets of opaque data, as hexadecimal digits"),
    ("key", "goaway_reserved", "GOAWAY: the reserved bit"), ("key", "last_stream_id", "GOAWAY: the last stream identifier processed"),
    ("list", "debug_data", "GOAWAY: additional debug data, as octets"), ("key", "window_reserved", "WINDOW_UPDATE: the reserved bit"),
    ("key", "window_size_increment", "WINDOW_UPDATE: the window size increment"), ("list", "payload", "a frame of another type: its payload, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- HTTP/3

Q = "h3"


def varint(key, mod=Q):
    return [F(mod, key + "_size", 2)] + sw("%s.%s_size" % (mod, key), [("0", [F(mod, key, 6)]), ("1", [F(mod, key, 14)]),
                                                                         ("2", [F(mod, key, 30)]), ("3", [F(mod, key, 62)])])


def h3_pack():
    payload = sw("h3.frame_type", [
        ("0", octets(Q, "data")),
        ("1", octets(Q, "field_section")),
        ("3,7,13", varint("id_value")),
        ("4", ["group  h3.settings  rest"] + ind(1, varint("setting_id") + varint("setting_value")) + ["end"]),
        ("5", varint("push_id") + octets(Q, "field_section"))],
        octets(Q, "payload"))
    L = head("http3-frame", ["HTTP/3 frame (RFC 9114 section 7): type and length as QUIC variable-length integers, then the payload by",
                             "type. One message is one frame. Written by tools/gen/webframes-pack.py; do not edit by hand."], "h3", [Q])
    L += varint("frame_type") + varint("frame_length") + payload
    return text(L)


def vkeys(key, what):
    return [("key", key + "_size", what + ": the varint size code (0 one octet, 1 two, 2 four, 3 eight)"), ("key", key, what)]


H3_KEYS = (vkeys("frame_type", "frame type (0 DATA, 1 HEADERS, 3 CANCEL_PUSH, 4 SETTINGS, 5 PUSH_PROMISE, 7 GOAWAY, 13 MAX_PUSH_ID; 0x1f*N+0x21 reserved)") +
           vkeys("frame_length", "frame length, octets of the payload (carried, not computed)") +
           [("list", "data", "DATA: the payload, as octets"), ("list", "field_section", "HEADERS, PUSH_PROMISE: the encoded field section (QPACK), as octets")] +
           vkeys("id_value", "CANCEL_PUSH push ID, GOAWAY stream or push ID, MAX_PUSH_ID push ID") +
           [("list", "settings", "SETTINGS: the settings")] + vkeys("setting_id", "setting identifier (1 QPACK_MAX_TABLE_CAPACITY, 6 MAX_FIELD_SECTION_SIZE, 7 QPACK_BLOCKED_STREAMS ...)") +
           vkeys("setting_value", "setting value") + vkeys("push_id", "PUSH_PROMISE: push ID") +
           [("list", "payload", "a frame of another type: its payload, as octets"), ("key", "octet", "one octet")])


# ---------------------------------------------------------------- WebSocket

W = "ws"


def ws_pack():
    L = head("websocket-frame", ["WebSocket frame (RFC 6455 section 5.2): FIN, RSV, opcode, mask bit, payload length (7, 7+16 or 7+64",
                                 "bits), masking key and payload. One message is one frame. Written by tools/gen/webframes-pack.py."], "ws", [W])
    L += [F(W, "fin", 1), F(W, "rsv1", 1), F(W, "rsv2", 1), F(W, "rsv3", 1), F(W, "opcode", 4), F(W, "mask", 1), F(W, "payload_len7", 7)]
    L += sw("ws.payload_len7", [("126", [F(W, "payload_len_ext", 16)]), ("127", [F(W, "payload_len_ext", 64)])], [])
    L += sw("ws.mask", [("1", [F(W, "masking_key", 32, "hex")])], [])
    # RFC 6455 5.5.1: a Close frame MAY contain a body; a body begins with the 2-octet status code
    close = sw("ws.payload_len7", [("0", octets(W, "close_reason"))], [F(W, "close_code", 16)] + octets(W, "close_reason"))
    L += sw("ws.opcode", [("8", close)], octets(W, "payload"))
    return text(L)


WS_KEYS = [
    ("key", "fin", "FIN: the final fragment of a message"), ("key", "rsv1", "RSV1 (per-message compression when negotiated)"),
    ("key", "rsv2", "RSV2"), ("key", "rsv3", "RSV3"),
    ("key", "opcode", "opcode: 0 continuation, 1 text, 2 binary, 8 close, 9 ping, 10 pong"), ("key", "mask", "MASK: the payload is masked (client to server)"),
    ("key", "payload_len7", "the 7-bit payload length: 0-125 the length, 126 a 16-bit length follows, 127 a 64-bit length follows"),
    ("key", "payload_len_ext", "the extended payload length (16 or 64 bits)"), ("key", "masking_key", "the masking key, as hexadecimal digits"),
    ("key", "close_code", "close frame: the status code (unmasked frames; 1000 normal ...)"), ("list", "close_reason", "close frame: the reason, as octets"),
    ("list", "payload", "the payload as on the wire (masked when MASK is 1), as octets"), ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- TLS 1.3

L_ = "tls13"


def ext_list(lst, typekey, cases):
    return (["length  16  bytes", "  group  tls13.%s  rest" % lst, "    " + F(L_, typekey, 16), "    length  16  bytes"] +
            ind(3, sw("tls13.%s" % typekey, cases, octets(L_, "extension_data"))) + ["    end", "  end", "end"])


def session_id():
    return ["count  session_id_length  8", "group  tls13.legacy_session_id  count  @session_id_length", "  " + F(L_, "octet", 8), "end"]


def tls_pack():
    sni = (["length  16  bytes", "  group  tls13.server_names  rest", "    " + F(L_, "name_type", 8), "    length  16  bytes"] +
           ind(3, octets(L_, "host_name")) + ["    end", "  end", "end"])
    ch_ext = ext_list("client_extensions", "extension_type", [
        ("0", sni),
        ("43", ["length  8  bytes", "  group  tls13.supported_versions  rest", "    " + F(L_, "version", 16), "  end", "end"])])
    sh_ext = ext_list("server_extensions", "extension_type", [("43", [F(L_, "selected_version", 16)])])
    client_hello = ([F(L_, "legacy_version", 16), F(L_, "random", 256, "hex")] + session_id() +
                    ["length  16  bytes", "  group  tls13.cipher_suites  rest", "    " + F(L_, "cipher_suite", 16), "  end", "end",
                     "length  8  bytes", "  group  tls13.compression_methods  rest", "    " + F(L_, "compression_method", 8), "  end", "end"] +
                    ch_ext)
    server_hello = ([F(L_, "legacy_version", 16), F(L_, "random", 256, "hex")] + session_id() +
                    [F(L_, "selected_cipher_suite", 16), F(L_, "selected_compression_method", 8)] + sh_ext)
    hs = (["group  tls13.handshakes  rest", "  " + F(L_, "handshake_type", 8), "  length  24  bytes"] +
          ind(2, sw("tls13.handshake_type", [("1", client_hello), ("2", server_hello)], octets(L_, "handshake_body"))) + ["  end", "end"])
    body = sw("inet.tls_content_type", [
        ("22", hs),
        ("21", ["field  inet.tls_alert_level  8  uint", "field  inet.tls_alert_description  8  uint"]),
        ("20", ["field  inet.tls_ccs_value  8  uint"])],
        octets(L_, "record_data"))
    L = head("tls-record", ["TLS 1.3 record (RFC 8446 section 5.1) with its handshake messages (section 4): the record header on the inet",
                            "keys of tls-record-header, then by content type the handshake messages (ClientHello and ServerHello laid out),",
                            "the alert, the change_cipher_spec, or the data. Written by tools/gen/webframes-pack.py; do not edit by hand."],
             "tls", ["inet", L_])
    L += ["field  inet.tls_content_type  8  uint", "field  inet.tls_legacy_version  16  uint", "length  16  bytes"] + ind(1, body) + ["end"]
    return text(L)


TLS_KEYS = [
    ("list", "handshakes", "the handshake messages of the record, in order"),
    ("key", "handshake_type", "handshake type: 1 client_hello, 2 server_hello, 4 new_session_ticket, 8 encrypted_extensions, 11 certificate, 13 certificate_request, 15 certificate_verify, 20 finished, 24 key_update"),
    ("key", "legacy_version", "ClientHello, ServerHello: legacy_version (0x0303)"), ("key", "random", "ClientHello, ServerHello: the 32-octet random, as hexadecimal digits"),
    ("list", "legacy_session_id", "ClientHello, ServerHello: the legacy session ID, as octets (its length is written from the list)"),
    ("list", "cipher_suites", "ClientHello: the offered cipher suites"), ("key", "cipher_suite", "a cipher suite code (0x1301 TLS_AES_128_GCM_SHA256 ...)"),
    ("list", "compression_methods", "ClientHello: legacy compression methods (one, 0)"), ("key", "compression_method", "a compression method"),
    ("list", "client_extensions", "ClientHello: the extensions"), ("list", "server_extensions", "ServerHello: the extensions"),
    ("key", "extension_type", "extension type (0 server_name, 10 supported_groups, 13 signature_algorithms, 16 ALPN, 43 supported_versions, 45 psk_key_exchange_modes, 51 key_share ...)"),
    ("list", "server_names", "server_name: the names"), ("key", "name_type", "server_name: name type (0 host_name)"),
    ("list", "host_name", "server_name: the host name, as its ASCII octets"),
    ("list", "supported_versions", "ClientHello supported_versions: the versions offered"), ("key", "version", "a protocol version (0x0304 TLS 1.3)"),
    ("key", "selected_version", "ServerHello supported_versions: the selected version"),
    ("list", "extension_data", "an extension of another type: its data, as octets"),
    ("key", "selected_cipher_suite", "ServerHello: the selected cipher suite"), ("key", "selected_compression_method", "ServerHello: legacy compression method (0)"),
    ("list", "handshake_body", "a handshake message of another type: its body, as octets"),
    ("list", "record_data", "a record of another content type (application data, encrypted records): its body, as octets"),
    ("key", "octet", "one octet"),
]


def build(out):
    out.write("packs/http2-frame/pack.def", h2_pack())
    out.write("packs/http3-frame/pack.def", h3_pack())
    out.write("packs/websocket-frame/pack.def", ws_pack())
    out.write("packs/tls-record/pack.def", tls_pack())
    out.write("model/h2.def", module("h2", ["# The h2 module: HTTP/2 frame fields (RFC 9113). Written by tools/gen/webframes-pack.py."], "h2", H2_KEYS, ["opaque_data"]))
    out.write("model/h3.def", module("h3", ["# The h3 module: HTTP/3 frame fields (RFC 9114). Written by tools/gen/webframes-pack.py."], "h3", H3_KEYS))
    out.write("model/ws.def", module("ws", ["# The ws module: WebSocket frame fields (RFC 6455). Written by tools/gen/webframes-pack.py."], "ws", WS_KEYS, ["masking_key"]))
    out.write("model/tls13.def", module("tls13", ["# The tls13 module: TLS 1.3 handshake fields (RFC 8446). Written by tools/gen/webframes-pack.py."], "tls", TLS_KEYS, ["random"]))
    return {"webframes": 8}


def main(argv=None):
    return genio.vector_main("webframes-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
