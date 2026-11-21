#!/usr/bin/env python3
"""Write the CubeSat Space Protocol packs (the CSP 1.x and 2.x headers, restated from libcsp) and the
CCSDS SDLS security header pack (CCSDS 355.0-B-2), with their modules.

The two CSP versions share their keys (priority, addresses, ports, flags), so a packet converts from
one to the other where its values fit. The SDLS header's only self-describing field is the SPI; the
other fields' sizes are managed parameters of the security association.
The vectors are not written here: tools/gen/space-more-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/space-more-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "csp2": 'source        "libcsp v2.1 (commit 48f7fb0b57f610bf65bab1aa2d1357c3b9722782), src/csp_id.c (sha256 ad02699c7c39abb69b2fcb119c51b2852ebb35ace94ca34c64ac28241b3233b8) and include/csp/csp_types.h, MIT License, https://github.com/libcsp/libcsp; the CSP 2.x header as csp_id2_prepend writes it; layout restated, no code copied"',
    "csp1": 'source        "libcsp v2.1 (commit 48f7fb0b57f610bf65bab1aa2d1357c3b9722782), src/csp_id.c (sha256 ad02699c7c39abb69b2fcb119c51b2852ebb35ace94ca34c64ac28241b3233b8), and libcsp v1.6 (commit 87006959696c78f70535ab382b0bcd4cb5a6558d) include/csp/csp_types.h (sha256 d469f59d2dfcaccf3548b0510367fccb20cc586be72fcd70637e724184b51e67), MIT License, https://github.com/libcsp/libcsp; the CSP 1.x header as csp_id1_prepend writes it (big-endian); layout restated, no code copied"',
    "sdls": 'source        "CCSDS 355.0-B-2 Space Data Link Security Protocol, Blue Book, July 2022, https://ccsds.org/Pubs/355x0b2.pdf (sha256 86717aedd33886013333054355b92d2d32ffaf84a4a3eb63b7b6ffc6f17d5818), section 4.1; reuse with attribution under the CCSDS reproduction permission statement"',
}
C = "csp"
S = "ccsdssdls"


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, comment, sources, uses):
    L = ["# %s" % c for c in comment] + ["format        %s" % name, "version       0.1.0", "distribution  public"]
    L += [SRC[s] for s in sources]
    L += ["uses          %s" % u for u in uses]
    return L + ["wire          bits", "layout        sequential", "bit_order     msb", ""]


def text(L):
    return "\n".join(L) + "\n"


def csp1_pack():
    L = head("csp-v1-packet", ["CubeSat Space Protocol 1.x packet: the 32-bit header (big-endian) and the data. Written by",
                               "tools/gen/space-more-pack.py; do not edit by hand."], ["csp1"], [C])
    L += [F(C, "priority", 2), F(C, "source", 5), F(C, "destination", 5), F(C, "destination_port", 6), F(C, "source_port", 6),
          F(C, "flag_reserved1", 1), F(C, "flag_reserved2", 1), F(C, "flag_reserved3", 1), F(C, "flag_frag", 1),
          F(C, "flag_hmac", 1), F(C, "flag_bit2", 1), F(C, "flag_rdp", 1), F(C, "flag_crc32", 1)] + octets(C, "data")
    return text(L)


def csp2_pack():
    L = head("csp-v2-packet", ["CubeSat Space Protocol 2.x packet: the 48-bit header (big-endian) and the data. Written by",
                               "tools/gen/space-more-pack.py; do not edit by hand."], ["csp2"], [C])
    L += [F(C, "priority", 2), F(C, "destination", 14), F(C, "source", 14), F(C, "destination_port", 6), F(C, "source_port", 6),
          F(C, "flag_reserved3", 1), F(C, "flag_frag", 1), F(C, "flag_hmac", 1), F(C, "flag_bit2", 1), F(C, "flag_rdp", 1),
          F(C, "flag_crc32", 1)] + octets(C, "data")
    return text(L)


CSP_KEYS = [
    ("key", "priority", "priority: 0 critical, 1 high, 2 normal, 3 low"),
    ("key", "source", "source address (5 bits in CSP 1.x, 14 bits in CSP 2.x)"),
    ("key", "destination", "destination address (5 bits in CSP 1.x, 14 bits in CSP 2.x); all ones is broadcast"),
    ("key", "destination_port", "destination port, 0-63"),
    ("key", "source_port", "source port, 0-63"),
    ("key", "flag_reserved1", "CSP 1.x flag 0x80, reserved"),
    ("key", "flag_reserved2", "CSP 1.x flag 0x40, reserved"),
    ("key", "flag_reserved3", "flag 0x20, reserved"),
    ("key", "flag_frag", "flag 0x10: fragmentation"),
    ("key", "flag_hmac", "flag 0x08: HMAC verification (a trailer in the data)"),
    ("key", "flag_bit2", "flag 0x04: XTEA encryption in CSP 1.x; not defined in libcsp 2.1"),
    ("key", "flag_rdp", "flag 0x02: the reliable datagram protocol (an RDP header in the data)"),
    ("key", "flag_crc32", "flag 0x01: a CRC32 checksum at the end of the data"),
    ("list", "data", "the data after the header (with any RDP header, HMAC or CRC32 it carries), as octets"),
    ("key", "octet", "one octet"),
]


def sdls_pack():
    L = head("ccsds-sdls-security-header", ["CCSDS SDLS security header (355.0-B-2 section 4.1.1): the SPI, then the rest of the",
                                            "protected frame data field (initialization vector, sequence number, pad length, frame data,",
                                            "security trailer) as octets. Written by tools/gen/space-more-pack.py; do not edit by hand."],
             ["sdls"], [S])
    return text(L + [F(S, "spi", 16)] + octets(S, "protected_octets"))


SDLS_KEYS = [
    ("key", "spi", "security parameter index, naming the security association (0 and 65535 reserved)"),
    ("list", "protected_octets", "what follows the SPI: the initialization vector, sequence number and pad length (sizes managed by the security association), the frame data and the security trailer (MAC), as octets"),
    ("key", "octet", "one octet"),
]


def module(name, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/csp-v1-packet/pack.def", csp1_pack())
    out.write("packs/csp-v2-packet/pack.def", csp2_pack())
    out.write("packs/ccsds-sdls-security-header/pack.def", sdls_pack())
    out.write("model/csp.def", module("csp", ["# The csp module: the fields of the CubeSat Space Protocol header, versions 1.x and 2.x. Written by tools/gen/space-more-pack.py."],
                                      'source        "libcsp (MIT); restated by goat-transformers"', CSP_KEYS))
    out.write("model/ccsdssdls.def", module("ccsdssdls", ["# The ccsdssdls module: the CCSDS SDLS security header (355.0-B-2). Written by tools/gen/space-more-pack.py."],
                                            SRC["sdls"], SDLS_KEYS))
    return {"space-more": 5}


def main(argv=None):
    return genio.vector_main("space-more-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
