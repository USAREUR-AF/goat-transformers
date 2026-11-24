#!/usr/bin/env python3
"""remote-vectors: write the vectors of the packs ssh-packet, ssh-message and smb2-message.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of RFC 4253 sections 6, 7, 10, 11 and 12, RFC 4251 section 5, RFC 4252, RFC
4254 and RFC 8308 (SSH, big-endian), and [MS-SMB2] sections 2.2.1-2.2.14, 2.2.41 and 2.2.42 (SMB2,
little-endian).

Inputs: packets and messages built here from values chosen here; none is copied from a document's
examples or a capture. Names, GUIDs, keys and identifiers are invented.

`expect` of every round trip is this program's packing of the values, which for these inputs is the
input; `model` holds values that were packed.

Usage: python3 -I tools/gen/remote-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/remote-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"


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


# ---------------------------------------------------------------- SSH (big-endian)

def u8(*v):
    return bytes(v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def s(b):
    if isinstance(b, str):
        b = b.encode()
    return u32(len(b)) + b


def ssh_packet_vectors():
    p, R, K = "ssh-packet", "RFC 4253 section 6", "sshpkt."
    out = []
    payload = u8(5) + s("ssh-userauth")
    pad = bytes(range(10))
    pkt = u32(1 + len(payload) + len(pad)) + u8(len(pad)) + payload + pad
    out.append((p, "01-unencrypted-roundtrip.json", vec(p, "unencrypted-roundtrip", pkt,
                {K + "padding_length": "10", K + "payload_and_padding.#": str(len(payload) + 10), K + "mac.#": "0"},
                ref=R + "; a packet carrying SERVICE_REQUEST before keys are exchanged, no MAC")))
    mac = bytes(range(100, 132))
    out.append((p, "02-with-mac-roundtrip.json", vec(p, "with-mac-roundtrip", pkt + mac, {K + "mac.#": "32"},
                ref=R + "; the same packet followed by a 32-octet MAC")))
    out.append((p, "03-cut-packet-is-malformed.json", vec(p, "cut-packet-is-malformed", pkt[:20], error="malformed-wire",
                ref=R + "; the packet of vector 01 cut before its length")))
    return out


def ssh_message_vectors():
    p, R, K = "ssh-message", "RFC 4253, RFC 4252, RFC 4254 and RFC 8308", "sshmsg."
    out = []
    cipher = "chacha20-poly1305" + "@" + "openssh" + ".com"   # an algorithm name of the form name@domain
    lists = ["curve25519-sha256,ext-info-c", "ssh-ed25519", cipher, cipher,
             "hmac-sha2-256", "hmac-sha2-256", "none", "none", "", ""]
    kex = u8(20) + bytes(range(16)) + b"".join(s(x) for x in lists) + u8(0) + u32(0)
    out.append((p, "01-kexinit-roundtrip.json", vec(p, "kexinit-roundtrip", kex,
                {K + "message_number": "20", K + "cookie": bytes(range(16)).hex(), K + "kex_algorithms.#": str(len(lists[0])),
                 K + "languages_s2c.#": "0", K + "first_kex_packet_follows": "0"},
                ref="RFC 4253 section 7.1; a KEXINIT with its ten name-lists")))
    out.append((p, "02-disconnect-roundtrip.json", vec(p, "disconnect-roundtrip", u8(1) + u32(11) + s("bye") + s(""),
                {K + "reason_code": "11", K + "description.#": "3", K + "language_tag.#": "0"}, ref="RFC 4253 section 11.1; DISCONNECT")))
    out.append((p, "03-ignore-roundtrip.json", vec(p, "ignore-roundtrip", u8(2) + s(b"\x00\x01\x02"), {K + "data.#": "3"},
                ref="RFC 4253 section 11.2; IGNORE")))
    out.append((p, "04-newkeys-roundtrip.json", vec(p, "newkeys-roundtrip", u8(21), {K + "message_number": "21"},
                ref="RFC 4253 section 7.3; NEWKEYS")))
    out.append((p, "05-service-accept-roundtrip.json", vec(p, "service-accept-roundtrip", u8(6) + s("ssh-userauth"),
                {K + "service_name.#": "12"}, ref="RFC 4253 section 10; SERVICE_ACCEPT")))
    out.append((p, "06-ext-info-roundtrip.json", vec(p, "ext-info-roundtrip", u8(7) + u32(1) + s("server-sig-algs") + s("ssh-ed25519,rsa-sha2-256"),
                {K + "extensions.#": "1", K + "extensions[0]." + K + "extension_name.#": "15"}, ref="RFC 8308 section 2.3; EXT_INFO")))
    ua = u8(50) + s("alice") + s("ssh-connection") + s("password") + u8(0) + s("secret")
    out.append((p, "07-userauth-request-roundtrip.json", vec(p, "userauth-request-roundtrip", ua,
                {K + "user_name.#": "5", K + "method_name.#": "8", K + "method_data.#": "11"},
                ref="RFC 4252 section 5; a password USERAUTH_REQUEST, the method fields as octets")))
    out.append((p, "08-userauth-failure-roundtrip.json", vec(p, "userauth-failure-roundtrip", u8(51) + s("publickey,password") + u8(0),
                {K + "authentications.#": "18", K + "partial_success": "0"}, ref="RFC 4252 section 5.1; USERAUTH_FAILURE")))
    co = u8(90) + s("session") + u32(0, 2097152, 32768)
    out.append((p, "09-channel-open-roundtrip.json", vec(p, "channel-open-roundtrip", co,
                {K + "channel_type.#": "7", K + "sender_channel": "0", K + "initial_window_size": "2097152", K + "maximum_packet_size": "32768"},
                ref="RFC 4254 section 5.1; CHANNEL_OPEN for a session")))
    out.append((p, "10-channel-data-roundtrip.json", vec(p, "channel-data-roundtrip", u8(94) + u32(3) + s("ls\n"),
                {K + "recipient_channel": "3", K + "data.#": "3"}, ref="RFC 4254 section 5.2; CHANNEL_DATA")))
    cr = u8(98) + u32(3) + s("exec") + u8(1) + s("uptime")
    out.append((p, "11-channel-request-roundtrip.json", vec(p, "channel-request-roundtrip", cr,
                {K + "request_name.#": "4", K + "want_reply": "1", K + "request_data.#": "10"}, ref="RFC 4254 section 6.5; an exec CHANNEL_REQUEST")))
    out.append((p, "12-kex-method-message-roundtrip.json", vec(p, "kex-method-message-roundtrip", u8(30) + s(bytes(32)),
                {K + "message_number": "30", K + "message_data.#": "36"},
                ref="RFC 4253 section 12; a key exchange method message (number 30), kept as octets")))
    out.append((p, "13-cut-string-is-malformed.json", vec(p, "cut-string-is-malformed", kex[:30], error="malformed-wire",
                ref="RFC 4253 section 7.1; the KEXINIT of vector 01 cut inside its first name-list")))
    return out


# ---------------------------------------------------------------- SMB2 (little-endian)

def le(fmt, *v):
    return struct.pack("<" + fmt, *v)


def lsbhex(b):
    """hex under bit_order lsb: each octet's low nibble first."""
    return "".join("%x%x" % (x & 15, x >> 4) for x in b)


