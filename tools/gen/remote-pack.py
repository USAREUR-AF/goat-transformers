#!/usr/bin/env python3
"""Write the remote-access and file-sharing packs and their modules: the SSH binary packet (RFC 4253
section 6), the SSH message (RFC 4253, 4252, 4254, 8308), and the SMB2/3 message (Microsoft [MS-SMB2]:
the header, the transform and compression transform headers, and the fixed parts of NEGOTIATE,
SESSION_SETUP, LOGOFF, TREE_CONNECT, TREE_DISCONNECT, CREATE and the error response).

SSH is big-endian; an SSH string or name-list is a 32-bit length then its octets, a `length 32 bytes`
block. SMB2 is little-endian (`bit_order lsb`); its variable buffers are named by offsets from the
header and in practice follow the fixed part, so they are octets to the end.
The vectors are not written here: tools/gen/remote-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/remote-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "sshp": 'source        "IETF RFC 4253, The Secure Shell (SSH) Transport Layer Protocol, January 2006, section 6, https://www.rfc-editor.org/rfc/rfc4253.txt; layout restated"',
    "sshm": ('source        "IETF RFC 4253 sections 7, 11, 12 and 10; RFC 4251 section 5 (data types); RFC 4252 sections 5, 5.1 and 5.4; '
             'RFC 4254 sections 4, 5 and 6; RFC 8308 section 2.3; https://www.rfc-editor.org/; layout restated"'),
    "smb2": ('source        "Microsoft, [MS-SMB2]: Server Message Block (SMB) Protocol Versions 2 and 3, revision 88.0, 2026-09-28, sections 2.2.1, '
             '2.2.2-2.2.14, 2.2.41 and 2.2.42, https://winprotocoldocs-bhdugrdyduf5h2e4.b02.azurefd.net/MS-SMB2/%5bMS-SMB2%5d.pdf (sha256 '
             'fef3a06507679130a8cfdcaeaed581482d7f235435dd904f6c794f113ff04bd1), Microsoft Open Specifications copyright permission; layout restated"'),
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


def head(name, comment, src, uses, order="msb"):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     %s" % order, ""])


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


# ---------------------------------------------------------------- SSH packet

P = "sshpkt"


def ssh_packet_pack():
    L = head("ssh-packet", ["SSH binary packet (RFC 4253 section 6), unencrypted or after decryption: the packet length, the padding",
                            "length, the payload and padding, and the MAC. Written by tools/gen/remote-pack.py; do not edit by hand."], "sshp", [P])
    L += ["length  32  bytes", "  " + F(P, "padding_length", 8)] + ind(1, octets(P, "payload_and_padding")) + ["end"] + octets(P, "mac")
    return text(L)


SSHP_KEYS = [
    ("key", "padding_length", "padding length, octets (4 to 255)"),
    ("list", "payload_and_padding", "the payload followed by the random padding (the last padding_length octets), as octets"),
    ("list", "mac", "the MAC after the packet (empty before keys are exchanged), as octets"), ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- SSH message

M = "sshmsg"


def string(lst):
    return ["length  32  bytes"] + ind(1, octets(M, lst)) + ["end"]


def ssh_message_pack():
    kex = [F(M, "cookie", 128, "hex")]
    for nl in ("kex_algorithms", "server_host_key_algorithms", "encryption_c2s", "encryption_s2c", "mac_c2s", "mac_s2c",
               "compression_c2s", "compression_s2c", "languages_c2s", "languages_s2c"):
        kex += string(nl)
    kex += [F(M, "first_kex_packet_follows", 8), F(M, "kexinit_reserved", 32)]
    cases = [
        ("1", [F(M, "reason_code", 32)] + string("description") + string("language_tag")),
        ("2", string("data")),
        ("3", [F(M, "rejected_sequence", 32)]),
        ("4", [F(M, "always_display", 8)] + string("description") + string("language_tag")),
        ("5,6", string("service_name")),
        ("7", ["count  extension_count  32", "group  sshmsg.extensions  count  @extension_count"] +
         ind(1, string("extension_name") + string("extension_value")) + ["end"]),
        ("20", kex),
        ("21,52,81,82", []),
        ("50", string("user_name") + string("service_name") + string("method_name") + octets(M, "method_data")),
        ("51", string("authentications") + [F(M, "partial_success", 8)]),
        ("53", string("description") + string("language_tag")),
        ("80", string("request_name") + [F(M, "want_reply", 8)] + octets(M, "request_data")),
        ("90", string("channel_type") + [F(M, "sender_channel", 32), F(M, "initial_window_size", 32), F(M, "maximum_packet_size", 32)] +
         octets(M, "request_data")),
        ("91", [F(M, "recipient_channel", 32), F(M, "sender_channel", 32), F(M, "initial_window_size", 32), F(M, "maximum_packet_size", 32)] +
         octets(M, "request_data")),
        ("92", [F(M, "recipient_channel", 32), F(M, "reason_code", 32)] + string("description") + string("language_tag")),
        ("93", [F(M, "recipient_channel", 32), F(M, "bytes_to_add", 32)]),
        ("94", [F(M, "recipient_channel", 32)] + string("data")),
        ("95", [F(M, "recipient_channel", 32), F(M, "data_type_code", 32)] + string("data")),
        ("96,97,99,100", [F(M, "recipient_channel", 32)]),
        ("98", [F(M, "recipient_channel", 32)] + string("request_name") + [F(M, "want_reply", 8)] + octets(M, "request_data")),
    ]
    L = head("ssh-message", ["SSH message (the payload of an SSH packet): the message number and its fields for the transport (RFC 4253,",
                             "RFC 8308), authentication (RFC 4252) and connection (RFC 4254) messages. Written by tools/gen/remote-pack.py."],
             "sshm", [M])
    L += [F(M, "message_number", 8)] + sw("sshmsg.message_number", cases, octets(M, "message_data"))
    return text(L)


SSHM_KEYS = [
    ("key", "message_number", "message number (1 DISCONNECT, 2 IGNORE, 3 UNIMPLEMENTED, 4 DEBUG, 5 SERVICE_REQUEST, 6 SERVICE_ACCEPT, 7 EXT_INFO, 20 KEXINIT, 21 NEWKEYS, 30-49 key exchange method, 50-53 userauth, 60-79 userauth method, 80-82 global requests, 90-100 channels)"),
    ("key", "reason_code", "DISCONNECT or CHANNEL_OPEN_FAILURE reason code"), ("list", "description", "a description string, as UTF-8 octets"),
    ("list", "language_tag", "a language tag string, as octets"), ("list", "data", "IGNORE, CHANNEL_DATA, CHANNEL_EXTENDED_DATA: the data, as octets"),
    ("key", "rejected_sequence", "UNIMPLEMENTED: the sequence number of the rejected packet"), ("key", "always_display", "DEBUG: always display"),
    ("list", "service_name", "SERVICE_REQUEST, SERVICE_ACCEPT, USERAUTH_REQUEST: the service name, as octets"),
    ("list", "extensions", "EXT_INFO: the extensions (their count is written from the list)"), ("list", "extension_name", "an extension name, as octets"),
    ("list", "extension_value", "an extension value, as octets"), ("key", "cookie", "KEXINIT: the 16 random octets, as hexadecimal digits"),
    ("list", "kex_algorithms", "KEXINIT: the key exchange algorithms name-list, as its comma-separated octets"),
    ("list", "server_host_key_algorithms", "KEXINIT: server host key algorithms name-list"),
    ("list", "encryption_c2s", "KEXINIT: encryption algorithms client to server"), ("list", "encryption_s2c", "KEXINIT: encryption algorithms server to client"),
    ("list", "mac_c2s", "KEXINIT: MAC algorithms client to server"), ("list", "mac_s2c", "KEXINIT: MAC algorithms server to client"),
    ("list", "compression_c2s", "KEXINIT: compression algorithms client to server"), ("list", "compression_s2c", "KEXINIT: compression algorithms server to client"),
    ("list", "languages_c2s", "KEXINIT: languages client to server"), ("list", "languages_s2c", "KEXINIT: languages server to client"),
    ("key", "first_kex_packet_follows", "KEXINIT: a guessed key exchange packet follows"), ("key", "kexinit_reserved", "KEXINIT: the reserved uint32, 0"),
    ("list", "user_name", "USERAUTH_REQUEST: the user name, as octets"), ("list", "method_name", "USERAUTH_REQUEST: the method name (password, publickey, none ...)"),
    ("list", "method_data", "USERAUTH_REQUEST: the method-specific fields, as octets"),
    ("list", "authentications", "USERAUTH_FAILURE: the methods that can continue, a name-list"), ("key", "partial_success", "USERAUTH_FAILURE: partial success"),
    ("list", "request_name", "GLOBAL_REQUEST or CHANNEL_REQUEST: the request name, as octets"), ("key", "want_reply", "GLOBAL_REQUEST or CHANNEL_REQUEST: want reply"),
    ("list", "request_data", "the request- or channel-type-specific fields, as octets"), ("list", "channel_type", "CHANNEL_OPEN: the channel type (session, direct-tcpip ...)"),
    ("key", "sender_channel", "the sender's channel number"), ("key", "recipient_channel", "the recipient's channel number"),
    ("key", "initial_window_size", "initial window size, octets"), ("key", "maximum_packet_size", "maximum packet size, octets"),
    ("key", "bytes_to_add", "CHANNEL_WINDOW_ADJUST: octets to add to the window"), ("key", "data_type_code", "CHANNEL_EXTENDED_DATA: data type (1 stderr)"),
    ("list", "message_data", "a message of another number (key exchange methods, userauth methods ...): its fields, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- SMB2

S = "smb2"


def smb2_body():
    negotiate_req = ["field  smb2.structure_size  16  uint", "count  dialect_count  16", F(S, "security_mode", 16), F(S, "reserved16", 16),
                     F(S, "capabilities", 32), F(S, "client_guid", 128, "hex"), F(S, "negotiate_context_or_start_time", 64),
                     "group  smb2.dialects  count  @dialect_count", "  " + F(S, "dialect", 16), "end"] + octets(S, "buffer")
    negotiate_resp = [F(S, "structure_size", 16), F(S, "security_mode", 16), F(S, "dialect_revision", 16), F(S, "negotiate_context_count", 16),
                      F(S, "server_guid", 128, "hex"), F(S, "capabilities", 32), F(S, "max_transact_size", 32), F(S, "max_read_size", 32),
                      F(S, "max_write_size", 32), F(S, "system_time", 64), F(S, "server_start_time", 64), F(S, "security_buffer_offset", 16),
                      F(S, "security_buffer_length", 16), F(S, "negotiate_context_offset", 32)] + octets(S, "buffer")
    session_req = [F(S, "structure_size", 16), F(S, "session_setup_flags", 8), F(S, "security_mode8", 8), F(S, "capabilities", 32),
                   F(S, "channel", 32), F(S, "security_buffer_offset", 16), F(S, "security_buffer_length", 16),
                   F(S, "previous_session_id", 64)] + octets(S, "buffer")
    session_resp = [F(S, "structure_size", 16), F(S, "session_flags", 16), F(S, "security_buffer_offset", 16),
                    F(S, "security_buffer_length", 16)] + octets(S, "buffer")
    small = [F(S, "structure_size", 16), F(S, "reserved16", 16)]
    tree_req = [F(S, "structure_size", 16), F(S, "tree_connect_flags", 16), F(S, "path_offset", 16), F(S, "path_length", 16)] + octets(S, "buffer")
    tree_resp = [F(S, "structure_size", 16), F(S, "share_type", 8), F(S, "reserved8", 8), F(S, "share_flags", 32), F(S, "share_capabilities", 32),
                 F(S, "maximal_access", 32)]
    create_req = [F(S, "structure_size", 16), F(S, "security_flags", 8), F(S, "requested_oplock_level", 8), F(S, "impersonation_level", 32),
                  F(S, "smb_create_flags", 64), F(S, "reserved64", 64), F(S, "desired_access", 32), F(S, "file_attributes", 32),
                  F(S, "share_access", 32), F(S, "create_disposition", 32), F(S, "create_options", 32), F(S, "name_offset", 16),
                  F(S, "name_length", 16), F(S, "create_contexts_offset", 32), F(S, "create_contexts_length", 32)] + octets(S, "buffer")
    create_resp = [F(S, "structure_size", 16), F(S, "oplock_level", 8), F(S, "create_response_flags", 8), F(S, "create_action", 32),
                   F(S, "creation_time", 64), F(S, "last_access_time", 64), F(S, "last_write_time", 64), F(S, "change_time", 64),
                   F(S, "allocation_size", 64), F(S, "end_of_file", 64), F(S, "file_attributes", 32), F(S, "reserved32", 32),
                   F(S, "file_id_persistent", 64), F(S, "file_id_volatile", 64), F(S, "create_contexts_offset", 32),
                   F(S, "create_contexts_length", 32)] + octets(S, "buffer")
    error = [F(S, "structure_size", 16), F(S, "error_context_count", 8), F(S, "reserved8", 8), F(S, "byte_count", 32)] + octets(S, "buffer")
    req = sw("smb2.command", [("0", negotiate_req), ("1", session_req), ("2,4", small), ("3", tree_req), ("5", create_req)], octets(S, "body"))
    resp_ok = sw("smb2.command", [("0", negotiate_resp), ("1", session_resp), ("2,4", small), ("3", tree_resp), ("5", create_resp)],
                 octets(S, "body"))
    # [MS-SMB2] 3.3.4.4: these statuses are not failures for these commands; every other one is
    more = sw("smb2.command", [("1", session_resp)], error)
    overflow = sw("smb2.command", [("8,11,16", octets(S, "body"))], error)
    enum_dir = sw("smb2.command", [("15", octets(S, "body"))], error)
    resp = sw("smb2.status", [("0", resp_ok), ("%d" % 0xC0000016, more), ("%d" % 0x80000005, overflow), ("%d" % 0x0000010C, enum_dir)], error)
    return sw("smb2.response", [("0", req), ("1", resp)])


def smb2_pack():
    hdr = [F(S, "structure_size_header", 16), F(S, "credit_charge", 16), F(S, "status", 32), F(S, "command", 16), F(S, "credits", 16),
           F(S, "response", 1), F(S, "async", 1), F(S, "related", 1), F(S, "signed", 1), F(S, "priority", 3), F(S, "flags_bits7_27", 21),
           F(S, "dfs_operation", 1), F(S, "replay_operation", 1), F(S, "flags_bits30_31", 2), F(S, "next_command", 32), F(S, "message_id", 64)]
    hdr += sw("smb2.async", [("1", [F(S, "async_id", 64)])], [F(S, "reserved_sync", 32), F(S, "tree_id", 32)])
    hdr += [F(S, "session_id", 64), F(S, "signature", 128, "hex")]
    L = head("smb2-message", ["SMB2/3 message ([MS-SMB2]): the 64-octet header (sync or async by the flag), and the fixed part of the",
                              "NEGOTIATE, SESSION_SETUP, LOGOFF, TREE_CONNECT, TREE_DISCONNECT and CREATE requests and responses and the",
                              "error response; the SMB3 transform and compression transform headers. Little-endian. Written by",
                              "tools/gen/remote-pack.py; do not edit by hand."], "smb2", [S], order="lsb")
    L += ["kind  smb2", "when  32  %d" % 0x424D53FE] + hdr + smb2_body() + [""]
    L += ["kind  transform", "when  32  %d" % 0x424D53FD, F(S, "signature", 128, "hex"), F(S, "nonce", 128, "hex"), F(S, "original_message_size", 32),
          F(S, "reserved16", 16), F(S, "encryption_flags", 16), F(S, "session_id", 64)] + octets(S, "body") + [""]
    L += ["kind  compression-transform", "when  32  %d" % 0x424D53FC, F(S, "original_compressed_segment_size", 32),
          F(S, "compression_algorithm", 16), F(S, "compression_flags", 16), F(S, "offset_or_length", 32)] + octets(S, "body")
    return text(L)


SMB2_KEYS = [
    ("key", "structure_size_header", "header StructureSize, 64"), ("key", "credit_charge", "credits the request consumes"),
    ("key", "status", "response: the NT status (0 success, 0xC0000016 more processing required ...); request: channel sequence and reserved"),
    ("key", "command", "command (0 NEGOTIATE, 1 SESSION_SETUP, 2 LOGOFF, 3 TREE_CONNECT, 4 TREE_DISCONNECT, 5 CREATE, 6 CLOSE, 8 READ, 9 WRITE, 11 IOCTL ...)"),
    ("key", "credits", "credits requested (request) or granted (response)"),
    ("key", "response", "flag SERVER_TO_REDIR: the message is a response"), ("key", "async", "flag ASYNC_COMMAND: the header is the async form"),
    ("key", "related", "flag RELATED_OPERATIONS: a related operation in a compound"), ("key", "signed", "flag SIGNED"),
    ("key", "priority", "flags PRIORITY_MASK (SMB 3.1.1): the I/O priority, 0-7"), ("key", "flags_bits7_27", "flag bits 7-27, unused"),
    ("key", "dfs_operation", "flag DFS_OPERATIONS"), ("key", "replay_operation", "flag REPLAY_OPERATION (SMB 3.x)"), ("key", "flags_bits30_31", "flag bits 30-31, unused"),
    ("key", "next_command", "offset of the next header in a compound, 0 for the last"), ("key", "message_id", "message ID"),
    ("key", "async_id", "async header: async ID"), ("key", "reserved_sync", "sync header: the reserved 32 bits (process ID)"), ("key", "tree_id", "sync header: tree ID"),
    ("key", "session_id", "session ID"), ("key", "signature", "signature, as hexadecimal digits, each octet low nibble first (0 when not signed)"),
    ("key", "structure_size", "the command's StructureSize (fixed by the command and direction)"),
    ("key", "security_mode", "NEGOTIATE: security mode (1 signing enabled, 2 signing required)"), ("key", "security_mode8", "SESSION_SETUP request: security mode"),
    ("key", "reserved16", "a 16-bit reserved field"), ("key", "reserved8", "an 8-bit reserved field"), ("key", "reserved32", "a 32-bit reserved field"),
    ("key", "reserved64", "a 64-bit reserved field"), ("key", "capabilities", "capabilities (1 DFS, 2 leasing, 4 large MTU, 8 multi-channel, 0x10 persistent handles, 0x20 directory leasing, 0x40 encryption)"),
    ("key", "client_guid", "NEGOTIATE request: client GUID, as hexadecimal digits, each octet low nibble first (the pack is bit_order lsb)"),
    ("key", "negotiate_context_or_start_time", "NEGOTIATE request: negotiate context offset, count and reserved (3.1.1), or client start time, as one 64-bit value"),
    ("list", "dialects", "NEGOTIATE request: the dialects (their count is written from the list)"), ("key", "dialect", "a dialect (0x0202, 0x0210, 0x0300, 0x0302, 0x0311)"),
    ("key", "dialect_revision", "NEGOTIATE response: the selected dialect"), ("key", "negotiate_context_count", "NEGOTIATE response: negotiate context count (3.1.1) or reserved"),
    ("key", "server_guid", "NEGOTIATE response: server GUID, as hexadecimal digits, each octet low nibble first (the pack is bit_order lsb)"), ("key", "max_transact_size", "NEGOTIATE response: maximum transact size"),
    ("key", "max_read_size", "NEGOTIATE response: maximum read size"), ("key", "max_write_size", "NEGOTIATE response: maximum write size"),
    ("key", "system_time", "NEGOTIATE response: system time, FILETIME (100 ns since 1601-01-01 UTC)"), ("key", "server_start_time", "NEGOTIATE response: server start time, FILETIME"),
    ("key", "security_buffer_offset", "security buffer offset from the header start"), ("key", "security_buffer_length", "security buffer length"),
    ("key", "negotiate_context_offset", "NEGOTIATE response: negotiate context offset (3.1.1) or reserved"),
    ("key", "session_setup_flags", "SESSION_SETUP request: flags (1 binding)"), ("key", "channel", "SESSION_SETUP request: channel, 0"),
    ("key", "previous_session_id", "SESSION_SETUP request: previous session ID"), ("key", "session_flags", "SESSION_SETUP response: session flags (1 guest, 2 null, 4 encrypt data)"),
    ("key", "tree_connect_flags", "TREE_CONNECT request: flags (3.1.1) or reserved"), ("key", "path_offset", "TREE_CONNECT request: path offset"),
    ("key", "path_length", "TREE_CONNECT request: path length, octets"), ("key", "share_type", "TREE_CONNECT response: share type (1 disk, 2 pipe, 3 print)"),
    ("key", "share_flags", "TREE_CONNECT response: share flags"), ("key", "share_capabilities", "TREE_CONNECT response: share capabilities"),
    ("key", "maximal_access", "TREE_CONNECT response: maximal access mask"), ("key", "security_flags", "CREATE request: security flags, 0"),
    ("key", "requested_oplock_level", "CREATE request: requested oplock level"), ("key", "impersonation_level", "CREATE request: impersonation level"),
    ("key", "smb_create_flags", "CREATE request: SmbCreateFlags, 0"), ("key", "desired_access", "CREATE request: desired access mask"),
    ("key", "file_attributes", "CREATE: file attributes"), ("key", "share_access", "CREATE request: share access (1 read, 2 write, 4 delete)"),
    ("key", "create_disposition", "CREATE request: disposition (0 supersede, 1 open, 2 create, 3 open if, 4 overwrite, 5 overwrite if)"),
    ("key", "create_options", "CREATE request: create options"), ("key", "name_offset", "CREATE request: name offset"),
    ("key", "name_length", "CREATE request: name length, octets"), ("key", "create_contexts_offset", "CREATE: create contexts offset"),
    ("key", "create_contexts_length", "CREATE: create contexts length"), ("key", "oplock_level", "CREATE response: oplock level granted"),
    ("key", "create_response_flags", "CREATE response: flags"), ("key", "create_action", "CREATE response: action taken (0 superseded, 1 opened, 2 created, 3 overwritten)"),
    ("key", "creation_time", "CREATE response: creation time, FILETIME"), ("key", "last_access_time", "CREATE response: last access time, FILETIME"),
    ("key", "last_write_time", "CREATE response: last write time, FILETIME"), ("key", "change_time", "CREATE response: change time, FILETIME"),
    ("key", "allocation_size", "CREATE response: allocation size"), ("key", "end_of_file", "CREATE response: end of file"),
    ("key", "file_id_persistent", "CREATE response: file ID, persistent part"), ("key", "file_id_volatile", "CREATE response: file ID, volatile part"),
    ("key", "error_context_count", "error response: error context count (3.1.1)"), ("key", "byte_count", "error response: error data length"),
    ("list", "buffer", "the variable part after the fixed part (dialects' padding and negotiate contexts, security buffer, path, name, create contexts, error data), as octets"),
    ("list", "body", "a command not laid out here, or the encrypted or compressed message, as octets"),
    ("key", "nonce", "transform header: nonce, as hexadecimal digits, each octet low nibble first"), ("key", "original_message_size", "transform header: size of the original message"),
    ("key", "encryption_flags", "transform header: flags (1 encrypted) or encryption algorithm"),
    ("key", "original_compressed_segment_size", "compression transform header: original size"), ("key", "compression_algorithm", "compression transform header: algorithm"),
    ("key", "compression_flags", "compression transform header: flags (1 chained)"), ("key", "offset_or_length", "compression transform header: offset (unchained) or length"),
    ("key", "octet", "one octet"),
]
SMB2_STRINGS = ["signature", "client_guid", "server_guid", "nonce"]


def build(out):
    out.write("packs/ssh-packet/pack.def", ssh_packet_pack())
    out.write("packs/ssh-message/pack.def", ssh_message_pack())
    out.write("packs/smb2-message/pack.def", smb2_pack())
    out.write("model/sshpkt.def", module("sshpkt", ["# The sshpkt module: the SSH binary packet (RFC 4253 section 6). Written by tools/gen/remote-pack.py."], "sshp", SSHP_KEYS))
    out.write("model/sshmsg.def", module("sshmsg", ["# The sshmsg module: SSH message fields (RFC 4253, 4252, 4254, 8308). Written by tools/gen/remote-pack.py."], "sshm", SSHM_KEYS, ["cookie"]))
    out.write("model/smb2.def", module("smb2", ["# The smb2 module: SMB2/3 header and command fields ([MS-SMB2]). Written by tools/gen/remote-pack.py."], "smb2", SMB2_KEYS, SMB2_STRINGS))
    return {"remote": 6}


def main(argv=None):
    return genio.vector_main("remote-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
