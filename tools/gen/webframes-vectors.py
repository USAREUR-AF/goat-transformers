#!/usr/bin/env python3
"""webframes-vectors: write the vectors of the packs http2-frame, http3-frame, websocket-frame and tls-record.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of RFC 9113 sections 4.1 and 6, RFC 9114 section 7 with RFC 9000 section 16,
RFC 6455 section 5.2, and RFC 8446 sections 4 and 5.1 (with RFC 6066 section 3): multi-octet fields
big-endian.

Inputs: frames and records built here from values chosen here; none is copied from a document or a
capture. Host names are under example.com; randoms and keys are invented octets.

`expect` of every round trip is this program's packing of the values, which for these inputs is the
input; `model` holds values that were packed.

Usage: python3 -I tools/gen/webframes-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/webframes-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"


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


def u24(v):
    return struct.pack(">I", v)[1:]


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


# ---------------------------------------------------------------- HTTP/2

def h2(ftype, flags, stream, payload):
    return u24(len(payload)) + u8(ftype, flags) + u32(stream) + payload


def h2_vectors():
    p, R, K = "http2-frame", "RFC 9113 sections 4.1 and 6", "h2."
    out = []
    s = h2(4, 0, 0, u16(3) + u32(100) + u16(4) + u32(65535) + u16(5) + u32(16384))
    out.append((p, "01-settings-roundtrip.json", vec(p, "settings-roundtrip", s,
                {K + "frame_type": "4", K + "stream_id": "0", K + "settings.#": "3", K + "settings[1]." + K + "setting_id": "4",
                 K + "settings[1]." + K + "setting_value": "65535"}, ref=R + "; SETTINGS with three parameters")))
    out.append((p, "02-settings-ack-roundtrip.json", vec(p, "settings-ack-roundtrip", h2(4, 1, 0, b""),
                {K + "flag_end_stream_or_ack": "1", K + "settings.#": "0"}, ref=R + "; a SETTINGS acknowledgement")))
    hd = h2(1, 0x25, 1, u32(0x80000000 | 0) + u8(15) + bytes.fromhex("828684418aa0e41d139d09b8f01e07"))
    out.append((p, "03-headers-priority-roundtrip.json", vec(p, "headers-priority-roundtrip", hd,
                {K + "frame_type": "1", K + "flag_priority": "1", K + "flag_end_headers": "1", K + "flag_end_stream_or_ack": "1",
                 K + "stream_id": "1", K + "exclusive": "1", K + "stream_dependency": "0", K + "weight": "15", K + "header_block.#": "15"},
                ref=R + "; HEADERS with END_STREAM, END_HEADERS and a priority (the HPACK block as octets)")))
    dt = h2(0, 0x09, 3, u8(4) + b"hello" + bytes(4))
    out.append((p, "04-data-padded-roundtrip.json", vec(p, "data-padded-roundtrip", dt,
                {K + "flag_padded": "1", K + "pad_length": "4", K + "data.#": "9"}, ref=R + "; DATA with END_STREAM and 4 octets of padding")))
    out.append((p, "05-ping-roundtrip.json", vec(p, "ping-roundtrip", h2(6, 0, 0, bytes(range(1, 9))),
                {K + "opaque_data": bytes(range(1, 9)).hex()}, ref=R + "; PING")))
    out.append((p, "06-goaway-roundtrip.json", vec(p, "goaway-roundtrip", h2(7, 0, 0, u32(7, 0) + b"bye"),
                {K + "last_stream_id": "7", K + "error_code": "0", K + "debug_data.#": "3"}, ref=R + "; GOAWAY with debug data")))
    out.append((p, "07-window-update-roundtrip.json", vec(p, "window-update-roundtrip", h2(8, 0, 1, u32(1048576)),
                {K + "window_size_increment": "1048576"}, ref=R + "; WINDOW_UPDATE")))
    out.append((p, "08-rst-stream-roundtrip.json", vec(p, "rst-stream-roundtrip", h2(3, 0, 5, u32(8)),
                {K + "error_code": "8"}, ref=R + "; RST_STREAM with CANCEL")))
    out.append((p, "09-push-promise-roundtrip.json", vec(p, "push-promise-roundtrip", h2(5, 0x04, 1, u32(2) + bytes.fromhex("8287")),
                {K + "promised_stream_id": "2", K + "header_block.#": "2"}, ref=R + "; PUSH_PROMISE")))
    out.append((p, "10-unknown-type-roundtrip.json", vec(p, "unknown-type-roundtrip", h2(0x0A, 0, 0, b"\x00\x01x"),
                {K + "frame_type": "10", K + "payload.#": "3"}, ref=R + "; a frame of type 10 (ALTSVC, defined elsewhere), kept as octets")))
    out.append((p, "11-cut-payload-is-malformed.json", vec(p, "cut-payload-is-malformed", s[:15], error="malformed-wire",
                ref=R + "; the SETTINGS frame of vector 01 cut inside its payload")))
    return out


# ---------------------------------------------------------------- HTTP/3

def qv(v, size=None):
    if size is None:
        size = 0 if v < 64 else 1 if v < 16384 else 2 if v < 2**30 else 3
    n = 1 << size
    return (v | (size << (8 * n - 2))).to_bytes(n, "big")


def h3_vectors():
    p, R, K = "http3-frame", "RFC 9114 section 7 and RFC 9000 section 16", "h3."
    out = []
    body = qv(1) + qv(4096) + qv(6) + qv(16384) + qv(7) + qv(100)
    s = qv(4) + qv(len(body)) + body
    out.append((p, "01-settings-roundtrip.json", vec(p, "settings-roundtrip", s,
                {K + "frame_type": "4", K + "frame_length": str(len(body)), K + "settings.#": "3",
                 K + "settings[0]." + K + "setting_value_size": "1", K + "settings[0]." + K + "setting_value": "4096",
                 K + "settings[1]." + K + "setting_value_size": "2", K + "settings[2]." + K + "setting_id": "7"},
                ref=R + "; SETTINGS with three parameters in one-, two- and four-octet integers")))
    d = qv(0) + qv(5) + b"hello"
    out.append((p, "02-data-roundtrip.json", vec(p, "data-roundtrip", d, {K + "frame_type": "0", K + "data.#": "5"}, ref=R + "; DATA")))
    hd = qv(1) + qv(4) + bytes.fromhex("0000d1d7")
    out.append((p, "03-headers-roundtrip.json", vec(p, "headers-roundtrip", hd, {K + "field_section.#": "4"},
                ref=R + "; HEADERS with a QPACK field section as octets")))
    g = qv(7) + qv(2) + qv(100, 1)
    out.append((p, "04-goaway-two-octet-id-roundtrip.json", vec(p, "goaway-two-octet-id-roundtrip", g,
                {K + "frame_type": "7", K + "id_value_size": "1", K + "id_value": "100"}, ref=R + "; GOAWAY with a two-octet stream ID")))
    big = qv(0, 3) + qv(0)
    out.append((p, "05-eight-octet-type-roundtrip.json", vec(p, "eight-octet-type-roundtrip", big,
                {K + "frame_type_size": "3", K + "frame_type": "0", K + "frame_length": "0"},
                ref=R + "; a DATA frame type written as an eight-octet integer, which the size code keeps")))
    out.append((p, "06-cut-varint-is-malformed.json", vec(p, "cut-varint-is-malformed", bytes.fromhex("c000"), error="malformed-wire",
                ref=R + "; an eight-octet integer cut after two octets")))
    return out


# ---------------------------------------------------------------- WebSocket

def ws(fin, opcode, payload, key=None, rsv=0):
    b = u8((fin << 7) | (rsv << 4) | opcode)
    m = 0x80 if key else 0
    n = len(payload)
    if n < 126:
        b += u8(m | n)
    elif n < 65536:
        b += u8(m | 126) + u16(n)
    else:
        b += u8(m | 127) + struct.pack(">Q", n)
    if key:
        b += key
        payload = bytes(c ^ key[i % 4] for i, c in enumerate(payload))
    return b + payload


def ws_vectors():
    p, R, K = "websocket-frame", "RFC 6455 section 5.2", "ws."
    out = []
    out.append((p, "01-text-unmasked-roundtrip.json", vec(p, "text-unmasked-roundtrip", ws(1, 1, b"Hello"),
                {K + "fin": "1", K + "opcode": "1", K + "mask": "0", K + "payload_len7": "5", K + "payload.#": "5"},
                ref=R + "; an unmasked text frame")))
    key = bytes.fromhex("37fa213d")
    out.append((p, "02-binary-masked-roundtrip.json", vec(p, "binary-masked-roundtrip", ws(1, 2, b"\x01\x02\x03\x04\x05\x06", key),
                {K + "opcode": "2", K + "mask": "1", K + "masking_key": "37fa213d", K + "payload.#": "6"},
                ref=R + "; a masked binary frame (payload kept masked)")))
    out.append((p, "03-extended-16-roundtrip.json", vec(p, "extended-16-roundtrip", ws(0, 2, bytes(200)),
                {K + "fin": "0", K + "payload_len7": "126", K + "payload_len_ext": "200", K + "payload.#": "200"},
                ref=R + "; a non-final binary fragment of 200 octets, with the 16-bit length")))
    out.append((p, "04-close-roundtrip.json", vec(p, "close-roundtrip", ws(1, 8, u16(1000) + b"bye"),
                {K + "opcode": "8", K + "close_code": "1000", K + "close_reason.#": "3"}, ref=R + "; an unmasked close frame with a status")))
    out.append((p, "05-ping-roundtrip.json", vec(p, "ping-roundtrip", ws(1, 9, b""), {K + "opcode": "9", K + "payload_len7": "0"},
                ref=R + "; an empty ping")))
    out.append((p, "06-cut-length-is-malformed.json", vec(p, "cut-length-is-malformed", ws(0, 2, bytes(200))[:3], error="malformed-wire",
                ref=R + "; the frame of vector 03 cut inside its 16-bit length")))
    return out


# ---------------------------------------------------------------- TLS

def record(ctype, body):
    return u8(ctype) + u16(0x0303) + u16(len(body)) + body


def hs(htype, body):
    return u8(htype) + u24(len(body)) + body


def ext(t, data):
    return u16(t, len(data)) + data


def tls_vectors():
    p, R, K = "tls-record", "RFC 8446 sections 4 and 5.1 and RFC 6066 section 3", "tls13."
    out = []
    rnd = bytes(range(32))
    sni = ext(0, u16(16) + u8(0) + u16(13) + b"a.example.com")
    sv = ext(43, u8(4) + u16(0x0304, 0x0303))
    ks = ext(51, u16(38) + u16(29, 32) + bytes(range(100, 132)))
    exts = sni + sv + ks
    ch = u16(0x0303) + rnd + u8(32) + bytes(range(32, 64)) + u16(4) + u16(0x1301, 0x1302) + u8(1, 0) + u16(len(exts)) + exts
    c = record(22, hs(1, ch))
    out.append((p, "01-client-hello-roundtrip.json", vec(p, "client-hello-roundtrip", c,
                {"inet.tls_content_type": "22", "inet.tls_legacy_version": str(0x0303), K + "handshakes.#": "1",
                 K + "handshakes[0]." + K + "handshake_type": "1", K + "handshakes[0]." + K + "random": rnd.hex(),
                 K + "handshakes[0]." + K + "legacy_session_id.#": "32", K + "handshakes[0]." + K + "cipher_suites.#": "2",
                 K + "handshakes[0]." + K + "client_extensions.#": "3",
                 K + "handshakes[0]." + K + "client_extensions[0]." + K + "server_names[0]." + K + "host_name.#": "13",
                 K + "handshakes[0]." + K + "client_extensions[1]." + K + "supported_versions.#": "2",
                 K + "handshakes[0]." + K + "client_extensions[2]." + K + "extension_type": "51"},
                ref=R + "; a ClientHello with server_name, supported_versions and key_share")))
    shx = ext(43, u16(0x0304)) + ext(51, u16(29, 32) + bytes(range(150, 182)))
    sh = u16(0x0303) + bytes(range(200, 232)) + u8(32) + bytes(range(32, 64)) + u16(0x1301) + u8(0) + u16(len(shx)) + shx
    s = record(22, hs(2, sh))
    out.append((p, "02-server-hello-roundtrip.json", vec(p, "server-hello-roundtrip", s,
                {K + "handshakes[0]." + K + "handshake_type": "2", K + "handshakes[0]." + K + "selected_cipher_suite": str(0x1301),
                 K + "handshakes[0]." + K + "server_extensions[0]." + K + "selected_version": str(0x0304),
                 K + "handshakes[0]." + K + "server_extensions[1]." + K + "extension_data.#": "36"},
                ref=R + "; a ServerHello selecting TLS 1.3 with a key_share")))
    two = record(22, hs(20, bytes(32)) + hs(24, u8(0)))
    out.append((p, "03-two-handshake-messages-roundtrip.json", vec(p, "two-handshake-messages-roundtrip", two,
                {K + "handshakes.#": "2", K + "handshakes[0]." + K + "handshake_type": "20", K + "handshakes[0]." + K + "handshake_body.#": "32",
                 K + "handshakes[1]." + K + "handshake_type": "24"},
                ref=R + "; a record of two handshake messages of other types (finished, key_update), their bodies as octets")))
    out.append((p, "04-alert-roundtrip.json", vec(p, "alert-roundtrip", record(21, u8(2, 40)),
                {"inet.tls_alert_level": "2", "inet.tls_alert_description": "40"}, ref=R + "; a fatal handshake_failure alert")))
    out.append((p, "05-change-cipher-spec-roundtrip.json", vec(p, "change-cipher-spec-roundtrip", record(20, u8(1)),
                {"inet.tls_ccs_value": "1"}, ref=R + "; the compatibility change_cipher_spec record")))
    out.append((p, "06-application-data-roundtrip.json", vec(p, "application-data-roundtrip", record(23, bytes(range(40))),
                {K + "record_data.#": "40"}, ref=R + "; an encrypted record, its body as octets")))
    out.append((p, "07-cut-handshake-is-malformed.json", vec(p, "cut-handshake-is-malformed", c[:60], error="malformed-wire",
                ref=R + "; the ClientHello record of vector 01 cut inside its session ID")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in h2_vectors() + h3_vectors() + ws_vectors() + tls_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("webframes-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