def smb2_header(command, msg_id, status=0, credits=1, response=0, async_id=None, tree_id=0, session_id=0, signature=bytes(16), flags_extra=0):
    flags = response | (2 if async_id is not None else 0) | flags_extra
    h = le("IHHIHHIIQ", 0x424D53FE, 64, 0, status, command, credits, flags, 0, msg_id)
    h += le("Q", async_id) if async_id is not None else le("II", 0xFEFF, tree_id)
    return h + le("Q", session_id) + signature


CLIENT_GUID = bytes(range(16))
SERVER_GUID = bytes(range(16, 32))


def smb2_vectors():
    p, R, K = "smb2-message", "[MS-SMB2] sections 2.2.1-2.2.14, 2.2.41 and 2.2.42", "smb2."
    out = []
    dialects = [0x0202, 0x0210, 0x0300, 0x0302, 0x0311]
    ctx = bytes(range(8))
    neg = (smb2_header(0, 0) + le("HHHHI", 36, len(dialects), 1, 0, 0x7F) + CLIENT_GUID + le("IHH", 112, 1, 0) +
           b"".join(le("H", d) for d in dialects) + ctx)
    out.append((p, "01-negotiate-request-roundtrip.json", vec(p, "negotiate-request-roundtrip", neg,
                {K + "command": "0", K + "response": "0", K + "async": "0", K + "structure_size": "36", K + "dialects.#": "5",
                 K + "dialects[4]." + K + "dialect": str(0x0311), K + "security_mode": "1", K + "capabilities": str(0x7F),
                 K + "client_guid": lsbhex(CLIENT_GUID), K + "buffer.#": "8"},
                ref="[MS-SMB2] 2.2.1.2 and 2.2.3; a NEGOTIATE request offering five dialects, the negotiate contexts as octets")))
    negr = (smb2_header(0, 0, response=1) + le("HHHH", 65, 1, 0x0311, 1) + SERVER_GUID +
            le("IIIIQQHHI", 0x2F, 8388608, 8388608, 8388608, 133000000000000000, 0, 128, 4, 136) + b"\x60\x02\xa0\x00" + bytes(8))
    out.append((p, "02-negotiate-response-roundtrip.json", vec(p, "negotiate-response-roundtrip", negr,
                {K + "response": "1", K + "status": "0", K + "dialect_revision": str(0x0311), K + "max_read_size": "8388608",
                 K + "system_time": "133000000000000000", K + "security_buffer_length": "4", K + "buffer.#": "12"},
                ref="[MS-SMB2] 2.2.4; a NEGOTIATE response selecting 3.1.1")))
    ss = (smb2_header(1, 2, status=0xC0000016, response=1, session_id=0x0000100000000001) + le("HHHH", 9, 0, 72, 6) + b"\x60\x04\xa1\x02\x30\x00")
    out.append((p, "03-session-setup-more-processing-roundtrip.json", vec(p, "session-setup-more-processing-roundtrip", ss,
                {K + "command": "1", K + "status": str(0xC0000016), K + "session_id": str(0x0000100000000001), K + "security_buffer_length": "6"},
                ref="[MS-SMB2] 2.2.6; a SESSION_SETUP response with STATUS_MORE_PROCESSING_REQUIRED, laid out as a success")))
    path = "\\\\server\\share".encode("utf-16-le")
    tc = smb2_header(3, 4, session_id=0x0000100000000001) + le("HHHH", 9, 0, 72, len(path)) + path
    out.append((p, "04-tree-connect-request-roundtrip.json", vec(p, "tree-connect-request-roundtrip", tc,
                {K + "command": "3", K + "path_length": str(len(path)), K + "buffer.#": str(len(path))},
                ref="[MS-SMB2] 2.2.9; a TREE_CONNECT request with the share path in UTF-16LE")))
    tcr = smb2_header(3, 4, response=1, tree_id=5, session_id=0x0000100000000001) + le("HBBIII", 16, 1, 0, 0x0800, 0, 0x001F01FF)
    out.append((p, "05-tree-connect-response-roundtrip.json", vec(p, "tree-connect-response-roundtrip", tcr,
                {K + "tree_id": "5", K + "share_type": "1", K + "share_flags": str(0x0800), K + "maximal_access": str(0x001F01FF)},
                ref="[MS-SMB2] 2.2.10; a TREE_CONNECT response for a disk share")))
    name = "dir\\file.txt".encode("utf-16-le")
    cr = (smb2_header(5, 5, tree_id=5, session_id=0x0000100000000001) +
          le("HBBIQQIIIIIHHII", 57, 0, 0, 2, 0, 0, 0x00120089, 0x80, 7, 1, 0x40, 120, len(name), 0, 0) + name)
    out.append((p, "06-create-request-roundtrip.json", vec(p, "create-request-roundtrip", cr,
                {K + "command": "5", K + "impersonation_level": "2", K + "desired_access": str(0x00120089), K + "share_access": "7",
                 K + "create_disposition": "1", K + "create_options": str(0x40), K + "name_length": str(len(name)), K + "buffer.#": str(len(name))},
                ref="[MS-SMB2] 2.2.13; a CREATE request to open a file for reading")))
    crr = (smb2_header(5, 5, response=1, tree_id=5, session_id=0x0000100000000001) +
           le("HBBIQQQQQQIIQQII", 89, 0, 0, 1, 133000000000000000, 133000000000000001, 133000000000000002, 133000000000000003, 4096, 12,
              0x20, 0, 0x11, 0x22, 0, 0))
    out.append((p, "07-create-response-roundtrip.json", vec(p, "create-response-roundtrip", crr,
                {K + "create_action": "1", K + "end_of_file": "12", K + "file_attributes": str(0x20), K + "file_id_persistent": "17",
                 K + "file_id_volatile": "34", K + "buffer.#": "0"},
                ref="[MS-SMB2] 2.2.14; a CREATE response")))
    er = smb2_header(5, 6, status=0xC0000034, response=1, tree_id=5) + le("HBBI", 9, 0, 0, 0) + b"\x00"
    out.append((p, "08-error-response-roundtrip.json", vec(p, "error-response-roundtrip", er,
                {K + "status": str(0xC0000034), K + "structure_size": "9", K + "byte_count": "0", K + "buffer.#": "1"},
                ref="[MS-SMB2] 2.2.2; an error response (object name not found) to a CREATE")))
    pend = smb2_header(5, 7, status=0x103, response=1, async_id=0x1234) + le("HBBI", 9, 0, 0, 0) + b"\x00"
    out.append((p, "09-async-pending-roundtrip.json", vec(p, "async-pending-roundtrip", pend,
                {K + "async": "1", K + "async_id": str(0x1234), K + "status": str(0x103)},
                ref="[MS-SMB2] 2.2.1.1 and 2.2.2; an async interim response, STATUS_PENDING")))
    lo = smb2_header(2, 8, session_id=0x0000100000000001, flags_extra=8, signature=bytes(range(16))) + le("HH", 4, 0)
    out.append((p, "10-signed-logoff-roundtrip.json", vec(p, "signed-logoff-roundtrip", lo,
                {K + "command": "2", K + "signed": "1", K + "signature": lsbhex(bytes(range(16))), K + "structure_size": "4"},
                ref="[MS-SMB2] 2.2.7; a signed LOGOFF request")))
    rd = smb2_header(8, 9, tree_id=5) + bytes(range(49))
    out.append((p, "11-other-command-roundtrip.json", vec(p, "other-command-roundtrip", rd, {K + "command": "8", K + "body.#": "49"},
                ref="[MS-SMB2] 2.2.1.2; a READ request, a command kept as octets")))
    tf = le("I", 0x424D53FD) + bytes(range(16)) + bytes(range(32, 48)) + le("IHHQ", 100, 0, 1, 0x0000100000000001) + bytes(range(20))
    out.append((p, "12-transform-header-roundtrip.json", vec(p, "transform-header-roundtrip", tf,
                {K + "original_message_size": "100", K + "encryption_flags": "1", K + "nonce": lsbhex(bytes(range(32, 48))), K + "body.#": "20"},
                ref="[MS-SMB2] 2.2.41; an encrypted message's transform header")))
    out.append((p, "13-smb1-is-no-kind.json", vec(p, "smb1-is-no-kind", le("I", 0x424D53FF) + bytes(28), error="no-kind",
                ref="[MS-SMB2] 2.2.1; an SMB1 header (0xFF 'SMB')")))
    out.append((p, "14-cut-header-is-malformed.json", vec(p, "cut-header-is-malformed", neg[:40], error="malformed-wire",
                ref="[MS-SMB2] 2.2.1.2; the NEGOTIATE request of vector 01 cut inside its header")))
    def resp(cmd, status, body):
        return smb2_header(cmd, 20, status=status, response=1, tree_id=5) + body

    E = "[MS-SMB2] 3.3.4.4 and "
    for fname, cmd, status, body, what in (
            ("15-read-buffer-overflow", 8, 0x80000005, le("HBBIII", 17, 80, 0, 4, 0, 0) + b"abcd", E + "2.2.20; a READ response on a named pipe, STATUS_BUFFER_OVERFLOW"),
            ("16-query-info-buffer-overflow", 16, 0x80000005, le("HHI", 9, 72, 4) + b"wxyz", E + "2.2.38; a QUERY_INFO response, STATUS_BUFFER_OVERFLOW"),
            ("17-change-notify-enum-dir", 15, 0x0000010C, le("HHI", 9, 0, 0), E + "2.2.36; a CHANGE_NOTIFY response, STATUS_NOTIFY_ENUM_DIR"),
            ("18-ioctl-buffer-overflow", 11, 0x80000005, le("HHIQQIIIIII", 49, 0, 0x0011C017, 1, 2, 112, 0, 112, 4, 0, 0) + b"pipe", E + "2.2.32; an FSCTL_PIPE_TRANSCEIVE response, STATUS_BUFFER_OVERFLOW")):
        out.append((p, fname + "-roundtrip.json", vec(p, fname[3:] + "-roundtrip", resp(cmd, status, body),
                    {K + "command": str(cmd), K + "status": str(status), K + "body.#": str(len(body)), "@absent": [K + "byte_count", K + "error_context_count"]}, ref=what)))
    for fname, cmd, status, what in (
            ("19-create-buffer-overflow-is-error", 5, 0x80000005, "a CREATE response with STATUS_BUFFER_OVERFLOW, not among the exceptions"),
            ("20-read-more-processing-is-error", 8, 0xC0000016, "a READ response with STATUS_MORE_PROCESSING_REQUIRED, an exception for SESSION_SETUP only")):
        out.append((p, fname + "-roundtrip.json", vec(p, fname[3:] + "-roundtrip", resp(cmd, status, le("HBBI", 9, 0, 0, 0) + b"\x00"),
                    {K + "command": str(cmd), K + "structure_size": "9", K + "byte_count": "0", K + "buffer.#": "1"}, ref=E + "2.2.2; " + what)))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in ssh_packet_vectors() + ssh_message_vectors() + smb2_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("remote-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
