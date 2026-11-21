#!/usr/bin/env python3
"""space-more-vectors: write the vectors of the CSP and SDLS packs.

Packs: csp-v1-packet, csp-v2-packet, ccsds-sdls-security-header.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of the CSP 1.x and 2.x headers as libcsp's csp_id.c packs them (the
fields as shifts of one big-endian integer) and of CCSDS 355.0-B-2 section 4.1.1.

Inputs: packets built here from values chosen here; no packet is taken from a document or a capture.

`expect` of a round trip is this program's packing of the decoded values, which for these packets
is the input; of a conversion, the other version's header packed here from the shared values;
`model` holds values that were packed.

Usage: python3 -I tools/gen/space-more-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/space-more-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_V1 = "libcsp csp_id.c (CSP 1.x: priority at bit 30, source 25, destination 20, ports 14 and 8, flags 0)"
R_V2 = "libcsp csp_id.c (CSP 2.x: priority at bit 46, destination 32, source 18, ports 12 and 6, flags 0, sent as the high 48 bits of a big-endian 64-bit word)"
R_SDLS = "CCSDS 355.0-B-2 section 4.1.1"


def vec(pack, name, inp, model=None, error=None, ref="", to=None, expect=None):
    v = {"name": name, "from": pack, "to": to or pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


def v1(pri, src, dst, dport, sport, flags):
    word = (pri << 30) | (src << 25) | (dst << 20) | (dport << 14) | (sport << 8) | flags
    return struct.pack(">I", word)


def v2(pri, dst, src, dport, sport, flags):
    word = (pri << 46) | (dst << 32) | (src << 18) | (dport << 12) | (sport << 6) | flags
    return struct.pack(">Q", word << 16)[:6]


def csp_vectors():
    out = []
    p = "csp-v1-packet"
    a = v1(2, 1, 10, 7, 33, 0x01) + b"ping" + b"\x12\x34\x56\x78"
    out.append((p, "01-crc-flag-roundtrip.json", vec(p, "crc-flag-roundtrip", a,
                {"csp.priority": "2", "csp.source": "1", "csp.destination": "10", "csp.destination_port": "7",
                 "csp.source_port": "33", "csp.flag_crc32": "1", "csp.flag_rdp": "0", "csp.data.#": "8"},
                ref=R_V1 + "; normal priority, port 7 to 33, the CRC32 flag set and four checksum octets in the data")))
    b = v1(0, 31, 31, 63, 63, 0xFF)
    out.append((p, "02-largest-values-roundtrip.json", vec(p, "largest-values-roundtrip", b,
                {"csp.priority": "0", "csp.source": "31", "csp.destination": "31", "csp.flag_reserved1": "1",
                 "csp.flag_bit2": "1", "csp.data.#": "0"},
                ref=R_V1 + "; every field at its largest, every flag set, no data")))
    c = v1(3, 5, 6, 1, 2, 0x0A) + b"\x00"
    out.append((p, "03-to-csp-v2.json", vec(p, "to-csp-v2", c, to="csp-v2-packet", expect=v2(3, 6, 5, 1, 2, 0x0A) + b"\x00",
                ref=R_V1 + " and " + R_V2 + "; HMAC and RDP flags; every value fits the 2.x header")))
    out.append((p, "04-cut-header-is-malformed.json", vec(p, "cut-header-is-malformed", a[:3], error="malformed-wire",
                ref=R_V1 + "; three octets of the header")))
    p = "csp-v2-packet"
    d = v2(1, 0x3FFF, 4000, 10, 11, 0x10) + b"hello"
    out.append((p, "01-broadcast-frag-roundtrip.json", vec(p, "broadcast-frag-roundtrip", d,
                {"csp.priority": "1", "csp.destination": str(0x3FFF), "csp.source": "4000", "csp.destination_port": "10",
                 "csp.source_port": "11", "csp.flag_frag": "1", "csp.data.#": "5"},
                ref=R_V2 + "; to the broadcast address 16383 from 4000, the fragmentation flag")))
    e = v2(2, 20, 21, 7, 8, 0x01)
    out.append((p, "02-to-csp-v1.json", vec(p, "to-csp-v1", e, to="csp-v1-packet", expect=v1(2, 21, 20, 7, 8, 0x01),
                ref=R_V2 + " and " + R_V1 + "; addresses below 32 fit the 1.x header")))
    out.append((p, "03-cut-header-is-malformed.json", vec(p, "cut-header-is-malformed", d[:5], error="malformed-wire",
                ref=R_V2 + "; five octets of the header")))
    return out


def sdls_vectors():
    p = "ccsds-sdls-security-header"
    out = []
    a = struct.pack(">H", 7) + bytes(range(12)) + b"frame data" + bytes(range(100, 116))
    out.append((p, "01-spi-and-protected-data-roundtrip.json", vec(p, "spi-and-protected-data-roundtrip", a,
                {"ccsdssdls.spi": "7", "ccsdssdls.protected_octets.#": str(len(a) - 2)},
                ref=R_SDLS + "; SPI 7, then a 12-octet initialization vector, frame data and a 16-octet MAC as octets")))
    out.append((p, "02-cut-spi-is-malformed.json", vec(p, "cut-spi-is-malformed", b"\x00", error="malformed-wire",
                ref=R_SDLS + "; one octet of the SPI")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in csp_vectors() + sdls_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("space-more-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
